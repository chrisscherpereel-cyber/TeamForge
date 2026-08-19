"""Team-quality scoring and diagnostics (UI-independent).

Defines the criteria the optimizer maximizes and the diagnostics the instructor
sees. Each criterion belongs to one of three philosophies:

  * DIVERSIFY  — the team should *cover* a spread (skills, roles, majors,
                 leadership). Concentrating strong people on one team is
                 penalized because it leaves other teams uncovered.
  * MATCH      — members should be *similar* (schedule, effort, pace,
                 communication responsiveness, meeting modality).
  * PREFERENCE — soft nudges (avoid repeat teammates, honor a requested one).

Hard constraints (do-not-pair, section, size) are enforced by the optimizer,
not scored here.

Every component function returns a value in [0, 1]; `component_scores` turns
those into 0-100 diagnostics and the weighted objective the optimizer uses.
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Optional

from .ingest import name_key
from .survey_schema import SKILLS, DAYS, TIME_BLOCKS, TZ_OFFSET, NO_PREF_ROLE

DIVERSIFY, MATCH, PREFERENCE = "diversify", "match", "preference"

# Skills treated as complementary capabilities to spread/cover across teams.
COVERAGE_SKILLS = ["quant", "excel", "research", "writing", "presentation",
                   "planning", "creative", "tech", "facilitation"]
_REF_OFFSET = -7  # Arizona reference for cross-timezone availability overlap


# --------------------------------------------------------------------------- #
# Feature parsing
# --------------------------------------------------------------------------- #
def _avail_slots(rec: dict) -> set:
    """Set of (day_idx, block_idx) normalized to the reference timezone."""
    avail = rec.get("availability") or {}
    tz = rec.get("timezone") or ""
    delta = TZ_OFFSET.get(tz, _REF_OFFSET) - _REF_OFFSET
    shift = round(delta / 3.0)
    slots = set()
    for di, day in enumerate(DAYS):
        for block in avail.get(day, []) or []:
            if block in TIME_BLOCKS:
                bi = TIME_BLOCKS.index(block) - shift
                bi = max(0, min(len(TIME_BLOCKS) - 1, bi))
                slots.add((di, bi))
    return slots


def parse_student(rec: dict) -> dict:
    """Normalize a raw survey/roster record into numeric features for scoring."""
    skills = rec.get("skills") or {}
    workstyle = rec.get("workstyle") or {}
    return {
        "pos": rec.get("pos"),
        "name": rec.get("name", ""),
        "key": name_key(rec.get("name", "")),
        "email": rec.get("email", ""),
        "section": rec.get("section", ""),
        "responded": bool(rec.get("responded", False)),
        "major": rec.get("major") or "",
        "subject_exp": _num(rec.get("subject_exp")),
        "work_exp": _num(rec.get("work_exp")),
        "meeting_format": _num(rec.get("meeting_format")),
        "weekly_time": _num(rec.get("weekly_time")),
        "leadership": _num(rec.get("leadership")),
        "effort": _num(rec.get("effort")),
        "pace": _num(rec.get("pace")),
        "response_time": _num(rec.get("response_time")),
        "skills": {k: _num(skills.get(k)) for k in SKILLS},
        "roles": [r for r in (rec.get("roles") or []) if r and r != NO_PREF_ROLE],
        "workstyle": {k: _num(v) for k, v in workstyle.items()},
        "slots": _avail_slots(rec),
        "prev": _name_list(rec.get("prev_teammates")),
        "preferred": name_key(rec.get("preferred_teammate") or "")
        if rec.get("preferred_teammate") else "",
    }


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _name_list(text) -> List[str]:
    """Accept either a list of names (new roster-dropdown format) or free text
    (legacy) and return normalized name keys."""
    if not text:
        return []
    if isinstance(text, (list, tuple, set)):
        return [name_key(str(t)) for t in text if str(t).strip()]
    parts = []
    for chunk in str(text).replace(",", "\n").splitlines():
        c = chunk.strip()
        if c:
            parts.append(name_key(c))
    return parts


# --------------------------------------------------------------------------- #
# Similarity / coverage primitives
# --------------------------------------------------------------------------- #
def _match_score(values: List[Optional[float]]) -> Optional[float]:
    """1 = identical, 0 = maximally spread, for 1-5 scale values. None if <2."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    return max(0.0, 1.0 - statistics.pstdev(vals) / 2.0)


