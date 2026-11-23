"""Improvements ported from PeerParley_AI 2.16 – 2.21, and the TeamForge bugs
found while porting them."""
from __future__ import annotations

import hashlib
import io
import os
import re
import subprocess
import sys
import threading
import time
import uuid

import pandas as pd
import pytest
from cryptography.fernet import Fernet

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def vault(tmp_path, monkeypatch):
    from teamformation import vault as vmod
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("VAULT_BACKEND", "local")
    monkeypatch.setenv("VAULT_FOLDER", f"p-{uuid.uuid4().hex[:6]}")
    vmod.clear_cache()
    yield vmod.Vault()
    vmod.clear_cache()


class _Slow:
    """Counts backend reads, makes each take a while, records concurrency."""

    def __init__(self, inner, delay=0.05):
        self.inner, self.delay = inner, delay
        self.gets, self.lock = [], threading.Lock()
        self.active = self.peak = 0

    def get(self, name):
        with self.lock:
            self.gets.append(name)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            return self.inner.get(name)
        finally:
            with self.lock:
                self.active -= 1

    def __getattr__(self, attr):
        return getattr(self.inner, attr)


def _roster(n=8):
    return pd.DataFrame([{"First Name": f"Ann{i}", "Last Name": "Lee",
                          "Email": f"a{i}@x.edu", "Section": "A"} for i in range(n)])


def _course(vault, course="MGT301", n=8, answered=6):
    from teamformation import survey_service as svc
    slug, students = svc.save_setup(course, "Teams", _roster(n), dict(svc.DEFAULT_SURVEY),
                                    vault=vault, owner="prof")
    for pos in range(answered):
        svc.save_response(vault, slug, pos, {"name": students[pos]["name"],
                                             "complete": True})
    return slug


# --------------------------------------------------------------------------- #
# Parallel reads, scoped refresh, summaries (2.20.1 / 2.20.2)
# --------------------------------------------------------------------------- #
def test_prefetch_reads_side_by_side_and_signs_in_once(vault):
    from teamformation import vault as vmod
    names = [f"o{i}.ppj" for i in range(12)]
    for n in names:
        vault.put_bytes(n, n.encode())
    vmod.clear_cache()
    slow = _Slow(vault.backend)
    vault._backend = slow
    t = time.perf_counter()
    vault.prefetch(names)
    took = time.perf_counter() - t
    assert sorted(slow.gets) == sorted(names)
    assert slow.peak > 1                      # in parallel
    assert slow.gets[0] == names[0]           # the first one went alone
    assert took < 12 * 0.05 * 0.6
    slow.gets.clear()
    assert [vault.get_bytes(n) for n in names] == [n.encode() for n in names]
    assert slow.gets == []                    # all served from the cache


def test_check_for_new_responses_drops_only_that_course(vault):
    from teamformation import survey_service as svc
    a = _course(vault, "A100")
    b = _course(vault, "B200")
    svc.all_responses(vault, a); svc.all_responses(vault, b)
    slow = _Slow(vault.backend, delay=0)
    vault._backend = slow
    vault.refresh(svc.response_prefixes(a))
    svc.all_responses(vault, b)
    assert slow.gets == []                    # the other course stayed cached
    svc.all_responses(vault, a)
    assert slow.gets and all(a in g for g in slow.gets)


def test_course_menu_summaries_survive_cache_expiry_but_not_a_change_here(vault, monkeypatch):
    from teamformation import survey_service as svc
    from teamformation import vault as vmod
    _course(vault, "A100"); _course(vault, "B200")
    svc.list_surveys(vault)
    real = vmod._now
    monkeypatch.setattr(vmod, "_now", lambda: real() + 120)   # cache expired
    slow = _Slow(vault.backend, delay=0)
    vault._backend = slow
    rows = svc.list_surveys(vault)
    assert {r["course"] for r in rows} == {"A100", "B200"}
    assert [g for g in slow.gets if g.startswith("roster__")] == []
    # A change made here replaces the remembered copy at once.
    svc.save_setup("A100", "Teams", _roster(9), dict(svc.DEFAULT_SURVEY), vault=vault)
    counts = {r["course"]: r["students"] for r in svc.list_surveys(vault)}
    assert counts["A100"] == 9


def test_a_name_missing_from_a_fresh_listing_costs_no_round_trip(vault):
    vault.put_bytes("here.ppj", b"x")
    vault.list()
    slow = _Slow(vault.backend, delay=0)
    vault._backend = slow
    with pytest.raises(KeyError):
        vault.get_bytes("not-yet-created.ppj")
    assert slow.gets == []


def test_an_empty_listing_is_not_trusted_to_mean_missing(vault):
    from teamformation import vault as vmod
    vmod._listings[vault._scope] = (vmod._now(), [])
    vault.backend.put("x.ppj", __import__("teamformation.security",
                                          fromlist=["e"]).encrypt_bytes(b"real"))
    assert vault.get_bytes("x.ppj") == b"real"


