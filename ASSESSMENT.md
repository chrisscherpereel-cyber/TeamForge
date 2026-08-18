# Architectural Assessment & Change Log

## Phase 1 — Audit of the original application (PeerParley)

A single Streamlit app (`app.py`, ~1,140 lines) drove a five-tab peer-evaluation
workflow backed by a `peerparley/` package (~3,500 lines). Findings:

**Entry / structure.** One process. `app.py` handled a shared-password gate, a
student token surface, and five instructor tabs (survey setup, collect responses,
grading rules, results/PDFs, send feedback) plus Compare and Vault tabs.

**Reusable infrastructure (kept):**
- `config.py` — secrets/env loader (Streamlit secrets → env → dataclasses).
- `security.py` — Fernet encryption of all PII at rest.
- `vault.py` — pluggable encrypted storage with a 4-method interface
  (`put/get/list/delete`) and Local / M365 (Graph) / Dropbox / pCloud backends.
- `tokens.py` — HMAC-signed, no-login student links (`?t=<body>.<sig>`).
- `accounts.py` — instructor accounts as PBKDF2 hashes in the vault; roles +
  per-object ownership; break-glass `admin`.
- `auth.py` — login gate + forced first-password change.
- `email_delivery.py` — Graph (device-code) + SMTP mailers, batch send, and a
  privacy validator; `ingest.read_table` / `Roster` / name-normalization.

**Peer-evaluation-specific (removed or replaced):**
- `grading.py`, `comments.py` — WebPA/CATME grade math and comment scoring.
- `pdfgen.py` — feedback/summary/confidential/comparison PDFs.
- `emailpack.py` — peer-eval `.eml`/auto-send packs.
- `ingest.parse_qualtrics_export` — the 113-column peer-eval parser.
- `survey.py` — the peer-evaluation survey (ratings, $100 allocation, forced
  ranking, confidential comments) and its team-preassigned roster model.

**Risks identified and addressed:** the original roster **pre-assigned** students
to teams (a link encoded team+position) — incompatible with team *formation*, so
the roster model was flattened to a position-stable list; session-state loss on
navigation and scroll position were called out in the spec and are handled;
confidentiality of the placement concern required a data-model split.

## Phase 2 — Design

Flat position-stable roster; a normalized survey schema as the single source of
truth; a three-category scoring model (diversify / match / preference) feeding a
UI-independent optimizer; hard constraints enforced in the optimizer; a
confidentiality boundary where finalized team records carry only name/email/
section (never survey answers or concerns).

## File inventory

### Added
```
app.py                                   new entry point (student token + 8 tabs)
teamformation/__init__.py                brand + version
teamformation/survey_schema.py           all questions/scales/categories
teamformation/survey_service.py          flat roster, links, responses (adapted)
teamformation/student_form.py            paged team-formation survey UI
teamformation/validation.py              survey/role validation (testable)
teamformation/optimizer.py               team-size + annealing optimizer
teamformation/scoring.py                 criteria, diagnostics, warnings
teamformation/formation_service.py       presets, config, finalized-team storage
teamformation/export_service.py          CSV / Excel / roster exports
teamformation/branding.py                TeamForge header
teamformation/ui_helpers.py              mailer wiring + assignment messages
teamformation/pages/*.py                 dashboard, roster, survey_setup, monitor,
                                         designer, finalize, communications, exports
tests/*.py                               55 tests
requirements.txt, README.md, ASSESSMENT.md, .streamlit/secrets.toml.example
```

### Reused essentially unchanged (from `peerparley/` → `teamformation/`)
```
security.py, vault.py, tokens.py, accounts.py, email_delivery.py
config.py (branding defaults only), auth.py (branding text only)
ingest.py (kept read_table / Roster / name-normalization; dropped Qualtrics parser)
```

### Removed (peer-evaluation only, not carried over)
```
grading.py, comments.py, pdfgen.py, emailpack.py, survey.py,
ingest.parse_qualtrics_export, the grading/results/compare tabs and PDF pipeline
```

## Acceptance-criteria coverage (§41)

Instructor creates a course and imports/edits a roster (Course & Roster);
activates the survey (Survey); students log in via link, complete a paged survey,
navigate without losing answers, submit, and can re-edit before the deadline
(student_form); responses persist and completion status shows immediately
(Responses); size *or* number of teams with a live distribution preview, weighted
criteria/presets, generation honoring hard constraints, understandable
diagnostics, manual move/swap, immediate diagnostic updates, lock + regenerate,
every active student assigned exactly once (Design Teams); finalize persists and
survives restart, with versioning and explicit reopen (Finalize); export and
email assignments; students view only released assignments; confidential
responses stay private; no peer-evaluation functionality remains. The headless
`tests/test_integration_workflow.py` exercises the roster→responses→generate→
finalize→export→student-view path end to end.
```
