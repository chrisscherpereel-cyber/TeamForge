"""⑥ Finalize — confirm, check hard constraints, and persist the team set."""
from __future__ import annotations

import streamlit as st

from .. import formation_service as fsvc
from .. import scoring
from ..ingest import name_key


def _hard_violations(design, cfg):
    problems = []
    cannot = {frozenset({name_key(a), name_key(b)}) for a, b in cfg.get("cannot_pairs", [])}
    same_section = cfg.get("same_section_only", False)
    for i, team in enumerate(design["teams"]):
        keys = [name_key(m["name"]) for m in team]
        for x in range(len(keys)):
            for y in range(x + 1, len(keys)):
                if frozenset({keys[x], keys[y]}) in cannot:
                    problems.append(f"{design['names'][i]}: "
                                    f"{team[x]['name']} & {team[y]['name']} must not be paired.")
        if same_section:
            secs = {m.get("section", "").strip() for m in team if m.get("section", "").strip()}
            if len(secs) > 1:
                problems.append(f"{design['names'][i]} mixes sections {sorted(secs)}.")
    # must-pairs satisfied?
    for a, b in cfg.get("must_pairs", []):
        ka, kb = name_key(a), name_key(b)
        together = any(ka in [name_key(m["name"]) for m in t]
                       and kb in [name_key(m["name"]) for m in t]
                       for t in design["teams"])
        if not together:
            problems.append(f"{a} & {b} are required together but are on different teams.")
    return problems


def render(ctx):
    st.subheader("Finalize teams")
    design = st.session_state.get(f"proposed::{ctx.slug}")
    existing = fsvc.load_final(ctx.vault, ctx.slug)

    if not (design and design.get("teams")):
        if existing:
            _show_finalized(ctx, existing)
        else:
            st.info("Generate teams under **Design Teams** first.")
        return

    cfg = fsvc.load_config(ctx.vault, ctx.slug)
    teams = design["teams"]
    sizes = [len(t) for t in teams]
    parsed = [[scoring.parse_student(m) for m in t] for t in teams]
    diag = scoring.configuration_diagnostics(parsed, cfg["weights"])
    violations = _hard_violations(design, cfg)

    st.markdown("##### Pre-finalization summary")
    c = st.columns(4)
    c[0].metric("Teams", len(teams))
    c[1].metric("Sizes", ", ".join(map(str, sizes)))
    c[2].metric("Overall score", f"{diag['overall']}/100")
    c[3].metric("Hard-constraint issues", len(violations))

    # ensure everyone appears exactly once
    all_keys = [name_key(m["name"]) for t in teams for m in t]
    if len(all_keys) != len(set(all_keys)):
        st.error("A student appears on more than one team — fix under Design Teams before "
                 "finalizing.")
        return

    if violations:
        st.error("**Hard-constraint violations:**\n\n"
                 + "\n".join(f"- {v}" for v in violations))
        override = st.checkbox("Override and finalize anyway (I accept these violations)")
    else:
        st.success("No hard-constraint violations.")
        override = False

    instructions = st.text_area("Optional team instructions (shown/sent to students)",
                                (existing or {}).get("instructions", ""), height=100)

    disabled = bool(violations) and not override
    if st.button("✅ Finalize teams", type="primary", disabled=disabled):
        records = fsvc.teams_to_records(teams, design.get("names"),
                                        design.get("locked_teams"))
        rec = fsvc.finalize(ctx.vault, ctx.slug, records, diag,
                            instructions=instructions, overridden=bool(violations))
        st.success(f"Finalized {len(records)} teams at {rec['finalized_at']} (UTC).")
        st.balloons()

    if existing:
        st.divider()
        _show_finalized(ctx, existing)


def _show_finalized(ctx, final):
    st.markdown("##### Finalized teams")
    st.caption(f"Finalized at {final.get('finalized_at')} (UTC)"
               + (" · **overridden hard constraints**" if final.get("overridden") else ""))
    for team in final.get("teams", []):
        with st.expander(f"{team['name']} — {len(team['members'])} members"):
            for m in team["members"]:
                st.write(f"• {m['name']}"
                         + (f" — {m['email']}" if m.get("email") else ""))
    hist = final.get("history", [])
    if hist:
        st.caption(f"{len(hist)} previous finalized version(s) retained.")
    if st.button("↩ Reopen for editing (keeps this version in history)"):
        st.session_state[f"design::{ctx.slug}"] = st.session_state.get(
            f"design::{ctx.slug}", {})
        st.info("Reopened. Adjust under **Design Teams**, then finalize again to save a "
                "new version.")
