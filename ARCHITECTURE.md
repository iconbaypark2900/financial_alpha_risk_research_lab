# Financial Alpha & Risk Research Lab — Architecture

## Design Goal

The system's primary goal is **not** finding strategies — it is making the
strategies it finds *believable*. Every component exists to make overfitting
visible rather than invisible.

> Run a large number of trials against historical data and keep the ones that
> scored best. That procedure reliably manufactures strategies with excellent
> backtests and zero forward performance. **The more thoroughly you search, the
> more confidently wrong you become.**

Research integrity controls are built first, before any search capability.

## Package Layout

```
src/
├── research_integrity/        # V0 controls — the seam that makes them binding
│   ├── core.py                # Deflated Sharpe, minimum backtest length (FR-09, FR-13)
│   ├── trial_counter.py       # Every trial, counted, append-only (FR-08, FR-15)
│   ├── holdout.py             # Protected holdout and pre-registration (FR-10..FR-12)
│   ├── cross_validation.py    # Purged, embargoed splits (FR-14)
│   ├── point_in_time.py       # As-of and as-reported queries (FR-01, FR-02, FR-06, FR-07)
│   ├── factors.py             # Small factor library, each causality-checked
│   ├── backtest.py            # NautilusTrader engine, audited (FR-19, FR-21)
│   ├── execution_costs.py     # Impact, borrow, capacity (FR-17, FR-18, FR-20)
│   ├── run_record.py          # Enforced reproducibility (FR-22..FR-25)
│   ├── search.py              # Trial harness and null benchmark (FR-16)
│   ├── study.py               # The seam — the supported way to run a backtest
│   ├── workspace.py           # The stores, persisted
│   ├── ingest.py              # EDGAR fundamentals ingestion
│   ├── mirror.py              # Point-in-time mirror for offline work
│   └── universe.py            # Universe assembly
├── portfolio/                 # V1 — position sizing and risk (not controls)
│   ├── drawdown.py            # Drawdown series, VaR, ulcer index
│   ├── kelly.py               # Kelly criterion allocation
│   └── simulator.py           # Monte Carlo scenario simulator
```

Import path is `src.research_integrity` — the top-level package is literally
`src` (documented in `pyproject.toml`).

## The Seam: `study.py`

Until `study.py` existed, three of four controls constrained nothing: the holdout
guard was called only by its own docstring, no code path wrote a run record, and
FR-07's refusal was never triggered by a caller. Each was correct and each was
unreachable.

`Study` is the supported entry point. It invokes controls in an order where the
refusals come first:

```
1. FR-07  refuse a dataset that is not point-in-time
2. FR-10  refuse a range that overlaps the protected holdout
3. FR-06  resolve the dataset version, or refuse
4. FR-24  refuse uncommitted code (or record the diff)
5. FR-08  count the trial, before it can succeed
6.        run
7. FR-25  record the outcome, including failure
```

Four entry points exist (`search`, `backtest`, `search_series`, `backtest_series`);
only the `_series` variants close the date hole — they derive the range from the
store rather than accepting strings from the caller.

## Data Layer

### PointInTimeStore (`point_in_time.py`)

DuckDB over a bitemporal fact table. Answers "what was known as of date D".
Every read is point-in-time; look-ahead contamination is structurally impossible.

- **met**: FR-01 (point-in-time queries), FR-02 (as-first-reported fundamentals),
  FR-06 (versioned datasets), FR-07 (refuse non-PIT datasets)
- **partial**: FR-03 (survivorship — EDGAR has no delisting date, only last filing)
- **not implemented**: FR-04 (index membership), FR-05 (corporate actions)

### ExperimentLog (`run_record.py`)

SQLite-backed, **not MLflow** (ratified 2026-08-28). FR-23 requires re-execution
to produce identical results; `replay()` restores seeds, re-runs, and compares
hashes. MLflow logs but never checks reproducibility.

- **met**: FR-22 (every field recorded), FR-23 (replay-identical),
  FR-24 (uncommitted code rejected or fully diffed), FR-25 (queryable across runs)