def test_dropbox_listing_failure_is_reported_not_read_as_empty():
    from teamformation.vault import DropboxBackend

    class Boom:
        def files_list_folder(self, folder):
            raise RuntimeError("network down")

    class NotFound:
        def files_list_folder(self, folder):
            raise RuntimeError("ApiError(path=LookupError('not_found'))")

    b = DropboxBackend.__new__(DropboxBackend)
    b.folder, b.dbx = "/TeamForge", Boom()
    with pytest.raises(RuntimeError):
        b.list()
    b.dbx = NotFound()
    assert b.list() == []


def test_unchanged_design_settings_are_not_reuploaded_each_minute(vault, monkeypatch):
    from teamformation import vault as vmod
    vault.put_bytes("formcfg__x.ppj", b"same")
    real = vmod._now
    monkeypatch.setattr(vmod, "_now", lambda: real() + 120)
    puts = []
    orig = vault.backend.put
    monkeypatch.setattr(vault.backend, "put", lambda n, d: (puts.append(n), orig(n, d)))
    vault.put_bytes("formcfg__x.ppj", b"same")
    assert puts == []


def test_submissions_already_read_are_not_reread_every_minute(vault, monkeypatch):
    from teamformation import survey_service as svc
    from teamformation import vault as vmod
    slug = _course(vault)
    assert len(svc.all_responses(vault, slug)) == 6
    real = vmod._now
    monkeypatch.setattr(vmod, "_now", lambda: real() + 120)
    slow = _Slow(vault.backend, delay=0)
    vault._backend = slow
    assert len(svc.all_responses(vault, slug)) == 6
    assert [g for g in slow.gets if g.startswith("resp__")] == []


