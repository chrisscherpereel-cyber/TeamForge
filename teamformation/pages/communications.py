"""⑦ Communicate — email students their finalized team assignment."""
from __future__ import annotations

import streamlit as st

from .. import formation_service as fsvc
from ..ui_helpers import build_assignment_messages, email_send_panel, email_body_editor
from .. import email_delivery as mail

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

    svy = ctx.vault and None  # placeholder to keep import graph obvious
    from .. import survey_service as svc
    survey = svc.load_survey(ctx.vault, ctx.slug)
    st.caption("Students " + ("**can** " if survey.get("release_teams") else "cannot ")
               + "currently view their team in-app when they open their survey link. "
               + ("" if survey.get("release_teams")
                  else "Enable “Release final teams” under **Survey** to turn that on."))

    subject = st.text_input("Subject", DEFAULT_SUBJECT)
    # sample values from the first real team, so the preview looks realistic
    _t0 = final["teams"][0] if final.get("teams") else {"name": "Team 1", "members": []}
    _m0 = _t0["members"][0] if _t0.get("members") else {"name": "Alex Johnson"}
    _sample = {"first_name": _m0["name"].split(" ")[0], "name": _m0["name"],
               "team": _t0.get("name", "Team 1"), "class": ctx.course,
               "members": "• " + "<br>• ".join(m["name"] for m in _t0.get("members", [])[:4]),
               "instructions": final.get("instructions", "")}
    body = email_body_editor("assign_body", DEFAULT_BODY, _sample, height=240)

    messages = build_assignment_messages(final, subject, body, ctx.course, ctx.label)
    n_no_email = sum(1 for t in final["teams"] for m in t["members"] if not m.get("email"))
    if n_no_email:
        st.warning(f"{n_no_email} student(s) have no email on file and will be skipped.")

    csv_rows = [{"Team": t["name"], "Student": m["name"], "Email": m.get("email", "")}
                for t in final["teams"] for m in t["members"]]
    email_send_panel("assign", messages, ctx.cfg, csv_rows=csv_rows, label="assignments")
