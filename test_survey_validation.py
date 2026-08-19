from teamformation.validation import (
    role_problems, normalize_roles, submission_problems,
)
from teamformation.survey_schema import DEFAULT_SURVEY, blank_response, DAYS, TIME_BLOCKS, SKILLS, WORKSTYLE, NO_PREF_ROLE


def test_role_max_three():
    assert role_problems(["Researcher", "Writer / editor", "Facilitator", "Presenter / spokesperson"])
    assert not role_problems(["Researcher", "Writer / editor", "Facilitator"])


def test_no_preference_exclusive():
    assert role_problems([NO_PREF_ROLE, "Researcher"])
    assert normalize_roles([NO_PREF_ROLE, "Researcher"]) == [NO_PREF_ROLE]
    assert normalize_roles(["Researcher", "Writer / editor", "Facilitator", "Presenter / spokesperson"]) == \
        ["Researcher", "Writer / editor", "Facilitator"]


def _complete_answers():
    a = blank_response()
    a["name"] = "Jamie Doe"
    a["major"] = "Finance"
    a["standing"] = "Junior"
    a["subject_exp"] = 3
    a["work_exp"] = 2
    a["meeting_format"] = 3
    a["timezone"] = "Arizona time (MST year-round)"
    a["availability"] = {d: [] for d in DAYS}
    a["availability"]["Monday"] = [TIME_BLOCKS[1]]
    a["weekly_time"] = 3
    a["skills"] = {k: 3 for k in SKILLS}
    a["workstyle"] = {k: 3 for k in WORKSTYLE}
    a["roles"] = ["Researcher"]
    a["leadership"] = 3
    a["effort"] = 3
    a["pace"] = 3
    a["response_time"] = 2
    return a


def test_complete_submission_has_no_problems():
    assert submission_problems(_complete_answers(), DEFAULT_SURVEY) == []


def test_missing_name_flagged():
    a = _complete_answers()
    a["name"] = ""
    assert any("name" in p.lower() for p in submission_problems(a, DEFAULT_SURVEY))


def test_missing_availability_flagged():
    a = _complete_answers()
    a["availability"] = {d: [] for d in DAYS}
    assert any("availability" in p.lower() for p in submission_problems(a, DEFAULT_SURVEY))


def test_concern_without_text_flagged():
    a = _complete_answers()
    a["has_concern"] = True
    a["concern_text"] = ""
    assert any("concern" in p.lower() for p in submission_problems(a, DEFAULT_SURVEY))


def test_toggled_off_sections_not_required():
    a = blank_response()
    a["name"] = "Only Name"
    cfg = dict(DEFAULT_SURVEY)
    for k in list(cfg):
        if k.startswith("ask_"):
            cfg[k] = False
    assert submission_problems(a, cfg) == []
