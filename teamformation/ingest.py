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
from typing import Dict, Optional

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
# File readers
# --------------------------------------------------------------------------- #
# A file an instructor uploads was made by someone else's spreadsheet program,
# saved in whatever format that program chose. PeerParley's release audit pushed thirty
# of those through the upload path and found two kinds of failure:
#
#   * five raised raw pandas errors — an empty file, a binary or a PDF with the
#     wrong extension, a corrupt workbook — and because the upload was not
#     guarded, each one replaced the whole page with a traceback;
#   * six were worse: they *read*, as nothing. Excel's "Unicode Text" format
#     (UTF-16, tab-separated), a European semicolon CSV, and a workbook whose
#     roster is on its second sheet all came back as zero students with no
#     word as to why, and the instructor saw an empty page.
#
# So every file goes through `_decode_table`, which tries the formats people
# actually have, and every failure becomes an `InputError` — a message written
# for the person who uploaded the file, which the app shows as it stands.


class InputError(ValueError):
    """A file that cannot be used, with a message meant for the instructor."""


_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def _as_bytes(file) -> bytes:
    raw = file.read() if hasattr(file, "read") else file
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return bytes(raw or b"")


def _decode_text(raw: bytes) -> str:
    """Bytes → text, in the encodings real spreadsheets are saved in."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")             # Excel "Unicode Text"
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", errors="replace")
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _looks_binary(raw: bytes) -> bool:
    """A file that is not text at all, whatever its extension says."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return False
    sample = raw[:4096]
    if not sample:
        return False
    if sample.startswith((b"%PDF", b"PK\x03\x04", b"\xd0\xcf\x11\xe0")):
        return True
    controls = sum(1 for b in sample if b < 9 or 13 < b < 32)
    return controls > len(sample) * 0.05


def _sniff_separator(text: str) -> str:
    """Comma, semicolon or tab — whichever the header line actually uses.

    A spreadsheet in a European locale saves "CSV" with semicolons, because the
    comma is its decimal mark. Read with a comma, the whole header becomes one
    column and the team column cannot be found — which used to come back as
    three students "with no team" rather than as a format problem.
    """
    head = next((ln for ln in text.splitlines() if ln.strip()), "")
    counts = {sep: head.count(sep) for sep in (",", ";", "\t")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def _decode_table(raw: bytes, filename: str, header) -> pd.DataFrame:
    """The one place a file becomes a frame. Raises InputError, nothing else."""
    name = (filename or "").lower()
    if not raw.strip():
        raise InputError("That file is empty. Check you uploaded the saved "
                         "file, not a new blank one.")
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        try:
            sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None,
                                   header=header, dtype=object)
        except Exception as exc:  # noqa: BLE001
            raise InputError(
                "That file has a spreadsheet's name but could not be opened as "
                "one. Open it in Excel and use Save As → Excel Workbook "
                f"(.xlsx), then upload it again. ({type(exc).__name__})"
            ) from exc
        # A workbook often has a notes or instructions sheet first. Take the
        # sheet with the most filled-in cells rather than whichever is first.
        filled = {n: int(df.notna().sum().sum()) for n, df in sheets.items()}
        if not filled or max(filled.values()) == 0:
            raise InputError("Every sheet in that workbook is empty.")
        return sheets[max(filled, key=filled.get)]

    if _looks_binary(raw):
        raise InputError(
            "That file is not a spreadsheet or a CSV — it looks like "
            + ("a PDF" if raw[:4] == b"%PDF" else
               "a Word or Excel file renamed to .csv" if raw[:2] == b"PK" else
               "a binary file")
            + ". Save it from Excel or Google Sheets as CSV or .xlsx and upload "
              "that instead.")
    text = _decode_text(raw)
    sep = _sniff_separator(text)
    try:
        return pd.read_csv(io.StringIO(text), sep=sep, header=header,
                           dtype=object if header is None else None,
                           skip_blank_lines=True)
    except pd.errors.EmptyDataError as exc:
        raise InputError("That file has no rows in it.") from exc
    except Exception as exc:  # noqa: BLE001
        raise InputError(
            "That file could not be read as a CSV — some rows have a different "
            "number of columns from the header. Open it in Excel or Google "
            "Sheets and save it again as CSV. "
            f"({type(exc).__name__}: {str(exc)[:120]})") from exc


def read_table(file, filename: str = "") -> pd.DataFrame:
    """A contact list, as a frame with its header row. Raises InputError.

    Blank rows and the unnamed empty columns Excel leaves after the last real
    one are dropped here, so nothing downstream mistakes them for students.
    """
    name = filename or getattr(file, "name", "")
    df = _decode_table(_as_bytes(file), name, header=0)
    # A cell holding only spaces is empty. The contact-list template's formula
    # columns leave a space in every unused row, so without this the template
    # read as a hundred rows long; the unused ones are dropped here.
    df = df.apply(lambda col: col.map(
        lambda v: None if isinstance(v, str) and not v.strip() else v))
    df = df.map(lambda v: None if type(v).__module__.startswith("openpyxl")
                else v) if hasattr(df, "map") else df
    df = df.dropna(how="all")
    df = df.loc[:, [c for c in df.columns
                    if not (str(c).startswith("Unnamed:")
                            and df[c].isna().all())]]
    if df.empty:
        raise InputError("That file has a header row but no students under "
                         "it.")
    return df.reset_index(drop=True)

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
