"""③ Survey — turn question blocks on/off, edit wording/majors, set the window."""
from __future__ import annotations

import datetime as dt

import streamlit as st

from .. import survey_service as svc
from ..survey_schema import (
    MAJORS, STANDINGS, SUBJECT_EXPERIENCE, WORK_EXPERIENCE, MEETING_FORMAT,
    TIMEZONES, DAYS, TIME_BLOCKS, WEEKLY_TIME, SKILLS, SKILL_SCALE, ROLES,
    LEADERSHIP, WORKSTYLE, WORKSTYLE_SCALE, EFFORT, PACE, RESPONSE_TIME,
)

_TOGGLES = [
    ("ask_section", "Course section"),
    ("ask_major", "Academic major/field"),
    ("ask_standing", "Academic standing"),
    ("ask_subject_exp", "Relevant subject-matter experience"),
    ("ask_work_exp", "Work/organizational experience"),
    ("ask_meeting_format", "Preferred meeting format"),
    ("ask_timezone", "Time zone"),
    ("ask_availability", "Weekly availability matrix"),
    ("ask_weekly_time", "Weekly time available"),
    ("ask_skills", "Skills self-ratings (9 areas)"),
    ("ask_roles", "Preferred contribution roles"),
    ("ask_leadership", "Leadership preference"),
    ("ask_workstyle", "Team work-style statements (8)"),
    ("ask_effort", "Desired effort level"),
    ("ask_pace", "Work pace"),
    ("ask_response_time", "Expected communication response time"),
    ("ask_prev_teammates", "Previous teammates"),
    ("ask_preferred_teammate", "Preferred teammate"),
    ("ask_concern", "Serious placement concern (instructor-only)"),
    ("ask_other_info", "Other relevant information"),
]


def _render_preview(cur):
    """Read-only rendering of the active survey questions and answer options."""
    def q(num, text, options=None):
        st.markdown(f"**Q{num}. {text}**")
        if options:
            st.markdown("\n".join(f"- {o}" for o in options))

    st.caption(cur.get("intro", ""))
    n = 1
    q(n, "Full name"); n += 1
    q(n, "Course email address"); n += 1
    if cur.get("ask_section", True):
        q(n, "Course section or class meeting time"); n += 1
    if cur.get("ask_major", True):
        q(n, "Primary academic major or field", cur.get("majors", MAJORS)); n += 1
    if cur.get("ask_standing", True):
        q(n, "Current academic standing", STANDINGS); n += 1
    if cur.get("ask_subject_exp", True):
        q(n, "Relevant subject-matter experience", SUBJECT_EXPERIENCE); n += 1
    if cur.get("ask_work_exp", True):
        q(n, "Work/organizational experience", WORK_EXPERIENCE); n += 1
    if cur.get("ask_meeting_format", True):
        q(n, "Preferred meeting format", MEETING_FORMAT); n += 1
    if cur.get("ask_timezone", True):
        q(n, "Time zone", TIMEZONES); n += 1
    if cur.get("ask_availability", True):
        q(n, "Weekly availability (select blocks per day)",
          [f"Days: {', '.join(DAYS)}", f"Blocks: {', '.join(TIME_BLOCKS)}"]); n += 1
    if cur.get("ask_weekly_time", True):
        q(n, "Weekly time available for team work", WEEKLY_TIME); n += 1
    if cur.get("ask_skills", True):
        q(n, "Rate current capability (1-5) in each area:",
          list(SKILLS.values()) + [f"Scale: {', '.join(SKILL_SCALE)}"]); n += 1
    if cur.get("ask_roles", True):
        q(n, "Preferred contribution roles (up to 3)", ROLES); n += 1
    if cur.get("ask_leadership", True):
        q(n, "Leadership preference", LEADERSHIP); n += 1
    if cur.get("ask_workstyle", True):
        q(n, "Work-style statements (1 Strongly disagree - 5 Strongly agree):",
          list(WORKSTYLE.values())); n += 1
    if cur.get("ask_effort", True):
        q(n, "Desired effort/performance level", EFFORT); n += 1
    if cur.get("ask_pace", True):
        q(n, "Natural work pace", PACE); n += 1
    if cur.get("ask_response_time", True):
        q(n, "Expected communication response time", RESPONSE_TIME); n += 1
    if cur.get("ask_prev_teammates", True):
        q(n, "Previous teammates (choose up to 3 classmates from the roster)"); n += 1
    if cur.get("ask_preferred_teammate", True):
        q(n, "Preferred teammate (choose one classmate from the roster — optional)"); n += 1
    if cur.get("ask_concern", True):
        q(n, "Serious placement concern? (Yes/No; if Yes, choose the classmate and "
          "explain — instructor-only)"); n += 1
    if cur.get("ask_other_info", True):
        q(n, "Other relevant non-sensitive information (optional)"); n += 1


