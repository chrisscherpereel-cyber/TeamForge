"""UI-side helpers: Graph/SMTP mailer wiring and team-assignment message building.

Reuses the original application's email_delivery layer (Message, batch_send,
Graph/SMTP mailers) unchanged; only the message *content* is new (team
assignments instead of feedback PDFs). No confidential survey data is ever put
into a student email.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from email.message import EmailMessage
from typing import Callable, Dict, Iterable, List, Optional

import streamlit as st

from . import email_delivery as mail
from .config import AppConfig


# Streamlit renamed `use_container_width=True` to `width="stretch"` and set a
# removal date for the old spelling that has now passed, while the older
# versions requirements.txt still allows only understand the old one. So the
# spelling is decided once, here, by asking the installed Streamlit which
# argument it takes — rather than shipping a call that a routine upgrade turns
# into a traceback, or dropping support for the older versions.
def _detect_width_kwargs() -> dict:
    try:
        import inspect
        if "width" in inspect.signature(st.button).parameters:
            return {"width": "stretch"}
    except Exception:  # noqa: BLE001
        pass
    return {"use_container_width": True}


FULL_WIDTH = _detect_width_kwargs()


def embed_html(markup: str) -> None:
    """Put a snippet of HTML/JS on the page, as invisibly as possible.

    `st.components.v1.html` is deprecated with a removal date that has passed,
    so a future Streamlit upgrade would break any page that calls it.
    `st.iframe` is the replacement, but it rejects the `height=0` the old call
    accepted, so the two cannot simply be swapped. Whichever is available is
    used; if neither works the only consequence is a missing nicety (e.g. the
    page does not scroll itself).
    """
    iframe = getattr(st, "iframe", None)
    if iframe is not None:
        try:
            iframe(markup, height=1)
            return
        except Exception:  # noqa: BLE001
            pass
    try:
        import streamlit.components.v1 as components
        components.html(markup, height=0)
    except Exception:  # noqa: BLE001
        pass


def this_app_url() -> str:
    """Where this page is open (no query string), or "" when unknown.
    See teamformation.webcontext."""
    try:
        from .webcontext import app_url
        return app_url(getattr(st, "context", None))
    except Exception:  # noqa: BLE001
        return ""


def default_public_url(cfg) -> str:
    """The address student links should point at: the configured public_url if
    one is set, otherwise the address the instructor is using right now."""
    return (getattr(cfg, "public_url", "") or "").strip() or this_app_url()


def note_if_elsewhere(base_url: str) -> None:
    """Say so when links would send students somewhere other than this app."""
    here = this_app_url()
    if here and base_url.strip() and base_url.strip().rstrip("/") != here:
        st.caption(f"ℹ️ Links will point to **{base_url.strip()}**, but you are using "
                   f"this app at **{here}** — students will be sent somewhere else.")


def as_fragment(fn):
    """`st.fragment` where this Streamlit has it, otherwise the plain function.

    A widget inside a fragment reruns only the fragment, not the whole page.
    That matters most for the email composers: the formatting toolbar reports
    the text 200 ms after every pause in typing, and each report used to rerun
    every tab — the team designer's diagnostics included — and grey the page
    out while it did. requirements.txt allows Streamlit from 1.36; `st.fragment`
    arrived in 1.37, hence the fallback. (From PeerParley_AI 2.19.2.)
    """
    frag = getattr(st, "fragment", None)
    return frag(fn) if callable(frag) else fn


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


# --------------------------------------------------------------------------- #
# Email composition (from PeerParley_AI 2.16.1 / 2.18.0 / 2.19.x)
# --------------------------------------------------------------------------- #
NOT_SCHEDULED = "TBA"
DATE_PLACEHOLDERS = {"open_date": "opens_at", "close_date": "closes_at"}

# Quill's toolbar, trimmed to what survives a real mail client. Fonts, colours
# and embedded media render badly in Outlook or are stripped, so they are left
# out rather than offered and silently lost.
TOOLBAR = [["bold", "italic", "underline"],
           [{"list": "ordered"}, {"list": "bullet"}],
           ["link"], ["clean"]]

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def when(value) -> str:
    """A schedule time as a student should read it: "Friday, November 20, 2026
    at 5:00 PM" — the weekday because that is how people remember a deadline,
    the time because "by Friday" alone is ambiguous. On the survey's own
    scheduling clock, so the email and the form agree."""
    from .survey_service import parse_dt
    d = parse_dt(value)
    if d is None:
        return ""
    hour = d.strftime("%I").lstrip("0") or "12"
    return f"{d:%A, %B} {d.day}, {d.year} at {hour}:{d:%M %p}"


def date_ctx(survey_cfg: Optional[dict]) -> Dict[str, str]:
    """{"open_date": …, "close_date": …} from the SAVED survey; TBA if unset."""
    cfg = survey_cfg or {}
    return {ph: (when(cfg.get(field)) or NOT_SCHEDULED)
            for ph, field in DATE_PLACEHOLDERS.items()}


def unknown_placeholders(templates: Iterable[str], known: Iterable[str]) -> List[str]:
    """Braced names nothing will fill in — `{firstname}` for `{first_name}`.
    Without this check they went out to every student exactly as typed."""
    known = set(known)
    found: List[str] = []
    for t in templates:
        for m in _PLACEHOLDER.finditer(t or ""):
            if m.group(1) not in known and m.group(1) not in found:
                found.append(m.group(1))
    return found


def date_warnings(templates: Iterable[str], survey_cfg: Optional[dict]) -> List[str]:
    """A date the message uses that the survey does not have would read "TBA"."""
    text = " ".join(t or "" for t in templates)
    out = []
    for ph, field in DATE_PLACEHOLDERS.items():
        if "{" + ph + "}" in text and not (survey_cfg or {}).get(field):
            what = "open" if ph == "open_date" else "close"
            out.append(f"The message uses `{{{ph}}}`, but the survey has no {what} date "
                       f"set — it would read **{NOT_SCHEDULED}**. Set the date under "
                       "**Survey → Schedule** and save, or remove the placeholder.")
    return out


def email_body_editor(key: str, default_html: str, sample_ctx: dict,
                      height: int = 200, placeholders: Iterable[str] = ()) -> str:
    """Write the email as it will look, with a rendered preview underneath.

    Uses the streamlit-quill editor (a core requirement, so it is there on
    Streamlit Cloud too) with a mail-safe toolbar; "Edit the HTML directly" is
    there for markup someone already has, and is the fallback if the editor
    cannot load. The stored and sent body is still HTML; the instructor just
    no longer has to write it.
    """
    names = list(placeholders) or ["first_name", "team", "members", "class", "link"]
    st.caption("Placeholders filled in per student: "
               + ", ".join("{" + n + "}" for n in names))
    html = None
    raw = st.checkbox("Edit the HTML directly", key=f"{key}_raw")
    if not raw:
        try:
            from streamlit_quill import st_quill
            html = st_quill(value=st.session_state.get(f"{key}_html", default_html),
                            html=True, toolbar=TOOLBAR, key=f"{key}_quill")
            html = html or st.session_state.get(f"{key}_html", default_html)
        except Exception:  # noqa: BLE001
            html = None
    if html is None:
        html = st.text_area("Email body (HTML)",
                            st.session_state.get(f"{key}_html", default_html),
                            height=height, key=f"{key}_ta")
    st.session_state[f"{key}_html"] = html
    with st.container(border=True):
        st.caption("Preview — as the first student receives it")
        st.markdown(mail.render_template(html, sample_ctx), unsafe_allow_html=True)
        with st.expander("Plain-text version"):
            from .webmail import plain_text
            st.text(plain_text(mail.render_template(html, sample_ctx)))
    return html


def _email_composer(key: str, *, subject_default: str, body_default: str,
                    build: Callable[[str, str], List[mail.Message]],
                    sample_ctx: dict, placeholders: List[str], cfg: AppConfig,
                    survey_cfg: Optional[dict] = None, csv_rows=None,
                    label: str = "emails", subject_label: str = "Subject",
                    subject_key: Optional[str] = None) -> None:
    """Subject, body, checks and delivery for one kind of email.

    Runs as a fragment: typing reruns only this composer — editor, preview,
    warnings and send options — not the whole app. Everything it needs from
    storage is read by the page and passed in (`build` closes over it), so an
    edit does no storage I/O at all.
    """
    dates = date_ctx(survey_cfg)
    subj = st.text_input(subject_label, subject_default, key=subject_key or f"{key}_subj")
    body = email_body_editor(f"{key}_body", body_default, {**sample_ctx, **dates},
                             placeholders=placeholders + list(DATE_PLACEHOLDERS))
    bad = unknown_placeholders([subj, body], list(placeholders) + list(DATE_PLACEHOLDERS))
    if bad:
        st.warning("Not a placeholder TeamForge fills in, so it would reach students "
                   "exactly as typed: " + ", ".join("`{" + b + "}`" for b in bad)
                   + ". The ones that work: "
                   + ", ".join("`{" + n + "}`" for n in placeholders + list(DATE_PLACEHOLDERS))
                   + ".", icon="⚠️")
    for w in date_warnings([subj, body], survey_cfg):
        st.warning(w, icon="📅")
    subj_t = mail.render_template(subj, dates)
    body_t = mail.render_template(body, dates)
    email_send_panel(key, build(subj_t, body_t), cfg, csv_rows=csv_rows, label=label)


email_composer = as_fragment(_email_composer)


def webmail_panel(key: str, messages: List[mail.Message]) -> None:
    """One "open in web mail" button per student, with a tick to keep count.

    For instructors who work in the browser and cannot get a Microsoft 365 app
    registration from IT. Nothing is sent from here: each button opens a
    pre-filled message in Outlook on the web or Gmail, in their own mailbox,
    and they press Send there. (From PeerParley_AI 2.19.0.)
    """
    from . import webmail
    provider = st.radio("Which web mail do you use?", list(webmail.PROVIDERS),
                        key=f"{key}_wm_p", horizontal=True,
                        captions=list(webmail.PROVIDERS.values()))
    st.caption("✓ Nothing is sent by this method. Each button opens a new message in "
               f"{provider}, in a new browser tab, with the address, subject and text "
               "filled in — read it and press **Send** there. Sign in to the right "
               "account first. The message is plain text: formatting is dropped, but "
               "every link is written out in full so it still works.")
    done = []
    for m in messages:
        tick = f"{key}_wm_sent_" + hashlib.sha1(
            m.to_email.strip().lower().encode()).hexdigest()[:12]
        done.append(tick)
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        c1.link_button(f"✉️ {m.to_name} — {m.to_email}",
                       webmail.compose_url(provider, m.to_email, m.subject, m.body),
                       **FULL_WIDTH)
        c2.checkbox("Sent", key=tick)
    n = sum(1 for k in done if st.session_state.get(k))
    st.caption(f"**{n} of {len(messages)}** ticked as sent. The ticks are only a "
               "checklist for this visit — they are not saved, and they don't check "
               "your mailbox.")


def email_send_panel(key: str, messages: List[mail.Message], cfg: AppConfig,
                     csv_rows=None, label: str = "emails") -> None:
    """Reusable delivery UI: Microsoft 365 / SMTP send, or offline packs.
    `messages` already have subject/body rendered per recipient."""
    if not messages:
        st.info("No recipients with an email address.")
        return
    method = st.selectbox("How do you want to send?",
                          ["Microsoft 365 — send now", "SMTP — send now",
                           "Open in web mail — Outlook or Gmail",
                           "Download auto-send scripts (Mac / Windows)",
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
            mailer = make_mailer(c, key=key)
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
    elif method.startswith("Open in web mail"):
        webmail_panel(key, messages)
    elif method.startswith("Download auto-send"):
        from . import emailpack
        if st.button("Build auto-send scripts", key=f"{key}_auto"):
            st.session_state[f"{key}_autobytes"] = emailpack.send_all_pack(messages, label)
        if st.session_state.get(f"{key}_autobytes"):
            st.download_button("⬇ Download auto-send zip", st.session_state[f"{key}_autobytes"],
                               f"{label}_autosend.zip", "application/zip",
                               key=f"{key}_autodl")
            st.caption("Unzip, then **double-click** `Send emails (Windows).cmd` on Windows "
                       "or `send_all_mac.applescript` on Mac. Sends from your own "
                       "Outlook / Apple Mail — no server setup needed.")
    elif method.startswith("Download .eml"):
        from . import emailpack
        if st.button("Build .eml zip", key=f"{key}_eml"):
            st.session_state[f"{key}_emlbytes"] = emailpack.eml_zip(messages, label)
        if st.session_state.get(f"{key}_emlbytes"):
            st.download_button("⬇ Download .eml zip", st.session_state[f"{key}_emlbytes"],
                               f"{label}_eml.zip", "application/zip", key=f"{key}_emldl")
    else:
        import pandas as pd
        rows = csv_rows or [{"To": m.to_email, "Subject": m.subject} for m in messages]
        st.download_button("⬇ Download recipients CSV", pd.DataFrame(rows).to_csv(index=False),
                           f"{label}_recipients.csv", "text/csv", key=f"{key}_csvdl")


def make_mailer(cfg: AppConfig, key: str = "mail"):
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
    if st.button("I've completed sign-in", key=f"{key}_graph_done"):
        if gm.complete_device_flow(flow):
            st.success("Microsoft 365 authenticated.")
            del st.session_state["graph_flow"]
            return gm
        st.error("Sign-in not completed yet — try again.")
    return None
