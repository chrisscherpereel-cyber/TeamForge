"""Roster ingestion + name normalization.

Trimmed from the original application: the Qualtrics peer-evaluation parser was
removed (no longer relevant). What remains is the generic table reader, robust
name-normalization used to match students across the roster and the survey, and
the lightweight Roster contact index used for email delivery.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd


# --------------------------------------------------------------------------- #
# Name normalization
# --------------------------------------------------------------------------- #
def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9,\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    if "," in s:
        parts = [p.strip() for p in s.split(",", 1)]
        if len(parts) == 2:
            s = f"{parts[1]} {parts[0]}".strip()
    return re.sub(r"\s+", " ", s).strip()


def name_key(name: str) -> str:
    """Order-independent key so 'First Last' == 'Last, First'."""
    return " ".join(sorted(normalize_name(name).split()))


def _find(cols, needles) -> Optional[str]:
    low = {str(c).lower().replace("_", " ").strip(): c for c in cols}
    for n in needles:
        for k, orig in low.items():
            if n in k:
                return orig
    return None


# --------------------------------------------------------------------------- #
# File reader
# --------------------------------------------------------------------------- #
def read_table(file, filename: str = "") -> pd.DataFrame:
    name = (filename or getattr(file, "name", "")).lower()
    raw = file.read() if hasattr(file, "read") else file
    buf = io.BytesIO(raw) if isinstance(raw, (bytes, bytearray)) else raw
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(buf)
    return pd.read_csv(buf)


# --------------------------------------------------------------------------- #
# Roster (name_key -> contact record) — used for email matching
# --------------------------------------------------------------------------- #
@dataclass
class Roster:
    by_key: Dict[str, dict] = field(default_factory=dict)

    @classmethod
    def from_df(cls, df: pd.DataFrame) -> "Roster":
        cols = list(df.columns)
        name_c = _find(cols, ["full name", "name", "student"])
        email_c = _find(cols, ["email"])
        first_c = _find(cols, ["first name", "first"])
        last_c = _find(cols, ["last name", "last"])
        team_c = _find(cols, ["team", "group"])
        r = cls()
        for _, row in df.iterrows():
            if name_c and pd.notna(row.get(name_c)):
                full = str(row[name_c])
            elif first_c and last_c:
                full = f"{row.get(first_c,'')} {row.get(last_c,'')}".strip()
            else:
                continue
            r.by_key[name_key(full)] = {
                "name": full,
                "first": str(row.get(first_c, "")).strip() if first_c else full.split(" ")[0],
                "last": str(row.get(last_c, "")).strip() if last_c else full.split(" ")[-1],
                "email": str(row.get(email_c, "")).strip() if email_c else "",
                "team": str(row.get(team_c, "")).strip() if team_c else "",
            }
        return r

    def match(self, name: str) -> Optional[dict]:
        return self.by_key.get(name_key(name))
