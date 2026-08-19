"""Exports: instructor datasets (CSV/Excel) and student-facing team lists.

The student-facing exports contain only names, team, and (optionally) emails —
never survey answers, skill ratings, or placement concerns. Instructor exports
are gated behind login and may include the full survey variables.
"""
from __future__ import annotations

import io
from typing import Dict, List, Optional

import pandas as pd

from .ingest import name_key
from .survey_schema import SKILLS, WORKSTYLE, DAYS


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _team_of(final: Optional[Dict]) -> Dict[str, str]:
    """name_key -> team name, from a finalized (or proposed) team record set."""
    out = {}
    if not final:
        return out
    for team in final.get("teams", []):
        for m in team.get("members", []):
            out[name_key(m["name"])] = team.get("name", "")
    return out


def _avail_count(rec: dict) -> int:
    avail = rec.get("availability") or {}
    return sum(len(avail.get(d, []) or []) for d in DAYS)


def _student_rows(students: List[dict], final: Optional[Dict],
                  include_concern: bool, custom_defs: Optional[List[dict]] = None) -> List[dict]:
    team_of = _team_of(final)
    custom_defs = custom_defs or []
    # stable set of extra roster columns across all students
    extra_keys = []
    for s in students:
        for k in (s.get("extra") or {}):
            if k not in extra_keys:
                extra_keys.append(k)
    rows = []
    for s in students:
        row = {
            "team": team_of.get(name_key(s["name"]), ""),
            "name": s.get("name", ""), "email": s.get("email", ""),
            "section": s.get("section", ""), "responded": s.get("responded", False),
            "major": s.get("major", ""), "standing": s.get("standing", ""),
            "subject_exp": s.get("subject_exp"), "work_exp": s.get("work_exp"),
            "meeting_format": s.get("meeting_format"), "timezone": s.get("timezone", ""),
            "avail_blocks": _avail_count(s), "weekly_time": s.get("weekly_time"),
            "leadership": s.get("leadership"), "effort": s.get("effort"),
            "pace": s.get("pace"), "response_time": s.get("response_time"),
            "roles": "; ".join(s.get("roles", []) or []),
        }
        for k in SKILLS:
            row[f"skill_{k}"] = (s.get("skills") or {}).get(k)
        for k in WORKSTYLE:
            row[f"ws_{k}"] = (s.get("workstyle") or {}).get(k)
        prev = s.get("prev_teammates", "")
        row["prev_teammates"] = "; ".join(prev) if isinstance(prev, (list, tuple)) else prev
        row["preferred_teammate"] = s.get("preferred_teammate", "")
        if include_concern:
            if s.get("has_concern"):
                who = s.get("concern_student", "")
                row["placement_concern"] = (f"[{who}] " if who else "") + s.get("concern_text", "")
            else:
                row["placement_concern"] = ""
            row["other_info"] = s.get("other_info", "")
        # preserved roster columns
        extra = s.get("extra") or {}
        for k in extra_keys:
            row[f"info_{k}"] = extra.get(k, "")
        # custom-question answers (keyed by label)
        custom = s.get("custom") or {}
        for q in custom_defs:
            v = custom.get(q.get("id"))
            row[q.get("label", q.get("id"))] = ("; ".join(map(str, v))
                                                if isinstance(v, (list, tuple)) else v)
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# CSV exports
# --------------------------------------------------------------------------- #
def student_dataset_csv(students: List[dict], final: Optional[Dict],
                        custom_defs: Optional[List[dict]] = None) -> str:
    """Full instructor-facing student dataset (includes placement concern)."""
    df = pd.DataFrame(_student_rows(students, final, include_concern=True,
                                    custom_defs=custom_defs))
    return df.to_csv(index=False)


def team_roster_csv(final: Dict) -> str:
    rows = []
    for team in final.get("teams", []):
        for m in team.get("members", []):
            rows.append({"Team": team.get("name", ""), "Student": m["name"],
                         "Email": m.get("email", "")})
    return pd.DataFrame(rows, columns=["Team", "Student", "Email"]).to_csv(index=False)


def student_facing_csv(final: Dict, include_email: bool = True) -> str:
    """Student-facing team list — no private survey information."""
    rows = []
    for team in final.get("teams", []):
        for m in team.get("members", []):
            row = {"Team": team.get("name", ""), "Student": m["name"]}
            if include_email:
                row["Email"] = m.get("email", "")
            rows.append(row)
    cols = ["Team", "Student"] + (["Email"] if include_email else [])
    return pd.DataFrame(rows, columns=cols).to_csv(index=False)


# --------------------------------------------------------------------------- #
# Excel workbook (multiple sheets)
# --------------------------------------------------------------------------- #
def workbook_xlsx(course: str, label: str, students: List[dict],
                  final: Optional[Dict], diagnostics: Optional[Dict],
                  config: Optional[Dict], custom_defs: Optional[List[dict]] = None) -> bytes:
    from . import scoring
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        # Final Teams
        team_rows = []
        if final:
            for team in final.get("teams", []):
                for m in team.get("members", []):
                    team_rows.append({"Team": team.get("name", ""),
                                      "Student": m["name"], "Email": m.get("email", ""),
                                      "Section": m.get("section", "")})
        pd.DataFrame(team_rows or [{"Team": "", "Student": "", "Email": "", "Section": ""}]
                     ).to_excel(xl, sheet_name="Final Teams", index=False)

        # Student Responses (instructor-facing, includes concern)
        pd.DataFrame(_student_rows(students, final, include_concern=True,
                                   custom_defs=custom_defs)
                     ).to_excel(xl, sheet_name="Student Responses", index=False)

        # Team Diagnostics
        diag_rows = []
        if diagnostics:
            diag_rows.append({"Metric": "Overall formation score",
                              "Value": diagnostics.get("overall")})
            for k, v in (diagnostics.get("components") or {}).items():
                crit = scoring.CRITERIA.get(k)
                diag_rows.append({"Metric": crit.label if crit else k, "Value": v})
        pd.DataFrame(diag_rows or [{"Metric": "", "Value": ""}]
                     ).to_excel(xl, sheet_name="Team Diagnostics", index=False)

        # Formation Settings
        set_rows = [{"Course": course, "Project": label}]
        if config:
            set_rows.append({"Course": "Preset", "Project": config.get("preset")})
            set_rows.append({"Course": "Structure",
                             "Project": f"{config.get('structure_mode')} = "
                             f"{config.get('team_size') if config.get('structure_mode')=='size' else config.get('num_teams')}"})
            set_rows.append({"Course": "Seed", "Project": config.get("seed")})
            for k, w in (config.get("weights") or {}).items():
                crit = scoring.CRITERIA.get(k)
                if crit and w:
                    set_rows.append({"Course": f"Weight: {crit.label}", "Project": w})
        pd.DataFrame(set_rows).to_excel(xl, sheet_name="Formation Settings", index=False)
    return buf.getvalue()
