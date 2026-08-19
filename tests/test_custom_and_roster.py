"""Tests for custom questions, extra-column recall, and custom validation."""
import uuid

import pandas as pd

from teamformation.vault import Vault
from teamformation import survey_service as svc
from teamformation import export_service as exp
from teamformation.validation import custom_problems, submission_problems
from teamformation.survey_schema import DEFAULT_SURVEY, blank_response, DAYS, TIME_BLOCKS, SKILLS, WORKSTYLE


def _roster_with_extra():
    return pd.DataFrame([
        {"First Name": "Alex", "Last Name": "Johnson", "Email": "a@x.edu",
         "Section": "A", "Student ID": "1001", "GPA": "3.8"},
        {"First Name": "Sam", "Last Name": "Rivera", "Email": "s@x.edu",
         "Section": "A", "Student ID": "1002", "GPA": "3.2"},
    ])


def test_extra_columns_preserved_and_recalled():
    vault = Vault()
    course, label = f"EX-{uuid.uuid4().hex[:6]}", "P1"
    slug, students = svc.save_setup(course, label, _roster_with_extra(),
                                    dict(DEFAULT_SURVEY))
    # extra columns retained on the stored roster
    assert students[0]["extra"].get("Student ID") in ("1001", "1002")
    assert "GPA" in students[0]["extra"]
    # recalled from a fresh vault (simulated reload)
    snap = svc.load_roster_snapshot(Vault(), slug)
    assert snap["students"][0]["extra"]["GPA"] in ("3.8", "3.2")
    # and they flow into the export
    active = svc.load_students_for_formation(vault, slug)
    csv = exp.student_dataset_csv(active, None)
    assert "info_Student ID" in csv and "info_GPA" in csv


def test_custom_question_validation_and_export():
    vault = Vault()
    course, label = f"CQ-{uuid.uuid4().hex[:6]}", "P1"
    survey = dict(DEFAULT_SURVEY)
    survey["custom_questions"] = [
        {"id": "cq_1", "label": "T-shirt size", "type": "select",
         "options": ["S", "M", "L"], "required": True},
        {"id": "cq_2", "label": "Anything else?", "type": "textarea",
         "options": [], "required": False},
    ]
    slug, students = svc.save_setup(course, label, _roster_with_extra(), survey)

    # required custom question unanswered -> flagged
    ans = blank_response()
    ans.update({"name": "Alex", "custom": {}})
    assert any("T-shirt" in p for p in custom_problems(ans, survey))

    # answered -> no custom problem
    ans["custom"] = {"cq_1": "M"}
    assert custom_problems(ans, survey) == []

    # custom answer flows into export under its label
    svc.save_response(vault, slug, 0, {"name": students[0]["name"], "complete": True,
                                       "custom": {"cq_1": "L", "cq_2": "hi"}})
    active = svc.load_students_for_formation(vault, slug)
    csv = exp.student_dataset_csv(active, None, survey["custom_questions"])
    assert "T-shirt size" in csv and "Anything else?" in csv


def _complete():
    a = blank_response()
    a.update({"name": "J D", "major": "Finance", "standing": "Junior",
              "subject_exp": 3, "work_exp": 2, "meeting_format": 3,
              "timezone": "Arizona time (MST year-round)", "weekly_time": 3,
              "leadership": 3, "effort": 3, "pace": 3, "response_time": 2,
              "skills": {k: 3 for k in SKILLS}, "workstyle": {k: 3 for k in WORKSTYLE},
              "roles": ["Researcher"]})
    a["availability"] = {d: [] for d in DAYS}
    a["availability"]["Monday"] = [TIME_BLOCKS[1]]
    return a


def test_required_custom_blocks_submission():
    survey = dict(DEFAULT_SURVEY)
    survey["custom_questions"] = [{"id": "cq_1", "label": "Pledge?", "type": "radio",
                                   "options": ["Yes", "No"], "required": True}]
    a = _complete()
    assert any("Pledge" in p for p in submission_problems(a, survey))
    a["custom"] = {"cq_1": "Yes"}
    assert submission_problems(a, survey) == []
