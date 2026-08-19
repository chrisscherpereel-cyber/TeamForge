"""④ Responses — completion dashboard, reminders, exclusions, data download."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import survey_service as svc
from ..survey_service import token_secret
from ..tokens import make_token
from ..ui_helpers import email_send_panel, email_body_editor
from .. import email_delivery as mail

REMINDER = (
    "Hi {first_name},<br><br>"
    "A quick reminder to complete the team-formation survey for {class}. It only "
    "takes a few minutes and I need it to place you on a team.<br><br>"
    '<a href="{link}">Open my survey</a><br><br>{link}<br><br>Thanks,<br>The teaching team'
)


def render(ctx):
    vault = ctx.vault
    st.subheader("Response monitoring")
    status = svc.response_status(vault, ctx.slug)
    if not status:
        st.info("No saved roster yet — import it under **Course & Roster**.")
        return

    total = len(status)
    active = [r for r in status if not r["excluded"]]
    got = sum(1 for r in status if r["responded"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Roster", total)
    m2.metric("Responses", f"{got} / {total}")
    m3.metric("Completion", f"{(100*got/total):.0f}%" if total else "—")
    m4.metric("Excluded", total - len(active))
    latest = svc.latest_submission(vault, ctx.slug)
    if latest:
        st.caption(f"Latest submission: **{latest}** (UTC)")

    svy = svc.load_survey(vault, ctx.slug)
    stt = svc.window_state(svy)
    badge = {"open": "🟢 Open", "not_yet": "🟡 Not open yet",
             "closed": "🔴 Closed", "disabled": "🔴 Closed (switch off)"}[stt]
    st.caption(f"Survey status: **{badge}** · {svc.window_message(svy)}")

    sdf = pd.DataFrame(status)
    sdf["status"] = sdf.apply(
        lambda r: "Excluded" if r["excluded"]
        else ("Responded" if r["responded"] else "No Survey Response"), axis=1)
    st.dataframe(sdf[["name", "email", "section", "status"]],
                 use_container_width=True, height=320)
    st.download_button("⬇ response-status.csv", sdf.to_csv(index=False),
                       f"{ctx.slug}_status.csv", "text/csv")

    # ---- Exclude / include a student ------------------------------------
    with st.expander("Exclude a student from team generation"):
        st.caption("Excluded students (e.g. withdrawn) are removed from generation but "
                   "keep their roster spot and link.")
        names = [f"{r['pos']} · {r['name']}"
                 + ("  (excluded)" if r["excluded"] else "") for r in status]
        pick = st.selectbox("Student", names, key="excl_pick") if names else None
        if pick:
            pos = int(pick.split(" · ", 1)[0])
            cur = status[[r["pos"] for r in status].index(pos)]["excluded"]
            if st.button("Include" if cur else "Exclude", key="excl_go"):
                svc.set_excluded(vault, ctx.slug, pos, not cur)
                st.rerun()

    # ---- Reminders to non-responders ------------------------------------
    nonresp = [r for r in status if not r["responded"] and not r["excluded"]]
    if nonresp:
        st.divider()
        st.markdown(f"##### {len(nonresp)} student(s) have not responded")
        base_url = st.text_input("Public app URL",
                                 st.session_state.get("inv_url")
                                 or getattr(ctx.cfg, "public_url", "") or "",
                                 key="rem_url")
        subj = st.text_input("Subject", "Reminder: team-formation survey for {class}",
                             key="rem_subj")
        body = email_body_editor("rem_body", REMINDER,
                                 {"first_name": "Alex", "class": ctx.course,
                                  "link": "https://…"})
        secret = token_secret(ctx.cfg)
        sep = "&" if "?" in (base_url or "") else "?"
        messages = []
        for r in nonresp:
            if not r["email"]:
                continue
            tok = make_token({"s": ctx.slug, "p": r["pos"]}, secret)
            link = f"{base_url}{sep}t={tok}" if base_url else f"?t={tok}"
            cx = {"first_name": r["name"].split(" ")[0], "class": ctx.course, "link": link}
            messages.append(mail.Message(
                to_email=r["email"], to_name=r["name"], team="",
                subject=mail.render_template(subj, cx),
                body=mail.render_template(body, cx), attachments=[]))
        email_send_panel("rem", messages, ctx.cfg, label="reminders")
