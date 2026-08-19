"""Team-formation survey definition — the single source of truth for questions,
option lists, scales, and the default instructor-configurable wording/toggles.

Everything the student form renders, the response parser reads, and the
optimizer scores is defined here, so the survey, storage, and algorithm can
never drift out of sync. Option lists the instructor is allowed to edit
(majors, categories) live in DEFAULT_SURVEY; fixed scales live as module
constants.
"""
from __future__ import annotations

from typing import Dict, List

# --------------------------------------------------------------------------- #
# Fixed option lists / scales
# --------------------------------------------------------------------------- #
MAJORS: List[str] = [
    "Accounting", "Economics", "Finance",
    "Information Systems / Business Analytics", "Management", "Marketing",
    "Supply Chain / Operations", "Hospitality / Tourism",
    "Entrepreneurship / Small Business", "Other Business", "Non-business",
    "Undeclared / Not yet determined",
]

STANDINGS: List[str] = [
    "First-year / Freshman", "Sophomore", "Junior", "Senior",
    "Graduate student", "Other",
]

# 1-5 experience relevance
SUBJECT_EXPERIENCE: List[str] = [
    "1 - Very little or none", "2 - Limited", "3 - Moderate",
    "4 - Substantial", "5 - Extensive",
]

WORK_EXPERIENCE: List[str] = [
    "None", "Less than 1 year", "1-2 years", "3-5 years", "6 or more years",
]

MEETING_FORMAT: List[str] = [
    "Strongly prefer in-person",
    "Prefer in-person, but online is workable",
    "No preference / either works equally well",
    "Prefer online, but in-person is workable",
    "Strongly prefer online",
]

TIMEZONES: List[str] = [
    "Arizona time (MST year-round)", "Pacific Time",
    "Mountain Time outside Arizona", "Central Time", "Eastern Time", "Other",
]

# Approximate UTC offsets (standard time) used for schedule-overlap scoring.
TZ_OFFSET: Dict[str, int] = {
    "Arizona time (MST year-round)": -7, "Pacific Time": -8,
    "Mountain Time outside Arizona": -7, "Central Time": -6,
    "Eastern Time": -5, "Other": -7,
}

DAYS: List[str] = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                   "Saturday", "Sunday"]

TIME_BLOCKS: List[str] = [
    "Before 9:00 a.m.", "9:00 a.m.-12:00 p.m.", "12:00-3:00 p.m.",
    "3:00-6:00 p.m.", "6:00-9:00 p.m.", "After 9:00 p.m.",
]

WEEKLY_TIME: List[str] = [
    "Less than 1 hour", "1-2 hours", "3-4 hours", "5-6 hours", "More than 6 hours",
]

# Skills — canonical key -> student-facing label. Order is display order.
SKILLS: Dict[str, str] = {
    "quant": "Quantitative analysis and working with numbers",
    "excel": "Excel / spreadsheets / data organization",
    "research": "Research and finding credible information",
    "writing": "Professional writing and editing",
    "presentation": "Presentation and public speaking",
    "planning": "Project planning, scheduling, and keeping work on track",
    "creative": "Creative ideation and generating alternatives",
    "tech": "AI tools, digital tools, or technology troubleshooting",
    "facilitation": "Facilitating discussion and helping a team work through disagreements",
}

SKILL_SCALE: List[str] = [
    "1 - Little or no experience", "2 - Basic", "3 - Competent",
    "4 - Strong", "5 - Advanced / could help teach others",
]

ROLES: List[str] = [
    "Coordinator / project manager", "Quantitative analyst", "Researcher",
    "Writer / editor", "Presenter / spokesperson", "Creative strategist",
    "Technology / AI specialist", "Quality / detail checker", "Facilitator",
    "No strong preference",
]
NO_PREF_ROLE = "No strong preference"
MAX_ROLES = 3

LEADERSHIP: List[str] = [
    "I strongly prefer not to be the primary coordinator",
    "I would rather support someone else as coordinator",
    "I have no preference",
    "I would like to coordinate if the team needs me to",
    "I strongly prefer to take a coordination / leadership role",
]

