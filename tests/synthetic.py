"""Synthetic student generators for tests."""
from __future__ import annotations

import random

from teamformation.survey_schema import DAYS, TIME_BLOCKS, SKILLS, WORKSTYLE, MAJORS


def make_student(pos, name=None, responded=True, **overrides):
    rec = {
        "pos": pos,
        "name": name or f"Student {pos:03d}",
        "email": f"s{pos:03d}@example.edu",
        "section": overrides.get("section", "A"),
        "responded": responded,
        "major": overrides.get("major", MAJORS[pos % len(MAJORS)]),
        "standing": "Junior",
        "subject_exp": overrides.get("subject_exp", (pos % 5) + 1),
        "work_exp": overrides.get("work_exp", (pos % 5) + 1),
        "meeting_format": overrides.get("meeting_format", (pos % 5) + 1),
        "timezone": overrides.get("timezone", "Arizona time (MST year-round)"),
        "availability": overrides.get("availability",
                                      {d: list(TIME_BLOCKS[:3]) for d in DAYS}),
        "weekly_time": overrides.get("weekly_time", 3),
        "skills": overrides.get("skills", {k: (pos % 5) + 1 for k in SKILLS}),
        "roles": overrides.get("roles", []),
        "leadership": overrides.get("leadership", (pos % 5) + 1),
        "workstyle": overrides.get("workstyle", {k: 3 for k in WORKSTYLE}),
        "effort": overrides.get("effort", (pos % 5) + 1),
        "pace": overrides.get("pace", (pos % 5) + 1),
        "response_time": overrides.get("response_time", (pos % 5) + 1),
        "prev_teammates": overrides.get("prev_teammates", ""),
        "preferred_teammate": overrides.get("preferred_teammate", ""),
        "has_concern": False, "concern_text": "", "other_info": "",
    }
    return rec


def cohort(n, seed=0, **kw):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        out.append(make_student(i, **kw))
    return out
