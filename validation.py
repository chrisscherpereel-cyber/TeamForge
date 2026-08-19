"""Pure validation helpers for the team-formation survey.

Kept free of Streamlit so they can be unit-tested and reused by the student
form (live feedback + submit gating) identically.
"""
from __future__ import annotations

from typing import Dict, List

from .survey_schema import SKILLS, WORKSTYLE, NO_PREF_ROLE, MAX_ROLES


def role_problems(roles: List[str]) -> List[str]:
    problems = []
    roles = roles or []
    if len(roles) > MAX_ROLES:
        problems.append(f"Select at most {MAX_ROLES} contribution roles.")
    if NO_PREF_ROLE in roles and len(roles) > 1:
        problems.append(f"“{NO_PREF_ROLE}” can't be combined with other role choices.")
    return problems


def normalize_roles(roles: List[str]) -> List[str]:
    """Enforce the role rules by construction: 'No strong preference' wins alone;
    otherwise cap at MAX_ROLES."""
    roles = list(roles or [])
    if NO_PREF_ROLE in roles:
        return [NO_PREF_ROLE]
    return roles[:MAX_ROLES]


def submission_problems(answers: Dict, survey_cfg: Dict) -> List[str]:
    """Human-readable list of what's stopping a complete submission ([] = ready)."""
    problems: List[str] = []

    if not str(answers.get("name", "")).strip():
        problems.append("Enter your name.")

    def require(flag, value, label):
        if survey_cfg.get(flag, True) and value in (None, "", []):
            problems.append(f"Answer: {label}.")

    require("ask_major", answers.get("major"), "primary academic major")
    require("ask_standing", answers.get("standing"), "academic standing")
    require("ask_subject_exp", answers.get("subject_exp"), "relevant experience")
    require("ask_work_exp", answers.get("work_exp"), "work/organizational experience")
    require("ask_meeting_format", answers.get("meeting_format"), "preferred meeting format")
    require("ask_timezone", answers.get("timezone"), "time zone")
    require("ask_weekly_time", answers.get("weekly_time"), "weekly time available")
    require("ask_leadership", answers.get("leadership"), "leadership preference")
    require("ask_effort", answers.get("effort"), "desired effort level")
    require("ask_pace", answers.get("pace"), "work pace")
    require("ask_response_time", answers.get("response_time"), "expected response time")

    if survey_cfg.get("ask_skills", True):
        skills = answers.get("skills") or {}
        missing = [k for k in SKILLS if skills.get(k) in (None, "")]
        if missing:
            problems.append(f"Rate all {len(SKILLS)} skill areas "
                            f"({len(missing)} still blank).")

    if survey_cfg.get("ask_workstyle", True):
        ws = answers.get("workstyle") or {}
        missing = [k for k in WORKSTYLE if ws.get(k) in (None, "")]
        if missing:
            problems.append(f"Answer all {len(WORKSTYLE)} work-style statements "
                            f"({len(missing)} still blank).")

    if survey_cfg.get("ask_roles", True):
        problems.extend(role_problems(answers.get("roles")))

    if survey_cfg.get("ask_availability", True):
        avail = answers.get("availability") or {}
        if not any(avail.get(d) for d in avail):
            problems.append("Select at least one weekly availability block.")

    if survey_cfg.get("ask_concern", True) and answers.get("has_concern") \
            and not str(answers.get("concern_text", "")).strip():
        problems.append("You marked a placement concern — please describe it, or "
                        "change your answer to “No”.")

    return problems
