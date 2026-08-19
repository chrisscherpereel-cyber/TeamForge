"""End-to-end workflow test (no Streamlit): roster -> responses -> generate ->
manual edit -> finalize -> exports -> student view. Mirrors the acceptance
criteria that don't require a browser."""
import uuid

import pandas as pd

from teamformation.vault import Vault
from teamformation import survey_service as svc
from teamformation import formation_service as fsvc
from teamformation import export_service as exp
from teamformation import scoring
from teamformation.optimizer import generate
from teamformation.survey_schema import DAYS, TIME_BLOCKS, SKILLS, WORKSTYLE
from teamformation.ingest import name_key


def _roster(n):
    rows = []
    for i in range(n):
        rows.append({"First Name": f"Stu{i:02d}", "Last Name": "Test",
                     "Email": f"stu{i:02d}@x.edu", "Section": "A"})
    return pd.DataFrame(rows)


def _survey_payload(name, i):
    return {
        "name": name, "complete": True, "major": ["Finance", "Marketing", "Management"][i % 3],
        "standing": "Junior", "subject_exp": (i % 5) + 1, "work_exp": (i % 5) + 1,
        "meeting_format": (i % 5) + 1, "timezone": "Arizona time (MST year-round)",
        "availability": {d: list(TIME_BLOCKS[:3]) for d in DAYS}, "weekly_time": 3,
        "skills": {k: (i % 5) + 1 for k in SKILLS}, "roles": ["Researcher"],
        "leadership": (i % 5) + 1, "workstyle": {k: 3 for k in WORKSTYLE},
        "effort": (i % 5) + 1, "pace": (i % 5) + 1, "response_time": (i % 5) + 1,
        "prev_teammates": "", "preferred_teammate": "", "has_concern": False,
        "concern_text": "", "other_info": "",
    }


def test_full_workflow():
    vault = Vault()
    course, label = f"WF-{uuid.uuid4().hex[:6]}", "P1"
    survey_cfg = dict(svc.DEFAULT_SURVEY)

    # 1-2. roster
    slug, students = svc.save_setup(course, label, _roster(23), survey_cfg,
                                    owner="prof")
    assert len(students) == 23

    # 5-8. responses for 20 of 23 (3 remain "No Survey Response")
    for pos in range(20):
        svc.save_response(vault, slug, pos,
                          _survey_payload(students[pos]["name"], pos))
    status = svc.response_status(vault, slug)
    assert sum(1 for r in status if r["responded"]) == 20

    # active students include the 3 non-respondents
    active = svc.load_students_for_formation(vault, slug)
    assert len(active) == 23
    assert sum(1 for s in active if not s["responded"]) == 3

    # 10-13. generate teams of 5, with a do-not-pair hard constraint
    a, b = active[0]["name"], active[1]["name"]
    res = generate(active, fsvc.default_config()["weights"], size=5,
                   cannot_pairs=[(a, b)], seed=1)
    assert sorted(res.sizes, reverse=True) == [5, 5, 5, 4, 4]
    for team in res.teams:
        keys = [name_key(m["name"]) for m in team]
        assert not (name_key(a) in keys and name_key(b) in keys)

    # 18. every active student assigned exactly once
    assigned = [name_key(m["name"]) for t in res.teams for m in t]
    assert len(assigned) == 23 and len(set(assigned)) == 23

    # 14-16. diagnostics
    parsed = [[scoring.parse_student(m) for m in t] for t in res.teams]
    diag = scoring.configuration_diagnostics(parsed, res.weights)
    assert 0 <= diag["overall"] <= 100

    # 19-20. finalize + persistence across "restart"
    records = fsvc.teams_to_records(res.teams)
    fsvc.finalize(vault, slug, records, diag, instructions="Kickoff Friday.")
    final = fsvc.load_final(Vault(), slug)   # fresh vault instance = restart
    assert final and len(final["teams"]) == 5

    # 21. exports
    csv = exp.student_dataset_csv(active, final)
    assert "team" in csv and "placement_concern" in csv
    xlsx = exp.workbook_xlsx(course, label, active, final, diag, fsvc.load_config(vault, slug))
    assert xlsx[:2] == b"PK"   # valid xlsx zip
    facing = exp.student_facing_csv(final, include_email=False)
    assert "skill_" not in facing and "concern" not in facing

    # 23-24. student view is confidentiality-safe
    view = fsvc.student_team_view(final, students[0]["name"])
    assert view and "Team" in view["team"]
    assert "concern" not in str(view).lower()
