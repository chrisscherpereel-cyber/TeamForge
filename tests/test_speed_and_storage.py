"""Improvements ported from PeerParley_AI: storage read cache, bounded storage,
storage problems reported instead of raised, the scheduling clock, the app's
own address, and the rerun budget. Plus TeamForge-specific fixes found while
porting (drafts kept apart from submissions, paged listings)."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import subprocess
import sys
import uuid

import pandas as pd
import pytest
from cryptography.fernet import Fernet

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _roster(n=4):
    return pd.DataFrame([{"First Name": f"Ann{i}", "Last Name": "Lee",
                          "Email": f"a{i}@x.edu", "Section": "A"} for i in range(n)])


@pytest.fixture
def fresh_vault(tmp_path, monkeypatch):
    from teamformation import vault as vault_mod
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VAULT_FOLDER", f"t-{uuid.uuid4().hex[:6]}")
    vault_mod.clear_cache()
    v = vault_mod.Vault()
    yield v
    vault_mod.clear_cache()


def _count(monkeypatch, backend_cls):
    calls = {"get": 0, "put": 0, "list": 0}
    for name in calls:
        orig = getattr(backend_cls, name)

        def wrapped(self, *a, _n=name, _o=orig, **kw):
            calls[_n] += 1
            return _o(self, *a, **kw)
        monkeypatch.setattr(backend_cls, name, wrapped)
    return calls


# --------------------------------------------------------------------------- #
# The read cache
# --------------------------------------------------------------------------- #
def test_reads_are_remembered_and_a_write_is_never_served_stale(fresh_vault, monkeypatch):
    from teamformation.vault import LocalBackend
    v = fresh_vault
    v.put_bytes("a.ppj", b"one")
    calls = _count(monkeypatch, LocalBackend)
    assert v.get_bytes("a.ppj") == b"one"          # served from the write
    assert v.get_bytes("a.ppj") == b"one"
    assert calls["get"] == 0
    v.put_bytes("a.ppj", b"two")
    assert v.get_bytes("a.ppj") == b"two"          # never the replaced value
    assert "a.ppj" in v.list() and calls["list"] <= 1
    v.list()
    assert calls["list"] <= 1
    v.refresh()                                     # "Check for new responses"
    assert v.get_bytes("a.ppj") == b"two"
    assert calls["get"] == 1


def test_repeating_our_own_identical_write_does_not_upload(fresh_vault, monkeypatch):
    from teamformation.vault import LocalBackend
    v = fresh_vault
    v.put_bytes("cfg.ppj", b"same")
    calls = _count(monkeypatch, LocalBackend)
    v.put_bytes("cfg.ppj", b"same")
    assert calls["put"] == 0
    v.put_bytes("cfg.ppj", b"changed")
    assert calls["put"] == 1


def test_another_process_write_becomes_visible_after_refresh(fresh_vault):
    from teamformation.vault import Vault
    v = fresh_vault
    v.put_bytes("r.ppj", b"old")
    # Simulate another process writing behind our cache.
    v.backend.put("r.ppj", __import__("teamformation.security", fromlist=["x"])
                  .encrypt_bytes(b"new"))
    assert v.get_bytes("r.ppj") == b"old"           # inside the window
    Vault().refresh()                               # any vault on the same store
    assert v.get_bytes("r.ppj") == b"new"


def test_two_local_stores_with_the_same_folder_name_do_not_share_a_cache(tmp_path, monkeypatch):
    from teamformation import vault as vault_mod
    monkeypatch.setenv("VAULT_FOLDER", "same-name")
    vault_mod.clear_cache()
    (tmp_path / "one").mkdir(); (tmp_path / "two").mkdir()
    monkeypatch.chdir(tmp_path / "one")
    a = vault_mod.Vault(); a.put_bytes("x.ppj", b"section one")
    monkeypatch.chdir(tmp_path / "two")
    b = vault_mod.Vault()
    with pytest.raises(Exception):
        b.get_bytes("x.ppj")
    vault_mod.clear_cache()


# --------------------------------------------------------------------------- #
# Storage problems are reported, not raised
# --------------------------------------------------------------------------- #
def test_a_backend_that_cannot_open_is_reported_without_network(monkeypatch):
    from teamformation.config import VaultConfig
    from teamformation.vault import Vault, VaultUnavailable
    v = Vault(VaultConfig(backend="dropbox", folder="x", options={}))
    assert not v.available and v.error
    ok, msg = v.healthcheck()
    assert not ok and msg
    with pytest.raises(VaultUnavailable):
        v.get_bytes("anything")


def test_dropbox_client_is_built_with_a_bounded_wait():
    src = open(os.path.join(REPO, "teamformation", "vault.py")).read()
    assert '"timeout": 20' in src and "max_retries_on_error" in src
    # every requests call in the vault names a timeout
    for m in re.finditer(r"requests\.(get|put|post|delete)\(", src):
        window = src[m.start(): m.start() + 400]
        assert "timeout=" in window, window[:120]


def test_m365_listing_follows_every_page_and_tokens_renew(monkeypatch):
    from teamformation import vault as vault_mod
    pages = {
        "first": {"value": [{"name": f"f{i}"} for i in range(200)],
                  "@odata.nextLink": "https://graph/next"},
        "next": {"value": [{"name": "f200"}]},
    }

    class R:
        def __init__(self, body): self.body, self.status_code = body, 200
        def raise_for_status(self): pass
        def json(self): return self.body

    def fake_get(url, **kw):
        return R(pages["next"] if url == "https://graph/next" else pages["first"])

    issued = []

    class FakeApp:
        def __init__(self, *a, **kw): pass
        def acquire_token_for_client(self, scopes):
            issued.append(1)
            return {"access_token": f"tok{len(issued)}"}

    import msal
    monkeypatch.setattr(msal, "ConfidentialClientApplication", FakeApp)
    monkeypatch.setattr(vault_mod.requests, "get", fake_get)
    b = vault_mod.M365Backend("TeamForge", {"tenant_id": "t", "client_id": "c",
                                            "client_secret": "s", "drive": "sharepoint",
                                            "site_id": "x"})
    names = b.list()
    assert len(names) == 201 and names[-1] == "f200"
    # MSAL is asked every time (it serves its own cache and renews near expiry)
    assert len(issued) == 2


def test_requirements_have_ceilings_and_every_backend_package():
    req = open(os.path.join(REPO, "requirements.txt")).read()
    lines = [ln.split("#")[0].strip() for ln in req.splitlines()]
    lines = [ln for ln in lines if ln]
    for ln in lines:
        assert "<" in ln, f"{ln} has no upper bound"
    names = {re.split(r"[<>=]", ln)[0].strip().lower() for ln in lines}
    assert {"msal", "dropbox", "requests", "streamlit", "cryptography"} <= names


# --------------------------------------------------------------------------- #
# Counting responses without reading them; drafts kept apart
# --------------------------------------------------------------------------- #
def test_response_status_reads_no_responses(fresh_vault, monkeypatch):
    from teamformation import survey_service as svc
    from teamformation.vault import LocalBackend
    v = fresh_vault
    slug, students = svc.save_setup("C1", "P", _roster(6), dict(svc.DEFAULT_SURVEY),
                                    vault=v, owner="prof")
    for pos in range(4):
        svc.save_response(v, slug, pos, {"name": students[pos]["name"], "complete": True})
    v.refresh()
    calls = _count(monkeypatch, LocalBackend)
    status = svc.response_status(v, slug)
    assert sum(r["responded"] for r in status) == 4
    assert calls["get"] == 1          # the roster snapshot only


def test_a_draft_is_not_a_response_and_submission_clears_it(fresh_vault):
    from teamformation import survey_service as svc
    v = fresh_vault
    slug, students = svc.save_setup("C2", "P", _roster(3), dict(svc.DEFAULT_SURVEY),
                                    vault=v, owner="prof")
    svc.save_draft(v, slug, 0, {"major": "Finance", "complete": False})
    assert not any(r["responded"] for r in svc.response_status(v, slug))
    assert svc.load_work_in_progress(v, slug, 0)["major"] == "Finance"
    assert all(not s["responded"] for s in svc.load_students_for_formation(v, slug))

    svc.save_response(v, slug, 0, {"major": "Finance", "complete": True})
    svc.clear_draft(v, slug, 0)
    assert [r["responded"] for r in svc.response_status(v, slug)][0] is True
    assert svc.load_draft(v, slug, 0) is None

    # A later unsubmitted edit no longer overwrites the submission.
    svc.save_draft(v, slug, 0, {"major": "Marketing", "complete": False})
    assert svc.load_response(v, slug, 0)["major"] == "Finance"
    assert svc.load_work_in_progress(v, slug, 0)["major"] == "Marketing"


def test_legacy_drafts_stored_as_responses_are_not_treated_as_submissions(fresh_vault):
    from teamformation import survey_service as svc
    v = fresh_vault
    slug, _ = svc.save_setup("C3", "P", _roster(2), dict(svc.DEFAULT_SURVEY),
                             vault=v, owner="prof")
    svc.save_response(v, slug, 1, {"major": "x", "complete": False})
    assert svc.all_responses(v, slug) == {}


# --------------------------------------------------------------------------- #
# The scheduling clock and the app's own address
# --------------------------------------------------------------------------- #
def test_window_is_read_against_the_instructors_clock(monkeypatch):
    from teamformation import survey_service as svc
    server_now = dt.datetime.now()
    # Instructor is 7 hours behind the (UTC) server; survey closes at 5pm local.
    closes = (server_now - dt.timedelta(hours=7) + dt.timedelta(hours=1))
    cfg = {"is_open": True, "closes_at": closes.isoformat(), "opens_at": ""}
    assert svc.window_state(cfg) == "closed"              # read in server time
    cfg[svc.CLOCK_KEY] = -420
    assert svc.window_state(cfg) == "open"                # read in their time


def test_offset_from_a_stated_wall_clock_rounds_to_five_minutes():
    from teamformation.survey_service import offset_from_wall_clock
    server = dt.datetime(2026, 11, 13, 15, 58, 37)
    assert offset_from_wall_clock(dt.datetime(2026, 11, 13, 9, 0), server) == -420
    assert offset_from_wall_clock(dt.datetime(2026, 11, 13, 16, 0), server) == 0


def test_app_url_drops_the_query_string_and_the_token():
    from teamformation.webcontext import app_url, clock_offset_minutes

    class Ctx:
        url = "https://teams.example.app/?t=secret.token#x"
        timezone_offset = 420             # browser: UTC-7
    assert app_url(Ctx()) == "https://teams.example.app"
    assert app_url(None) == ""
    utc = dt.datetime.now(dt.timezone.utc)
    assert clock_offset_minutes(Ctx(), server_now=utc) == -420


def test_no_fake_public_url_default_and_vault_folder_from_env(monkeypatch):
    from teamformation.config import load_config
    monkeypatch.setenv("VAULT_FOLDER", "from-env")
    cfg = load_config()
    assert cfg.public_url == ""
    assert cfg.vault.folder == "from-env"


# --------------------------------------------------------------------------- #
# The app, driven
# --------------------------------------------------------------------------- #
def test_storage_problem_has_its_own_screen_and_students_see_a_plain_message(tmp_path,
                                                                             monkeypatch):
    from streamlit.testing.v1 import AppTest
    from teamformation import survey_service as svc
    from teamformation.tokens import make_token
    monkeypatch.chdir(tmp_path)
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_KEY", key)

    def app():
        a = AppTest.from_file(os.path.join(REPO, "app.py"), default_timeout=60)
        a.secrets["fernet_key"] = key
        a.secrets["app_password_sha256"] = hashlib.sha256(b"pw").hexdigest()
        a.secrets["vault"] = {"backend": "dropbox", "folder": "x"}   # no credentials
        return a

    inst = app()
    inst.run()
    assert not inst.exception
    assert any("cannot reach its storage" in m.value for m in inst.markdown)
    assert not inst.text_input                      # no sign-in form behind it

    stu = app()
    stu.query_params["t"] = make_token({"s": "any", "p": 0}, svc.token_secret())
    stu.run()
    assert not stu.exception
    assert any("isn't available" in e.value for e in stu.error)


def test_a_rerun_costs_no_storage_round_trips(tmp_path):
    done = subprocess.run(
        [sys.executable, os.path.join(REPO, "tests", "_rerun_cost.py"),
         str(tmp_path / "cost"), "--budget", "2"],
        capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
    assert "PASS - one rerun stays within" in done.stdout
