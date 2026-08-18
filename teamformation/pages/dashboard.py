"""① Dashboard — at-a-glance course status and next actions."""
from __future__ import annotations

import streamlit as st

from .. import survey_service as svc
from .. import formation_service as fsvc


def render(ctx):
    st.subheader(f"{ctx.course or 'No course selected'}"
                 + (f" · {ctx.label}" if ctx.course else ""))
    if not ctx.course:
        st.info("Create or pick a course in the sidebar, then import your roster under "
                "**Course & Roster**.")
        return

    status = svc.response_status(ctx.vault, ctx.slug)
    total = len(status)
    active = [r for r in status if not r["excluded"]]
    got = sum(1 for r in status if r["responded"])
    final = fsvc.load_final(ctx.vault, ctx.slug)
    proposed = st.session_state.get(f"proposed::{ctx.slug}")

    m = st.columns(4)
    m[0].metric("Enrollment", total)
    m[1].metric("Survey responses", f"{got} / {total}")
    m[2].metric("Completion", f"{(100*got/total):.0f}%" if total else "—")
    m[3].metric("Excluded", total - len(active))

    m2 = st.columns(4)
    if proposed and proposed.get("teams"):
        diag = proposed.get("_diag", {})
        m2[0].metric("Proposed teams", len(proposed["teams"]))
        m2[1].metric("Formation quality", f"{diag.get('overall', '—')}/100")
        assigned = sum(len(t) for t in proposed["teams"])
        m2[2].metric("Unassigned", max(0, len(active) - assigned))
    else:
        m2[0].metric("Proposed teams", "—")
        m2[1].metric("Formation quality", "—")
        m2[2].metric("Unassigned", len(active))
    m2[3].metric("Finalized", "Yes" if final else "No")

    st.divider()
    st.markdown("##### Next actions")
    if total == 0:
        st.warning("No roster yet → open **Course & Roster** and import your students.")
        return
    missing = [r for r in status if not r["responded"] and not r["excluded"]]
    if missing:
        st.warning(f"{len(missing)} student(s) have not completed the survey → "
                   "**Responses** tab to send a reminder.")
    if not (proposed and proposed.get("teams")):
        st.info("Ready to build teams → **Design Teams** tab.")
    elif not final:
        st.info("Teams proposed but not finalized → review under **Finalize**.")
    else:
        st.success("Teams finalized. Send assignments under **Communicate**, or download "
                   "under **Export**.")
        st.caption(f"Finalized at {final.get('finalized_at')} (UTC).")
