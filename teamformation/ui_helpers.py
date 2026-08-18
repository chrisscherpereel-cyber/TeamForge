"""UI-side helpers: Graph/SMTP mailer wiring and team-assignment message building.

Reuses the original application's email_delivery layer (Message, batch_send,
Graph/SMTP mailers) unchanged; only the message *content* is new (team
assignments instead of feedback PDFs). No confidential survey data is ever put
into a student email.
"""
from __future__ import annotations

import io
import zipfile
from email.message import EmailMessage
from typing import Dict, List, Optional

import streamlit as st

from . import email_delivery as mail
from .config import AppConfig


def render_pdf(pdf_bytes: bytes) -> None:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in doc:
            pix = page.get_pixmap(dpi=120)
            st.image(pix.tobytes("png"), use_container_width=True)
        return
    except Exception:
        pass
    st.download_button("⬇ Download PDF", pdf_bytes, "preview.pdf", "application/pdf")


def _members_html(members: List[dict], exclude_name: str) -> str:
    lines = []
    for m in members:
        if m["name"] == exclude_name:
            continue
        line = m["name"]
        if m.get("email"):
            line += f" &lt;{m['email']}&gt;"
        lines.append("• " + line)
    return "<br>".join(lines) if lines else "(you are the only listed member)"


def build_assignment_messages(final: Dict, subject_t: str, body_t: str,
                              course: str, label: str) -> List[mail.Message]:
    """One email per student with their team name and teammates (no private data)."""
    messages: List[mail.Message] = []
    for team in final.get("teams", []):
        tname = team.get("name", "")
        for m in team.get("members", []):
            if not m.get("email"):
                continue
            ctx = {
                "first_name": m["name"].split(" ")[0],
                "last_name": m["name"].split(" ")[-1],
                "name": m["name"], "team": tname,
                "class": course, "project": label,
                "members": _members_html(team.get("members", []), m["name"]),
                "instructions": final.get("instructions", "") or "",
            }
            messages.append(mail.Message(
                to_email=m["email"], to_name=m["name"], team=tname,
                subject=mail.render_template(subject_t, ctx),
                body=mail.render_template(body_t, ctx), attachments=[]))
    return messages


def eml_zip(messages: List[mail.Message], sender: str = "") -> bytes:
    """Build a zip of .eml files the instructor can drag into their mail client."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, msg in enumerate(messages, 1):
            em = EmailMessage()
            em["To"] = msg.to_email
            em["Subject"] = msg.subject
            if sender:
                em["From"] = sender
            em.set_content("This message is best viewed as HTML.")
            em.add_alternative(msg.body, subtype="html")
            safe = msg.to_name.replace(" ", "_").replace("/", "-") or f"msg{i}"
            z.writestr(f"{i:03d}_{safe}.eml", em.as_bytes())
    return buf.getvalue()


def email_send_panel(key: str, messages: List[mail.Message], cfg: AppConfig,
                     csv_rows=None, label: str = "emails") -> None:
    """Reusable delivery UI: Microsoft 365 / SMTP send, or offline packs.
    `messages` already have subject/body rendered per recipient."""
    if not messages:
        st.info("No recipients with an email address.")
        return
    method = st.selectbox("How do you want to send?",
                          ["Microsoft 365 — send now", "SMTP — send now",
                           "Download .eml files", "Download recipients CSV"],
                          key=f"{key}_method")
    if method.startswith(("Microsoft", "SMTP")):
        mode = "graph" if method.startswith("Microsoft") else "smtp"
        drafts = False
        if mode == "graph":
            drafts = st.checkbox("Create Outlook drafts only (don't send yet)",
                                 value=True, key=f"{key}_drafts")
        if st.button("Send now", type="primary", key=f"{key}_go"):
            import dataclasses
            c = dataclasses.replace(cfg, email=dataclasses.replace(cfg.email, mode=mode))
            mailer = make_mailer(c)
            if mailer is not None:
                prog = st.progress(0.0); log = st.empty(); lines = []

                def _cb(i, total, status):
                    prog.progress(i / total)
                    lines.append(status)
                    log.code("\n".join(lines[-12:]))

                res = mail.batch_send(messages, mailer, drafts_only=drafts, progress=_cb)
                st.success(f"Sent {res['sent']}, drafted {res['drafted']}, "
                           f"failed {len(res['failed'])} of {res['total']}.")
                if res["failed"]:
                    import pandas as pd
                    st.dataframe(pd.DataFrame(res["failed"]))
    elif method.startswith("Download .eml"):
        if st.button("Build .eml zip", key=f"{key}_eml"):
            st.session_state[f"{key}_emlbytes"] = eml_zip(messages, cfg.email.sender)
        if st.session_state.get(f"{key}_emlbytes"):
            st.download_button("⬇ Download .eml zip", st.session_state[f"{key}_emlbytes"],
                               f"{label}_eml.zip", "application/zip")
    else:
        import pandas as pd
        rows = csv_rows or [{"To": m.to_email, "Subject": m.subject} for m in messages]
        st.download_button("⬇ Download recipients CSV", pd.DataFrame(rows).to_csv(index=False),
                           f"{label}_recipients.csv", "text/csv")


def make_mailer(cfg: AppConfig):
    """Return a ready mailer, driving the Graph device-code flow in the UI.
    (Reused from the original application.)"""
    if cfg.email.mode == "smtp":
        if not cfg.email.smtp_password:
            st.error("SMTP selected but no smtp_password in secrets.")
            return None
        return mail.SmtpMailer(cfg.email)

    m365 = cfg.m365
    tenant = m365.get("tenant_id", "")
    client = m365.get("client_id", "")
    if not tenant or not client:
        st.error("Graph mode needs vault.m365.tenant_id and client_id in secrets.")
        return None

    if "graph_mailer" not in st.session_state:
        st.session_state["graph_mailer"] = mail.GraphMailer(tenant, client, cfg.email.sender)
    gm: mail.GraphMailer = st.session_state["graph_mailer"]
    if gm.ready:
        return gm

    if "graph_flow" not in st.session_state:
        st.session_state["graph_flow"] = gm.begin_device_flow()
    flow = st.session_state["graph_flow"]
    st.info(flow.get("message", "Complete sign-in in your browser."))
    st.code(f"{flow.get('verification_uri')}\nCode: {flow.get('user_code')}")
    if st.button("I've completed sign-in"):
        if gm.complete_device_flow(flow):
            st.success("Microsoft 365 authenticated.")
            del st.session_state["graph_flow"]
            return gm
        st.error("Sign-in not completed yet — try again.")
    return None