def render(ctx):
    vault = ctx.vault
    st.subheader("Survey setup")
    if not ctx.course:
        st.info("Choose a course in the sidebar first.")
        return
    cur = svc.load_survey(vault, ctx.slug)

    with st.expander("👁 Preview the survey as students will see it", expanded=True):
        _render_preview(cur)

    with st.expander("Wording", expanded=False):
        cur["title"] = st.text_input("Title", cur.get("title", ""))
        cur["intro"] = st.text_area("Intro", cur.get("intro", ""), height=100)

    with st.expander("Question blocks — turn each on or off", expanded=True):
        st.caption("Switch a block off and students won't see it; the optimizer simply "
                   "skips criteria with no data.")
        cols = st.columns(2)
        for i, (key, label) in enumerate(_TOGGLES):
            cur[key] = cols[i % 2].checkbox(label, value=cur.get(key, True), key=f"t_{key}")

    with st.expander("Academic major categories (editable)"):
        text = st.text_area("One major per line", "\n".join(cur.get("majors", MAJORS)),
                            height=200)
        cur["majors"] = [ln.strip() for ln in text.splitlines() if ln.strip()]

    st.markdown("##### Availability & release")
    c1, c2 = st.columns(2)
    cur["allow_edit"] = c1.toggle("Let students reopen & edit before the deadline",
                                  value=cur.get("allow_edit", True))
    cur["release_teams"] = c2.toggle("Release final teams to students in-app",
                                     value=cur.get("release_teams", False),
                                     help="When on, a student opening their link sees their "
                                          "finalized team (after you finalize).")

    cur["is_open"] = st.toggle("Accept submissions (master switch)",
                               value=cur.get("is_open", True))
    with st.expander("Schedule — open / close dates (optional)"):
        st.caption(f"Server clock now: **{dt.datetime.now():%b %d, %Y %I:%M %p}**.")
        use_open = st.checkbox("Set an OPEN date", value=bool(cur.get("opens_at")))
        if use_open:
            o = svc.parse_dt(cur.get("opens_at")) or dt.datetime.now()
            a, b = st.columns(2)
            od = a.date_input("Opens on", o.date(), key="o_d")
            ot = b.time_input("Opens at", o.time().replace(microsecond=0), key="o_t")
            cur["opens_at"] = dt.datetime.combine(od, ot).isoformat()
        else:
            cur["opens_at"] = ""
        use_close = st.checkbox("Set a CLOSE date", value=bool(cur.get("closes_at")))
        if use_close:
            c = svc.parse_dt(cur.get("closes_at")) or (dt.datetime.now() + dt.timedelta(days=7))
            a, b = st.columns(2)
            cd = a.date_input("Closes on", c.date(), key="c_d")
            ct = b.time_input("Closes at", c.time().replace(microsecond=0), key="c_t")
            cur["closes_at"] = dt.datetime.combine(cd, ct).isoformat()
        else:
            cur["closes_at"] = ""

    state = svc.window_state(cur)
    badge = {"open": "🟢 Open", "not_yet": "🟡 Scheduled — not open yet",
             "closed": "🔴 Closed (past close date)",
             "disabled": "🔴 Closed (master switch off)"}[state]
    st.caption(f"Status for students: **{badge}** · {svc.window_message(cur)}")

    if st.button("💾 Save survey settings", type="primary"):
        snap = svc.load_roster_snapshot(vault, ctx.slug)
        if not snap:
            # persist config even before a roster exists
            from ..survey_service import key_survey, _save_json
            _save_json(vault, key_survey(ctx.slug), cur)
        else:
            from ..survey_service import key_survey, _save_json
            _save_json(vault, key_survey(ctx.slug), cur)
        st.success("Saved survey settings.")
