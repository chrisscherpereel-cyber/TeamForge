"""Survey + roster + response persistence for team formation.

Adapted from the original peer-evaluation survey module. The essential change:
students are **not** pre-assigned to teams, so the roster snapshot is a flat,
position-indexed list of students (not a team->members map). A student's
personal link encodes only (slug, position); positions are stable for the life
of the survey so links never break. New students are appended (keeping existing
positions); students can be marked excluded without reindexing.

Storage layout (every blob encrypted by the Vault before it leaves the process):

    survey__<slug>.ppj     the survey wording/config for one course+project
    roster__<slug>.ppj     the flat student roster snapshot (ordered, owner)
    resp__<slug>__p<pos>.ppj   one student's submission
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from .config import load_config
from .ingest import Roster, name_key
from .survey_schema import DEFAULT_SURVEY, DAYS, SKILLS, WORKSTYLE
from .tokens import make_token
from .vault import Vault


# --------------------------------------------------------------------------- #
# Open / close scheduling
# --------------------------------------------------------------------------- #
def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def window_state(survey_cfg: Dict) -> str:
    """One of 'open', 'not_yet', 'closed', 'disabled' for the survey right now."""
    if not survey_cfg.get("is_open", True):
        return "disabled"
    now = datetime.now()
    opens = parse_dt(survey_cfg.get("opens_at"))
    closes = parse_dt(survey_cfg.get("closes_at"))
    if opens and now < opens:
        return "not_yet"
    if closes and now > closes:
        return "closed"
    return "open"


def window_message(survey_cfg: Dict) -> str:
    state = window_state(survey_cfg)
    if state == "not_yet":
        opens = parse_dt(survey_cfg.get("opens_at"))
        return (f"This survey opens on {opens:%b %d, %Y at %I:%M %p}. Please come back then."
                if opens else "This survey isn't open yet.")
    if state in ("closed", "disabled"):
        return survey_cfg.get("closed_note", "This survey is now closed. Thank you.")
    closes = parse_dt(survey_cfg.get("closes_at"))
    return (f"Open now — closes {closes:%b %d, %Y at %I:%M %p}." if closes else "Open now.")


# --------------------------------------------------------------------------- #
# Slugs, secrets, storage keys
# --------------------------------------------------------------------------- #
def slugify(course: str, label: str) -> str:
    base = f"{course or 'course'}_{label or 'teams'}"
    return re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-") or "course-teams"


def token_secret(cfg=None) -> str:
    cfg = cfg or load_config()
    explicit = (getattr(cfg, "token_secret", "") or "").strip()
    if explicit:
        return explicit
    import hashlib
    seed = (getattr(cfg, "fernet_key", "") or "teamforge").encode("utf-8")
    return hashlib.sha256(b"teamforge-links:" + seed).hexdigest()


def key_survey(slug: str) -> str:
    return f"survey__{slug}.ppj"


def key_roster(slug: str) -> str:
    return f"roster__{slug}.ppj"


def key_response(slug: str, pos: int) -> str:
    return f"resp__{slug}__p{pos}.ppj"


def _resp_prefix(slug: str) -> str:
    return f"resp__{slug}__"


# --------------------------------------------------------------------------- #
# Encrypted JSON helpers (Vault encrypts on write / decrypts on read)
# --------------------------------------------------------------------------- #
def _save_json(vault: Vault, name: str, obj) -> None:
    vault.put_bytes(name, json.dumps(obj, default=str, ensure_ascii=False).encode("utf-8"))


def _load_json(vault: Vault, name: str):
    return json.loads(vault.get_bytes(name).decode("utf-8"))


# --------------------------------------------------------------------------- #
# Roster snapshot (flat, ordered list of students)
# --------------------------------------------------------------------------- #
def _contact_columns(df: pd.DataFrame):
    low = {str(c).lower().strip(): c for c in df.columns}

    def exact(cands):
        for cand in cands:
            if cand in low:
                return low[cand]
        return None

    def contains(cands):
        for cand in cands:
            for k, orig in low.items():
                if cand in k:
                    return orig
        return None

    full = exact(["name", "full name", "fullname", "student name", "student"])
    first = contains(["first name", "firstname", "first"])
    last = contains(["last name", "lastname", "last"])
    email = contains(["primaryemail", "email", "e-mail"])
    section = exact(["section", "sec"]) or contains(["section"])
    klass = exact(["class", "course", "class name"]) or contains(["class", "course"])
    return full, first, last, email, section, klass


def build_students(contact_df: pd.DataFrame) -> List[dict]:
    """Flat, de-duplicated, name-sorted list of student records from a roster."""
    full_c, first_c, last_c, email_c, section_c, class_c = _contact_columns(contact_df)
    out: List[dict] = []
    seen = set()
    for _, row in contact_df.iterrows():
        first = str(row.get(first_c, "")).strip() if first_c else ""
        last = str(row.get(last_c, "")).strip() if last_c else ""
        if full_c and pd.notna(row.get(full_c)) and str(row.get(full_c)).strip():
            name = str(row[full_c]).strip()
        else:
            name = f"{first} {last}".strip()
        if not name:
            continue
        key = name_key(name)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "name": name,
            "first": first or name.split(" ")[0],
            "last": last or name.split(" ")[-1],
            "email": str(row.get(email_c, "")).strip() if email_c else "",
            "section": str(row.get(section_c, "")).strip() if section_c else "",
            "excluded": False,
        })
    out.sort(key=lambda m: name_key(m["name"]))
    return out


def save_setup(course: str, label: str, contact_df: pd.DataFrame,
               survey_cfg: Dict, vault: Optional[Vault] = None,
               owner: Optional[str] = None):
    """Persist the roster snapshot + survey config. Preserves existing positions
    where students already exist; appends genuinely new students at the end."""
    vault = vault or Vault()
    slug = slugify(course, label)
    incoming = build_students(contact_df)
    existing = load_roster_snapshot(vault, slug)
    if existing and existing.get("students"):
        students = _merge_students(existing["students"], incoming)
        snap_owner = owner or existing.get("owner", "") or ""
    else:
        students = incoming
        snap_owner = owner or ""
    _save_json(vault, key_roster(slug),
               {"course": course, "label": label, "students": students, "owner": snap_owner})
    _save_json(vault, key_survey(slug), survey_cfg)
    return slug, students


def _merge_students(existing: List[dict], incoming: List[dict]) -> List[dict]:
    """Keep existing students (stable positions); append new ones; refresh email."""
    by_key = {name_key(s["name"]): i for i, s in enumerate(existing)}
    merged = [dict(s) for s in existing]
    for s in incoming:
        k = name_key(s["name"])
        if k in by_key:
            # refresh contact details but keep position + excluded flag
            cur = merged[by_key[k]]
            cur["email"] = s.get("email") or cur.get("email", "")
            cur["section"] = s.get("section") or cur.get("section", "")
        else:
            merged.append(dict(s))
    return merged


def set_excluded(vault: Vault, slug: str, pos: int, excluded: bool) -> None:
    snap = load_roster_snapshot(vault, slug)
    if not snap:
        return
    students = snap.get("students", [])
    if 0 <= pos < len(students):
        students[pos]["excluded"] = bool(excluded)
        _save_json(vault, key_roster(slug), snap)


def survey_owner(vault: Vault, slug: str) -> Optional[str]:
    snap = load_roster_snapshot(vault, slug)
    if snap is None:
        return None
    return snap.get("owner", "") or ""


def list_surveys(vault: Optional[Vault] = None):
    vault = vault or Vault()
    try:
        names = [n for n in vault.list()
                 if str(n).startswith("roster__") and str(n).endswith(".ppj")]
    except Exception:
        names = []
    out = []
    for n in names:
        try:
            snap = _load_json(vault, n)
        except Exception:
            continue
        students = snap.get("students", [])
        out.append({"slug": n[len("roster__"):-len(".ppj")],
                    "course": snap.get("course", ""), "label": snap.get("label", ""),
                    "owner": snap.get("owner", "") or "",
                    "students": len(students)})
    return sorted(out, key=lambda s: (s["course"], str(s["label"])))


def can_access(owner: Optional[str], user: Optional[dict]) -> bool:
    if user and user.get("role") == "admin":
        return True
    return bool(user) and bool(owner) and owner == user.get("user")


def visible_surveys(all_surveys, user: Optional[dict]):
    if user and user.get("role") == "admin":
        return all_surveys
    me = (user or {}).get("user")
    return [s for s in all_surveys if s.get("owner") == me]


def load_roster_snapshot(vault: Vault, slug: str) -> Optional[dict]:
    try:
        return _load_json(vault, key_roster(slug))
    except Exception:
        return None


def load_survey(vault: Vault, slug: str) -> Dict:
    try:
        return {**DEFAULT_SURVEY, **_load_json(vault, key_survey(slug))}
    except Exception:
        return dict(DEFAULT_SURVEY)


def roster_for_matching(snapshot: dict) -> Roster:
    r = Roster()
    for m in (snapshot or {}).get("students", []):
        r.by_key[name_key(m["name"])] = {
            "name": m["name"], "first": m.get("first", ""),
            "last": m.get("last", ""), "email": m.get("email", ""), "team": "",
        }
    return r


# --------------------------------------------------------------------------- #
# Links
# --------------------------------------------------------------------------- #
def student_links(base_url: str, slug: str, students: List[dict], secret: str) -> List[dict]:
    base = (base_url or "").strip()
    sep = "&" if "?" in base else "?"
    out = []
    for pos, m in enumerate(students):
        tok = make_token({"s": slug, "p": pos}, secret)
        link = f"{base}{sep}t={tok}" if base else f"?t={tok}"
        out.append({"pos": pos, "name": m["name"], "email": m.get("email", ""),
                    "link": link})
    return out


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #
def save_response(vault: Vault, slug: str, pos: int, payload: dict) -> None:
    _save_json(vault, key_response(slug, pos), payload)


def load_response(vault: Vault, slug: str, pos: int) -> Optional[dict]:
    try:
        return _load_json(vault, key_response(slug, pos))
    except Exception:
        return None


def all_responses(vault: Vault, slug: str) -> Dict[int, dict]:
    """Map position -> response payload for every submitted response."""
    prefix = _resp_prefix(slug)
    try:
        names = [n for n in vault.list() if str(n).startswith(prefix)]
    except Exception:
        names = []
    out: Dict[int, dict] = {}
    for n in names:
        m = re.search(r"__p(\d+)\.ppj$", str(n))
        if not m:
            continue
        try:
            out[int(m.group(1))] = _load_json(vault, n)
        except Exception:
            pass
    return out


def response_status(vault: Vault, slug: str) -> List[dict]:
    """Per-student responded/excluded rows for the monitoring dashboard."""
    snap = load_roster_snapshot(vault, slug)
    if not snap:
        return []
    got = set(all_responses(vault, slug).keys())
    rows = []
    for pos, m in enumerate(snap.get("students", [])):
        rows.append({"pos": pos, "name": m["name"], "email": m.get("email", ""),
                     "section": m.get("section", ""),
                     "excluded": bool(m.get("excluded", False)),
                     "responded": pos in got})
    return rows


def latest_submission(vault: Vault, slug: str) -> Optional[str]:
    times = [r.get("submitted") for r in all_responses(vault, slug).values()
             if r.get("submitted")]
    return max(times) if times else None


def load_students_for_formation(vault: Vault, slug: str) -> List[dict]:
    """Merge roster + responses into one record per active student, ready for the
    optimizer. Non-respondents are included (marked responded=False) so they stay
    assignable. Excluded students are dropped."""
    snap = load_roster_snapshot(vault, slug)
    if not snap:
        return []
    responses = all_responses(vault, slug)
    out = []
    for pos, m in enumerate(snap.get("students", [])):
        if m.get("excluded"):
            continue
        rec = {"pos": pos, "name": m["name"], "first": m.get("first", ""),
               "last": m.get("last", ""), "email": m.get("email", ""),
               "section": m.get("section", ""), "responded": pos in responses}
        resp = responses.get(pos, {})
        # copy every survey field through (missing -> None/empty)
        blank = {
            "major": "", "standing": "", "subject_exp": None, "work_exp": None,
            "meeting_format": None, "timezone": "",
            "availability": {d: [] for d in DAYS}, "weekly_time": None,
            "skills": {k: None for k in SKILLS}, "roles": [], "leadership": None,
            "workstyle": {k: None for k in WORKSTYLE}, "effort": None, "pace": None,
            "response_time": None, "prev_teammates": "", "preferred_teammate": "",
            "has_concern": False, "concern_text": "", "other_info": "",
        }
        for k, default in blank.items():
            rec[k] = resp.get(k, default) if resp else default
        # respondents may supply their own section/name
        if resp.get("section"):
            rec["section"] = resp["section"]
        out.append(rec)
    return out
