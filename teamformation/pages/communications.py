"""⑦ Communicate — email students their finalized team assignment."""
from __future__ import annotations

import streamlit as st

from .. import formation_service as fsvc
from ..ui_helpers import build_assignment_messages, email_composer

DEFAULT_SUBJECT = "Your team assignment for {class}"
DEFAULT_BODY = (
    "Hello {first_name},<br><br>"
    "You have been assigned to <b>{team}</b> for {class}.<br><br>"
    "Your team members are:<br>{members}<br><br>"
    "{instructions}<br><br>"
    "Please reach out to your teammates and begin coordinating your work.<br><br>"
    "Best,<br>The teaching team"
)


def render(ctx):
    st.subheader("Communicate assignments")
    final = fsvc.load_final(ctx.vault, ctx.slug)
    if not final:
        st.info("Finalize teams first (under **Finalize**).")
        return

    from .. import survey_service as svc
    survey = svc.load_survey(ctx.vault, ctx.slug)
    st.caption("Students " + ("**can** " if survey.get("release_teams") else "cannot ")
               + "currently view their team in-app when they open their survey link. "
               + ("" if survey.get("release_teams")
                  else "Enable “Release final teams” under **Survey** to turn that on."))

    # sample values from the first real team, so the preview looks realistic
    _t0 = final["teams"][0] if final.get("teams") else {"name": "Team 1", "members": []}
    _m0 = _t0["members"][0] if _t0.get("members") else {"name": "Alex Johnson"}
    from ..ui_helpers import _members_html
    _sample = {"first_name": _m0["name"].split(" ")[0],
               "last_name": _m0["name"].split(" ")[-1], "name": _m0["name"],
               "team": _t0.get("name", "Team 1"), "class": ctx.course,
               "project": ctx.label,
               "members": _members_html(_t0.get("members", []), _m0["name"]),
               "instructions": final.get("instructions", "") or ""}

    n_no_email = sum(1 for t in final["teams"] for m in t["members"] if not m.get("email"))
    if n_no_email:
        st.warning(f"{n_no_email} student(s) have no email on file and will be skipped.")

    course, label = ctx.course, ctx.label
    csv_rows = [{"Team": t["name"], "Student": m["name"], "Email": m.get("email", "")}
                for t in final["teams"] for m in t["members"]]
    email_composer("assign", subject_default=DEFAULT_SUBJECT, body_default=DEFAULT_BODY,
                   build=lambda s_t, b_t: build_assignment_messages(final, s_t, b_t,
                                                                    course, label),
                   sample_ctx=_sample,
                   placeholders=["first_name", "last_name", "name", "team", "members",
                                 "class", "project", "instructions"],
                   cfg=ctx.cfg, survey_cfg=survey, csv_rows=csv_rows,
                   label="assignments", subject_key="assign_subj")
