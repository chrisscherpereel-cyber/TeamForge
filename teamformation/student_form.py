"""Public student survey — the only surface reachable without an instructor login.

Rendered by app.py when a valid ?t=<token> link is present. Presents the
team-formation survey in short, logical pages with a progress bar, preserves
answers across page navigation and across browser sessions (drafts are saved to
the encrypted vault), validates required fields, and lets the student review
before a final submit. Scrolls to the top of the page on every navigation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

import streamlit as st
import streamlit.components.v1 as components

from .config import load_config
from .ingest import name_key
from .survey_schema import (
    DAYS, TIME_BLOCKS, MEETING_FORMAT, TIMEZONES, WEEKLY_TIME, SKILLS,
    SKILL_SCALE, ROLES, LEADERSHIP, WORKSTYLE, WORKSTYLE_SCALE, EFFORT, PACE,
    RESPONSE_TIME, SUBJECT_EXPERIENCE, WORK_EXPERIENCE, STANDINGS,
)
from .survey_service import (
    load_roster_snapshot, load_survey, load_response, save_response,
    token_secret, window_state, window_message, parse_dt,
)
from .tokens import read_token
from .validation import submission_problems, normalize_roles, role_problems
from .vault import Vault


def _scroll_top(token: int) -> None:
    components.html(
        f"""<script>
        /* nav:{token} */
        (function() {{
          try {{
            var d = window.parent.document;
            window.parent.scrollTo(0, 0);
            ['section.main','[data-testid="stMain"]','[data-testid="stAppViewContainer"]']
              .forEach(function(s){{var e=d.querySelector(s); if(e) e.scrollTo(0,0);}});
          }} catch(e) {{}}
        }})();
        </script>""",
        height=0,
    )


def _scale_index(options: List[str], value) -> int | None:
    """value stored 1-based -> options index; None if unset."""
    if value in (None, "", 0):
        return None
    try:
        i = int(value) - 1
        return i if 0 <= i < len(options) else None
    except (TypeError, ValueError):
        return None


def render_student_app(token: str) -> None:
    cfg = load_config()
    payload = read_token(token, token_secret(cfg))
    if not payload:
        st.error("This link is invalid or has expired. Please contact your instructor.")
        return

    slug = payload.get("s", "")
    pos = int(payload.get("p", -1))

    vault = Vault()
    snap = load_roster_snapshot(vault, slug)
    survey = load_survey(vault, slug)
    if not snap:
        st.error("This survey isn't available right now. Please try again later.")
        return
    students = snap.get("students", [])
    if pos < 0 or pos >= len(students):
        st.error("This link doesn't match the current roster. Contact your instructor.")
        return
    me = students[pos]

    st.header(survey.get("title", "Team Formation Profile"))
    st.caption(f"{snap.get('course', '')} · {me['name']}")

    state = window_state(survey)
    if state != "open" and not st.session_state.get(f"tf_submitted::{slug}::{pos}"):
        (st.info if state == "not_yet" else st.warning)(window_message(survey))
        # still let a student view a released team assignment if enabled
        _maybe_show_team(survey, slug, pos, me)
        return

    # ---- working answers (session + vault draft) --------------------------
    akey = f"tf_ans::{slug}::{pos}"
    if akey not in st.session_state:
        prior = load_response(vault, slug, pos) or {}
        base = _blank_prefilled(me, snap)
        base.update({k: v for k, v in prior.items() if k in base})
        st.session_state[akey] = base
    A: Dict = st.session_state[akey]

    if survey.get("intro"):
        st.markdown(survey["intro"])

    pages = _active_pages(survey)
    seckey = f"tf_sec::{slug}::{pos}"
    idx = min(st.session_state.get(seckey, 0), len(pages) - 1)
    st.session_state[seckey] = idx

    st.progress((idx) / (len(pages) - 1) if len(pages) > 1 else 1.0,
                text=f"Section {idx + 1} of {len(pages)}: {pages[idx][1]}")
    _scroll_top(idx + 1000 * hash(slug) % 7)

    st.markdown(f"### {pages[idx][1]}")
    pages[idx][2](A, survey)   # render current section into A

    # ---- navigation --------------------------------------------------------
    st.markdown("---")
    cols = st.columns([1, 1, 2])
    if idx > 0 and cols[0].button("← Back"):
        _save_draft(vault, slug, pos, me, A)
        st.session_state[seckey] = idx - 1
        st.rerun()
    if idx < len(pages) - 1 and cols[1].button("Next →", type="primary"):
        _save_draft(vault, slug, pos, me, A)
        st.session_state[seckey] = idx + 1
        st.rerun()

    if idx == len(pages) - 1:
        _render_submit(vault, slug, pos, me, A, survey)


# --------------------------------------------------------------------------- #
# Section renderers — each reads/writes the shared answers dict A
# --------------------------------------------------------------------------- #
def _blank_prefilled(me: dict, snap: dict) -> Dict:
    from .survey_schema import blank_response
    b = blank_response()
    b["name"] = me.get("name", "")
    b["email"] = me.get("email", "")
    b["section"] = me.get("section", "")
    return b


def _sec_info(A, survey):
    A["name"] = st.text_input("Full name", A.get("name", ""))
    A["email"] = st.text_input("Course email address", A.get("email", ""))
    if survey.get("ask_section", True):
        A["section"] = st.text_input(
            "Course section or class meeting time (leave blank if only one section)",
            A.get("section", ""))
    if survey.get("ask_major", True):
        majors = survey.get("majors") or []
        A["major"] = st.selectbox("Primary academic major or field",
                                  [""] + majors,
                                  index=(majors.index(A["major"]) + 1
                                         if A.get("major") in majors else 0))
    if survey.get("ask_standing", True):
        A["standing"] = st.selectbox("Current academic standing", [""] + STANDINGS,
                                     index=(STANDINGS.index(A["standing"]) + 1
                                            if A.get("standing") in STANDINGS else 0))
    if survey.get("ask_subject_exp", True):
        A["subject_exp"] = _radio_scale(
            "Prior coursework/experience directly relevant to this course's subject",
            SUBJECT_EXPERIENCE, A.get("subject_exp"), "subj_exp")
    if survey.get("ask_work_exp", True):
        A["work_exp"] = _radio_scale(
            "Paid, internship, military, volunteer, or organizational work experience",
            WORK_EXPERIENCE, A.get("work_exp"), "work_exp")


def _sec_schedule(A, survey):
    if survey.get("ask_meeting_format", True):
        A["meeting_format"] = _radio_scale(
            "Preferred meeting format for team meetings outside class",
            MEETING_FORMAT, A.get("meeting_format"), "mfmt")
    if survey.get("ask_timezone", True):
        A["timezone"] = st.selectbox("Time zone you'll normally be in", [""] + TIMEZONES,
                                     index=(TIMEZONES.index(A["timezone"]) + 1
                                            if A.get("timezone") in TIMEZONES else 0))
    if survey.get("ask_availability", True):
        st.caption("Select every time block that is **usually workable** for each day. "
                   "Leave a day empty if you're generally unavailable.")
        avail = dict(A.get("availability") or {})
        for d in DAYS:
            avail[d] = st.multiselect(d, TIME_BLOCKS, default=avail.get(d, []),
                                      key=f"av_{d}")
        A["availability"] = avail
    if survey.get("ask_weekly_time", True):
        A["weekly_time"] = _radio_scale(
            "Realistic weekly time you can devote to team work outside class",
            WEEKLY_TIME, A.get("weekly_time"), "wtime")


def _sec_skills(A, survey):
    if survey.get("ask_skills", True):
        st.caption("Rate your **current** capability in each area (realistic present level).")
        skills = dict(A.get("skills") or {})
        for k, label in SKILLS.items():
            skills[k] = _radio_scale(label, SKILL_SCALE, skills.get(k), f"sk_{k}",
                                     compact=True)
        A["skills"] = skills
    if survey.get("ask_roles", True):
        st.markdown("**Preferred contribution roles**")
        st.caption("Choose up to three. If you truly have no preference, pick only "
                   "“No strong preference.”")
        chosen = st.multiselect("Roles you'd most like to play", ROLES,
                                default=A.get("roles", []), key="roles_ms")
        chosen = normalize_roles(chosen)
        A["roles"] = chosen
        for p in role_problems(chosen):
            st.warning(p)
    if survey.get("ask_leadership", True):
        A["leadership"] = _radio_scale(
            "Preference for taking a formal coordination / leadership role",
            LEADERSHIP, A.get("leadership"), "lead")


def _sec_workstyle(A, survey):
    if survey.get("ask_workstyle", True):
        st.caption("How accurately does each statement describe your typical approach?")
        ws = dict(A.get("workstyle") or {})
        for k, stmt in WORKSTYLE.items():
            ws[k] = _radio_scale(stmt, WORKSTYLE_SCALE, ws.get(k), f"ws_{k}",
                                 compact=True)
        A["workstyle"] = ws
    if survey.get("ask_effort", True):
        A["effort"] = _radio_scale("Level of effort/performance you want your team to pursue",
                                   EFFORT, A.get("effort"), "effort")
    if survey.get("ask_pace", True):
        A["pace"] = _radio_scale("Your natural work pace on team assignments",
                                 PACE, A.get("pace"), "pace")
    if survey.get("ask_response_time", True):
        A["response_time"] = _radio_scale(
            "Response time teammates can normally expect from you during the week",
            RESPONSE_TIME, A.get("response_time"), "resp")


def _sec_history(A, survey):
    if survey.get("ask_prev_teammates", True):
        A["prev_teammates"] = st.text_area(
            "Up to three classmates you've previously completed a substantial team "
            "project with (helps avoid repeats). One per line; leave blank if none.",
            A.get("prev_teammates", ""), height=90)
    if survey.get("ask_preferred_teammate", True):
        A["preferred_teammate"] = st.text_input(
            "OPTIONAL: one classmate you'd especially like to work with "
            "(a preference, not a guarantee)", A.get("preferred_teammate", ""))
    if survey.get("ask_concern", True):
        A["has_concern"] = st.radio(
            "Is there a serious prior team conflict or placement issue the instructor "
            "should know about? (Not for ordinary preferences.)",
            ["No", "Yes"], index=1 if A.get("has_concern") else 0,
            horizontal=True) == "Yes"
        if A["has_concern"]:
            st.caption("This response is treated as **instructor-only** information and is "
                       "never shown to other students or included in student-facing files.")
            A["concern_text"] = st.text_area(
                "Briefly describe the concern and identify the student involved.",
                A.get("concern_text", ""), height=90)
        else:
            A["concern_text"] = ""
    if survey.get("ask_other_info", True):
        A["other_info"] = st.text_area(
            "Any other NON-SENSITIVE information about your schedule, experience, or "
            "working preferences that would help form a workable team? Please do not "
            "include medical, disability, or other highly personal information.",
            A.get("other_info", ""), height=90)


def _sec_review(A, survey):
    st.caption("Review your answers below, then submit. You can go Back to change anything.")
    problems = submission_problems(A, survey)
    st.write(f"**Name:** {A.get('name','')}  ·  **Email:** {A.get('email','')}")
    if survey.get("ask_major", True):
        st.write(f"**Major:** {A.get('major','—')}  ·  **Standing:** {A.get('standing','—')}")
    if survey.get("ask_availability", True):
        avail = A.get("availability") or {}
        days = [d for d in DAYS if avail.get(d)]
        st.write("**Available days:** " + (", ".join(days) if days else "—"))
    if survey.get("ask_roles", True):
        st.write("**Preferred roles:** " + (", ".join(A.get("roles", [])) or "—"))
    if problems:
        st.error("**Before you can submit:**\n\n" + "\n".join(f"- {p}" for p in problems))
    else:
        st.success("Everything looks complete — you're ready to submit.")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _radio_scale(label, options, current, key, compact=False):
    idx = _scale_index(options, current)
    choice = st.radio(label, options, index=idx, key=key,
                      horizontal=compact and len(options) <= 5)
    return (options.index(choice) + 1) if choice in options else None


def _active_pages(survey):
    pages = [("info", "Student information", _sec_info)]
    if any(survey.get(f, True) for f in ("ask_meeting_format", "ask_timezone",
                                         "ask_availability", "ask_weekly_time")):
        pages.append(("schedule", "Schedule compatibility", _sec_schedule))
    if any(survey.get(f, True) for f in ("ask_skills", "ask_roles", "ask_leadership")):
        pages.append(("skills", "Skills & contribution", _sec_skills))
    if any(survey.get(f, True) for f in ("ask_workstyle", "ask_effort", "ask_pace",
                                         "ask_response_time")):
        pages.append(("workstyle", "Team work style", _sec_workstyle))
    if any(survey.get(f, True) for f in ("ask_prev_teammates", "ask_preferred_teammate",
                                         "ask_concern", "ask_other_info")):
        pages.append(("history", "Team history & preferences", _sec_history))
    pages.append(("review", "Review & submit", _sec_review))
    return pages


def _save_draft(vault, slug, pos, me, A):
    rec = dict(A)
    rec.update({"slug": slug, "pos": pos, "evaluator_key": name_key(me["name"]),
                "complete": False})
    try:
        save_response(vault, slug, pos, rec)
    except Exception:
        pass  # draft save is best-effort; session_state still holds answers


def _render_submit(vault, slug, pos, me, A, survey):
    problems = submission_problems(A, survey)
    if st.button("Submit survey", type="primary", disabled=bool(problems)):
        if window_state(survey) != "open":
            st.warning(window_message(survey))
            return
        rec = dict(A)
        rec.update({
            "slug": slug, "pos": pos, "name": A.get("name", me["name"]),
            "evaluator_key": name_key(me["name"]),
            "roles": normalize_roles(A.get("roles", [])),
            "submitted": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "complete": True,
        })
        try:
            save_response(vault, slug, pos, rec)
            st.session_state[f"tf_submitted::{slug}::{pos}"] = True
            st.success("Thank you — your survey has been recorded."
                       + (" You may reopen this link to update it until the survey closes."
                          if survey.get("allow_edit", True) else ""))
            st.balloons()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Sorry, we couldn't save your response: {exc}")


def _maybe_show_team(survey, slug, pos, me):
    """If the instructor has released teams, let the student see their assignment."""
    if not survey.get("release_teams"):
        return
    from .formation_service import load_final, student_team_view
    final = load_final(Vault(), slug)
    if not final:
        return
    view = student_team_view(final, me["name"])
    if view:
        st.success(f"You have been assigned to **{view['team']}**.")
        st.write("**Your teammates:**")
        for mate in view["members"]:
            line = mate["name"]
            if mate.get("email"):
                line += f" — {mate['email']}"
            st.write("- " + line)
        if final.get("instructions"):
            st.info(final["instructions"])
