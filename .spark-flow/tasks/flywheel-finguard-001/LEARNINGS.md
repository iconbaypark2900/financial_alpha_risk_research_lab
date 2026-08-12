# Learnings — flywheel-finguard-001

## Learning 1 — pytest.ini isolation pattern for partial merges

**Tags:** financial_alpha_risk_research_lab, flywheel, finguard-backtest-v1, testing

When merging a module from an external codebase (migration_inbox) into a repo with pre-existing unrelated tests, use `pytest.ini` with `addopts = --ignore=tests/<unrelated_test>.py` to isolate the new integration tests. This prevents false negatives from tests that depend on infrastructure not yet wired and keeps the CI signal clean for the merged module.

**Applicability:** Any staged merge integration where target repo has pre-existing tests in unknown state.

## Learning 2 — workload_id as flywheel anchor

**Tags:** financial_alpha_risk_research_lab, flywheel, finguard-backtest-v1

Explicitly tagging a task with `workload_id: <project>-<workload>-<semver>` in `BRIEF.md` before running the workload creates a clear traceability anchor. Future regression runs for the same workload can reference this ID to compare outcomes across versions (e.g. `finguard-backtest-v2` after next merge). This is the minimal viable flywheel tracking without requiring CLI schema support.

**Applicability:** All Beta+ flywheel tasks; backfillable to existing Alpha tasks advancing toward Beta.

## Learning 3 — Alpha projects benefit from flywheel discipline pre-Beta

**Tags:** financial_alpha_risk_research_lab, flywheel, alpha-to-beta

Running the full antifragile loop on an Alpha project (not yet Beta-gated) de-risks the Beta transition. The observe→evaluate→learn→improve cycle surfaces edge cases and documents rationale before the project is under production SLO pressure. The overhead is low (< 30 min for a small module merge) and the institutional memory gain is durable.

**Applicability:** Any Alpha project with a repeatable workload (test suite, benchmark, eval dataset) should run at least one flywheel pilot before declaring Beta readiness.
