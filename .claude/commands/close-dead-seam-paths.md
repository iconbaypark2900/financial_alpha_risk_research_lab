---
description: Study.backtest is dead code and two tests pass vacuously — the orphaned-control failure, one layer up
---

# Close the dead seam paths

## The finding

`src/research_integrity/study.py` opens with the sentence this whole repository
turns on:

> Every control in this package worked, was tested, and constrained nothing.

**It has happened again, in the file written to end it.** `Study.backtest` — the
method that applies the FR-07 / FR-10 / FR-06 / FR-24 / FR-08 / FR-25 `ORDER` to
an event-driven backtest — is invoked by nothing. Proven by mutation:

```
inserted `raise RuntimeError("MUTATION")` at study.py:165  ->  508 passed
```

A line-coverage trace over the suite shows every statement of `study.py:162-182`
uncovered. `grep -rn '\.backtest(' tests/ scripts/ src/ README.md docs/`, minus
`run_backtest`, returns exactly one hit: the method's own docstring example at
`study.py:93`.

Meanwhile the README's engine section (`README.md:1085-1094`) documents calling
`run_backtest(...)` **directly**, which bypasses the holdout guard, the
point-in-time refusal and the run record entirely. So "the supported way to run a
backtest, with the controls attached" describes a path nobody takes, and the
documented path is the unguarded one.

**`test_no_control_is_orphaned` structurally cannot catch this.** It is a static
text search for control call-strings inside `src/research_integrity/*.py`, and
`_admit` (`study.py:112-123`) satisfies every entry regardless of whether
`backtest` is reachable. A control can be reachable by grep and dead in practice.

## The work

1. Wire `Study.backtest` — or `backtest_series` if `/close-backtest-range-hole`
   has landed — into a script and a test, so the FR-19/FR-21 half of the seam is
   executed. `real_data_pipeline.py` already wires `Study.search`; follow it.
2. Decide what the README should document as the engine entry point. If
   `run_backtest` stays documented, say plainly that it is the unguarded path and
   why someone would want it.
3. **Add an execution guard to sit beside the text guard.** Assert every public
   `Study` method is actually executed by the suite — coverage-based, or a
   mutation check. The text guard stays; it catches a different thing. Say in the
   docstring what each one can and cannot see.

## Two vacuous tests, both verified by mutation

**`tests/test_workspace.py::test_run_records_accumulate` asserts `0 == 0`.** Its
body opens a log, never writes a run through it, and asserts the count is zero —
so nothing in the suite ever observes a workspace run count rise above zero.
Replacing `workspace.py:154` with `"runs_recorded": 0,` still gives 508 passed.
It is named for a property it does not test, in the file whose subject is
persistent provenance.

**`tests/test_mirror.py::test_iteration_respects_a_limit` uses `<= 1`.** It cannot
distinguish "the limit was honoured" from "the iterator returned nothing."
Changing the guard to `if limit is not None: return` — yield nothing whenever a
limit is passed — still gives `1 passed`. It is also masking a real bug; see
`/fix-verified-defects` item 5.

Fix both to assert the property in their names. Then ask what else has this shape:
these two were found by mutating the code under the test, and that sweep was not
exhaustive.

## One tautology worth labelling

`tests/test_study.py::test_the_counted_trials_feed_the_deflation` asserts
`0.0 <= v <= 1.0` on a deflated Sharpe. That holds for **any** statistic
whatsoever, because `core.py:190` returns `NormalDistribution.cdf(...)`.
`tests/test_research_integrity.py` is honest about this — its section header says
"necessary, and demonstrably not sufficient" — but the `test_study.py` one carries
no such caveat and reads as coverage of the seam. Either strengthen it or label it.

## House rules

- A control that grep can see and the interpreter never reaches is the exact
  failure this file exists to name. Prefer a guard that **executes** over one that
  **matches text**, and keep both where they see different things.
- Every fix here should be demonstrated the way the finding was: mutate the code,
  show the test now fails, revert the mutation.
- `git status` must be clean of mutations before you finish.
