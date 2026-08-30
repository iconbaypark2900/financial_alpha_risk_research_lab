---
description: Nine documented claims that contradict the code or each other — including a wrong number the guard is switched off for
---

# Reconcile the documentation with the code

This repository's standard is that a claim must be true, or marked partial with
the gap named. Every item below was verified on 2026-08-30 against `b426964`.
None of them is caught by an existing guard, and the reason each guard misses it
is part of the finding.

## The wrong number

**"338 of the 508 tests" is wrong. The real figure is 351.** A genuinely minimal
venv (`numpy` + `pytest` only) runs **351 passed, 18 skipped**, 369 collected.

It is stated three times — `README.md:76`, `pyproject.toml:35`,
`requirements.txt:5` — and guarded nowhere, because
`tests/test_packaging.py::test_the_documented_test_count_is_the_real_one`
explicitly `pytest.skip`s in the minimal install (`test_packaging.py:155-158`),
which is the only environment that could check it. **The guard is switched off
precisely where this number lives.** Fix the number, and make the guard run in
that configuration instead of skipping — this is the one claim it was most needed
for.

## Contradictions inside the docs

- **FR-03 is described as "still not implemented" in two places.**
  `README.md:535` says "FR-03, FR-04 and FR-05 are **still not implemented**",
  and `README.md:540` adds "`docs/REQUIREMENTS.md` still says so." It does not —
  `docs/REQUIREMENTS.md:32` marks FR-03 **partial**, and `README.md:686-692`,
  later on the same page, says so too. `point_in_time.py:45-50` carries the same
  stale "WHAT IS NOT BUILT" text. The vendor data *is* loaded: `listing_status()`
  exists at `ingest.py:381` with tests at `test_edgar.py:166-186`.
  `test_requirements_map.py` cannot see this — it compares the *set* of FR
  numbers, never their statuses or the prose.

- **`docs/REQUIREMENTS.md:90` says "FR-19 is the one open requirement in V0"**
  while the same page tallies 2 partial and 2 not implemented, and FR-03/04/05
  are all §5.1, which is V0. Four open, not one.

- **`docs/LIAISON_PROJECT_BRIEF.md` disagrees with itself about finGuard.** The
  problem statement says the migration completed 2026-08-28 and the source is
  retired; the non-goals and risk table still describe it as deferred to L4. Its
  Related link points at `docs/merge_plans/...`, which does not exist. Its risk
  table still lists "Missing pyproject.toml" — the file exists and is guarded by a
  test. And its happy path still says "Expected: 248 tests passing".

- **Four files point at `migration_inbox/finGuard/`, a path the suite asserts must
  not exist** (`test_requirements_map.py:139-143`). Stale references at
  `requirements.txt:50`, `README.md:213`, `src/portfolio/__init__.py:8`,
  `src/portfolio/kelly.py:1`. The actual location is `docs/superseded/finGuard/`.

## Overstated mitigations

- **The brief claims `test_readme_is_true.py` "recomputes every numeric table in
  the README."** It covers 8 blocks out of roughly 20. This row is the brief's
  stated mitigation for "documentation drifting from the code", so overstating it
  does the most damage here: it tells a reader the drift problem is mechanically
  solved when most README figures are hand-transcribed one-offs with no
  regeneration path.

- **The README's newest figures are guarded by nothing and cannot be recomputed
  from a clean clone.** `data/` is in `.gitignore` and `git ls-files data/`
  returns zero files. The EDGAR restatement study and the six-series panel result
  — `README.md:640-646` and the cross-section section — have no test and no
  regeneration path. Decide: extend `scripts/readme_tables.py`, or mark those
  figures explicitly as one-off measurements with the date they were taken. The
  second is honest; silence is not.

- **`docs/REQUIREMENTS.md`'s "Where" column never mentions `study.py` or
  `workspace.py`.** The page bills itself as "where each one lives", and for the
  requirements whose enforcement was the hard part it points at the wrong file.
  `study.py` cites thirteen FR numbers and is the only thing making FR-07, FR-10
  and FR-22–FR-25 binding on a real run; `workspace.py` is what stops the
  FR-08/FR-15 count resetting to zero.

## House rules

- Fix the **claim**, not the guard, unless the guard is the thing that is wrong —
  and for the 338 figure, both are.
- Where a figure genuinely cannot be regenerated, say so with the date it was
  measured. "A measurement, not a law" is already this repository's phrasing for
  exactly that, and it is the right move.
- After editing, run `python scripts/readme_tables.py` and `pytest -q`.