def _pair_overlap(a: dict, b: dict) -> Optional[float]:
    if not a["slots"] and not a["responded"]:
        return None
    if not b["slots"] and not b["responded"]:
        return None
    inter = len(a["slots"] & b["slots"])
    return min(inter, 3) / 3.0


# --------------------------------------------------------------------------- #
# Component functions: team(list of parsed students) -> [0,1] or None
# --------------------------------------------------------------------------- #
def c_schedule(team, ctx=None):
    scores = []
    for i in range(len(team)):
        for j in range(i + 1, len(team)):
            ov = _pair_overlap(team[i], team[j])
            if ov is not None:
                scores.append(ov)
    return statistics.mean(scores) if scores else None


def c_meeting_format(team, ctx=None):
    return _match_score([s["meeting_format"] for s in team])


def c_major_diversity(team, ctx=None):
    majors = [s["major"] for s in team if s["major"]]
    if not majors:
        return None
    return len(set(majors)) / len(majors)


def _coverage_skill(team, key):
    vals = [s["skills"].get(key) for s in team]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return 1.0 if max(vals) >= 3 else max(vals) / 3.0


def c_skill_coverage(team, ctx=None):
    parts = [_coverage_skill(team, k) for k in COVERAGE_SKILLS]
    parts = [p for p in parts if p is not None]
    return statistics.mean(parts) if parts else None


def _skill_balance_one(team, key):
    return _coverage_skill(team, key)


def _make_skill_component(key):
    def fn(team, ctx=None):
        return _coverage_skill(team, key)
    return fn


def c_experience_balance(team, ctx=None):
    vals = [s["subject_exp"] for s in team if s["subject_exp"] is not None]
    if not vals:
        return None
    return 1.0 if max(vals) >= 3 else max(vals) / 3.0


def c_work_experience_balance(team, ctx=None):
    vals = [s["work_exp"] for s in team if s["work_exp"] is not None]
    if not vals:
        return None
    return 1.0 if max(vals) >= 3 else max(vals) / 3.0


def c_leadership(team, ctx=None):
    vals = [s["leadership"] for s in team if s["leadership"] is not None]
    if not vals:
        return None
    willing = sum(1 for v in vals if v >= 4)
    if willing == 0:
        return 0.0
    # one or two willing leaders is ideal; more is slightly less ideal
    return 1.0 if willing <= 2 else max(0.6, 1.0 - 0.15 * (willing - 2))


def c_role_coverage(team, ctx=None):
    roles = set()
    for s in team:
        roles.update(s["roles"])
    if not any(s["roles"] for s in team):
        return None
    target = min(len(team), 6)
    return min(1.0, len(roles) / target)


def c_commitment(team, ctx=None):
    return _match_score([s["effort"] for s in team])


def c_pace(team, ctx=None):
    return _match_score([s["pace"] for s in team])


def c_response(team, ctx=None):
    return _match_score([s["response_time"] for s in team])


def c_avoid_repeats(team, ctx=None):
    keys = {s["key"] for s in team}
    pairs = 0
    repeats = 0
    for i in range(len(team)):
        for j in range(i + 1, len(team)):
            pairs += 1
            a, b = team[i], team[j]
            if b["key"] in a["prev"] or a["key"] in b["prev"]:
                repeats += 1
    if pairs == 0:
        return None
    return 1.0 - repeats / pairs


def c_preferred(team, ctx=None):
    keys = {s["key"] for s in team}
    wanted = 0
    honored = 0
    for s in team:
        if s["preferred"]:
            wanted += 1
            if s["preferred"] in keys:
                honored += 1
    if wanted == 0:
        return None
    return honored / wanted


# --------------------------------------------------------------------------- #
# Criteria registry
# --------------------------------------------------------------------------- #
class Criterion:
    def __init__(self, key, label, category, default, fn):
        self.key = key
        self.label = label
        self.category = category
        self.default = default
        self.fn = fn


CRITERIA: Dict[str, Criterion] = {}


def _reg(key, label, cat, default, fn):
    CRITERIA[key] = Criterion(key, label, cat, default, fn)


