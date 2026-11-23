"""④ Responses — completion dashboard, reminders, exclusions, data download."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import survey_service as svc
from ..survey_service import token_secret
from ..tokens import make_token
from ..ui_helpers import email_composer
from .. import email_delivery as mail
from ..ui_helpers import FULL_WIDTH, default_public_url

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
    if st.button("↻ Check for new responses", key="resp_refresh",
                 help="Stored data is re-read at most once a minute so clicks stay "
                      "fast. This re-reads it now."):
        vault.refresh(svc.response_prefixes(ctx.slug))
        st.rerun()
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
                 **FULL_WIDTH, height=320)
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
                                 or default_public_url(ctx.cfg),
                                 key="rem_url")
        secret = token_secret(ctx.cfg)
        sep = "&" if "?" in (base_url or "") else "?"
        course = ctx.course
        recips = []
        for r in nonresp:
            tok = make_token({"s": ctx.slug, "p": r["pos"]}, secret)
            recips.append({**r, "link": f"{base_url}{sep}t={tok}" if base_url else f"?t={tok}"})
        no_email = [r["name"] for r in recips if not r["email"]]
        if no_email:
            st.caption("No email address for: " + ", ".join(no_email[:10])
                       + ("…" if len(no_email) > 10 else ""))

        def _build(subj_t: str, body_t: str):
            out = []
            for r in recips:
                if not r["email"]:
                    continue
                cx = {"first_name": r["name"].split(" ")[0], "name": r["name"],
                      "class": course, "link": r["link"]}
                out.append(mail.Message(
                    to_email=r["email"], to_name=r["name"], team="",
                    subject=mail.render_template(subj_t, cx),
                    body=mail.render_template(body_t, cx), attachments=[]))
            return out

        first = recips[0]
        email_composer("rem", subject_default="Reminder: team-formation survey for {class}",
                       body_default=REMINDER, build=_build,
                       sample_ctx={"first_name": first["name"].split(" ")[0],
                                   "name": first["name"], "class": course,
                                   "link": first["link"]},
                       placeholders=["first_name", "name", "class", "link"], cfg=ctx.cfg,
                       survey_cfg=svc.load_survey(vault, ctx.slug), label="reminders",
                       subject_key="rem_subj")
