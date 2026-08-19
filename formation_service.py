"""Formation configuration, presets, and finalized-team persistence.

Keeps the instructor's weights/constraints, the current proposed configuration,
and the finalized teams. Finalized teams are versioned (a small history list) so
a re-finalize never silently destroys the previous assignment. Only
non-confidential fields (name, email, section, team) are persisted into the
finalized structure — survey answers and placement concerns never travel into a
team record, so student-facing views and exports stay clean.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import scoring
from .ingest import name_key
from .vault import Vault

# --------------------------------------------------------------------------- #
# Presets
# --------------------------------------------------------------------------- #
def _preset(**overrides) -> Dict[str, int]:
    w = scoring.default_weights()
    w.update(overrides)
    return w


PRESETS: Dict[str, Dict[str, int]] = {
    "Balanced Teams": _preset(),
    "Compatibility First": _preset(
        schedule=5, commitment=5, pace=4, response=4, meeting_format=4,
        major_diversity=1, skill_coverage=2, experience_balance=1,
        work_experience_balance=1, role_coverage=2, leadership=3),
    "Skill Diversity": _preset(
        skill_coverage=5, role_coverage=5, quant_balance=3, writing_balance=3,
        presentation_balance=3, research_balance=2, planning_balance=2,
        tech_balance=2, leadership=4, schedule=3),
    "Academic Diversity": _preset(
        major_diversity=5, experience_balance=5, work_experience_balance=4,
        skill_coverage=3, schedule=3),
    "Student Preference": _preset(
        preferred=4, role_coverage=4, avoid_repeats=4, schedule=3,
        major_diversity=2),
    "Instructor Custom": None,  # sentinel: use instructor-set weights
}

PRESET_NAMES = list(PRESETS.keys())


# --------------------------------------------------------------------------- #
# Storage keys
# --------------------------------------------------------------------------- #
def key_config(slug: str) -> str:
    return f"formcfg__{slug}.ppj"


def key_final(slug: str) -> str:
    return f"final__{slug}.ppj"


def key_proposed(slug: str) -> str:
    return f"proposed__{slug}.ppj"


def _save_json(vault: Vault, name: str, obj) -> None:
    vault.put_bytes(name, json.dumps(obj, default=str, ensure_ascii=False).encode("utf-8"))


def _load_json(vault: Vault, name: str):
    return json.loads(vault.get_bytes(name).decode("utf-8"))


# --------------------------------------------------------------------------- #
# Formation configuration (weights + constraints + team structure)
# --------------------------------------------------------------------------- #
def default_config() -> Dict:
    return {
        "preset": "Balanced Teams",
        "weights": scoring.default_weights(),
        "method": "linear",            # optimizer method (see optimizer.generate)
        "structure_mode": "size",      # "size" | "num_teams"
        "team_size": 4,
        "num_teams": 0,
        "same_section_only": False,
        "cannot_pairs": [],            # list of [nameA, nameB]
        "must_pairs": [],
        "seed": 0,
    }


def load_config(vault: Vault, slug: str) -> Dict:
    try:
        cfg = {**default_config(), **_load_json(vault, key_config(slug))}
        cfg["weights"] = {**scoring.default_weights(), **(cfg.get("weights") or {})}
        return cfg
    except Exception:
        return default_config()


def save_config(vault: Vault, slug: str, cfg: Dict) -> None:
    _save_json(vault, key_config(slug), cfg)


# --------------------------------------------------------------------------- #
# Serializing a proposed configuration
# --------------------------------------------------------------------------- #
def teams_to_records(teams: List[List[dict]], names: Optional[List[str]] = None,
                     locked: Optional[List[bool]] = None) -> List[Dict]:
    """Convert optimizer team lists into serializable, confidentiality-safe records."""
    out = []
    for i, team in enumerate(teams):
        out.append({
            "name": (names[i] if names and i < len(names) else f"Team {i + 1}"),
            "locked": bool(locked[i]) if locked and i < len(locked) else False,
            "members": [{"name": s.get("name", ""), "email": s.get("email", ""),
                         "section": s.get("section", ""), "pos": s.get("pos")}
                        for s in team],
        })
    return out


# --------------------------------------------------------------------------- #
# Finalization (versioned)
# --------------------------------------------------------------------------- #
def finalize(vault: Vault, slug: str, team_records: List[Dict],
             diagnostics: Dict, instructions: str = "",
             overridden: bool = False) -> Dict:
    prior = load_final(vault, slug)
    history = (prior or {}).get("history", []) if prior else []
    if prior:
        history = history + [{"finalized_at": prior.get("finalized_at"),
                              "teams": prior.get("teams")}]
        history = history[-10:]
    record = {
        "slug": slug,
        "finalized_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": team_records,
        "diagnostics": diagnostics,
        "instructions": instructions,
        "overridden": overridden,
        "history": history,
    }
    _save_json(vault, key_final(slug), record)
    return record


def save_proposed(vault: Vault, slug: str, design: Dict) -> None:
    """Persist the in-progress (unfinalized) design so a reload can restore it.
    Stores stable roster positions, not full survey records."""
    assignment = [[m.get("pos") for m in team] for team in design.get("teams", [])]
    _save_json(vault, key_proposed(slug), {
        "assignment": assignment,
        "names": design.get("names", []),
        "locked_teams": design.get("locked_teams", []),
        "locked_students": design.get("locked_students", {}),
        "seed": design.get("seed"),
    })


def load_proposed(vault: Vault, slug: str) -> Optional[Dict]:
    try:
        return _load_json(vault, key_proposed(slug))
    except Exception:
        return None


def rehydrate_proposed(saved: Dict, active_students: list) -> Optional[Dict]:
    """Rebuild a design dict (teams of full student records) from a saved
    position-based assignment and the current active roster."""
    if not saved:
        return None
    by_pos = {s.get("pos"): s for s in active_students}
    teams = []
    for team in saved.get("assignment", []):
        teams.append([by_pos[p] for p in team if p in by_pos])
    if not any(teams):
        return None
    names = saved.get("names") or [f"Team {i+1}" for i in range(len(teams))]
    locked = saved.get("locked_teams") or [False] * len(teams)
    # ensure lengths line up with rebuilt teams
    names = (names + [f"Team {i+1}" for i in range(len(teams))])[:len(teams)]
    locked = (list(locked) + [False] * len(teams))[:len(teams)]
    return {"teams": teams, "names": names, "locked_teams": locked,
            "locked_students": saved.get("locked_students", {}),
            "seed": saved.get("seed")}


def clear_proposed(vault: Vault, slug: str) -> None:
    try:
        vault.delete(key_proposed(slug))
    except Exception:
        pass


def load_final(vault: Vault, slug: str) -> Optional[Dict]:
    try:
        return _load_json(vault, key_final(slug))
    except Exception:
        return None


def clear_final(vault: Vault, slug: str) -> None:
    try:
        vault.delete(key_final(slug))
    except Exception:
        pass


def student_team_view(final: Dict, student_name: str) -> Optional[Dict]:
    """The confidentiality-safe view one student may see of their own team."""
    key = name_key(student_name)
    for team in final.get("teams", []):
        member_keys = [name_key(m["name"]) for m in team.get("members", [])]
        if key in member_keys:
            return {"team": team.get("name", ""),
                    "members": [{"name": m["name"], "email": m.get("email", "")}
                                for m in team.get("members", [])]}
    return None