_reg("schedule", "Schedule compatibility", MATCH, 4, c_schedule)
_reg("major_diversity", "Major diversity", DIVERSIFY, 3, c_major_diversity)
_reg("experience_balance", "Relevant experience balance", DIVERSIFY, 3, c_experience_balance)
_reg("work_experience_balance", "Work experience balance", DIVERSIFY, 2, c_work_experience_balance)
_reg("skill_coverage", "Overall skill coverage", DIVERSIFY, 4, c_skill_coverage)
_reg("quant_balance", "Quantitative skill coverage", DIVERSIFY, 0, _make_skill_component("quant"))
_reg("writing_balance", "Writing skill coverage", DIVERSIFY, 0, _make_skill_component("writing"))
_reg("presentation_balance", "Presentation skill coverage", DIVERSIFY, 0, _make_skill_component("presentation"))
_reg("research_balance", "Research skill coverage", DIVERSIFY, 0, _make_skill_component("research"))
_reg("planning_balance", "Project-management skill coverage", DIVERSIFY, 0, _make_skill_component("planning"))
_reg("tech_balance", "AI/technology skill coverage", DIVERSIFY, 0, _make_skill_component("tech"))
_reg("leadership", "Leadership distribution", DIVERSIFY, 4, c_leadership)
_reg("role_coverage", "Preferred-role coverage", DIVERSIFY, 3, c_role_coverage)
_reg("commitment", "Commitment similarity", MATCH, 3, c_commitment)
_reg("pace", "Work-pace similarity", MATCH, 2, c_pace)
_reg("response", "Communication-response similarity", MATCH, 2, c_response)
_reg("meeting_format", "Meeting-format compatibility", MATCH, 2, c_meeting_format)
_reg("avoid_repeats", "Avoid repeated teammates", PREFERENCE, 2, c_avoid_repeats)
_reg("preferred", "Honor preferred teammate", PREFERENCE, 1, c_preferred)


def default_weights() -> Dict[str, int]:
    return {k: c.default for k, c in CRITERIA.items()}


# Plain-English explanations shown behind the (?) on each diagnostic metric.
OVERALL_HELP = (
    "A 0-100 roll-up: the size-weighted average of every active criterion below, "
    "each weighted by the importance you set. 100 = every team scores perfectly on "
    "every criterion you care about. It measures fit to YOUR chosen criteria, not "
    "an absolute 'best' — reweighting changes it."
)

CRITERION_HELP: Dict[str, str] = {
    "schedule": "Average timezone-adjusted overlap of teammates' weekly availability "
                "blocks. Higher = teammates can actually meet at the same times.",
    "major_diversity": "Share of distinct majors within each team. Higher = a broader "
                       "mix of academic backgrounds per team.",
    "experience_balance": "Whether each team has at least one member with relevant "
                          "subject-matter experience (rated 3+). Higher = no team is "
                          "left without experience.",
    "work_experience_balance": "Whether each team includes someone with real work/"
                               "organizational experience. Higher = experience is spread, "
                               "not concentrated.",
    "skill_coverage": "Across the nine skills, the share for which each team has at least "
                      "one capable member (rated 3+). Higher = teams cover more skills.",
    "quant_balance": "Whether each team has a capable quantitative analyst (rated 3+).",
    "writing_balance": "Whether each team has a capable writer/editor (rated 3+).",
    "presentation_balance": "Whether each team has a capable presenter (rated 3+).",
    "research_balance": "Whether each team has a capable researcher (rated 3+).",
    "planning_balance": "Whether each team has a capable project manager/planner (rated 3+).",
    "tech_balance": "Whether each team has a capable AI/technology person (rated 3+).",
    "leadership": "Whether each team has at least one student willing to coordinate "
                  "(leadership 4+), without piling too many would-be leaders together.",
    "role_coverage": "Variety of distinct preferred contribution roles represented in each "
                     "team. Higher = broader role coverage.",
    "commitment": "Similarity of teammates' desired effort level. Higher = closer aligned "
                  "expectations, fewer effort mismatches.",
    "pace": "Similarity of teammates' natural work pace (early-starters vs. deadline-driven).",
    "response": "Similarity of teammates' expected communication response times.",
    "meeting_format": "Similarity of teammates' in-person vs. online meeting preferences.",
    "avoid_repeats": "Fraction of teammate pairs who have NOT worked together before. "
                     "Higher = fewer repeated pairings.",
    "preferred": "Fraction of students whose requested preferred teammate ended up on their "
                 "team. Higher = more honored preferences (a soft goal, never a guarantee).",
}


