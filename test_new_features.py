"""Tests for the added features: methods, proposed persistence, email packs,
roster-dropdown teammate fields."""
import uuid

import pandas as pd

from teamformation.optimizer import generate
from teamformation.scoring import default_weights, parse_student
from teamformation import formation_service as fsvc
from teamformation import survey_service as svc
from teamformation import emailpack
from teamformation import email_delivery as mail
from teamformation.vault import Vault
from teamformation.ingest import name_key
from tests.synthetic import cohort


# ---- optimizer methods -----------------------------------------------------
def test_all_methods_assign_everyone():
    students = cohort(24)
    for m in ("linear", "hill", "greedy", "random"):
        res = generate(students, default_weights(), size=4, seed=1, method=m,
                       iterations=2000 if m in ("linear", "hill") else None)
        assigned = [name_key(x["name"]) for t in res.teams for x in t]
        assert len(set(assigned)) == 24, m
        assert res.meta["method"] == m


def test_linear_beats_random_on_targeted_weight():
    students = cohort(40)
    w = {k: 0 for k in default_weights()}
    w["commitment"] = 5
    for i, s in enumerate(students):
        s["effort"] = 1 if i % 2 == 0 else 5
    rnd = generate(students, w, size=5, seed=1, method="random")
    lin = generate(students, w, size=5, seed=1, method="linear", iterations=8000)
    assert lin.objective >= rnd.objective


# ---- proposed-team persistence --------------------------------------------
def test_proposed_persistence_roundtrip():
    vault = Vault()
    course, label = f"PROP-{uuid.uuid4().hex[:6]}", "P1"
    df = pd.DataFrame([{"First Name": f"S{i}", "Last Name": "T",
                        "Email": f"s{i}@x.edu", "Section": "A"} for i in range(12)])
    slug, students = svc.save_setup(course, label, df, dict(svc.DEFAULT_SURVEY))
    active = svc.load_students_for_formation(vault, slug)
    res = generate(active, default_weights(), size=4, seed=1, iterations=1000)
    design = {"teams": [list(t) for t in res.teams],
              "names": [f"Team {i+1}" for i in range(len(res.teams))],
              "locked_teams": [False] * len(res.teams),
              "locked_students": {}, "seed": res.seed}
    fsvc.save_proposed(vault, slug, design)
    saved = fsvc.load_proposed(Vault(), slug)          # fresh vault = restart
    hydrated = fsvc.rehydrate_proposed(saved, active)
    assert hydrated is not None
    orig = [[name_key(m["name"]) for m in t] for t in design["teams"]]
    back = [[name_key(m["name"]) for m in t] for t in hydrated["teams"]]
    assert orig == back


# ---- email packs -----------------------------------------------------------
def _msgs():
    return [mail.Message(to_email=f"s{i}@x.edu", to_name=f"Stu {i}", team="Team 1",
                         subject="Your team", body="Hi {}<br>welcome".format(i),
                         attachments=[]) for i in range(3)]


def test_autosend_pack_contains_scripts():
    import io, zipfile
    z = zipfile.ZipFile(io.BytesIO(emailpack.send_all_pack(_msgs(), "invitations")))
    names = z.namelist()
    assert "Send emails (Windows).cmd" in names
    assert "send_all_windows.ps1" in names
    assert "send_all_mac.applescript" in names


def test_eml_pack_one_per_recipient():
    import io, zipfile
    z = zipfile.ZipFile(io.BytesIO(emailpack.eml_zip(_msgs(), "invitations")))
    assert sum(1 for n in z.namelist() if n.endswith(".eml")) == 3


# ---- roster-dropdown teammate fields feed scoring --------------------------
def test_prev_teammates_list_scored():
    students = cohort(16)
    # list format (new roster-dropdown) instead of free text
    students[0]["prev_teammates"] = [students[1]["name"]]
    p = parse_student(students[0])
    assert name_key(students[1]["name"]) in p["prev"]
    w = {k: 0 for k in default_weights()}
    w["avoid_repeats"] = 5
    res = generate(students, w, size=4, seed=3, iterations=6000)
    for team in res.teams:
        keys = [name_key(m["name"]) for m in team]
        assert not (name_key(students[0]["name"]) in keys
                    and name_key(students[1]["name"]) in keys)
