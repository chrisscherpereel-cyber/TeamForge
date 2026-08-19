# TeamForge — Team Formation for University Courses

TeamForge builds balanced, workable course teams from a short student survey. An
instructor imports a roster, opens the survey, monitors responses, generates
recommended teams from criteria they weight, edits and locks teams by hand,
checks quality diagnostics, finalizes, and emails each student their assignment.
The instructor keeps final control throughout — the algorithm assists, it does
not decide.

It is a refactor of an existing Streamlit **peer-evaluation** application
(PeerParley). The proven infrastructure was reused wholesale — instructor
accounts and login, the encrypted pluggable storage vault, tokenized
no-login student links, and Microsoft 365 / SMTP email — while everything
specific to peer grading was removed and replaced with team-formation
functionality. See `ASSESSMENT.md` for the original-architecture audit and the
full list of what was reused, changed, added, and removed.

---

## 1. Running it locally

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then edit it
streamlit run app.py
```

Minimum secrets to start (the rest enable real storage/email):

```toml
app_password_sha256 = "<sha256 of a password>"   # sign in as user: admin
fernet_key          = "<Fernet.generate_key()>"
[vault]
backend = "local"      # writes encrypted blobs to ./vault_cache (dev only)
```

Generate the two values:

```bash
python -c "import hashlib,getpass;print(hashlib.sha256(getpass.getpass().encode()).hexdigest())"
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
```

Sign in with username `admin` and your password, then add instructor accounts
from the sidebar. For real collection set `[vault] backend` to `m365`,
`dropbox`, or `pcloud` so responses persist off the public host.

Run the tests:

```bash
pip install pytest
python -m pytest -q          # 55 tests
```

---

## 2. Workflow

`Dashboard → Course & Roster → Survey → Responses → Design Teams → Finalize →
Communicate → Export`

Students never sign in: each receives a personal `?t=<token>` link that opens
the survey directly and records a sealed, encrypted response.

---

## 3. The survey (sections mirror the provided Qualtrics spec)

Student information (name, email, section, major, standing, subject-matter
experience, work experience); schedule compatibility (meeting format, time zone,
a weekly availability matrix, weekly hours); nine skill self-ratings; up to three
preferred contribution roles plus leadership preference; eight work-style
statements; effort level, work pace, and communication responsiveness; team
history (previous teammates, one preferred teammate, an instructor-only placement
concern, and an optional non-sensitive note). Every block can be switched on or
off by the instructor, and the major categories are editable.

The student form is paged with a progress bar, preserves answers across page
navigation and across browser sessions (drafts are saved encrypted), validates
required fields, enforces the "at most three roles / No-strong-preference-is-
exclusive" rule, lets the student review before submitting, and scrolls to the
top on every navigation.

---

## 4. Team-formation algorithm

`teamformation/optimizer.py`, fully independent of the UI.

1. **Team-size distribution** — from a target size *or* a target number of teams,
   the other is derived and the remainder distributed so sizes differ by at most
   one (23 students at size 5 → `5, 5, 5, 4, 4`, never a lone team of 3).
2. **Feasible construction** — locked students first, then must-be-together
   groups, then everyone else placed greedily while respecting do-not-pair and
   capacity.
3. **Simulated-annealing local search** over student *swaps* between teams. Swaps
   preserve the size distribution; every candidate swap is rejected if it would
   violate a hard constraint; each move only re-scores the two affected teams, so
   it scales to ~250 students in a few seconds.
4. **Sections** are enforced structurally: when "same section only" is on, each
   section is solved as an independent sub-problem, so teams can never mix
   sections.

Randomness is seeded and the seed is stored with the run, so a configuration is
reproducible; **Generate alternative** searches from a fresh seed.

The objective the search maximizes is the weighted team-quality score below.

---

## 5. Scoring model & criteria

`teamformation/scoring.py`. Every criterion belongs to one of three philosophies:

- **Diversify / cover** across a team (concentrating strong people is penalized
  because it leaves other teams uncovered): overall skill coverage and per-skill
  coverage (quant, writing, presentation, research, planning, tech), major
  diversity, relevant-experience balance, work-experience balance, leadership
  distribution, preferred-role coverage.
- **Match** within a team: schedule compatibility (pairwise availability overlap,
  timezone-adjusted), meeting-format compatibility, commitment (effort)
  similarity, work-pace similarity, communication-response similarity.
- **Preference** (soft): avoid repeated teammates, honor a preferred teammate.

Each component returns 0–1; the overall score is a size-weighted average across
teams and active criteria, shown as **N/100** plus a per-criterion breakdown. The
diagnostics also produce concrete **warnings** (e.g. "Team 3 has no member rated
3+ in quantitative analysis", "Team 5 has no student willing to coordinate",
"Team 2 contains two students requested not to be paired") and a plain-English
explanation per team.

### Default weights (0 ignore … 5 very high)

| Criterion | Category | Default |
|---|---|---|
| Schedule compatibility | match | 4 |
| Overall skill coverage | diversify | 4 |
| Leadership distribution | diversify | 4 |
| Major diversity | diversify | 3 |
| Relevant-experience balance | diversify | 3 |
| Preferred-role coverage | diversify | 3 |
| Commitment similarity | match | 3 |
| Work-experience balance | diversify | 2 |
| Work-pace similarity | match | 2 |
| Communication-response similarity | match | 2 |
| Meeting-format compatibility | match | 2 |
| Avoid repeated teammates | preference | 2 |
| Honor preferred teammate | preference | 1 |
| Per-skill coverage (quant/writing/…) | diversify | 0 (opt-in) |

**Presets:** Balanced Teams, Compatibility First, Skill Diversity, Academic
Diversity, Student Preference, Instructor Custom. Selecting a preset loads its
weights (shown on the sliders); moving any slider switches to Instructor Custom.

---

## 6. Hard constraints & instructor overrides

Hard constraints are enforced by the optimizer, not merely weighted: **do-not-
place-together**, **must-be-together**, **same-section-only**, and the min/max
team size implied by the distribution. A preferred teammate is a *soft* nudge and
is never treated as equivalent to a do-not-pair restriction.

The instructor always retains control: manual **move / swap / assign**, **rename
/ add / delete** teams, **lock** individual students or whole teams and
**regenerate only the unlocked** students, a reproducible **seed**, a **what-if**
baseline comparison, and a **Finalize** step that refuses to complete while hard
constraints are violated *unless the instructor explicitly overrides* (the
override is recorded on the finalized record). Diagnostics recompute immediately
after every manual change.

---

## 7. Confidentiality

Survey responses are instructor-facing. Students only ever see their own final
team assignment (name, teammates, optional instructions) — never another
student's answers, ratings, or the confidential placement concern. Placement
concerns are stored instructor-only and are excluded from student-facing exports
and from every student email. No protected demographic characteristic is used as
a formation criterion.

---

## 8. Exports & communication

CSV student dataset (team + all survey variables, instructor-only), a multi-sheet
Excel workbook (Final Teams, Student Responses, Team Diagnostics, Formation
Settings), a simple team-roster CSV, and a student-facing team list that contains
only names/teams. Assignments are emailed through the reused Microsoft 365 (Graph
device-code) or SMTP path, with offline `.eml` and CSV fallbacks; if
"Release final teams" is on, students also see their team in-app.

---

## 9. Persistence & storage layout

Everything durable is Fernet-encrypted before it leaves the process and written
to the chosen vault backend:

```
accounts.ppj              instructor accounts (PBKDF2 hashes)
roster__<slug>.ppj        flat, position-stable student roster + owner
survey__<slug>.ppj        survey wording / toggles / schedule
resp__<slug>__p<pos>.ppj  one student's (draft or complete) response
formcfg__<slug>.ppj       weights, structure, constraints, seed
final__<slug>.ppj         finalized teams + diagnostics + version history
```

`<slug>` is derived from course + project so sections/rounds never collide.
Finalized teams are versioned (a re-finalize retains the prior version), so a
mistake never silently destroys the previous assignment.

---

## 10. Files & tests

Project layout and the added/modified/removed inventory are in `ASSESSMENT.md`.
Automated tests (`tests/`, 55 total): `test_team_sizes`, `test_optimizer`,
`test_scoring`, `test_constraints`, `test_persistence`, `test_survey_validation`,
`test_designer_helpers`, and `test_integration_workflow` (a full headless
roster → responses → generate → finalize → export → student-view run).

---

## 11. Migration from the peer-evaluation app

This is a new package (`teamformation/`) alongside a new entry point (`app.py`);
it does not read or write the old PeerParley `.ppx/.ppj` peer-evaluation bundles,
so existing peer-eval data is untouched. To adopt TeamForge, point it at a vault
folder (reuse the same M365/Dropbox account with a new `folder`, or a new
folder in the existing one) and the same `fernet_key`/accounts if you want to
keep instructor logins. No destructive migration is performed. If you deploy into
the *same* vault folder as PeerParley, the two apps' key prefixes
(`resp__`, `roster__`, `survey__`, `final__`, `formcfg__`) do not collide with
peer-eval bundle names, but using a separate `folder` is cleanest.

---

## 12. Known limitations

- Availability overlap uses coarse 3-hour blocks with an approximate timezone
  shift (no day-boundary rollover); it is a scoring signal, not a scheduler.
- Lock-in-place combined with same-section-only is not exercised together (locks
  apply in the single-section case); regeneration otherwise honors both.
- Very large cohorts (≫250) still run, but tune the iteration cap in
  `optimizer.generate` if you need tighter optima.
- Email sending depends on your M365/SMTP secrets; without them, use the `.eml`
  or CSV fallbacks.
