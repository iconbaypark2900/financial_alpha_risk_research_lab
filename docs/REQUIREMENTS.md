# PRD 04 requirements — where each one lives, and whether it is met

**PRD 04 is not in this repository and is not reachable from it.** This page is
a reconstruction from the code: every module quotes the requirements it
implements at the top of its docstring, and this collects all 25 into one place.
It is a navigational aid and a status board, **not a substitute for the
document** — a requirement quoted by the code that implements it cannot
contradict itself, which is exactly the check this page cannot perform.

`tests/test_requirements_map.py` fails if a requirement referenced in `src/`
is missing here, or if this page invents one the code has never heard of.

Status vocabulary, used strictly:

- **met** — implemented, and a test fails if the behaviour regresses.
- **partial** — some clauses met, others not, with the gap named.
- **not implemented** — nothing here does this. Not "planned".

---

## §5.1 Data (FR-01 – FR-07)

| FR | Requirement | Status | Where |
|---|---|---|---|
| FR-01 | Data MUST be point-in-time: answer "what was known as of date D" | met | `point_in_time.py` |
| FR-02 | Fundamentals as-first-reported; restatements as separate versioned records; restated reads blocked or flagged | met | `point_in_time.py`, `factors.py` |
| FR-03 | Delisted securities retained (survivorship) | **not implemented** | `point_in_time.py` (schema only) |
| FR-04 | Index membership with effective dates | **not implemented** | `point_in_time.py` (schema only) |
| FR-05 | Corporate actions | **not implemented** | `point_in_time.py` (schema only) |
| FR-06 | Datasets immutably versioned; backtests record the version used | met | `point_in_time.py`, `run_record.py` |
| FR-07 | REFUSE to run against a dataset that cannot supply point-in-time semantics | met | `point_in_time.py` |

**On FR-03 to FR-05.** These are data-*content* requirements. The schema carries
them as ordinary facts with effective dates, but nobody has loaded the vendor
data. Calling the store survivorship-free because it *could* hold delisted names
would be a claim about data that is not there, so they are marked not
implemented rather than partial.

## §5.2 Research integrity (FR-08 – FR-16)

| FR | Requirement | Status | Where |
|---|---|---|---|
| FR-08 | Global count of every backtest per dataset, including discarded runs | met | `trial_counter.py`, `backtest.py` |
| FR-09 | Deflated Sharpe as the headline figure | met | `core.py`, `search.py` |
| FR-10 | Holdout inaccessible to ordinary backtests | met | `holdout.py` |
| FR-11 | Access requires a pre-registered hypothesis, recorded before the run | met | `holdout.py` |
| FR-12 | Every evaluation recorded permanently; repeats flagged as exhaustion | met | `holdout.py` |
| FR-13 | Minimum backtest length; short samples flagged | met | `core.py` |
| FR-14 | Purged, embargoed CV; naive k-fold MUST NOT be offered | met | `cross_validation.py` |
| FR-15 | Trial count across all researchers and all time | met | `trial_counter.py` |
| FR-16 | Null-result benchmark | met | `search.py`, `scripts/null_benchmark_demo.py` |

FR-09 and FR-13 are tested in `tests/test_research_integrity.py`, which
exercises the functions heavily (15 and 4 references respectively) without
citing the FR numbers in the test text.

## §5.3 Execution and the engine (FR-17 – FR-21)

| FR | Requirement | Status | Where |
|---|---|---|---|
| FR-17 | Market impact as a function of participation rate | met | `execution_costs.py`, `backtest.py` |
| FR-18 | Borrow availability as a hard constraint, not a cost adjustment | met | `execution_costs.py` |
| FR-19 | Partial fills and latency | **partial** | `backtest.py` |
| FR-20 | Capacity as a primary output | met | `execution_costs.py` |
| FR-21 | Look-ahead structurally impossible | met | `backtest.py` |

**FR-19 is the one open requirement in V0.** Latency and slippage are wired and
demonstrably change results. Partial fills are **not** produced: market orders
against daily bars fill in full even at 100x the bar's volume with
`liquidity_consumption=True`, because a bar carries no depth to consume, and
this project has no order-book data. `test_market_orders_against_daily_bars_do_not_partially_fill`
pins this and will fail if it ever changes.

**FR-21 is met and audited rather than argued.** `LookAheadAudit` checks on every
bar that nothing visible postdates it and that the visible count equals the
count delivered. A test plants a bar from 120 days ahead and requires the audit
to catch it, because an audit that has never failed is a decoration.

## §5.4 Reproducibility (FR-22 – FR-25)

| FR | Requirement | Status | Where |
|---|---|---|---|
| FR-22 | Record dataset versions, code SHA, parameters, seeds, environment, timestamps | met | `run_record.py` |
| FR-23 | Any past run re-executable, producing identical results | met | `run_record.py` |
| FR-24 | Uncommitted code rejected, or recorded as a full diff | met | `run_record.py` |
| FR-25 | Log queryable by strategy, factor, date range, outcome | met | `run_record.py` |

**FR-23 is enforced, not asserted.** `replay()` restores the recorded seeds,
re-executes, and compares a canonical hash against the one stored at the time; a
test consumes an unrecorded random source and requires the replay to catch it.
This is why the log is SQLite rather than the MLflow the PRD names — MLflow logs
and never checks. Ratified 2026-08-28 in `.spark-flow/memory/decisions.md`.

---

## Summary

| status | count |
|---|---:|
| met | 21 |
| partial | 1 |
| not implemented | 3 |

The three not-implemented requirements (FR-03, FR-04, FR-05) and the partial one
(FR-19) all block on **data this project does not have** — vendor delisting and
corporate-action histories, index membership with effective dates, and order-book
depth. None is blocked on engineering.
