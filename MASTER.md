# Financial Alpha & Risk Research Lab — Master Plan

## Vision

A quantitative research platform whose primary design goal is **not** finding
strategies — it is making the strategies it finds *believable*. Research
integrity controls built first, before any search capability.

**Version**: 0.1.0
**Tests**: 601 passing (421 with minimal install — numpy alone)
**Python**: 3.12+ (numpy and nautilus_trader both require it; nautilus caps at <3.15)

## Components

### V0 — Research Integrity (built)

| Component | Module | Requirements |
|---|---|---|
| Deflated Sharpe & min backtest length | `core.py` | FR-09, FR-13 |
| Trial counter (append-only, global) | `trial_counter.py` | FR-08, FR-15 |
| Protected holdout & pre-registration | `holdout.py` | FR-10, FR-11, FR-12 |
| Purged, embargoed cross-validation | `cross_validation.py` | FR-14 |
| Point-in-time data store (DuckDB) | `point_in_time.py` | FR-01, FR-02, FR-06, FR-07 |
| Factor library (causality-checked) | `factors.py` | — |
| NautilusTrader backtest engine | `backtest.py` | FR-19, FR-21 |
| Execution costs (impact, borrow, capacity) | `execution_costs.py` | FR-17, FR-18, FR-20 |
| Experiment log (SQLite, replay-identical) | `run_record.py` | FR-22, FR-23, FR-24, FR-25 |
| Trial harness & null benchmark | `search.py` | FR-16 |
| The seam (supported entry point) | `study.py` | All controls binding |
| Workspace (persisted stores) | `workspace.py` | — |
| EDGAR fundamentals ingestion | `ingest.py` | — |
| Point-in-time mirror (offline) | `mirror.py` | — |
| Universe assembly | `universe.py` | — |

### V1 — Portfolio Construction (built, not controls)

| Component | Module |
|---|---|
| Drawdown series, VaR, ulcer index | `portfolio/drawdown.py` |
| Kelly criterion allocation | `portfolio/kelly.py` |
| Monte Carlo scenario simulator | `portfolio/simulator.py` |

### Build Slices

| Install | Dependencies | Tests |
|---|---|---|
| `pip install -e .` | numpy | 421 |
| `pip install -e .[store]` | + duckdb | + point-in-time tests |
| `pip install -e .[engine]` | + nautilus_trader | + backtest tests |
| `pip install -e .[all]` | + both + pytest | 601 |

## Requirements Status

### Data (FR-01 – FR-07)

| FR | Requirement | Status |
|---|---|---|
| FR-01 | Point-in-time queries | met |
| FR-02 | Fundamentals as-first-reported | met |
| FR-03 | Survivorship (delisted retained) | **partial** — EDGAR has no delisting date |
| FR-04 | Index membership with effective dates | not implemented |
| FR-05 | Corporate actions | not implemented |
| FR-06 | Datasets immutably versioned | met |
| FR-07 | Refuse non-PIT datasets | met |

### Research Integrity (FR-08 – FR-16)

| FR | Requirement | Status |
|---|---|---|
| FR-08 | Global trial count | met |
| FR-09 | Deflated Sharpe as headline | met |
| FR-10 | Holdout inaccessible to ordinary backtests | met |
| FR-11 | Pre-registered hypothesis required | met |
| FR-12 | Permanent evaluation record | met |
| FR-13 | Minimum backtest length | met |
| FR-14 | Purged, embargoed CV | met |
| FR-15 | Trial count across all researchers | met |
| FR-16 | Null-result benchmark | met |

### Execution & Engine (FR-17 – FR-21)

| FR | Requirement | Status |
|---|---|---|
| FR-17 | Market impact vs participation rate | met |
| FR-18 | Borrow availability as hard constraint | met |
| FR-19 | Partial fills and latency | **partial** — no order-book depth |
| FR-20 | Capacity as primary output | met |
| FR-21 | Look-ahead structurally impossible | met |

### Reproducibility (FR-22 – FR-25)

| FR | Requirement | Status |
|---|---|---|
| FR-22 | Record dataset, code SHA, params, seeds, env | met |
| FR-23 | Replay produces bitwise-identical results | met |
| FR-24 | Uncommitted code rejected or fully diffed | met |
| FR-25 | Queryable across all runs | met |

See [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) for full status with
justifications and [`docs/DATA_DECISION.md`](docs/DATA_DECISION.md) for the
data-source decisions.

## Development History

### Superseded Spec

The project's original spec (in four formats) lived unmarked at the repo root,
contradicting this README on Neo4j, Backtrader, Vault, OPA and MLflow. It is now
in [`docs/superseded/`](docs/superseded/) with a note on what it broke: it is
where `requirements.txt`'s 26 unused pins came from, and where the task backlog
got the idea that this project needed semantic retrieval.

### Key Ratifications

- **2026-08-28**: Experiment log is SQLite, not MLflow (FR-23 requires replay,
  which MLflow cannot enforce)
- **2026-08-30**: Data-blocked requirements (FR-03..FR-05, FR-19) are decided,
  not pending — free data (EDGAR) adopted; paid licences rejected

## Running It

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[all]'
.venv/bin/python -m pytest -q                    # 601 passed
.venv/bin/python scripts/null_benchmark_demo.py  # acceptance criteria 4 & 5
.venv/bin/python scripts/readme_tables.py        # regenerate this page's tables
```
