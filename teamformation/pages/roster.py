"""② Course & Roster — import the roster and send personal survey links."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import survey_service as svc
from .. import ingest
from ..survey_service import token_secret, student_links, build_students
from ..ui_helpers import email_send_panel
from .. import email_delivery as mail

DEFAULT_INVITE = (
    "Hi {first_name},<br><br>"
    "Please complete the short team-formation survey for {class}. It takes only a "
    "few minutes and helps me build balanced, workable teams. Open your personal "
    "link below — you can revise your answers until it closes.<br><br>"
    '<a href="{link}">Open my team-formation survey</a><br><br>'
    "If the button doesn't work, paste this address into your browser:<br>{link}"
    "<br><br>Thanks,<br>The teaching team"
)


def render(ctx):
    S, vault = ctx.S, ctx.vault
    st.subheader("Course & roster")
    if not ctx.course:
        st.info("Enter a course name and project in the sidebar to begin.")
        return
    st.caption(f"Course **{ctx.course}** · project **{ctx.label}** → id `{ctx.slug}`")

    st.markdown("##### 1. Import the roster")
    st.caption("Upload a CSV/XLSX with columns for first name, last name, email, and "
               "(optionally) section. Names/emails prepopulate each student's survey.")
    up = st.file_uploader("Roster (CSV/XLSX)", type=["csv", "xlsx", "xls"], key="roster_up")
    if up is not None:
        try:
            S[f"roster_df::{ctx.slug}"] = ingest.read_table(up, up.name)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Couldn't read that file: {exc}")

    df = S.get(f"roster_df::{ctx.slug}")
    existing = svc.load_roster_snapshot(vault, ctx.slug)
    if df is not None:
        preview = build_students(df)
        st.success(f"{len(preview)} student(s) parsed.")
        with st.expander("Preview parsed roster"):
            st.dataframe(pd.DataFrame(preview)[["name", "email", "section"]],
                         use_container_width=True, height=280)
        no_email = [m["name"] for m in preview if not m.get("email")]
        if no_email:
            st.warning(f"{len(no_email)} student(s) have no email and can't be emailed a "
                       "link: " + ", ".join(no_email[:8]) + ("…" if len(no_email) > 8 else ""))

    survey_cfg = svc.load_survey(vault, ctx.slug)
    stamp = ctx.user["user"] if (existing is None or not existing.get("owner")) else None
    if st.button("💾 Save roster to vault", type="primary", disabled=df is None):
        try:
            slug, students = svc.save_setup(ctx.course, ctx.label, df, survey_cfg, owner=stamp)
            st.success(f"Saved {len(students)} student(s). Survey links are live. "
                       + ("Existing positions were preserved and new students appended."
                          if existing else ""))
            S.pop(f"roster_df::{ctx.slug}", None)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Save failed: {exc}")

    if existing:
        st.caption(f"Saved roster: **{len(existing.get('students', []))} student(s)**.")

    # ---- Manual add (late-added students) --------------------------------
    if existing:
        with st.expander("Add a student manually (late add)"):
            c1, c2, c3 = st.columns(3)
            fn = c1.text_input("First name", key="add_fn")
            ln = c2.text_input("Last name", key="add_ln")
            em = c3.text_input("Email", key="add_em")
            sec = st.text_input("Section (optional)", key="add_sec")
            if st.button("Add student", key="add_student"):
                name = f"{fn} {ln}".strip()
                if not name:
                    st.error("Enter a name.")
                else:
                    add_df = pd.DataFrame([{"First Name": fn, "Last Name": ln,
                                            "Email": em, "Section": sec}])
                    svc.save_setup(ctx.course, ctx.label, add_df, survey_cfg,
                                   owner=None)
                    st.success(f"Added {name}. Their link is on the list below.")
                    st.rerun()

    # ---- Send links ------------------------------------------------------
    st.divider()
    st.markdown("##### 2. Send personal survey links")
    snap = svc.load_roster_snapshot(vault, ctx.slug)
    if not snap:
        st.info("Save the roster first, then send links here.")
        return
    base_url = st.text_input("Public app URL", getattr(ctx.cfg, "public_url", "") or "",
                             key="inv_url",
                             help="The deployed address, e.g. https://yourapp.streamlit.app")
    links = student_links(base_url, ctx.slug, snap["students"], token_secret(ctx.cfg))
    with st.expander(f"Preview {len(links)} links"):
        st.dataframe(pd.DataFrame(links)[["name", "email", "link"]],
                     use_container_width=True, height=260)
    subj = st.text_input("Email subject",
                         "Team-formation survey for {class}", key="inv_subj")
    body = st.text_area("Email body (HTML). Placeholders: {first_name}, {class}, {link}",
                        DEFAULT_INVITE, height=200, key="inv_body")
    if not base_url.strip():
        st.warning("Enter the public app URL so the links have a destination.")
    messages = []
    for r in links:
        if not r.get("email"):
            continue
        cx = {"first_name": r["name"].split(" ")[0], "name": r["name"],
              "class": ctx.course, "link": r.get("link", "")}
        messages.append(mail.Message(
            to_email=r["email"], to_name=r["name"], team="",
            subject=mail.render_template(subj, cx),
            body=mail.render_template(body, cx), attachments=[]))
    csv_rows = [{"Name": r["name"], "Email": r.get("email", ""), "Link": r["link"]}
                for r in links]
    email_send_panel("inv", messages, ctx.cfg, csv_rows=csv_rows, label="invitations")
