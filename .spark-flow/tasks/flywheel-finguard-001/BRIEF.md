# Task: flywheel-finguard-001

**Goal:** Flywheel pilot — validate Kelly/drawdown regression after finGuard merge.

**Workload:** Run Kelly criterion and drawdown test suites post-merge; confirm 23+ tests pass; close the antifragile loop with promoted learnings.

## Metadata

- owner: liaison
- workflow: data-flywheel
- workload_id: finguard-backtest-v1
- project: financial_alpha_risk_research_lab
- phase: alpha (Beta candidate)
- created: 2026-05-31

## Flywheel

workload_id: finguard-backtest-v1

## Objective

23+ kelly/drawdown tests must pass cleanly; no regression from finGuard merge.
Metric: `pytest tests/test_kelly.py tests/test_drawdown.py -q` → 23 passed, 0 failed.
