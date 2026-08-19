"""⑦ Communicate — email students their finalized team assignment."""
from __future__ import annotations

import streamlit as st

from .. import formation_service as fsvc
from ..ui_helpers import build_assignment_messages, email_send_panel
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
    body = st.text_area("Body (HTML). Placeholders: {first_name}, {team}, {members}, "
                        "{class}, {instructions}", DEFAULT_BODY, height=240)

    messages = build_assignment_messages(final, subject, body, ctx.course, ctx.label)
    n_no_email = sum(1 for t in final["teams"] for m in t["members"] if not m.get("email"))
    if n_no_email:
        st.warning(f"{n_no_email} student(s) have no email on file and will be skipped.")

    if messages:
        with st.expander("Live preview (first recipient)"):
            st.write("**Subject:** " + messages[0].subject)
            st.markdown(messages[0].body, unsafe_allow_html=True)

    csv_rows = [{"Team": t["name"], "Student": m["name"], "Email": m.get("email", "")}
                for t in final["teams"] for m in t["members"]]
    email_send_panel("assign", messages, ctx.cfg, csv_rows=csv_rows, label="assignments")
