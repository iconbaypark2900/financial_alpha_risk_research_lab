# Improvements — flywheel-finguard-001

## Improvement 1 — Add `finguard-backtest-v2` baseline on next merge

**Priority:** high
**Owner:** liaison
**Action:** When the next finGuard module is integrated (e.g. `simulator.py` end-to-end stress test), create `flywheel-finguard-002` with `workload_id: finguard-backtest-v2`. Diff outcome against this task's evaluation score to track regression.

**Trigger:** Next staged merge from `migration_inbox/finGuard` or equivalent.

## Improvement 2 — Enable full test suite after resolving test_market_data_pipeline.py deps

**Priority:** medium
**Owner:** liaison
**Action:** Remove the `--ignore=tests/test_market_data_pipeline.py` exemption from `pytest.ini` once the market data pipeline's external dependencies (e.g. data source connectors) are available in the dev environment. Until then, document the exemption in the project README so operators are aware.

**Trigger:** Dev environment dependency availability or explicit decision to stub the pipeline.

## Improvement 3 — Formalize Beta readiness gate for financial_alpha_risk_research_lab

**Priority:** medium
**Owner:** liaison
**Action:** Open a liaison task `financial-alpha-beta-gate-001` to formally assess Beta readiness: SLO definition, rollback path, data policy review, and flywheel cadence confirmation. This pilot establishes the observability baseline needed for that gate.

**Trigger:** Post-L5 layer close or when operator declares this project ready for Beta promotion.
