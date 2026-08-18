"""⑧ Export — instructor datasets and student-facing team lists."""
from __future__ import annotations

import streamlit as st

from .. import survey_service as svc
from .. import formation_service as fsvc
from .. import export_service as exp


def render(ctx):
    st.subheader("Export")
    students = svc.load_students_for_formation(ctx.vault, ctx.slug)
    if not students:
        st.info("No active students yet.")
        return
    final = fsvc.load_final(ctx.vault, ctx.slug)
    proposed = st.session_state.get(f"proposed::{ctx.slug}")

    # Prefer finalized teams; fall back to the current proposal for previews.
    team_source = final
    if not team_source and proposed and proposed.get("teams"):
        team_source = {"teams": fsvc.teams_to_records(proposed["teams"],
                                                      proposed.get("names"))}
        st.caption("Using the current (unfinalized) proposal for exports.")
    diag = (final or {}).get("diagnostics") or (proposed or {}).get("_diag")
    cfg = fsvc.load_config(ctx.vault, ctx.slug)

    st.markdown("##### Instructor exports (include survey variables)")
    c1, c2 = st.columns(2)
    c1.download_button("⬇ Student dataset (CSV)",
                       exp.student_dataset_csv(students, team_source),
                       f"{ctx.slug}_students.csv", "text/csv")
    c2.download_button("⬇ Full workbook (Excel)",
                       exp.workbook_xlsx(ctx.course, ctx.label, students, team_source,
                                         diag, cfg),
                       f"{ctx.slug}_teamforge.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.markdown("##### Team rosters")
    if team_source:
        c3, c4 = st.columns(2)
        c3.download_button("⬇ Team roster (CSV)", exp.team_roster_csv(team_source),
                           f"{ctx.slug}_team_roster.csv", "text/csv")
        include_email = c4.checkbox("Include emails on student-facing list", value=False)
        c4.download_button("⬇ Student-facing team list (CSV)",
                           exp.student_facing_csv(team_source, include_email),
                           f"{ctx.slug}_teams.csv", "text/csv")
        st.caption("The student-facing list contains only names and teams — no survey "
                   "answers, ratings, or placement concerns.")
    else:
        st.info("Generate or finalize teams to export rosters.")
