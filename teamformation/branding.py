"""Brand header (inline SVG wordmark) rendered at the top of the app."""
from __future__ import annotations

import streamlit as st

from . import APP_NAME, APP_TAGLINE, __version__

_HEADER_SVG = """
<div style="display:flex;align-items:center;gap:14px;padding:6px 0 2px">
  <svg width="300" height="60" viewBox="0 0 320 78"
       xmlns="http://www.w3.org/2000/svg" role="img" aria-label="TeamForge">
    <circle cx="18" cy="24" r="9" fill="#0E2A3B"/>
    <circle cx="40" cy="24" r="9" fill="#3FB07A"/>
    <circle cx="29" cy="44" r="9" fill="#0B7A4B"/>
    <path d="M18 24 L40 24 L29 44 Z" fill="none" stroke="#9AA9AF" stroke-width="2"/>
    <text x="64" y="34" font-family="Helvetica,Arial,sans-serif" font-size="30"
          font-weight="800" fill="#0E2A3B">Team<tspan fill="#0B7A4B">Forge</tspan></text>
    <text x="66" y="55" font-family="Helvetica,Arial,sans-serif" font-size="13"
          font-style="italic" fill="#6B7A80">team formation, made clear</text>
  </svg>
</div>
"""


def render_header() -> None:
    st.markdown(_HEADER_SVG, unsafe_allow_html=True)


def caption() -> str:
    return f"{APP_NAME} v{__version__} — {APP_TAGLINE}"
