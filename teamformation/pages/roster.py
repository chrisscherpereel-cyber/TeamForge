"""② Course & Roster — templates, roster import (auto-saved & recalled), links."""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from .. import survey_service as svc
from .. import ingest
from ..survey_service import token_secret, student_links, build_students
from ..ui_helpers import email_send_panel, email_body_editor
from .. import email_delivery as mail

_TEMPLATE_COLS = ["First Name", "Last Name", "Email", "Section"]
_TEMPLATE_ROWS = [
    {"First Name": "Alex", "Last Name": "Johnson", "Email": "alex.johnson@school.edu", "Section": "A"},
    {"First Name": "Morgan", "Last Name": "Lee", "Email": "morgan.lee@school.edu", "Section": "A"},
]

DEFAULT_INVITE = (
    "Hi {first_name},<br><br>"
    "Please complete the short team-formation survey for {class}. It takes only a "
    "few minutes and helps me build balanced, workable teams. Open your personal "
    "link below — you can revise your answers until it closes.<br><br>"
    '<a href="{link}">Open my team-formation survey</a><br><br>'
    "If the button doesn't work, paste this address into your browser:<br>{link}"
    "<br><br>Thanks,<br>The teaching team"
)


def _template_bytes():
    df = pd.DataFrame(_TEMPLATE_ROWS, columns=_TEMPLATE_COLS)
    csv = df.to_csv(index=False).encode("utf-8")
    xbuf = io.BytesIO()
    with pd.ExcelWriter(xbuf, engine="openpyxl") as xl:
        df.to_excel(xl, index=False, sheet_name="Roster")
    return csv, xbuf.getvalue()


def render(ctx):
    S, vault = ctx.S, ctx.vault
    st.subheader("Course & roster")
    if not ctx.course:
        st.info("Enter a course name and project in the sidebar to begin.")
        return
    st.caption(f"Course **{ctx.course}** · project **{ctx.label}** → id `{ctx.slug}`")

    # ---- Templates -------------------------------------------------------
    st.markdown("##### 1. Download a roster template (optional)")
    st.caption("Fill in one row per student. Only First Name, Last Name, Email, and "
               "(optionally) Section are needed.")
    csv_b, xlsx_b = _template_bytes()
    t1, t2 = st.columns(2)
    t1.download_button("⬇ Template (.xlsx)", xlsx_b, "roster_template.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    t2.download_button("⬇ Template (.csv)", csv_b, "roster_template.csv", "text/csv")

    # ---- Import (auto-saved) --------------------------------------------
    st.markdown("##### 2. Import the roster")
    st.caption("Uploading **saves immediately** to the vault, so the roster is recalled "
               "automatically whenever you reopen this course.")
    survey_cfg = svc.load_survey(vault, ctx.slug)
    up = st.file_uploader("Roster (CSV/XLSX)", type=["csv", "xlsx", "xls"], key="roster_up")
    if up is not None:
        sig = f"{up.name}:{up.size}"
        if S.get(f"roster_sig::{ctx.slug}") != sig:
            try:
                df = ingest.read_table(up, up.name)
                existing = svc.load_roster_snapshot(vault, ctx.slug)
                stamp = ctx.user["user"] if (existing is None or not existing.get("owner")) else None
                slug, students = svc.save_setup(ctx.course, ctx.label, df, survey_cfg, owner=stamp)
                S[f"roster_sig::{ctx.slug}"] = sig
                st.success(f"Imported and saved {len(students)} student(s)."
                           + (" Existing positions were preserved and new students appended."
                              if existing else ""))
            except Exception as exc:  # noqa: BLE001
                st.error(f"Couldn't read/save that file: {exc}")

    # ---- Always show the saved roster (recalled from vault) --------------
    snap = svc.load_roster_snapshot(vault, ctx.slug)
    if snap and snap.get("students"):
        students = snap["students"]
        st.markdown(f"##### Saved roster — {len(students)} student(s)")
        st.caption("Recalled automatically from storage — all previously uploaded "
                   "information is preserved.")
        disp = []
        for s in students:
            row = {"name": s.get("name", ""), "email": s.get("email", ""),
                   "section": s.get("section", ""), "excluded": s.get("excluded", False)}
            row.update(s.get("extra", {}))   # preserved extra columns
            disp.append(row)
        st.dataframe(pd.DataFrame(disp), use_container_width=True, height=280)
        no_email = [m["name"] for m in students if not m.get("email")]
        if no_email:
            st.warning(f"{len(no_email)} student(s) have no email and can't be emailed a "
                       "link: " + ", ".join(no_email[:8]) + ("…" if len(no_email) > 8 else ""))

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
                    svc.save_setup(ctx.course, ctx.label, add_df, survey_cfg, owner=None)
                    st.success(f"Added {name}.")
                    st.rerun()
    else:
        st.info("No roster saved yet — upload one above.")
        return

    # ---- Send links ------------------------------------------------------
    st.divider()
    st.markdown("##### 3. Send personal survey links")
    base_url = st.text_input("Public app URL", getattr(ctx.cfg, "public_url", "") or "",
                             key="inv_url",
                             help="The deployed address, e.g. https://yourapp.streamlit.app")
    links = student_links(base_url, ctx.slug, snap["students"], token_secret(ctx.cfg))
    with st.expander(f"Preview {len(links)} links"):
        st.dataframe(pd.DataFrame(links)[["name", "email", "link"]],
                     use_container_width=True, height=260)
    subj = st.text_input("Email subject", "Team-formation survey for {class}", key="inv_subj")
    _sample = {"first_name": "Alex", "name": "Alex Johnson", "class": ctx.course,
               "link": (links[0]["link"] if links else "https://…")}
    body = email_body_editor("inv_body", DEFAULT_INVITE, _sample)
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
