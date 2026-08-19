import pytest

from teamformation.optimizer import team_size_distribution, generate
from teamformation.scoring import default_weights
from tests.synthetic import cohort


@pytest.mark.parametrize("n", [11, 17, 23, 31, 50, 101])
@pytest.mark.parametrize("size", [3, 4, 5])
def test_distribution_sums_and_balances(n, size):
    sizes = team_size_distribution(n, size=size)
    assert sum(sizes) == n
    assert max(sizes) - min(sizes) <= 1          # balanced
    assert all(s >= 1 for s in sizes)


def test_23_size5_avoids_tiny_team():
    assert sorted(team_size_distribution(23, size=5), reverse=True) == [5, 5, 5, 4, 4]


def test_num_teams_mode():
    sizes = team_size_distribution(50, num_teams=7)
    assert sum(sizes) == 50
    assert len(sizes) == 7
    assert max(sizes) - min(sizes) <= 1


def test_enrollment_smaller_than_team_size():
    # 3 students, target size 5 -> one team of 3 (not an empty/oversized mess)
    sizes = team_size_distribution(3, size=5)
    assert sizes == [3]


def test_generate_assigns_everyone_exactly_once():
    students = cohort(23)
    res = generate(students, default_weights(), size=5, seed=1, iterations=2000)
    assigned = [m["name"] for team in res.teams for m in team]
    assert len(assigned) == 23
    assert len(set(assigned)) == 23               # no duplicates, no omissions
    assert sorted(res.sizes, reverse=True) == [5, 5, 5, 4, 4]


def test_zero_students():
    res = generate([], default_weights(), size=5)
    assert res.teams == []
