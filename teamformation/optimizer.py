"""Team-formation optimizer (UI-independent, testable).

Approach: a feasible greedy construction followed by simulated-annealing local
search over student *swaps* between teams. Swaps preserve the chosen team-size
distribution, so the search explores composition without ever creating an
oversized or undersized team. Hard constraints (do-not-pair, must-be-together,
locked students/teams) are enforced on every move; section restrictions are
enforced structurally by solving each section as an independent subproblem. The
objective (from `scoring.objective`) is what annealing maximizes.

This scales comfortably to typical class sizes (tested to ~250 students) because
each move only re-scores the two affected teams.

Public API:
    team_size_distribution(n, size=None, num_teams=None) -> list[int]
    generate(students, weights, size=None, num_teams=None, ...) -> GenerationResult
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from . import scoring
from .ingest import name_key


# --------------------------------------------------------------------------- #
# Team-size distribution
# --------------------------------------------------------------------------- #
def team_size_distribution(n: int, size: Optional[int] = None,
                           num_teams: Optional[int] = None) -> List[int]:
    """Split `n` students into balanced team sizes.

    Given a target team size (or number of teams), compute the other and
    distribute the remainder so sizes differ by at most one — e.g. 23 with target
    size 5 -> [5, 5, 5, 4, 4] rather than a lone team of 3.
    """
    if n <= 0:
        return []
    if num_teams is None:
        size = size if (size and size > 0) else 4
        num_teams = max(1, round(n / size))
    num_teams = max(1, min(int(num_teams), n))
    base, rem = divmod(n, num_teams)
    sizes = [base + 1] * rem + [base] * (num_teams - rem)
    return sizes


# --------------------------------------------------------------------------- #
# Result + constraints
# --------------------------------------------------------------------------- #
@dataclass
class GenerationResult:
    teams: List[List[dict]]                 # each team = list of raw student dicts
    sizes: List[int]
    seed: int
    objective: int                          # 0-100
    weights: Dict[str, int]
    meta: Dict = field(default_factory=dict)


@dataclass
class Constraints:
    cannot_pairs: Set[frozenset] = field(default_factory=set)
    must_pairs: List[frozenset] = field(default_factory=list)


def normalize_pairs(pairs, students_by_key) -> Set[frozenset]:
    out = set()
    for a, b in pairs or []:
        ka, kb = name_key(a), name_key(b)
        if ka and kb and ka != kb and ka in students_by_key and kb in students_by_key:
            out.add(frozenset({ka, kb}))
    return out


def _must_adjacency(must_pairs) -> Dict[str, Set[str]]:
    adj: Dict[str, Set[str]] = {}
    for pair in must_pairs:
        ks = list(pair)
        if len(ks) == 2:
            adj.setdefault(ks[0], set()).add(ks[1])
            adj.setdefault(ks[1], set()).add(ks[0])
    return adj


# --------------------------------------------------------------------------- #
# Feasibility (do-not-pair only; sections handled by partitioning)
# --------------------------------------------------------------------------- #
def _feasible_team(idxs: List[int], parsed: List[dict], cons: Constraints) -> bool:
    for i in range(len(idxs)):
        for j in range(i + 1, len(idxs)):
            if frozenset({parsed[idxs[i]]["key"], parsed[idxs[j]]["key"]}) in cons.cannot_pairs:
                return False
    return True


def _must_ok(idxs: List[int], parsed: List[dict], must_adj: Dict[str, Set[str]]) -> bool:
    keys = {parsed[i]["key"] for i in idxs}
    for i in idxs:
        for partner in must_adj.get(parsed[i]["key"], ()):
            if partner not in keys:
                return False
    return True


# --------------------------------------------------------------------------- #
# Greedy feasible construction
# --------------------------------------------------------------------------- #
def _union_groups(keys: List[str], must_pairs: List[frozenset]) -> List[List[str]]:
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for pair in must_pairs:
        ks = list(pair)
        if len(ks) == 2 and ks[0] in parent and ks[1] in parent:
            parent[find(ks[0])] = find(ks[1])
    groups: Dict[str, List[str]] = {}
    for k in keys:
        groups.setdefault(find(k), []).append(k)
    return list(groups.values())


def _construct(block_idxs, parsed, sizes, cons, locked_pos, rng) -> List[List[int]]:
    teams: List[List[int]] = [[] for _ in sizes]
    key_to_idx = {parsed[i]["key"]: i for i in block_idxs}
    placed = set()

    for idx, t in locked_pos.items():
        if idx in block_idxs and 0 <= t < len(teams):
            teams[t].append(idx)
            placed.add(idx)

    groups = _union_groups([parsed[i]["key"] for i in block_idxs], cons.must_pairs)
    singles = []
    for grp in sorted(groups, key=len, reverse=True):
        idxs = [key_to_idx[k] for k in grp if k in key_to_idx and key_to_idx[k] not in placed]
        if not idxs:
            continue
        if len(idxs) == 1:
            singles.append(idxs[0])
            continue
        t = _best_team_for(teams, sizes, idxs, parsed, cons)
        for idx in idxs:
            teams[t].append(idx)
            placed.add(idx)

    rng.shuffle(singles)
    remaining = singles + [i for i in block_idxs if i not in placed and i not in singles]
    rng.shuffle(remaining)
    for idx in remaining:
        t = _best_team_for(teams, sizes, [idx], parsed, cons)
        teams[t].append(idx)
        placed.add(idx)
    return teams


def _best_team_for(teams, sizes, idxs, parsed, cons) -> int:
    need = len(idxs)
    candidates = []
    for t in range(len(teams)):
        if len(teams[t]) + need > sizes[t]:
            continue
        if _feasible_team(teams[t] + idxs, parsed, cons):
            candidates.append((len(teams[t]), t))
    if candidates:
        candidates.sort()
        return candidates[0][1]
    cap = [(len(teams[t]), t) for t in range(len(teams)) if len(teams[t]) + need <= sizes[t]]
    if cap:
        cap.sort()
        return cap[0][1]
    return min(range(len(teams)), key=lambda t: len(teams[t]))


# --------------------------------------------------------------------------- #
# Scoring cache
# --------------------------------------------------------------------------- #
def _team_num_den(idxs, parsed, weights):
    team = [parsed[i] for i in idxs]
    comps = scoring.team_component_scores(team, weights)
    num = den = 0.0
    size = len(team)
    for k, v in comps.items():
        if v is None:
            continue
        w = weights.get(k, 0)
        num += w * v * size
        den += w * size
    return num, den


# --------------------------------------------------------------------------- #
# Simulated annealing over swaps
# --------------------------------------------------------------------------- #
def _anneal(teams, parsed, weights, cons, must_adj, movable_mask,
            locked_team_mask, rng, iterations):
    nteams = len(teams)
    num = [0.0] * nteams
    den = [0.0] * nteams
    for t in range(nteams):
        num[t], den[t] = _team_num_den(teams[t], parsed, weights)

    def total():
        d = sum(den)
        return (sum(num) / d) if d else 0.0

    slots = [(t, k) for t in range(nteams) if not locked_team_mask[t]
             for k, idx in enumerate(teams[t]) if movable_mask[idx]]
    if len(slots) < 2 or iterations <= 0:
        return teams, round(100 * total())

    best_obj = cur = total()
    best = [list(t) for t in teams]
    T0, T1 = 0.20, 0.001
    for it in range(iterations):
        ta, ka = slots[rng.randrange(len(slots))]
        tb, kb = slots[rng.randrange(len(slots))]
        if ta == tb:
            continue
        ia, ib = teams[ta][ka], teams[tb][kb]
        new_a = list(teams[ta]); new_a[ka] = ib
        new_b = list(teams[tb]); new_b[kb] = ia
        if not _feasible_team(new_a, parsed, cons) or not _feasible_team(new_b, parsed, cons):
            continue
        if must_adj and (not _must_ok(new_a, parsed, must_adj)
                         or not _must_ok(new_b, parsed, must_adj)):
            continue
        na_num, na_den = _team_num_den(new_a, parsed, weights)
        nb_num, nb_den = _team_num_den(new_b, parsed, weights)
        new_sum_num = sum(num) - num[ta] - num[tb] + na_num + nb_num
        new_sum_den = sum(den) - den[ta] - den[tb] + na_den + nb_den
        new_obj = (new_sum_num / new_sum_den) if new_sum_den else 0.0
        delta = new_obj - cur
        T = T0 * ((T1 / T0) ** (it / iterations))
        if delta >= 0 or rng.random() < math.exp(delta / max(T, 1e-6)):
            teams[ta][ka] = ib
            teams[tb][kb] = ia
            num[ta], den[ta] = na_num, na_den
            num[tb], den[tb] = nb_num, nb_den
            cur = new_obj
            if cur > best_obj:
                best_obj = cur
                best = [list(t) for t in teams]
    return best, round(100 * best_obj)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def generate(students: List[dict], weights: Dict[str, int],
             size: Optional[int] = None, num_teams: Optional[int] = None,
             cannot_pairs=None, must_pairs=None, same_section_only: bool = False,
             locked_assignments: Optional[Dict[str, int]] = None,
             locked_teams: Optional[List[int]] = None,
             initial_teams: Optional[List[List[dict]]] = None,
             seed: Optional[int] = None, iterations: Optional[int] = None
             ) -> GenerationResult:
    """Generate teams. See module docstring for constraint semantics."""
    n = len(students)
    if seed is None:
        seed = random.randrange(1, 2**31 - 1)
    rng = random.Random(seed)

    if n == 0:
        return GenerationResult([], [], seed, 0, weights, {"n": 0})

    parsed = [scoring.parse_student(s) for s in students]
    by_key = {p["key"]: i for i, p in enumerate(parsed)}
    cons = Constraints(
        cannot_pairs=normalize_pairs(cannot_pairs, by_key),
        must_pairs=list(normalize_pairs(must_pairs, by_key)),
    )
    must_adj = _must_adjacency(cons.must_pairs)

    if iterations is None:
        iterations = min(max(3000, 250 * n), 80000)

    # ---- Regeneration from an existing configuration (keeps team count/sizes) --
    if initial_teams is not None:
        teams_idx = [[by_key[name_key(s["name"])] for s in t
                      if name_key(s["name"]) in by_key] for t in initial_teams]
        locked_assignments = {name_key(k): v for k, v in (locked_assignments or {}).items()}
        movable_mask = [True] * n
        for k, i in by_key.items():
            if k in locked_assignments:
                movable_mask[i] = False
        locked_team_mask = [False] * len(teams_idx)
        for t in (locked_teams or []):
            if 0 <= t < len(teams_idx):
                locked_team_mask[t] = True
        best, obj = _anneal(teams_idx, parsed, weights, cons, must_adj,
                            movable_mask, locked_team_mask, rng, iterations)
        result_teams = [[students[i] for i in team] for team in best]
        return GenerationResult(result_teams, [len(t) for t in best], seed, obj,
                                dict(weights), {"n": n, "regenerated": True})

    # ---- Partition into blocks: one per section when section-restricted -------
    if same_section_only and len({p["section"].strip() for p in parsed}) > 1:
        blocks: Dict[str, List[int]] = {}
        for i, p in enumerate(parsed):
            blocks.setdefault(p["section"].strip(), []).append(i)
    else:
        blocks = {"": list(range(n))}

    locked_assignments = {name_key(k): v for k, v in (locked_assignments or {}).items()}
    all_teams: List[List[int]] = []
    for _, block_idxs in sorted(blocks.items()):
        bn = len(block_idxs)
        if num_teams is not None and len(blocks) > 1:
            bteams = max(1, round(num_teams * bn / n))
            sizes = team_size_distribution(bn, num_teams=bteams)
        elif num_teams is not None:
            sizes = team_size_distribution(bn, num_teams=num_teams)
        else:
            sizes = team_size_distribution(bn, size=size)

        # locks only apply in the single-block (non-section) case
        locked_pos = {}
        if len(blocks) == 1:
            locked_pos = {by_key[k]: t for k, t in locked_assignments.items()
                          if k in by_key and 0 <= t < len(sizes)}

        teams_idx = _construct(block_idxs, parsed, sizes, cons, locked_pos, rng)
        movable_mask = [True] * n
        for idx in locked_pos:
            movable_mask[idx] = False
        best, _ = _anneal(teams_idx, parsed, weights, cons, must_adj,
                          movable_mask, [False] * len(teams_idx), rng, iterations)
        all_teams.extend(best)

    # Overall objective across the combined configuration
    parsed_teams = [[parsed[i] for i in t] for t in all_teams]
    obj = round(100 * scoring.objective(parsed_teams, weights))
    result_teams = [[students[i] for i in team] for team in all_teams]
    return GenerationResult(
        result_teams, [len(t) for t in all_teams], seed, obj, dict(weights),
        {"n": n, "iterations": iterations, "cannot_pairs": len(cons.cannot_pairs),
         "must_pairs": len(cons.must_pairs), "sections": len(blocks)})
