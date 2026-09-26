# Financial Alpha & Risk Research Lab — Workflow

## Overview

The supported workflow is: **ingest → build universe → preregister → run study →
record → query**. The `Study` class (`src/research_integrity/study.py`) is the
only supported entry point for running backtests. It enforces the control order:
refusals first, then counting, then execution, then recording.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[all]'
.venv/bin/python -m pytest -q
```

Minimal install (`pip install -e .`) gives numpy alone and runs 421 of 601 tests.
The point-in-time store and engine degrade to `None` and their tests skip.

## Data Ingestion

### EDGAR Fundamentals

```python
from src.research_integrity.ingest import fetch_fundamentals
from src.research_integrity.workspace import install_workspace

# Install the workspace (creates DuckDB store)
workspace = install_workspace("sp500")

# Fetch fundamentals for a CIK
df = fetch_fundamentals(cik="0000320193")  # Apple
```

EDGAR retains companies after delisting — survivorship is partial (FR-03).
No price data, no delisting dates, no index membership.

### Point-in-Time Queries

```python
from src.research_integrity.point_in_time import PointInTimeStore

store = PointInTimeStore(workspace.path)

# "What was known as of 2024-06-15?"
df = store.panel.as_of("2024-06-15")

# Look-ahead contamination is structurally impossible
# (verified by test, not by documentation)
```

## Running a Study

### The Supported Path: `Study`

```python
from src.research_integrity.study import Study
from src.research_integrity.trial_counter import TrialCounter
from src.research_integrity.holdout import ProtectedHoldout
from src.research_integrity.run_record import ExperimentLog
from src.research_integrity.workspace import install_workspace

# Every argument is required — no defaults, because a missing control
# is a control switched off, and the whole point is that switching one off
# should take more effort than leaving it on.
workspace = install_workspace("sp500")
counter = TrialCounter(workspace.trials_db)
holdout = ProtectedHoldout(workspace.holdout_db)
log = ExperimentLog(workspace.experiments_db)

study = Study(
    dataset_id="sp500",
    store=workspace.store,
    counter=counter,
    holdout=holdout,
    log=log,
)

# The supported entry points
result = study.backtest_series(
    "AAPL",
    params={"lookback": 60},
    seeds={"numpy": 42},
)

# Or search across a grid
results = study.search_series(
    "AAPL",
    grid={"lookback": [30, 60, 120]},
    seeds={"numpy": 42},
)
```

### Control Order (enforced by `Study`)

```
1. FR-07  refuse a dataset that is not point-in-time
2. FR-10  refuse a range that overlaps the protected holdout
3. FR-06  resolve the dataset version, or refuse
4. FR-24  refuse uncommitted code (or record the diff)
5. FR-08  count the trial, before it can succeed
6.        run the backtest
7. FR-25  record the outcome, including failure
```

### Direct Module Access (not recommended)

The individual modules are correct but were unreachable before `study.py`
existed. Using them directly bypasses the control seam:

```python
# NOT RECOMMENDED — bypasses holdout guard, trial counter, run recording
from src.research_integrity.search import run_search
from src.research_integrity.cross_validation import PurgedKFold
from src.research_integrity.core import deflated_sharpe_ratio
```

## Experiment Logging & Replay

```python
from src.research_integrity.run_record import ExperimentLog, NotReproducible

log = ExperimentLog(workspace.experiments_db)

# Query across runs
runs = log.query(strategy="momentum", date_range=("2024-01-01", "2024-12-31"))

# Replay a past run — enforces FR-23 (bitwise-identical)
try:
    log.replay(run_id)
except NotReproducible:
    print("This run cannot be reproduced — seeds, code, or data changed")
```

`replay()` restores seeds, re-executes, and compares a canonical hash against
the one stored at the time. If they differ, the run was not reproducible.

### Seed Handling

Seeds belong in `params`, not in a `seeds` dict. The legacy `np.random.seed()`
global has no effect on `np.random.default_rng()`, which every module here uses.
Recording `seeds={"numpy": N}` is refused — it would claim reproducibility while
doing nothing. Use `seeds={"numpy_legacy": N}` only if you actually use the
legacy global (you shouldn't).

## Backtesting

```python
from src.research_integrity.backtest import run_backtest, bars_from_prices
from src.research_integrity.execution_costs import execution_cost

