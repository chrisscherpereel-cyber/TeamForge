from teamformation import scoring
from teamformation.optimizer import generate
from teamformation.scoring import default_weights, parse_student
from teamformation.survey_schema import DAYS, TIME_BLOCKS, SKILLS
from tests.synthetic import make_student, cohort


def test_skill_coverage_distributes_specialists():
    # 4 "specialists" each strong in ONE distinct skill, everyone else weak.
    specialties = ["quant", "writing", "presentation", "tech"]
    students = []
    for i in range(16):
        skills = {k: 1 for k in SKILLS}
        spec = specialties[i % 4]
        skills[spec] = 5
        students.append(make_student(i, skills=skills))
    weights = {k: 0 for k in default_weights()}
    weights["skill_coverage"] = 5
    res = generate(students, weights, size=4, seed=1, iterations=8000)
    # each team of 4 should end up with all four specialties covered
    for team in res.teams:
        parsed = [parse_student(m) for m in team]
        for spec in specialties:
            assert max(p["skills"][spec] for p in parsed) >= 5


def test_schedule_high_weight_groups_compatible():
    # Half available only mornings, half only evenings.
    students = []
    for i in range(16):
        if i < 8:
            avail = {d: [TIME_BLOCKS[0], TIME_BLOCKS[1]] for d in DAYS}
        else:
            avail = {d: [TIME_BLOCKS[4], TIME_BLOCKS[5]] for d in DAYS}
        students.append(make_student(i, availability=avail))
    weights = {k: 0 for k in default_weights()}
    weights["schedule"] = 5
    res = generate(students, weights, size=4, seed=2, iterations=8000)
    # every team should be internally schedule-consistent (overlap > 0)
    for team in res.teams:
        parsed = [parse_student(m) for m in team]
        assert scoring.c_schedule(parsed) is not None
        assert scoring.c_schedule(parsed) > 0.8


def test_commitment_similarity_clusters():
    # effort levels 1 and 5 only; matching should cluster like with like.
    students = [make_student(i, effort=(1 if i < 10 else 5)) for i in range(20)]
    weights = {k: 0 for k in default_weights()}
    weights["commitment"] = 5
    res = generate(students, weights, size=5, seed=4, iterations=8000)
    for team in res.teams:
        efforts = {m["effort"] for m in team}
        assert len(efforts) == 1        # each team internally uniform


def test_missing_responses_still_scored():
    students = cohort(12)
    for s in students[:4]:
        s["responded"] = False
        s["skills"] = {k: None for k in SKILLS}
        s["availability"] = {d: [] for d in DAYS}
    res = generate(students, default_weights(), size=4, seed=1, iterations=3000)
    assigned = [m["name"] for t in res.teams for m in t]
    assert len(assigned) == 12          # non-respondents remain assignable


def test_avoid_repeats_penalized():
    students = cohort(16)
    # make 0 and 1 prior teammates
    students[0]["prev_teammates"] = students[1]["name"]
    weights = {k: 0 for k in default_weights()}
    weights["avoid_repeats"] = 5
    res = generate(students, weights, size=4, seed=6, iterations=8000)
    from teamformation.ingest import name_key
    for team in res.teams:
        keys = [name_key(m["name"]) for m in team]
        assert not (name_key(students[0]["name"]) in keys
                    and name_key(students[1]["name"]) in keys)


def test_diagnostics_shape():
    students = cohort(20)
    res = generate(students, default_weights(), size=5, seed=1, iterations=3000)
    parsed = [[parse_student(m) for m in t] for t in res.teams]
    diag = scoring.configuration_diagnostics(parsed, default_weights())
    assert 0 <= diag["overall"] <= 100
    assert "components" in diag and diag["components"]
