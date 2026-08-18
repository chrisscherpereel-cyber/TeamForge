import uuid

import pandas as pd

from teamformation.vault import Vault
from teamformation import survey_service as svc
from teamformation import formation_service as fsvc
from teamformation.scoring import default_weights, parse_student, configuration_diagnostics
from teamformation.optimizer import generate


def _roster_df():
    return pd.DataFrame([
        {"First Name": "Alex", "Last Name": "Johnson", "Email": "alex@x.edu", "Section": "A"},
        {"First Name": "Morgan", "Last Name": "Lee", "Email": "morgan@x.edu", "Section": "A"},
        {"First Name": "Sam", "Last Name": "Rivera", "Email": "sam@x.edu", "Section": "A"},
        {"First Name": "Taylor", "Last Name": "Chen", "Email": "taylor@x.edu", "Section": "A"},
    ])


def test_roster_roundtrip_and_positions_stable():
    vault = Vault()
    course, label = f"TEST-{uuid.uuid4().hex[:6]}", "P1"
    slug, students = svc.save_setup(course, label, _roster_df(), dict(svc.DEFAULT_SURVEY))
    assert len(students) == 4
    snap = svc.load_roster_snapshot(vault, slug)
    assert snap["students"][0]["name"]  # ordered
    # re-save with an extra student -> existing positions preserved, new appended
    df2 = pd.concat([_roster_df(),
                     pd.DataFrame([{"First Name": "Jordan", "Last Name": "Smith",
                                    "Email": "jordan@x.edu", "Section": "A"}])],
                    ignore_index=True)
    slug2, students2 = svc.save_setup(course, label, df2, dict(svc.DEFAULT_SURVEY))
    assert len(students2) == 5
    assert [s["name"] for s in students2[:4]] == [s["name"] for s in students]


def test_response_roundtrip_and_status():
    vault = Vault()
    course, label = f"TEST-{uuid.uuid4().hex[:6]}", "P1"
    slug, students = svc.save_setup(course, label, _roster_df(), dict(svc.DEFAULT_SURVEY))
    svc.save_response(vault, slug, 0, {"name": students[0]["name"], "major": "Finance",
                                       "complete": True, "skills": {"quant": 5}})
    status = svc.response_status(vault, slug)
    assert sum(1 for r in status if r["responded"]) == 1
    loaded = svc.load_response(vault, slug, 0)
    assert loaded["major"] == "Finance"


def test_excluded_student_dropped_from_formation():
    vault = Vault()
    course, label = f"TEST-{uuid.uuid4().hex[:6]}", "P1"
    slug, students = svc.save_setup(course, label, _roster_df(), dict(svc.DEFAULT_SURVEY))
    svc.set_excluded(vault, slug, 3, True)
    active = svc.load_students_for_formation(vault, slug)
    assert len(active) == 3
    assert all(not s.get("excluded") for s in active)


def test_nonrespondents_included_in_formation():
    vault = Vault()
    course, label = f"TEST-{uuid.uuid4().hex[:6]}", "P1"
    slug, students = svc.save_setup(course, label, _roster_df(), dict(svc.DEFAULT_SURVEY))
    svc.save_response(vault, slug, 0, {"name": students[0]["name"], "complete": True})
    active = svc.load_students_for_formation(vault, slug)
    assert len(active) == 4
    assert sum(1 for s in active if s["responded"]) == 1


def test_finalize_versioning_and_student_view():
    vault = Vault()
    course, label = f"TEST-{uuid.uuid4().hex[:6]}", "P1"
    slug, students = svc.save_setup(course, label, _roster_df(), dict(svc.DEFAULT_SURVEY))
    active = svc.load_students_for_formation(vault, slug)
    res = generate(active, default_weights(), size=2, seed=1, iterations=1000)
    parsed = [[parse_student(m) for m in t] for t in res.teams]
    diag = configuration_diagnostics(parsed, default_weights())
    records = fsvc.teams_to_records(res.teams)
    fsvc.finalize(vault, slug, records, diag)
    again = fsvc.finalize(vault, slug, records, diag)   # second finalize -> history
    assert len(again["history"]) == 1
    final = fsvc.load_final(vault, slug)
    view = fsvc.student_team_view(final, students[0]["name"])
    assert view is not None
    assert "concern_text" not in str(view)   # confidentiality