# Convert prices to bars
bars = bars_from_prices(prices, frequency="D")

# Run with execution costs
result = run_backtest(
    bars=bars,
    strategy=your_strategy,
    cost_model=execution_cost,
)

# Look-ahead audit runs on every bar
# (test plants a bar from 120 days ahead and verifies the audit catches it)
```

**Limitation**: FR-19 (partial fills) is partial. Daily bars carry no order-book
depth, so market orders fill in full even at 100× the bar's volume. This is
pinned by a test.

## Factor Research

```python
from src.research_integrity.factors import (
    FACTORS, book_to_market_as_of, momentum, realised_volatility
)

# Each factor is causality-checked (look-ahead impossible)
value = book_to_market_as_of(store, date="2024-06-15")
mom = momentum(prices, window=12)
vol = realised_volatility(prices, window=20)

# FACTORS is the registered library
for name, factor in FACTORS.items():
    print(f"{name}: {factor.description}")
```

## Cross-Validation

```python
from src.research_integrity.cross_validation import PurgedKFold, assert_no_leakage

# Purged + embargoed — naive k-fold is deliberately not offered
cv = PurgedKFold(n_splits=5, purge_periods=10, embargo_periods=5)

for train, test in cv.split(X):
    assert_no_leakage(X, train, test)  # structural guarantee
```

## Null Benchmark

Demonstrates that with enough trials on pure noise, a Sharpe above 2 on
in-sample data is achievable. The expected out-of-sample Sharpe is ~0.

```bash
.venv/bin/python scripts/null_benchmark_demo.py
```

## Portfolio Construction (V1)

```python
from src.portfolio.drawdown import risk_metrics, max_drawdown
from src.portfolio.kelly import portfolio_kelly, HALF_KELLY
from src.portfolio.simulator import simulate, stress

# Risk metrics
metrics = risk_metrics(returns)

# Position sizing
allocation = portfolio_kelly(returns, fraction=HALF_KELLY)

# Scenario simulation
result = simulate(returns, n_scenarios=10000)
stress_result = stress(result, scenarios=["2020-03", "2008-09"])
```

**Nothing here is a control.** This layer asks how much to bet on a strategy;
the research-integrity layer asks whether the strategy's results are believable.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/null_benchmark_demo.py` | Acceptance criteria 4 & 5 — null-result demonstration |
| `scripts/readme_tables.py` | Regenerate tables in README and MASTER |
| `scripts/install_workspace.py` | Install a named workspace (DuckDB store) |
| `scripts/real_data_pipeline.py` | End-to-end pipeline with real EDGAR data |

## Test Suite

```bash
.venv/bin/python -m pytest -q                    # 601 passed
.venv/bin/python -m pytest tests/test_packaging.py  # verifies pyproject.toml matches requirements.txt
.venv/bin/python -m pytest tests/test_readme_is_true.py  # README claims are verified
.venv/bin/python -m pytest tests/test_requirements_map.py  # FR references are consistent
```

## Key Workflows

### Adding a New Factor

1. Implement in `src/research_integrity/factors.py`
2. Add to `FACTORS` registry
3. Write causality test (look-ahead impossible)
4. Write known-value test against published example
5. Add to `tests/test_factors.py`

### Adding a New Data Source

1. Implement ingestion in a new module (follow `ingest.py` pattern)
2. Add to `PointInTimeStore` schema if needed
3. Update `workspace.py` if persistence is required
4. Write tests for point-in-time semantics
5. Update `docs/REQUIREMENTS.md` if new FRs are involved

### Running a Reproducibility Check

```python
from src.research_integrity.run_record import ExperimentLog

log = ExperimentLog(workspace.experiments_db)
log.replay(run_id)  # raises NotReproducible if anything changed
```