# --------------------------------------------------------------------------- #
# Team + configuration scoring
# --------------------------------------------------------------------------- #
def team_component_scores(team: List[dict], weights: Dict[str, int]) -> Dict[str, Optional[float]]:
    """Per-team component scores in [0,1] (None where not applicable), only for
    criteria with nonzero weight."""
    out = {}
    for key, crit in CRITERIA.items():
        if weights.get(key, 0) <= 0:
            continue
        out[key] = crit.fn(team)
    return out


def objective(teams: List[List[dict]], weights: Dict[str, int]) -> float:
    """Weighted average (0-1) across teams and active criteria — what the
    optimizer maximizes. Teams are weighted by size; missing components skipped."""
    num = 0.0
    den = 0.0
    for team in teams:
        comps = team_component_scores(team, weights)
        for key, val in comps.items():
            if val is None:
                continue
            w = weights.get(key, 0)
            num += w * val * len(team)
            den += w * len(team)
    return (num / den) if den else 0.0


def configuration_diagnostics(teams: List[List[dict]], weights: Dict[str, int]) -> Dict:
    """Overall score, per-criterion averages, and per-team component scores."""
    per_crit: Dict[str, List[float]] = {}
    team_scores = []
    for team in teams:
        comps = team_component_scores(team, weights)
        team_scores.append(comps)
        for key, val in comps.items():
            if val is not None:
                per_crit.setdefault(key, []).append(val)
    components = {key: round(100 * statistics.mean(vals))
                 for key, vals in per_crit.items() if vals}
    overall = round(100 * objective(teams, weights))
    return {"overall": overall, "components": components, "team_scores": team_scores}


# --------------------------------------------------------------------------- #
# Warnings + explanations
# --------------------------------------------------------------------------- #
def team_warnings(team: List[dict], team_name: str, cannot_pairs=None) -> List[str]:
    warns = []
    cannot_pairs = cannot_pairs or set()
    # quantitative capability
    q = [s["skills"].get("quant") for s in team if s["skills"].get("quant") is not None]
    if q and max(q) < 3:
        warns.append(f"{team_name} has no member rated 3+ in quantitative analysis.")
    # writing capability
    w = [s["skills"].get("writing") for s in team if s["skills"].get("writing") is not None]
    if w and max(w) < 3:
        warns.append(f"{team_name} has no strong writer (max writing rating below 3).")
    # leadership
    lead = [s["leadership"] for s in team if s["leadership"] is not None]
    if lead and max(lead) < 4:
        warns.append(f"{team_name} has no student willing to coordinate.")
    # schedule
    sched = c_schedule(team)
    if sched is not None and sched < 0.34:
        warns.append(f"{team_name} has poor schedule overlap.")
    # repeated teammates
    keys = [s["key"] for s in team]
    repeats = 0
    for i in range(len(team)):
        for j in range(i + 1, len(team)):
            if team[j]["key"] in team[i]["prev"] or team[i]["key"] in team[j]["prev"]:
                repeats += 1
    if repeats >= 2:
        warns.append(f"{team_name} contains multiple pairs who previously worked together.")
    elif repeats == 1:
        warns.append(f"{team_name} contains a pair who previously worked together.")
    # do-not-pair (hard constraint violation surfaced as a warning too)
    for i in range(len(team)):
        for j in range(i + 1, len(team)):
            pair = frozenset({team[i]["key"], team[j]["key"]})
            if pair in cannot_pairs:
                warns.append(f"⛔ {team_name} contains two students requested not to be "
                             f"paired: {team[i]['name']} & {team[j]['name']}.")
    return warns


def explain_team(team: List[dict], team_name: str) -> str:
    bits = []
    sched = c_schedule(team)
    if sched is not None and sched >= 0.6:
        bits.append("strong schedule overlap")
    cov = c_skill_coverage(team)
    if cov is not None and cov >= 0.7:
        bits.append("broad skill coverage")
    if c_commitment(team) and c_commitment(team) >= 0.7:
        bits.append("compatible effort expectations")
    lead = [s["leadership"] for s in team if s["leadership"] is not None]
    if lead and max(lead) >= 4:
        bits.append("a student willing to coordinate")
    majors = {s["major"] for s in team if s["major"]}
    if len(majors) >= max(2, len(team) - 1):
        bits.append("a diverse mix of majors")
    if not bits:
        return f"{team_name} was formed to balance the active criteria as evenly as possible."
    return f"{team_name} was recommended for its " + ", ".join(bits) + "."
