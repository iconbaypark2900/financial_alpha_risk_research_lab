# LIAISON PROJECT BRIEF — financial_alpha_risk_research_lab

> Machine: DGX Spark | Org: dataScience | Phase: Alpha
> Path: `~/dataScience/financial_alpha_risk_research_lab`
> Last updated: 2026-05-30

---

## Problem statement

A quantitative finance research platform for developing, testing, and optimizing trading strategies with advanced risk management — and the target integration repo for the finGuard Kelly/drawdown/simulator migration.

---

## Happy path

```bash
cd ~/dataScience/financial_alpha_risk_research_lab
.venv/bin/python -m pytest tests/ -q
# Expected: 28 tests passing
PYTHONPATH=migration_inbox/finGuard/src .venv/bin/python -m pytest migration_inbox/finGuard/tests/ -q
# Expected: 23 tests passing
```

---

## Non-goals

- Live trading or brokerage API connections on DGX Spark
- Full finGuard merge in L2 scope (deferred to L4)

---

## Validation profile

| Field | Value |
|-------|-------|
| Profile | `python` |
| Smoke command | `.venv/bin/python -m pytest tests/ -q` |
| Note | Requires: `pip install pandas numpy yfinance pytest-asyncio` in `.venv` |

```bash
cd ~/dataScience/financial_alpha_risk_research_lab
liaison validate --profile python
```

---

## Hub pattern and recommended agents

| Agent | Role |
|-------|------|
| hermes | Integration engineering, git, Kelly/drawdown implementation |
| codex | Minimal patches — test fixes, import cleanup |

Pattern: `python-cli`

---

## Open risks

| Risk | Mitigation |
|------|------------|
| Financial risk — research vs live | Label all outputs as research; no live API keys in git |
| finGuard merge scope creep | L1 proof closed (`finguard-proof-001`); merge scoped to L4 |
| Missing pyproject.toml | python profile runs but uses system pytest; venv activation required |

---

## Related

- [project_profile.yaml](../.spark-flow/project_profile.yaml)
- [.spark-flow/README.md](../.spark-flow/README.md)
- Task: `finguard-proof-001` (closed L1)
- Merge plan: [docs/merge_plans/finGuard_to_financial_alpha_risk_research_lab_integration_plan.md](merge_plans/finGuard_to_financial_alpha_risk_research_lab_integration_plan.md)

---

## L4 Domain Risk Review — Financial (2026-05-31)

**Review scope:** financial domain — paper trading gate, API key hygiene, backtest labeling

| Control | Status | Evidence |
|---------|--------|----------|
| `paper_trading_mode = True` / no live API keys in `.spark-flow/` | PASS | No live brokerage keys found in repo; yfinance used read-only |
| Backtest outputs labeled as research | PASS | outputs directory is gitignored; no production trade signals |
| risk_metric boundaries documented | PASS | KellyCriterion caps at 1.0; DrawdownManager default max 20% |
| finGuard integration: kelly/drawdown/simulator | PASS | L4 merge complete; 23 tests green; execution owner Hermes |

**Risk classification:** MEDIUM — quantitative research tool; no live trading wired; no external credentials in git.

**Decision:** Accept current risk posture. Follow-up: wire `paper_trading_mode` check into validation profile (L5).

---

## L5 Flywheel Pilot — financial_alpha_risk_research_lab (2026-05-31)

**workload_id:** `finguard-backtest-v1`
**Task:** `flywheel-finguard-001` (closed)

**Pilot outcome:** Full antifragile loop closed. 23/23 kelly/drawdown tests passed. `liaison validate --profile data-flywheel` passed.

**Loop artifacts:**

| Artifact | Status |
|----------|--------|
| OBSERVATIONS.md | Present — workload results + hub pattern confirmation |
| EVALUATIONS.md | Present — regression gate PASS (5/5), loop completeness PASS (5/5) |
| LEARNINGS.md | Present — 3 durable learnings |
| IMPROVEMENTS.md | Present — 3 improvement actions queued |
| CLOSEOUT.md | Present — flywheel pilot closed 2026-05-31 |

**Promoted learnings (tags: financial_alpha_risk_research_lab, flywheel, finguard-backtest-v1):**
1. pytest.ini isolation pattern for partial merges
2. workload_id as flywheel anchor
3. Alpha projects benefit from flywheel discipline pre-Beta

**Flywheel cadence (ongoing):**
- Run `finguard-backtest-v{n+1}` on each new module merge from migration_inbox
- Gate: `liaison validate --profile data-flywheel` before task close
- Promote learnings with tags `financial_alpha_risk_research_lab,flywheel`
- Beta readiness task: `financial-alpha-beta-gate-001` (queued)

