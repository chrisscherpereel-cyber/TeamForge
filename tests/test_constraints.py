from teamformation.optimizer import generate
from teamformation.scoring import default_weights
from teamformation.ingest import name_key
from tests.synthetic import cohort, make_student


def _teams_of_keys(res):
    return [[name_key(m["name"]) for m in team] for team in res.teams]


def test_cannot_pairs_never_together():
    students = cohort(24)
    a, b = students[0]["name"], students[1]["name"]
    res = generate(students, default_weights(), size=4,
                   cannot_pairs=[(a, b)], seed=3, iterations=4000)
    for team in _teams_of_keys(res):
        assert not (name_key(a) in team and name_key(b) in team)


def test_multiple_cannot_pairs():
    students = cohort(30)
    pairs = [(students[0]["name"], students[1]["name"]),
             (students[2]["name"], students[3]["name"]),
             (students[0]["name"], students[4]["name"])]
    res = generate(students, default_weights(), size=5,
                   cannot_pairs=pairs, seed=7, iterations=6000)
    teams = _teams_of_keys(res)
    for a, b in pairs:
        for team in teams:
            assert not (name_key(a) in team and name_key(b) in team)


def test_must_pairs_together():
    students = cohort(24)
    a, b = students[5]["name"], students[6]["name"]
    res = generate(students, default_weights(), size=4,
                   must_pairs=[(a, b)], seed=2, iterations=4000)
    together = any(name_key(a) in team and name_key(b) in team
                   for team in _teams_of_keys(res))
    assert together


def test_same_section_only():
    students = [make_student(i, section=("A" if i < 12 else "B")) for i in range(24)]
    res = generate(students, default_weights(), size=4,
                   same_section_only=True, seed=5, iterations=5000)
    for team in res.teams:
        sections = {m["section"] for m in team}
        assert len(sections) == 1


def test_locked_student_stays_put():
    students = cohort(20)
    locked_name = students[0]["name"]
    res = generate(students, default_weights(), size=5,
                   locked_assignments={locked_name: 2}, seed=9, iterations=4000)
    # locked student must be on team index 2
    assert name_key(locked_name) in [name_key(m["name"]) for m in res.teams[2]]


def test_locked_team_membership_frozen_on_regenerate():
    students = cohort(20)
    first = generate(students, default_weights(), size=5, seed=1, iterations=3000)
    frozen_team = [dict(m) for m in first.teams[0]]
    frozen_keys = {name_key(m["name"]) for m in frozen_team}
    regen = generate(students, default_weights(), initial_teams=first.teams,
                     locked_teams=[0], seed=42, iterations=5000)
    assert {name_key(m["name"]) for m in regen.teams[0]} == frozen_keys
