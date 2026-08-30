---
description: Split the 1,209-line README into a quickstart, a findings log and a design record — without breaking test_readme_is_true
---

# Split the README

## Why

`README.md` is 1,209 lines doing four jobs at once: a quickstart, a
design-rationale essay, a lab notebook of empirical findings, and a limitations
register. It is genuinely excellent as the second and third of those, and that
is the problem — **the prose is an asset being hidden by its container.**

A newcomer needs the install and a first study in the first screen. Someone
evaluating the project needs the findings without the packaging notes. Right now
both have to read all of it.

## Proposed split

| File | Holds | Roughly |
|---|---|---|
| `README.md` | What it is, why, install, first study, scope, status summary, links out | ~150 lines |
| `docs/FINDINGS.md` | The empirical write-ups: S&P 500 sweep, Faber, the cross-section, the EDGAR restatement measurement, what real data did not fix | ~450 lines |
| `docs/DESIGN.md` | Why each control is shaped the way it is: the seam, the orphan-control problem, the workspace, Iceberg vs point-in-time, NautilusTrader vs hand-rolling, MLflow vs replay | ~450 lines |
| `docs/REQUIREMENTS.md` | Unchanged — it is already the status board | — |

Argue with these boundaries if the content suggests better ones. The one thing
not to do is delete material to hit a line count; this is a move, not a cut.

## The trap — read this before editing anything

`tests/test_readme_is_true.py` (279 lines) recomputes each table and asserts the
result appears **in the bytes of `README.md`**. Its docstring is explicit about
why: "A test that recomputes a number and compares it to another recomputation
of the same number proves nothing; the assertion has to be against the bytes a
reader will actually see."

So the tests must follow the tables to their new homes. Concretely:

- Parameterise the file each assertion reads, or split the test file to match.
- `scripts/readme_tables.py` regenerates those tables — it must learn about the
  new files too, and CI runs it on every push.
- `tests/test_requirements_map.py` and `tests/test_packaging.py` also read
  specific files; check them.
- Grep for every path reference before moving anything: the README, the docs,
  `.spark-flow/`, and the module docstrings all cross-link.

**Do not weaken the assertions to make the move easier.** If a table now lives
in `docs/FINDINGS.md`, the test asserts against `docs/FINDINGS.md`. A test that
stops checking the bytes is the failure this whole file exists to prevent.

## Done when

`pytest -q` is green, `python scripts/readme_tables.py` regenerates every table
in whichever file now holds it, no cross-link is broken, and the README fits on
roughly two screens before the first link out.
