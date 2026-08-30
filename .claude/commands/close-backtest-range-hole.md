---
description: Close the declared-date-range hole on the backtest path, the way search_series already closed it for search
argument-hint: "[optional: --dry-run to report the boundary without changing code]"
---

# Close the declared-date-range hole on the backtest path

## Why this is first

Every other control in this repository is enforced by a trigger, an audit, or a
refusal. This one is enforced by good manners, and it guards FR-10 — the
requirement that the protected holdout is inaccessible to ordinary backtests.

## The actual state — verify before you trust it

Read `src/research_integrity/study.py` in full first. As of commit `b426964`:

- `Study.search_series()` (~line 195) **already closes the hole for search.** It
  reads through `self.series()` → `store.series()` and derives `start`/`end`
  from the dates actually returned, so "the holdout check and the data are the
  same fact." Its own docstring calls it "the version without the hole."
- `Study.backtest()` (~line 156) **still has the hole.** It takes `prices`
  handed in plus declared `start`/`end`, and there is no `backtest_series()`.
- `Study.search()` (~line 126) also still takes a declared range and is public.
- `Study.replay_search()` exists; there is no replay twin for backtest.

**Two documents are stale and overstate the limitation.** The module docstring
("WHAT THIS DOES NOT DO") and `README.md` (§"What it does not do", ~line 932)
both say the range is declared, full stop, and that closing it "needs a
price-shaped read the fact table does not yet offer." `store.series()` exists at
`point_in_time.py:325` and `search_series` already uses it. Correct the prose to
describe the real boundary — this repository normally guards against
overclaiming, and here it has overclaimed a weakness, which is the same failure
wearing the other coat.

## The work

1. Add `Study.backtest_series(entity_id, ...)` mirroring `search_series`: read
   through `self.series()`, derive `start`/`end` from the returned dates, refuse
   after the read and before anything is counted, then delegate to `backtest()`.
   Record the full call signature in `replay_params` the way `search_series`
   does — FR-22 means the *full* parameter set.
2. Decide what happens to raw `search()` / `backtest()`. They are still needed
   for arrays that do not come from the store, so keep them — but move the
   weaker guarantee into **their** docstrings, where a caller will meet it,
   rather than leaving it as a blanket claim in the module header.
3. Add `replay_backtest()` if `backtest_series` can be replayed deterministically.
   Mirror `replay_search`, **including the throwaway `TrialCounter`** — a replay
   re-executes a run that was already counted, and counting it twice inflates
   the very number the deflated Sharpe depends on.
4. **Do not add the new method to `tests/test_study.py::test_no_control_is_orphaned`.**
   That test maps *control call-strings* (`.require_point_in_time(`, `.log.replay(`
   and so on) to their defining module and asserts that some **other** file inside
   `src/research_integrity/` contains that string. `scripts/` and `tests/` are never
   scanned, and nothing in the package calls a `Study` method — so adding
   `".backtest_series("` makes it fail unconditionally. `search_series`, the
   precedent you are mirroring, is deliberately absent from that dict for the same
   reason. `replay_backtest()` needs no entry either: it is already covered, because
   it calls `.log.replay(`.

   Write a **separate** guard instead — one that asserts every public `Study` method
   is actually *executed* by the suite. That guard is needed independently: a
   coverage trace shows `Study.backtest` (study.py:162-182) is currently dead code.
   Inserting `raise RuntimeError(...)` at its first line still leaves the suite at
   508 passed. The orphan test cannot see this, because it matches call sites as
   **text in the source tree**, not as behaviour. Closing that is arguably a bigger
   win than the range hole itself, and it is the same class of bug.

   *(Verified by mutation, 2026-08-30.)*
5. Rewrite the module docstring's "WHAT THIS DOES NOT DO" and the README section
   to state the boundary that actually exists.

## Tests that must exist when you are done

- The `_series` path refuses a range overlapping the holdout **after** the read
  and **before** the trial is counted — assert the counter did not move.
- A caller cannot defeat the check on the `_series` path by declaring a range,
  because there is nothing to declare.
- The raw `backtest()` path still raises `HoldoutViolation` on a declared
  overlap, and its docstring says plainly that the range is trusted.

## House rules for this repository

- A requirement is **met** only if a test fails when the behaviour regresses.
  Do not upgrade a status in `docs/REQUIREMENTS.md` without that test.
- Prefer refusing to warning. FR-07's `require_point_in_time` is the precedent:
  "a warning is read once and then filtered out of the logs."
- Do not trim a range to make it legal — the existing `assert_ordinary_access`
  docstring explains why trimming is worse than raising.
- `tests/test_requirements_map.py` fails if `docs/REQUIREMENTS.md` and the FR
  references in `src/` disagree. `tests/test_readme_is_true.py` asserts against
  README bytes; regenerate tables with `python scripts/readme_tables.py`.
- Keep the minimal install working: core is numpy alone, DuckDB and
  NautilusTrader are import-guarded and degrade to `None`.

## Done when

`.venv/bin/python -m pytest -q` is green with a higher test count than 508, the
new count is updated everywhere it appears (README, `docs/`), and the README
describes a boundary you can demonstrate rather than one you inherited.
