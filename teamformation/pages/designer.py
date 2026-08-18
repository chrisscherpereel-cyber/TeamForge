"""⑤ Design Teams — structure, criteria, generation, diagnostics, manual editing.

Every generation is a *proposed scenario* held in session state until the
instructor finalizes it. Diagnostics recompute on every render, so any manual
edit immediately updates the scores and warnings.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import survey_service as svc
from .. import formation_service as fsvc
from .. import scoring
from ..optimizer import generate, team_size_distribution
from ..ingest import name_key


# --------------------------------------------------------------------------- #
def _dstate(ctx):
    return st.session_state.setdefault(f"design::{ctx.slug}", {})


def _active_students(ctx):
    return svc.load_students_for_formation(ctx.vault, ctx.slug)


def render(ctx):
    st.subheader("Design teams")
    students = _active_students(ctx)
    n = len(students)
    if n < 2:
        st.info("Need at least two active students. Import a roster and collect responses.")
        return
    resp = sum(1 for s in students if s["responded"])
    st.caption(f"{n} active student(s) · {resp} with a survey response · "
               f"{n - resp} labeled **No Survey Response** (still assignable).")

    cfg = fsvc.load_config(ctx.vault, ctx.slug)

    # ---- Team structure --------------------------------------------------
    st.markdown("##### Team structure")
    c1, c2 = st.columns(2)
    mode = c1.radio("Choose by", ["Team size", "Number of teams"],
                    index=0 if cfg["structure_mode"] == "size" else 1, horizontal=True)
    if mode == "Team size":
        cfg["structure_mode"] = "size"
        cfg["team_size"] = int(c2.number_input("Target team size", 2, max(2, n),
                                               int(cfg.get("team_size", 4) or 4)))
        sizes = team_size_distribution(n, size=cfg["team_size"])
    else:
        cfg["structure_mode"] = "num_teams"
        cfg["num_teams"] = int(c2.number_input("Number of teams", 1, n,
                                               int(cfg.get("num_teams") or max(1, n // 4))))
        sizes = team_size_distribution(n, num_teams=cfg["num_teams"])
    st.caption(f"Proposed distribution: **{len(sizes)} teams** → sizes "
               f"{', '.join(map(str, sizes))}")

    # ---- Criteria & preset ----------------------------------------------
    st.markdown("##### Formation criteria")
    preset = st.selectbox("Preset", fsvc.PRESET_NAMES,
                          index=fsvc.PRESET_NAMES.index(cfg.get("preset", "Balanced Teams"))
                          if cfg.get("preset") in fsvc.PRESET_NAMES else 0)
    if preset != cfg.get("preset"):
        cfg["preset"] = preset
        if fsvc.PRESETS[preset] is not None:
            cfg["weights"] = dict(fsvc.PRESETS[preset])
    weights = dict(cfg.get("weights") or scoring.default_weights())
    with st.expander("Adjust weights (0 = ignore … 5 = very high)"):
        st.caption("Sliders override the preset (which switches to Instructor Custom).")
        changed = False
        for cat, title in [(scoring.MATCH, "Match within a team"),
                           (scoring.DIVERSIFY, "Diversify / cover across a team"),
                           (scoring.PREFERENCE, "Preferences")]:
            st.markdown(f"**{title}**")
            for key, crit in scoring.CRITERIA.items():
                if crit.category != cat:
                    continue
                nv = st.slider(crit.label, 0, 5, int(weights.get(key, crit.default)),
                               key=f"w_{key}")
                if nv != weights.get(key):
                    changed = True
                weights[key] = nv
        if changed:
            cfg["preset"] = "Instructor Custom"
    cfg["weights"] = weights

    # ---- Hard constraints ------------------------------------------------
    with st.expander("Hard constraints (do-not-pair, must-pair, sections)"):
        cfg["same_section_only"] = st.checkbox(
            "Keep students in the same section together (never mix sections)",
            value=cfg.get("same_section_only", False))
        names = [s["name"] for s in students]
        st.caption("Do-NOT-place-together (hard block) and must-be-together (hard link):")
        _pair_editor(cfg, "cannot_pairs", "⛔ Do not place together", names)
        _pair_editor(cfg, "must_pairs", "🔗 Must be together", names)

    fsvc.save_config(ctx.vault, ctx.slug, cfg)

    # ---- Generate --------------------------------------------------------
    st.markdown("##### Generate")
    g1, g2, g3 = st.columns([1, 1, 2])
    seed_in = g3.number_input("Random seed (0 = new each time)", 0, 2**31 - 1,
                              int(cfg.get("seed", 0) or 0))
    if g1.button("⚙️ Generate teams", type="primary"):
        _generate(ctx, students, cfg, sizes, mode, seed=(seed_in or None), fresh=True)
    if g2.button("🎲 Generate alternative"):
        _generate(ctx, students, cfg, sizes, mode, seed=None, fresh=True)

    design = _dstate(ctx)
    if not design.get("teams"):
        st.info("Set your structure and criteria, then generate teams.")
        return

    # keep the proposal current with any roster changes (assign new students)
    _reconcile_unassigned(design, students)

    weights = cfg["weights"]
    cannot = {frozenset({name_key(a), name_key(b)}) for a, b in cfg.get("cannot_pairs", [])}
    _render_diagnostics(design, weights, seed=design.get("seed"))
    _render_baseline_compare(ctx, design, weights)
    _render_teams(ctx, design, weights, cannot)
    _render_manual(ctx, design, students)

    # hand the proposal to Finalize
    st.session_state[f"proposed::{ctx.slug}"] = design


# --------------------------------------------------------------------------- #
# Generation + reconciliation
# --------------------------------------------------------------------------- #
def _generate(ctx, students, cfg, sizes, mode, seed, fresh):
    kwargs = dict(cannot_pairs=cfg.get("cannot_pairs"), must_pairs=cfg.get("must_pairs"),
                  same_section_only=cfg.get("same_section_only", False), seed=seed)
    if mode == "Team size":
        kwargs["size"] = cfg["team_size"]
    else:
        kwargs["num_teams"] = cfg["num_teams"]
    res = generate(students, cfg["weights"], **kwargs)
    d = _dstate(ctx)
    d["teams"] = [list(t) for t in res.teams]
    d["names"] = [f"Team {i+1}" for i in range(len(res.teams))]
    d["locked_teams"] = [False] * len(res.teams)
    d["locked_students"] = {}
    d["seed"] = res.seed
    cfg["seed"] = res.seed
    fsvc.save_config(ctx.vault, ctx.slug, cfg)
    st.success(f"Generated {len(res.teams)} teams (seed {res.seed}, score {res.objective}/100).")


def _reconcile_unassigned(design, students):
    assigned = {name_key(m["name"]) for t in design["teams"] for m in t}
    for s in students:
        if name_key(s["name"]) not in assigned:
            # place onto the smallest team so nobody is silently dropped
            smallest = min(range(len(design["teams"])), key=lambda i: len(design["teams"][i]))
            design["teams"][smallest].append(s)
    # drop anyone no longer active (excluded/removed)
    active_keys = {name_key(s["name"]) for s in students}
    for i, t in enumerate(design["teams"]):
        design["teams"][i] = [m for m in t if name_key(m["name"]) in active_keys]


# --------------------------------------------------------------------------- #
# Diagnostics
# --------------------------------------------------------------------------- #
def _parsed(design):
    return [[scoring.parse_student(m) for m in t] for t in design["teams"]]


def _render_diagnostics(design, weights, seed=None):
    parsed = _parsed(design)
    diag = scoring.configuration_diagnostics(parsed, weights)
    st.markdown("##### Formation quality")
    st.metric("Overall formation score", f"{diag['overall']} / 100")
    comps = diag["components"]
    if comps:
        items = list(comps.items())
        cols = st.columns(min(4, len(items)))
        for i, (k, v) in enumerate(items):
            crit = scoring.CRITERIA.get(k)
            cols[i % len(cols)].metric(crit.label if crit else k, f"{v}")
    # warnings
    warns = []
    for i, team in enumerate(parsed):
        warns.extend(scoring.team_warnings(team, design["names"][i]))
    if warns:
        st.markdown("**Warnings**")
        for w in warns:
            (st.error if w.startswith("⛔") else st.warning)(w)
    else:
        st.success("No warnings — no hard-constraint violations or coverage gaps detected.")
    design["_diag"] = diag


def _render_baseline_compare(ctx, design, weights):
    with st.expander("What-if: compare against a saved baseline"):
        c1, c2 = st.columns(2)
        if c1.button("📌 Save current as baseline"):
            st.session_state[f"baseline::{ctx.slug}"] = {
                "teams": [list(t) for t in design["teams"]],
                "diag": design.get("_diag")}
            st.success("Baseline saved. Change weights/size and regenerate to compare.")
        base = st.session_state.get(f"baseline::{ctx.slug}")
        if base and base.get("diag"):
            cur = design.get("_diag", {})
            rows = [{"Metric": "Overall", "Baseline": base["diag"]["overall"],
                     "Current": cur.get("overall"),
                     "Δ": cur.get("overall", 0) - base["diag"]["overall"]}]
            for k, v in (cur.get("components") or {}).items():
                crit = scoring.CRITERIA.get(k)
                bv = base["diag"]["components"].get(k)
                rows.append({"Metric": crit.label if crit else k,
                             "Baseline": bv, "Current": v,
                             "Δ": (v - bv) if bv is not None else None})
            c2.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------- #
# Team display
# --------------------------------------------------------------------------- #
def _profile(team):
    p = [scoring.parse_student(m) for m in team]

    def strong(skill):
        vals = [s["skills"].get(skill) for s in p if s["skills"].get(skill) is not None]
        if not vals:
            return "—"
        mx = max(vals)
        return "Strong" if mx >= 4 else ("Moderate" if mx >= 3 else "Limited")

    lead = [s["leadership"] for s in p if s["leadership"] is not None]
    sched = scoring.c_schedule(p)
    commit = scoring.c_commitment(p)
    return {
        "Quantitative": strong("quant"), "Writing": strong("writing"),
        "Presentation": strong("presentation"), "Technology": strong("tech"),
        "Leadership": "Covered" if (lead and max(lead) >= 4) else "None willing",
        "Schedule overlap": _band(sched), "Commitment alignment": _band(commit),
    }


def _band(v):
    if v is None:
        return "—"
    return "High" if v >= 0.66 else ("Moderate" if v >= 0.34 else "Low")


def _render_teams(ctx, design, weights, cannot):
    st.markdown("##### Proposed teams")
    for i, team in enumerate(design["teams"]):
        parsed = [scoring.parse_student(m) for m in team]
        wl = scoring.team_warnings(parsed, design["names"][i], cannot)
        flag = " ⚠️" if wl else ""
        with st.expander(f"**{design['names'][i]}** — {len(team)} members{flag}",
                         expanded=(len(design["teams"]) <= 6)):
            for m in team:
                p = scoring.parse_student(m)
                major = m.get("major") or ("no survey response" if not m.get("responded") else "—")
                st.write(f"• {m['name']} — {major}")
            prof = _profile(team)
            st.caption(" · ".join(f"{k}: **{v}**" for k, v in prof.items()))
            st.info(scoring.explain_team(parsed, design["names"][i]))
            if wl:
                for w in wl:
                    st.warning(w)


# --------------------------------------------------------------------------- #
# Manual editing + locking + regenerate
# --------------------------------------------------------------------------- #
def _render_manual(ctx, design, students):
    st.divider()
    st.markdown("##### Manual adjustments")
    teams = design["teams"]
    names = design["names"]
    tlabels = [f"{i}: {names[i]}" for i in range(len(teams))]
    student_labels = [f"{i}·{m['name']}" for i in range(len(teams)) for m in teams[i]]

    tab_move, tab_swap, tab_lock, tab_struct = st.tabs(
        ["Move / assign", "Swap", "Lock & regenerate", "Rename / add / delete"])

    with tab_move:
        c1, c2 = st.columns(2)
        who = c1.selectbox("Student", student_labels, key="mv_who") if student_labels else None
        to = c2.selectbox("Move to team", tlabels, key="mv_to") if tlabels else None
        if who and to and st.button("Move", key="mv_go"):
            ti = int(who.split("·", 1)[0]); nm = who.split("·", 1)[1]
            dest = int(to.split(":", 1)[0])
            _move(teams, ti, nm, dest)
            st.rerun()

    with tab_swap:
        c1, c2 = st.columns(2)
        a = c1.selectbox("Student A", student_labels, key="sw_a") if student_labels else None
        b = c2.selectbox("Student B", student_labels, key="sw_b") if student_labels else None
        if a and b and a != b and st.button("Swap", key="sw_go"):
            _swap(teams, a, b)
            st.rerun()

    with tab_lock:
        st.caption("Lock whole teams or individual students, then regenerate only the "
                   "unlocked students into the remaining slots.")
        for i in range(len(teams)):
            design["locked_teams"][i] = st.checkbox(
                f"Lock {names[i]}", value=design["locked_teams"][i], key=f"lockt_{i}")
        locked_students = st.multiselect(
            "Lock individual students in place",
            [m["name"] for t in teams for m in t],
            default=list(design.get("locked_students", {}).keys()), key="locks_ms")
        # map locked student -> current team index
        pos_of = {m["name"]: i for i in range(len(teams)) for m in teams[i]}
        design["locked_students"] = {nm: pos_of[nm] for nm in locked_students if nm in pos_of}
        cfg = fsvc.load_config(ctx.vault, ctx.slug)
        if st.button("🔁 Regenerate unlocked students", key="regen_go"):
            locked_assignments = {name_key(nm): idx
                                  for nm, idx in design["locked_students"].items()}
            res = generate(students, cfg["weights"], initial_teams=teams,
                           locked_teams=[i for i, v in enumerate(design["locked_teams"]) if v],
                           locked_assignments=locked_assignments,
                           cannot_pairs=cfg.get("cannot_pairs"),
                           must_pairs=cfg.get("must_pairs"), seed=None)
            design["teams"] = [list(t) for t in res.teams]
            st.success(f"Regenerated unlocked students (score {res.objective}/100).")
            st.rerun()

    with tab_struct:
        c1, c2 = st.columns(2)
        ren = c1.selectbox("Rename team", tlabels, key="rn_pick") if tlabels else None
        newname = c2.text_input("New name", key="rn_name")
        if ren and newname and st.button("Rename", key="rn_go"):
            names[int(ren.split(":", 1)[0])] = newname
            st.rerun()
        if st.button("➕ Add empty team", key="addteam"):
            teams.append([]); names.append(f"Team {len(teams)}")
            design["locked_teams"].append(False)
            st.rerun()
        empties = [f"{i}: {names[i]}" for i in range(len(teams)) if not teams[i]]
        if empties:
            de = st.selectbox("Delete empty team", empties, key="del_pick")
            if st.button("Delete", key="del_go"):
                di = int(de.split(":", 1)[0])
                teams.pop(di); names.pop(di); design["locked_teams"].pop(di)
                st.rerun()


def _move(teams, ti, name, dest):
    for k, m in enumerate(teams[ti]):
        if m["name"] == name:
            student = teams[ti].pop(k)
            teams[dest].append(student)
            return


def _swap(teams, a, b):
    ai, an = int(a.split("·", 1)[0]), a.split("·", 1)[1]
    bi, bn = int(b.split("·", 1)[0]), b.split("·", 1)[1]
    ak = next(k for k, m in enumerate(teams[ai]) if m["name"] == an)
    bk = next(k for k, m in enumerate(teams[bi]) if m["name"] == bn)
    teams[ai][ak], teams[bi][bk] = teams[bi][bk], teams[ai][ak]


def _pair_editor(cfg, field, label, names):
    st.markdown(f"**{label}**")
    pairs = cfg.setdefault(field, [])
    c1, c2, c3 = st.columns([2, 2, 1])
    a = c1.selectbox("Student", [""] + names, key=f"{field}_a")
    b = c2.selectbox("and", [""] + names, key=f"{field}_b")
    if c3.button("Add", key=f"{field}_add") and a and b and a != b:
        if [a, b] not in pairs and [b, a] not in pairs:
            pairs.append([a, b])
    for i, (x, y) in enumerate(list(pairs)):
        cc1, cc2 = st.columns([4, 1])
        cc1.write(f"— {x} ↔ {y}")
        if cc2.button("Remove", key=f"{field}_rm_{i}"):
            pairs.remove([x, y])
            st.rerun()
