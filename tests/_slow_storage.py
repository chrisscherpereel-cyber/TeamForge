"""How long common actions take on cloud storage. Run as a script.

Every backend call is slowed to DELAY seconds (0.3 s ~ Microsoft 365 /
Dropbox / pCloud from Streamlit Cloud), with 6 courses of 40 students each.
Prints wall-clock seconds and backend calls per action.

Usage:  python tests/_slow_storage.py <working-dir> [delay]
"""
from __future__ import annotations

import hashlib
import os
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

N_COURSES, N_STUDENTS = 6, 40
TRACE = [] if os.environ.get("SLOW_TRACE") else None


def main(workdir: str, delay: float = 0.3) -> int:
    os.makedirs(workdir, exist_ok=True)
    os.chdir(workdir)
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    os.environ.update(FERNET_KEY=key, VAULT_BACKEND="local", VAULT_FOLDER="slow")

    import pandas as pd
    from teamformation import survey_service as svc
    from teamformation import vault as vmod
    from teamformation.tokens import make_token
    from teamformation.vault import LocalBackend, Vault
    from test_integration_workflow import _survey_payload

    v = Vault()
    slugs = []
    for c in range(N_COURSES):
        rows = [{"First Name": f"S{c}x{i:02d}", "Last Name": "Lee",
                 "Email": f"s{c}{i}@x.edu", "Section": "A"} for i in range(N_STUDENTS)]
        slug, students = svc.save_setup(f"MGT{c}", "Teams", pd.DataFrame(rows),
                                        dict(svc.DEFAULT_SURVEY), vault=v, owner="admin")
        for pos in range(N_STUDENTS - 4):
            svc.save_response(v, slug, pos, _survey_payload(students[pos]["name"], pos))
        slugs.append(slug)

    lock = threading.Lock()
    calls = {"n": 0}

    def slow(fn):
        def inner(self, *a, **kw):
            with lock:
                calls["n"] += 1
                if TRACE is not None:
                    import traceback
                    fr = [f for f in traceback.extract_stack()
                          if REPO in f.filename and "vault.py" not in f.filename
                          and "_slow_storage" not in f.filename]
                    TRACE.append((time.perf_counter(), fn.__name__, a[0] if a else "",
                                  f"{os.path.relpath(fr[-1].filename, REPO)}:{fr[-1].lineno}"
                                  if fr else "?"))
            time.sleep(delay)
            return fn(self, *a, **kw)
        return inner

    for name in ("get", "put", "list", "delete"):
        setattr(LocalBackend, name, slow(getattr(LocalBackend, name)))

    real_now = vmod._now
    skew = {"s": 0.0}
    vmod._now = lambda: real_now() + skew["s"]

    from streamlit.testing.v1 import AppTest

    def new_app():
        a = AppTest.from_file(os.path.join(REPO, "app.py"), default_timeout=600)
        a.secrets["fernet_key"] = key
        a.secrets["app_password_sha256"] = hashlib.sha256(b"pw").hexdigest()
        a.secrets["vault"] = {"backend": "local", "folder": "slow"}
        return a

    results = []

    def timed(label, fn):
        calls["n"] = 0
        if TRACE is not None:
            TRACE.clear()
        t = time.perf_counter()
        fn()
        results.append((label, time.perf_counter() - t, calls["n"]))
        if TRACE is not None and os.environ.get("SLOW_TRACE") in label:
            for at, what, arg, where in TRACE:
                print(f"  {at - t:5.2f}s {what:6s} {str(arg)[:36]:36s} {where}")

    vmod.clear_cache()
    app = new_app()
    app.session_state["pp_user"] = {"user": "admin", "name": "A", "role": "admin",
                                    "source": "secrets"}
    app.session_state["new_course"] = "MGT0"
    app.session_state["new_label"] = "Teams"
    timed("open the app (cold)", app.run)
    if app.exception:
        print("app raised:", [str(e.value)[:300] for e in app.exception]); return 1
    timed("click, cache warm", app.run)
    skew["s"] += 120
    timed("click after the cache expired", app.run)

    def switch():
        app.session_state["new_course"] = "MGT3"
        app.run()
    timed("switch to another course", switch)

    def refresh():
        b = [x for x in app.button if "Check for new" in str(x.label)]
        b[0].click().run()
    timed("Check for new responses", refresh)

    def student():
        vmod.clear_cache()
        s = new_app()
        s.query_params["t"] = make_token({"s": slugs[1], "p": 39}, svc.token_secret())
        s.run()
        if s.exception:
            raise RuntimeError(s.exception)
    timed("student opens their link (cold)", student)

    print(f"\n{N_COURSES} courses x {N_STUDENTS} students, {delay}s per storage call")
    for label, secs, n in results:
        print(f"  {label:36s} {secs:6.1f} s   {n:4d} calls")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    raise SystemExit(main(a[0] if a else ".", float(a[1]) if len(a) > 1 else 0.3))
