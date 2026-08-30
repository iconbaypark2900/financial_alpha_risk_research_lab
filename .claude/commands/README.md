# Commands

Reusable prompts for the work queued against this repository. Run one with
`/<name>` in Claude Code.

Each carries the current state with file references, the task, this repository's
house rules for that area, and a definition of done. They are written to be run
one at a time, in roughly this order.

**Provenance.** The first eight came from a codebase assessment at commit
`b426964`. The five defect-driven ones came from a 39-agent audit on 2026-08-30
that verified 326 claims against the code, found 25 candidate errors, and killed
15 of them with adversarial skeptics. Every finding cited in those five was
**reproduced** — by benchmark, by mutation, or by running the code — not inferred.

## Controls that do not control

The repository's own thesis is that a control nobody invokes is not a control.
These are the places where that has happened again.

| Command | What it closes |
|---|---|
| `/fix-verified-defects` | Six reproduced defects. Four are controls failing in the exact case they exist for — the null benchmark inverts its verdict on negative Sharpes, FR-24 records that code was unknown then discards the evidence, FR-23 raises false `NotReproducible` on every search after the first, and the numpy seed branch seeds an RNG nothing uses. |
| `/close-dead-seam-paths` | `Study.backtest` is dead code — mutating it to `raise` still gives 508 passed. Plus two tests verified vacuous by mutation, and one tautology presented as coverage. |
| `/close-backtest-range-hole` | FR-10 is enforced by good manners on the backtest path. `search_series` already fixed this for search; `backtest` has no twin. The README and module docstring also *overstate* the limitation. |

## Scope, data and adoption

| Command | What it closes |
|---|---|
| `/resolve-data-question` | A decision record, not code. Four open requirements block on data. License, engineer around, or rescope — and write down which. |
| `/fix-scale-blockers` | Eight measured O(n) paths, invisible on fixtures and fatal on the 20,281-company universe. The practical blocker on whatever data the decision above buys. |
| `/reconstruct-v1-spec` | `src/portfolio/` is ~900 lines built against a specification nobody has read. Find §5.5, or write an honest reconstruction labelled as one. |
| `/add-cli` | No console entry points. The seam should be the obvious path at the shell, not just the documented one. |

## Truth maintenance

| Command | What it closes |
|---|---|
| `/reconcile-docs` | Nine documented claims that contradict the code or each other — including "338 of 508", which is wrong (it is 351) and whose guard skips in the only install that could check it. |
| `/add-quality-gates` | No ruff, no mypy, no coverage. The project cannot currently report which of its own lines are unexercised. |
| `/fix-packaging-claims` | The built sdist fails its own suite (9 failed, 6 errors). The CI file is the only claim-bearing file no test reads. |
| `/split-readme` | 1,209 lines doing four jobs. The trap is `test_readme_is_true.py`, which asserts against README *bytes*. |
| `/rename-package` | Top-level package is literally `src`. Mechanical, documented in `pyproject.toml`, and cheaper now than after publishing. |
| `/tidy-deferred-debt` | Upstream pandas warnings, seven `except Exception` clauses that are *not* all the same pattern, and a brief that still says 248 tests. |

## Rules that apply to all of them

- A requirement is **met** only when a test fails if the behaviour regresses.
  Statuses in `docs/REQUIREMENTS.md` move when a test does, never before — and
  when a fix is deferred, the status comes **down**.
- **Partial with the gap named beats met.** FR-03 and FR-19 are the models.
- Prefer refusing to warning — "a warning is read once and then filtered out of
  the logs."
- **Prefer a guard that executes over a guard that matches text.**
  `test_no_control_is_orphaned` is a static search over
  `src/research_integrity/*.py`; it cannot see that `Study.backtest` is never
  reached. Keep both kinds, and say in each what it can and cannot see.
- Watch for tests that pass **vacuously**. Three are now confirmed in this suite,
  all found by mutation: mutate the code under a test, and if the suite stays
  green the test is decoration. The causality checker was bitten by this once
  already, passing without comparing anything because NaN equals NaN.
- Keep the minimal install working: core is numpy alone, with DuckDB and
  NautilusTrader import-guarded to `None`. CI asserts the degradation. The
  "338 of 508" figure printed in three files is **wrong** — it is 351 — and
  should be corrected rather than preserved.
- `pyproject.toml` and `requirements.txt` must agree
  (`test_the_two_dependency_files_agree`), **and** every declared dependency must
  appear in an import (`test_every_declared_dependency_is_actually_imported`,
  `test_packaging.py:70`). The second one catches people out.