# Work-style statements (canonical key -> statement), 1-5 SD..SA
WORKSTYLE: Dict[str, str] = {
    "early_start": "I begin my assigned work well before the final deadline.",
    "written_plan": "I prefer a written plan with milestones and clear task ownership.",
    "communicates": "I communicate my progress to teammates without needing to be asked.",
    "raises_concerns": "I am comfortable respectfully raising concerns when I disagree.",
    "invites_input": "I actively invite ideas and input from other team members.",
    "adapts": "I adapt reasonably well when new information requires the team to change direction.",
    "detail": "I pay close attention to accuracy, details, and the quality of the final submission.",
    "integrates": "I am comfortable integrating work produced by several people into one coherent final product.",
}

WORKSTYLE_SCALE: List[str] = [
    "1 - Strongly disagree", "2 - Disagree", "3 - Neither agree nor disagree",
    "4 - Agree", "5 - Strongly agree",
]

EFFORT: List[str] = [
    "Meet the basic course requirements with limited extra time",
    "Complete the requirements reliably and efficiently",
    "Produce solid work and invest a reasonable amount of extra effort",
    "Aim for high-quality work even when additional effort is required",
    "Aim for exceptional performance and invest substantial effort when needed",
]

PACE: List[str] = [
    "I prefer to finish major work as early as practical",
    "I usually like to be comfortably ahead of deadlines",
    "I prefer steady progress throughout the available time",
    "I often do more of my work as deadlines get closer",
    "I generally prefer working close to the deadline",
]

RESPONSE_TIME: List[str] = [
    "Usually within a few hours", "Usually within 12 hours",
    "Usually within 24 hours", "Usually within 48 hours",
    "It varies substantially depending on the week",
]


# --------------------------------------------------------------------------- #
# Instructor-configurable survey: toggles + editable wording/categories
# --------------------------------------------------------------------------- #
DEFAULT_SURVEY: Dict = {
    "title": "Team Formation Profile",
    "intro": ("This survey will be used to help form balanced and workable course "
              "teams. Please answer candidly based on what you can realistically "
              "contribute during this course, not what you think is the \"best\" "
              "answer. Preferences will be considered when practical but are not "
              "guaranteed."),

    # Section toggles (instructor can switch blocks off)
    "ask_section": True,          # course section question
    "ask_major": True,
    "ask_standing": True,
    "ask_subject_exp": True,
    "ask_work_exp": True,
    "ask_meeting_format": True,
    "ask_timezone": True,
    "ask_availability": True,
    "ask_weekly_time": True,
    "ask_skills": True,
    "ask_roles": True,
    "ask_leadership": True,
    "ask_workstyle": True,
    "ask_effort": True,
    "ask_pace": True,
    "ask_response_time": True,
    "ask_prev_teammates": True,
    "ask_preferred_teammate": True,
    "ask_concern": True,
    "ask_other_info": True,

    # Editable category lists
    "majors": list(MAJORS),

    # Instructor-defined custom questions (collected in an "Additional questions"
    # section). Each: {id, label, type, options[], required}. type is one of
    # CUSTOM_TYPES below.
    "custom_questions": [],
    "custom_seq": 0,

    # Scheduling
    "is_open": True,
    "opens_at": "",
    "closes_at": "",
    "closed_note": "This survey is now closed. Thank you.",
    # Whether students may reopen and edit before the deadline
    "allow_edit": True,
    # Whether students may view their released team assignment inside the app
    "release_teams": False,
}


# Custom-question types: key -> (instructor-facing label, needs_options?)
CUSTOM_TYPES: Dict[str, tuple] = {
    "text": ("Short text", False),
    "textarea": ("Paragraph text", False),
    "radio": ("Multiple choice (pick one)", True),
    "select": ("Dropdown (pick one)", True),
    "multiselect": ("Checkboxes (pick many)", True),
    "number": ("Number", False),
    "scale5": ("1–5 rating scale", False),
}


def blank_response() -> Dict:
    """An empty response payload with every field present (typed defaults)."""
    return {
        "name": "", "email": "", "section": "",
        "major": "", "standing": "",
        "subject_exp": None, "work_exp": None,
        "meeting_format": None, "timezone": "",
        "availability": {d: [] for d in DAYS}, "weekly_time": None,
        "skills": {k: None for k in SKILLS}, "roles": [], "leadership": None,
        "workstyle": {k: None for k in WORKSTYLE},
        "effort": None, "pace": None, "response_time": None,
        "prev_teammates": [], "preferred_teammate": "",
        "has_concern": False, "concern_student": "", "concern_text": "",
        "other_info": "", "custom": {},
    }
