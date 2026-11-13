"""What one rerun costs, measured. Run as a script, not collected by pytest.

Streamlit re-executes the whole script on every click, keystroke and checkbox,
and `st.tabs` runs the body of *every* tab, not just the visible one. So the
number that predicts how the app feels on Microsoft 365 / Dropbox / pCloud —
where each storage call is an HTTPS round trip of 100-300 ms — is **backend
round trips per rerun**, counted at the backend (below any cache). A timing on
local disk cannot see it.

Usage:  python tests/_rerun_cost.py <working-dir> [--budget N]
Prints the counts and exits non-zero if the budget is exceeded.
"""
from __future__ import annotations

import collections
import hashlib
import os
import sys
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

N_STUDENTS = 40


def main(workdir: str, budget: int = 4) -> int:
    os.makedirs(workdir, exist_ok=True)
    os.chdir(workdir)

    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    os.environ.update(FERNET_KEY=key, VAULT_BACKEND="local",
                      VAULT_FOLDER="rerun-cost")

    import pandas as pd
    from teamformation import survey_service as svc
    from teamformation import formation_service as fsvc
    from teamformation.optimizer import generate
    from teamformation.vault import LocalBackend, Vault
    from test_integration_workflow import _survey_payload

    rows = [{"First Name": f"Stu{i:02d}", "Last Name": "Perf",
             "Email": f"s{i:02d}@example.edu", "Section": "A"}
            for i in range(N_STUDENTS)]
    vault = Vault()
    slug, students = svc.save_setup("PERF101", "Teams", pd.DataFrame(rows),
                                    dict(svc.DEFAULT_SURVEY), vault=vault,
                                    owner="admin")
    for pos in range(N_STUDENTS - 4):
        svc.save_response(vault, slug, pos,
                          _survey_payload(students[pos]["name"], pos))
    # A proposed scenario, so Design Teams renders its full diagnostics.
    active = svc.load_students_for_formation(vault, slug)
    cfg = fsvc.load_config(vault, slug)
    res = generate(active, cfg["weights"], size=4, seed=7, method="greedy")
    fsvc.save_proposed(vault, slug, {
        "teams": [list(t) for t in res.teams],
        "names": [f"Team {i+1}" for i in range(len(res.teams))],
        "locked_teams": [False] * len(res.teams), "locked_students": {},
        "seed": res.seed})

    hits: collections.Counter = collections.Counter()
    askers: collections.Counter = collections.Counter()

    def counted(label, fn):
        def inner(self, *a, **kw):
            hits[label] += 1
            for frame in reversed(traceback.extract_stack()[:-1]):
                if (REPO in frame.filename and "vault.py" not in frame.filename
                        and "_rerun_cost" not in frame.filename):
                    askers[f"{label} {os.path.relpath(frame.filename, REPO)}:"
                           f"{frame.lineno}"] += 1
                    break
            return fn(self, *a, **kw)
        return inner

    for name in ("get", "put", "list", "delete"):
        setattr(LocalBackend, name, counted(name, getattr(LocalBackend, name)))

    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(os.path.join(REPO, "app.py"), default_timeout=300)
    app.secrets["fernet_key"] = key
    app.secrets["app_password_sha256"] = hashlib.sha256(b"pw").hexdigest()
    app.secrets["vault"] = {"backend": "local", "folder": "rerun-cost"}
    app.session_state["pp_user"] = {"user": "admin", "name": "A",
                                    "role": "admin", "source": "secrets"}
    app.session_state["new_course"] = "PERF101"
    app.session_state["new_label"] = "Teams"

    from teamformation import vault as vault_mod
    vault_mod.clear_cache()                     # measure a cold start
    app.run()                                   # first paint
    if app.exception:
        print("FAIL - the app raised:", [str(e.value)[:300] for e in app.exception])
        return 1
    if os.environ.get("RC_DEBUG"):
        print("subheaders:", [s.value for s in app.subheader], "errors:", [e.value for e in app.error], "info:", [i.value for i in app.info])
    first = sum(hits.values())
    print(f"storage round trips for the first paint: {first}")
    hits.clear(); askers.clear()

    app.run()                                   # the rerun being measured
    steady = sum(hits.values())
    print(f"storage round trips for one steady-state rerun: {steady}  {dict(hits)}")
    for where, n in askers.most_common(10):
        print(f"   {n:3d}  {where}")
    for latency_ms in (50, 150, 300):
        print(f"   at {latency_ms}ms per call: "
              f"{steady * latency_ms / 1000:.1f}s of waiting per click")

    # A small interaction: tick "Set a CLOSE date" on the Survey tab.
    hits.clear(); askers.clear()
    boxes = [c for c in app.checkbox if str(getattr(c, "label", "")) == "Set a CLOSE date"]
    if boxes:
        boxes[0].check().run()
        schedule = sum(hits.values())
        print(f"storage round trips for a schedule change: {schedule}  {dict(hits)}")
        for where, n in askers.most_common(6):
            print(f"   {n:3d}  {where}")
    else:
        schedule = 0
        print("note: the close-date control was not on the page")

    worst = max(steady, schedule)
    ok = worst <= budget and not app.exception
    if app.exception:
        print("the app raised:", [str(e.value)[:300] for e in app.exception])
    print(("PASS" if ok else "FAIL"),
          f"- one rerun stays within {budget} storage round trip(s) (worst: {worst})")
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    budget = 4
    if "--budget" in args:
        budget = int(args[args.index("--budget") + 1])
        args = args[:args.index("--budget")]
    raise SystemExit(main(args[0] if args else ".", budget))
