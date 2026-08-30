---
description: Add ruff, mypy and coverage to the project and CI — the one place this repository does not verify itself
---

# Add the missing quality gates

## Why this is conspicuous here specifically

Ruff, mypy, black and coverage are absent from `pyproject.toml`,
`requirements.txt` and `.github/workflows/tests.yml`. In a repository whose
entire thesis is that untested claims rot, three of its own claims have no
mechanism:

- 508 passing tests say the behaviour is right and say nothing about whether
  5,921 source lines are internally consistent.
- The project **cannot currently report which of its own lines are unexercised** —
  which is the exact question it asks of everything else.
- The CI comment says the guards "only mean something if something runs them."
  These are guards nothing runs because they do not exist.

## The work

1. **Coverage first** — it is the one that matters most given the thesis. Add
   `coverage` (or `pytest-cov`), produce a report in CI, and record the current
   number honestly. Do **not** set a threshold you have to lower later; set it
   at or just under wherever the code actually lands today, and note it.
2. **Ruff** for lint and format. Configure it in `pyproject.toml`. On the seven
   broad `except Exception` clauses, ruff flags **three, not seven**: BLE001
   exempts a handler that re-raises, and four of the seven do. The flagged ones
   are `search.py:196` (which also draws S112, try-except-continue) and
   `run_record.py:142,178`. Do not pre-emptively `noqa` the other four —
   RUF100 (unused-noqa) is on by default and will fail on them. Where a `noqa`
   is warranted, give it the reason inline, in the style this codebase already
   uses for its `# type: ignore` lines.
3. **Mypy**, incrementally. The codebase is broadly annotated and uses
   `from __future__ import annotations` throughout. Start non-strict, get to
   green, then tighten module by module. Do not add annotations that are wrong
   just to satisfy it.

## The trap in this repository

There are **two** guards here, and the second one is the one that will actually
stop you:

- `test_the_two_dependency_files_agree` fails if you add a dependency to
  `pyproject.toml` but not `requirements.txt`, or the reverse. Dependencies are
  declared twice on purpose and this is what keeps them from drifting.
- `test_every_declared_dependency_is_actually_imported`
  (`tests/test_packaging.py:70-84`) fails **even when you add it to both**,
  because it requires every declared dependency to appear in an `import` or
  `from` statement somewhere under `src/` or `tests/`. Ruff, mypy, black and
  coverage are never imported by this codebase.

So "add it to both files" is precisely the action that leaves the suite red, and
the failure will look unrelated to what you did. Decide up front what happens to
that test — the most likely answer is widening its allowlist, which already
special-cases `nautilus_trader` and `pytest` in its docstring. Whatever you
choose, that decision belongs in the "Done when" list below.

Also: the `minimal` CI job asserts DuckDB and NautilusTrader are **absent**. Do
not let a new tool pull either in transitively.

## CI shape

Add a separate job rather than bolting onto `full` — the matrix runs three
Python versions and lint does not need three runs. Keep it fast; the existing
suite finishes in about 14 seconds and that is worth preserving.

## Done when

`pytest -q` is still green, `ruff check` and `mypy` pass or have documented
scoped exemptions, coverage is reported on every push with the current figure
written down, and `test_packaging.py` agrees with both dependency files.
