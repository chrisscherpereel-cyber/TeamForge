"""TeamForge — team-formation application for university courses.

One Streamlit process serves two audiences:

  * Students reach a personal ?t=<token> link that opens the team-formation
    survey directly (no login) and records a sealed, encrypted response.
  * Instructors sign in and move through the workflow tabs:
    Dashboard → Course & Roster → Survey → Responses → Design Teams →
    Finalize → Communicate → Export.

All student PII is encrypted at rest in the university-controlled vault; the
public host never stores plaintext. Reuses the original application's
authentication, accounts, encrypted vault, and email delivery.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import streamlit as st
import streamlit.components.v1 as components

from teamformation import __version__, APP_NAME
from teamformation import accounts
from teamformation.auth import logout, require_login
from teamformation.branding import render_header
from teamformation.config import load_config
from teamformation import survey_service as svc
from teamformation import student_form
from teamformation.vault import Vault
from teamformation.pages import (
    dashboard, roster as roster_page, survey_setup, monitor, designer,
    finalize as finalize_page, communications, exports,
)

_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_ICON = os.path.join(_ASSET_DIR, "teamforge_mark.png")

st.set_page_config(page_title=APP_NAME,
                   page_icon=_ICON if os.path.exists(_ICON) else "🧩",
                   layout="wide")


@dataclass
class Ctx:
    S: object
    vault: Vault
    cfg: object
    user: dict
    is_admin: bool
    course: str
    label: str
    slug: str


# --------------------------------------------------------------------------- #
# Public student surface — a valid token bypasses the instructor gate.
# --------------------------------------------------------------------------- #
render_header()

_token = None
try:
    _token = st.query_params.get("t")
except Exception:
    _qp = st.experimental_get_query_params()
    _token = (_qp.get("t") or [None])[0]
if _token:
    student_form.render_student_app(_token)
    st.stop()

if not require_login():
    st.stop()

cfg = load_config()
S = st.session_state
user = S.get("pp_user") or {"user": "admin", "name": "Administrator",
                            "role": "admin", "source": "secrets"}
is_admin = accounts.is_admin(user)
vault = Vault()


# --------------------------------------------------------------------------- #
# Scroll-to-top on navigation (server rerun bumps a token; tab clicks hook JS)
# --------------------------------------------------------------------------- #
def _scroll_to_top():
    token = S.get("_nav_token", 0)
    components.html(
        f"""<script>
        /* nav-token:{token} */
        (function() {{
          var doc = window.parent.document;
          function toTop() {{
            try {{
              window.parent.scrollTo(0, 0);
              ['section.main','[data-testid="stMain"]','[data-testid="stAppViewContainer"]']
                .forEach(function(s){{var e=doc.querySelector(s); if(e) e.scrollTo(0,0);}});
            }} catch(e) {{}}
          }}
          toTop();
          if (!window.parent.__tfTabScrollHooked) {{
            window.parent.__tfTabScrollHooked = true;
            doc.addEventListener('click', function(e) {{
              if (e.target.closest('button[role="tab"]')) setTimeout(toTop, 40);
            }}, true);
          }}
        }})();
        </script>""", height=0)


# --------------------------------------------------------------------------- #
# Sidebar — identity, storage health, course/project picker, admin accounts
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown(f"**{user.get('name', 'User')}**")
    st.caption(f"`{user.get('user')}` · "
               + ("administrator — every course" if is_admin
                  else "instructor — your courses only"))
    ok, msg = vault.healthcheck()
    (st.success if ok else st.warning)(msg)
    st.caption(f"Storage: **{cfg.vault.backend}** · {APP_NAME} v{__version__}")
    if st.button("Sign out"):
        logout(); st.rerun()

    if user.get("source") == "vault":
        with st.expander("Change my password"):
            p1 = st.text_input("New password", type="password", key="own_pw1")
            p2 = st.text_input("Confirm", type="password", key="own_pw2")
            if st.button("Save password", key="own_pw_save"):
                if p1 != p2:
                    st.error("Those don't match.")
                elif len(p1) < 8:
                    st.error("Use at least 8 characters.")
                else:
                    try:
                        accounts.set_password(user["user"], p1, must_change=False)
                        st.success("Changed.")
                    except Exception as exc:  # noqa: BLE001
                        st.error(str(exc))

    st.divider()
    st.markdown("### Working on")
    _all = svc.list_surveys(vault)
    _mine = svc.visible_surveys(_all, user)
    _labels = [f"{(s['course'] or '(no course)')} · {s['label']}"
               + (f" — {s['owner'] or 'unowned'}" if is_admin else "")
               for s in _mine]
    choice = st.selectbox("Course / project", ["➕ New…"] + _labels, key="survey_pick")
    if choice == "➕ New…":
        course = st.text_input("Course", S.get("course", ""), key="new_course")
        label = st.text_input("Project / assignment name", S.get("label", "Teams"),
                              key="new_label")
    else:
        _s = _mine[_labels.index(choice)]
        course, label = _s["course"], str(_s["label"])
        st.caption(f"Editing **{course} · {label}**"
                   + (f" · owner `{_s['owner'] or 'unowned'}`" if is_admin else ""))
    S["course"], S["label"] = course, label

    # Drop carried-over per-course state when the active course changes.
    _active_slug = svc.slugify(course, label)
    if S.get("_active_slug") not in (None, _active_slug):
        for _k in list(S.keys()):
            if str(_k).startswith(("design::", "roster_df::")):
                S.pop(_k, None)
        S["_nav_token"] = S.get("_nav_token", 0) + 1
    S["_active_slug"] = _active_slug

    if is_admin:
        st.divider()
        with st.expander("👥 Manage instructors"):
            accts = accounts.load_accounts()
            st.caption(f"{len(accts)} stored account(s), plus the built-in `admin`.")
            nu = st.text_input("Username", key="acct_new_user")
            nn = st.text_input("Display name", key="acct_new_name")
            nr = st.selectbox("Role", ["instructor", "admin"], key="acct_new_role")
            npw = st.text_input("Temporary password", value="TeamForge-Welcome",
                                key="acct_new_pw")
            if st.button("Add instructor", key="acct_add"):
                try:
                    accounts.add_account(nu, nn, nr, npw or "TeamForge-Welcome")
                    st.success(f"Added `{nu}`.")
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
            if accts:
                who = st.selectbox("Account", list(accts), key="acct_pick")
                a1, a2 = st.columns(2)
                if a1.button("Reset password", key="acct_reset"):
                    accounts.set_password(who, "TeamForge-Welcome", must_change=True)
                    st.success("Reset to `TeamForge-Welcome`.")
                if a2.button("Toggle role", key="acct_role"):
                    accounts.set_role(who, "instructor"
                                      if accts[who].get("role") == "admin" else "admin")
                    st.success("Role changed.")
                a3, a4 = st.columns(2)
                if a3.button(("Deactivate" if accts[who].get("active", True) else "Activate"),
                             key="acct_active"):
                    accounts.set_active(who, not accts[who].get("active", True))
                    st.success("Updated.")
                if a4.button("Remove", key="acct_remove"):
                    accounts.remove_account(who); st.success(f"Removed `{who}`.")

_scroll_to_top()

ctx = Ctx(S=S, vault=vault, cfg=cfg, user=user, is_admin=is_admin,
          course=course, label=label, slug=svc.slugify(course, label))

# Block access to a course owned by another instructor.
_owner = svc.survey_owner(vault, ctx.slug)
_blocked = _owner not in (None, "") and not svc.can_access(_owner, user)

st.caption("Workflow → ① Dashboard · ② Course & Roster · ③ Survey · ④ Responses · "
           "⑤ Design Teams · ⑥ Finalize · ⑦ Communicate · ⑧ Export")

tabs = st.tabs(["① Dashboard", "② Course & Roster", "③ Survey", "④ Responses",
                "⑤ Design Teams", "⑥ Finalize", "⑦ Communicate", "⑧ Export"])

if _blocked:
    for t in tabs:
        with t:
            st.error(f"This course belongs to another instructor (`{_owner or 'unowned'}`). "
                     "Only its owner or an administrator can open it.")
else:
    with tabs[0]:
        dashboard.render(ctx)
    with tabs[1]:
        roster_page.render(ctx)
    with tabs[2]:
        survey_setup.render(ctx)
    with tabs[3]:
        monitor.render(ctx)
    with tabs[4]:
        designer.render(ctx)
    with tabs[5]:
        finalize_page.render(ctx)
    with tabs[6]:
        communications.render(ctx)
    with tabs[7]:
        exports.render(ctx)