def test_slow_storage_click_after_expiry_is_a_handful_of_calls(tmp_path):
    done = subprocess.run([sys.executable, os.path.join(REPO, "tests", "_slow_storage.py"),
                           str(tmp_path / "slow"), "0.02"],
                          capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    rows = dict(re.findall(r"^\s+(.+?)\s{2,}[\d.]+ s\s+(\d+) calls", done.stdout, re.M))
    assert int(rows["click after the cache expired"]) <= 6, done.stdout
    assert int(rows["click, cache warm"]) == 0, done.stdout


# --------------------------------------------------------------------------- #
# Email (2.16.1 / 2.18.0 / 2.19.0 / 2.19.2)
# --------------------------------------------------------------------------- #
def test_date_placeholders_read_like_a_deadline():
    from teamformation.ui_helpers import date_ctx, date_warnings
    d = date_ctx({"opens_at": "2026-11-16T09:00:00", "closes_at": "2026-11-20T17:00:00"})
    assert d == {"open_date": "Monday, November 16, 2026 at 9:00 AM",
                 "close_date": "Friday, November 20, 2026 at 5:00 PM"}
    assert date_ctx({})["close_date"] == "TBA"
    assert date_warnings(["Due {close_date}"], {"closes_at": ""})
    assert not date_warnings(["Due {close_date}"], {"closes_at": "2026-11-20T17:00:00"})


def test_mistyped_placeholders_are_named():
    from teamformation.ui_helpers import unknown_placeholders
    assert unknown_placeholders(["Hi {firstname}", "{link} {class} {first_name}"],
                                ["first_name", "link", "class"]) == ["firstname"]


def test_plain_text_keeps_every_link_everywhere():
    from teamformation.emailpack import _strip_html
    from teamformation.webmail import compose_url, plain_text
    body = 'Hi,<br><a href="https://app/?t=abc">Open my survey</a><ul><li>one</li></ul>'
    assert "Open my survey: https://app/?t=abc" in plain_text(body)
    assert "• one" in plain_text(body)
    assert "https://app/?t=abc" in _strip_html(body)      # Mac script / .eml text
    url = compose_url("Gmail", "a@x.edu", "Subj", body)
    assert url.startswith("https://mail.google.com/") and "a%40x.edu" in url
    assert compose_url("Outlook on the web", "a@x.edu", "S", body).startswith(
        "https://outlook.office.com/")


def test_composer_is_a_fragment():
    from teamformation import ui_helpers
    import streamlit as st
    if getattr(st, "fragment", None) is None:
        pytest.skip("Streamlit < 1.37")
    assert ui_helpers.email_composer is not ui_helpers._email_composer


# --------------------------------------------------------------------------- #
# Contact lists (2.17.0)
# --------------------------------------------------------------------------- #
def _read(data: bytes, name: str):
    from teamformation.ingest import read_table
    return read_table(io.BytesIO(data), name)


def test_real_world_roster_files_read():
    from teamformation.survey_service import build_students
    csv = "First Name,Last Name,Email\nAnn,Lee,a@x.edu\nBo,Kim,b@x.edu\n"
    assert len(build_students(_read(csv.encode("utf-16"), "r.txt"))) == 2   # Excel Unicode Text
    assert len(build_students(_read(csv.replace(",", ";").encode(), "r.csv"))) == 2
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        pd.DataFrame({"Read me": ["Fill in the next sheet"]}).to_excel(xw, "Notes", index=False)
        pd.read_csv(io.StringIO(csv)).to_excel(xw, "Roster", index=False)
    assert len(build_students(_read(buf.getvalue(), "r.xlsx"))) == 2


@pytest.mark.parametrize("data,name,words", [
    (b"", "r.csv", "empty"),
    (b"%PDF-1.4 binary\x00\x01\x02" * 20, "r.csv", "PDF"),
    (b"PK\x03\x04garbage" * 30, "r.xlsx", "could not be opened"),
])
def test_unusable_files_explain_themselves(data, name, words):
    from teamformation.ingest import InputError
    with pytest.raises(InputError, match=words):
        _read(data, name)


def test_blank_cells_are_blank_not_nan():
    from teamformation.survey_service import build_students
    df = pd.DataFrame({"First Name": ["Ann", None], "Last Name": ["Lee", None],
                       "Email": [None, None], "Section": [1.0, None],
                       "Notes": [None, "stray"]})
    out = build_students(df)
    assert len(out) == 1 and out[0]["name"] == "Ann Lee"
    assert out[0]["email"] == "" and out[0]["section"] == "1"


# --------------------------------------------------------------------------- #
# Accounts (2.17.0)
# --------------------------------------------------------------------------- #
def test_temporary_passwords_are_random_and_short_ones_refused(vault):
    from teamformation import accounts
    a, b = accounts.new_temp_password(), accounts.new_temp_password()
    assert a != b and len(a) >= 12
    with pytest.raises(ValueError):
        accounts.add_account("prof", "Prof", "instructor", "short", vault=vault)
    accounts.add_account("prof", "Prof", "instructor", a, vault=vault)
    with pytest.raises(ValueError):
        accounts.set_password("prof", "", vault=vault)
    src = open(os.path.join(REPO, "app.py")).read()
    assert '"TeamForge-Welcome"' not in src.replace('prefilled with "TeamForge-Welcome"', "")


# --------------------------------------------------------------------------- #
# The app, driven
# --------------------------------------------------------------------------- #
def _app(key):
    from streamlit.testing.v1 import AppTest
    a = AppTest.from_file(os.path.join(REPO, "app.py"), default_timeout=120)
    a.secrets["fernet_key"] = key
    a.secrets["app_password_sha256"] = hashlib.sha256(b"pw").hexdigest()
    a.secrets["vault"] = {"backend": "local", "folder": "drive"}
    a.session_state["pp_user"] = {"user": "admin", "name": "A", "role": "admin",
                                  "source": "secrets"}
    return a


def test_uploader_does_not_carry_a_roster_into_the_next_course():
    src = open(os.path.join(REPO, "teamformation", "pages", "roster.py")).read()
    assert 'key=f"roster_up::{ctx.slug}"' in src


def test_reminder_composer_and_web_mail_in_the_real_app(tmp_path, monkeypatch):
    from teamformation import survey_service as svc
    from teamformation import vault as vmod
    monkeypatch.chdir(tmp_path)
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_KEY", key)
    monkeypatch.setenv("VAULT_BACKEND", "local")
    monkeypatch.setenv("VAULT_FOLDER", "drive")
    vmod.clear_cache()
    v = vmod.Vault()
    cfg = dict(svc.DEFAULT_SURVEY, closes_at="2026-12-04T17:00:00")
    slug, _ = svc.save_setup("MGT301", "Teams", _roster(4), cfg, vault=v, owner="admin")

    a = _app(key)
    a.session_state["new_course"] = "MGT301"
    a.session_state["new_label"] = "Teams"
    a.run()
    assert not a.exception, a.exception
    subj = [t for t in a.text_input if t.key == "rem_subj"][0]

    calls = []
    for name in ("get", "put", "list"):
        orig = getattr(vmod.LocalBackend, name)
        monkeypatch.setattr(vmod.LocalBackend, name,
                            lambda self, *x, _o=orig, _n=name: (calls.append(_n), _o(self, *x))[1])
    subj.set_value("Due {close_date} — {firstname}").run()
    assert not a.exception, a.exception
    assert calls == []                         # editing does no storage I/O
    warns = " ".join(w.value for w in a.warning)
    assert "{firstname}" in warns
    method = [s for s in a.selectbox if s.key == "rem_method"][0]
    method.set_value("Open in web mail — Outlook or Gmail").run()
    assert not a.exception, a.exception
    vmod.clear_cache()
