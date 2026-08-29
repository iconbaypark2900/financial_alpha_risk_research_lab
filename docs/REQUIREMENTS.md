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
| FR-03 | Delisted securities retained (survivorship) | **partial** | `ingest.py` (EDGAR), `point_in_time.py` |
| FR-04 | Index membership with effective dates | **not implemented** | `point_in_time.py` (schema only) |
| FR-05 | Corporate actions | **not implemented** | `point_in_time.py` (schema only) |
| FR-06 | Datasets immutably versioned; backtests record the version used | met | `point_in_time.py`, `run_record.py` |
| FR-07 | REFUSE to run against a dataset that cannot supply point-in-time semantics | met | `point_in_time.py` |

**On FR-03 to FR-05.** These are data-*content* requirements. The schema carries
them as ordinary facts with effective dates, but nobody has loaded the vendor
data. Calling the store survivorship-free because it *could* hold delisted names
would be a claim about data that is not there, so they are marked not
implemented rather than partial.

**FR-03 moved, via SEC EDGAR.** EDGAR retains a company after it stops trading:
Bed Bath & Beyond (CIK 886158) still returns its full filing history under the
name of its post-bankruptcy shell, with empty `tickers` and `exchanges`. So a
universe assembled from EDGAR contains the dead, which is what the requirement
asks for, and `listing_status()` reads the signal.

It is **partial**, not met, and the gap is specific: EDGAR publishes no
delisting DATE, so `last_filing` is a proxy; and it carries FUNDAMENTALS, not
prices, so a survivorship-free *return* series is still unavailable. Calling
this met would be the overclaim this project keeps catching.

**FR-04 has not moved at all.** EDGAR publishes no index membership, with or
without effective dates.

**A cross-section does not close them.** `PointInTimeStore.panel` now reads a
real multi-asset cross-section, and six FRED index series have been loaded and
ranked. That is a genuine cross-section and it is **not** a universe: an index
has its constituent changes baked in, no name in it has ever been delisted, and
FRED publishes no membership history. FR-03 and FR-04 are exactly as open as
they were before the panel existed. The temptation is to read "we have a
cross-section now" as progress against them; it is progress against the *code
paths*, which had never seen more than one series, and against nothing else.

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

**FR-02 is demonstrated on a 13.68% restatement.** Apple's FY2009 stockholders'
equity was first reported as 27,832,000,000 on 2009-10-27 and restated to
31,640,000,000 a year later. A book-to-market computed today for early 2010 uses
a number nobody had, and it is out by 13.68% — not a rounding error, and enough
to move a value factor between deciles. `series()` returns the first report
however many times it was revised; the revision needs
`acknowledge_contamination=True`.

**FR-23 now covers the data too.** A run re-executing against a live API is not
reproducible however well its seeds were recorded. `mirror.py` downloads the
bulk EDGAR archive once, hashes it, and reads offline thereafter, so a run
record can name a specific 1,407,496,523-byte file by digest rather than a URL.

**FR-23 is enforced, not asserted.** `replay()` restores the recorded seeds,
re-executes, and compares a canonical hash against the one stored at the time; a
test consumes an unrecorded random source and requires the replay to catch it.
This is why the log is SQLite rather than the MLflow the PRD names — MLflow logs
and never checks. Ratified 2026-08-28 in `.spark-flow/memory/decisions.md`.

---

## §5.5 Portfolio construction (V1) — **requirements not known**

`src/portfolio/` implements PRD 04 §5.5. **Nobody in this repository has read
§5.5**, and unlike V0 its requirements cannot be reconstructed from the code,
because no module here has ever seen them. The section is listed so the hole is
recorded rather than implied by its absence.

The discipline everywhere else in this project is that a module opens by quoting
the requirement it implements. `src/portfolio/` quotes a *section number*. The
only FR numbers in it — FR-14 and FR-23 — are borrowed from V0 to explain design
decisions, not requirements V1 satisfies.

What is built, and what it was actually checked against:

| module | verified against | status |
|---|---|---|
| `kelly.py` | Kelly (1956); Thorp (2006) §7 | correct per the literature |
| `drawdown.py` | Martin & McCann (1989) for the Ulcer index; definitions for the rest | correct per the literature |
| `simulator.py` | its own closed forms — a zero-variance path has an exact terminal value | correct per construction |

**"Correct against the literature" is not "meets §5.5", and nothing here can
tell the difference.** Verifying against the published papers is what surfaced
thirteen defects in the migrated finGuard code, so it is far from worthless —
but it answers a question §5.5 did not ask. A portfolio layer can implement the
Kelly criterion flawlessly and still be the wrong thing to have built.

Two ways to close this, in order of preference:

1. Put PRD 04 in the repository, or a copy of §5.5 in `docs/`. Then each module
   gets its FR quotation like every V0 module has, and this section becomes a
   table like the four above it.
2. Failing that, write down what §5.5 is *believed* to require and mark it a
   reconstruction of unknown fidelity — which is worse than the document but
   better than the current state, where the requirement is neither written down
   nor known to be missing by anyone who has not read this page.

Until then, treat every V1 status claim as "correct mathematics, unverified
scope".

---

## Summary

Covers **FR-01 to FR-25 only** — V0, sections 5.1 through 5.4. V1 (§5.5) has no
requirement numbers here because nobody has them; see the section above.

| status | count |
|---|---:|
| met | 21 |
| partial | 2 |
| not implemented | 2 |

The remaining gaps still block on **data**, not engineering: order-book depth
(FR-19), a delisting date and survivorship-free PRICES (FR-03), index membership
with effective dates (FR-04), and corporate actions (FR-05). FR-03 moved from
not-implemented to partial because SEC EDGAR supplies survivorship-free
fundamentals with real filing dates — the first of these that turned out to be
reachable after all.
