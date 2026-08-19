import time

from teamformation.optimizer import generate
from teamformation.scoring import default_weights
from tests.synthetic import cohort


def test_reproducible_with_seed():
    students = cohort(30)
    r1 = generate(students, default_weights(), size=5, seed=123, iterations=4000)
    r2 = generate(students, default_weights(), size=5, seed=123, iterations=4000)
    names1 = [[m["name"] for m in t] for t in r1.teams]
    names2 = [[m["name"] for m in t] for t in r2.teams]
    assert names1 == names2
    assert r1.seed == r2.seed == 123


def test_alternative_seed_can_differ():
    students = cohort(30)
    r1 = generate(students, default_weights(), size=5, seed=1, iterations=4000)
    r2 = generate(students, default_weights(), size=5, seed=999, iterations=4000)
    # not guaranteed different, but objective should be comparable and valid
    assert 0 <= r1.objective <= 100
    assert 0 <= r2.objective <= 100


def test_scales_to_250_quickly():
    students = cohort(250)
    t0 = time.time()
    res = generate(students, default_weights(), size=5, seed=1)
    elapsed = time.time() - t0
    assigned = [m["name"] for t in res.teams for m in t]
    assert len(set(assigned)) == 250
    assert elapsed < 45         # generous ceiling for CI


def test_objective_improves_over_random():
    students = cohort(40)
    weights = {k: 0 for k in default_weights()}
    weights["commitment"] = 5
    for i, s in enumerate(students):
        s["effort"] = 1 if i % 2 == 0 else 5
    baseline = generate(students, weights, size=5, seed=1, iterations=0)
    optimized = generate(students, weights, size=5, seed=1, iterations=8000)
    assert optimized.objective >= baseline.objective
