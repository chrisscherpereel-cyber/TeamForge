"""Unit tests for the Design-Teams manual-edit helpers (no Streamlit)."""
from teamformation.pages.designer import _move, _swap, _reconcile_unassigned
from teamformation.ingest import name_key
from tests.synthetic import cohort


def _teams():
    students = cohort(8)
    return [students[:4], students[4:]], students


def test_move_between_teams():
    teams, students = _teams()
    name = teams[0][0]["name"]
    _move(teams, 0, name, 1)
    assert name not in [m["name"] for m in teams[0]]
    assert name in [m["name"] for m in teams[1]]
    assert len(teams[0]) == 3 and len(teams[1]) == 5


def test_swap_between_teams():
    teams, students = _teams()
    a = f"0·{teams[0][0]['name']}"
    b = f"1·{teams[1][0]['name']}"
    an, bn = teams[0][0]["name"], teams[1][0]["name"]
    _swap(teams, a, b)
    assert bn in [m["name"] for m in teams[0]]
    assert an in [m["name"] for m in teams[1]]


def test_reconcile_assigns_new_and_drops_removed():
    students = cohort(9)
    design = {"teams": [students[:4], students[4:8]]}  # student 8 unassigned
    _reconcile_unassigned(design, students)
    assigned = [name_key(m["name"]) for t in design["teams"] for m in t]
    assert len(assigned) == 9 and len(set(assigned)) == 9
    # now remove two students from the active list -> they should be dropped
    _reconcile_unassigned(design, students[:7])
    assigned = [name_key(m["name"]) for t in design["teams"] for m in t]
    assert len(assigned) == 7