### EDGAR Ingestion (`ingest.py`)

Free fundamentals from SEC EDGAR. Retains companies after delisting (CIK still
returns filings under post-bankruptcy shell name), providing partial survivorship.
No price data — fundamentals only.

## Research Integrity Modules

### Deflated Sharpe & Minimum Backtest Length (`core.py`)

Implements PRD 04 §5.2 (FR-09, FR-13). Formulas verified line-by-line against
published papers:

- **DSR**: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio"
- **MinBTL**: Bailey et al. (2014), "Pseudo-Mathematics and Financial Charlatanism"

Worked examples pinned as tests. All Sharpe ratios are **per-period**, matching
`sample_length` frequency — mixing annualised and daily is the failure this module
exists to prevent.

### Trial Counter (`trial_counter.py`)

Every trial counted, append-only. Global across all researchers and all time.
Used by `search` and `backtest` — counted before the result exists.

### Protected Holdout (`holdout.py`)

Holdout data is inaccessible to ordinary backtests. Access requires a
pre-registered hypothesis recorded before the run. Every evaluation recorded
permanently; repeats flagged as exhaustion.

### Purged Cross-Validation (`cross_validation.py`)

Purged and embargoed splits. Naive k-fold `KFold` is deliberately not offered —
`assert_no_leakage` enforces this.

### Factor Library (`factors.py`)

Small, each factor unit-tested against known values and causality-checked:

- `book_to_market_as_of` — value factor, point-in-time book value
- `momentum` — return momentum
- `realised_volatility` — volatility factor
- `reversal` — short-term reversal
- `size` — market capitalisation

### Backtest Engine (`backtest.py`)

NautilusTrader, event-driven. `LookAheadAudit` checks on every bar that nothing
visible postdates it. FR-21 is met and audited rather than argued — a test plants
a bar from 120 days ahead and requires the audit to catch it.

**Partial**: FR-19 (partial fills). Market orders against daily bars fill in full
even at 100× the bar's volume with `liquidity_consumption=True` because a bar
carries no depth. `test_market_orders_against_daily_bars_do_not_partial_fill` pins
this.

### Execution Costs (`execution_costs.py`)

Market impact as function of participation rate, borrow availability as hard
constraint, capacity as primary output.

## Portfolio Layer (`src/portfolio/`)

Separate from `research_integrity` because the two answer different questions.
The research-integrity layer asks whether a result is believable; this layer asks
how much to bet on one. **Nothing here is a control.**

- **drawdown.py**: Drawdown series, historical VaR, max drawdown, recovery time,
  ulcer index, risk metrics
- **kelly.py**: Kelly criterion, fractional Kelly, growth rate
- **simulator.py**: Monte Carlo scenario simulator, stress testing, statistics

Migrated from `docs/superseded/finGuard/` on 2026-08-28, formula by formula
against sources. Thirteen defects found and fixed across the three modules.

## Null Benchmark (`search.py`)

FR-16: null-result benchmark. Demonstrates that with enough trials on pure noise,
a Sharpe above 2 on in-sample data is achievable. The expected out-of-sample
Sharpe of the selected strategy is approximately zero.

## Key Decisions

| Decision | Rationale | Trade-off |
|---|---|---|
| SQLite over MLflow | FR-23 requires replay-identical results; MLflow logs but cannot enforce this | No MLflow UI/artifact storage |
| DuckDB over PostgreSQL | Time-series queries, point-in-time semantics, no external DB dependency | Not optimal for multi-tenant workloads |
| NautilusTrader over custom engine | Event-driven, audited, FR-21 structural guarantee | Heavy dependency, Cython |
| EDGAR over paid data | Free, retains delisted names (survivorship), no license destruction clause | No price data, no delisting dates, no index membership |
| No Neo4j / knowledge graph | Tabular time-series problems throughout | Cannot represent relational financial data |
| No multi-tenancy / OPA / Vault | Internal tool, no threat model justifies it | Not deployable as a service |
