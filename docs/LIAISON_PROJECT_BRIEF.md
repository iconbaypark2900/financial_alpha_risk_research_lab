# LIAISON PROJECT BRIEF — financial_alpha_risk_research_lab

> Machine: DGX Spark | Org: dataScience | Phase: Alpha
> Path: `~/dataScience/financial_alpha_risk_research_lab`
> Last updated: 2026-08-28

> **The sections below dated 2026-05-30/31 describe an architecture that no
> longer exists.** Commit `6eb543f` removed the template scaffolding and rebuilt
> the repository against the revised PRD 04; `src/portfolio_risk_service/` and
> its Kelly, drawdown and simulator modules went with it, and finGuard returned
> to `migration_inbox/` as V1 input. Those sections are kept as dated records of
> what was reviewed at the time — they are not descriptions of the current tree.
> The problem statement, happy path and validation profile have been rewritten
> to match what is actually here.

---

## Problem statement

A quantitative research platform whose design goal is not finding strategies but
making the ones it finds believable. V0 is the research-integrity layer: a global
trial counter, deflated Sharpe, a protected holdout, purged cross-validation, a
point-in-time store, execution costs and capacity, and enforced run
reproducibility. V1 (portfolio construction) is under way in `src/portfolio/`;
the finGuard migration that fed it **completed 2026-08-28**, and the source is
retired to `docs/superseded/finGuard/`.

---

## Happy path

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
# Expected: 248 tests passing

.venv/bin/python scripts/null_benchmark_demo.py
# Acceptance criteria 4 and 5. Deterministic; seeds are fixed in the script.
```

finGuard is retired and is not part of this project's gate. Its own 23 tests
still pass from `docs/superseded/finGuard/`, which is a caution rather than a
reassurance: thirteen defects were found in the code beneath them, including a
sign inversion in the portfolio Kelly. Do not import from there.

---

## Non-goals

- Live trading or brokerage API connections on DGX Spark
- Full finGuard merge in L2 scope (deferred to L4)

---

## Validation profile

| Field | Value |
|-------|-------|
| Profile | `python` |
| Smoke command | `.venv/bin/python -m pytest -q` |
| Note | `pip install numpy duckdb pytest nautilus_trader` — the engine slice needs the last one; its tests skip without it. |

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
| Documentation drifting from the code | `tests/test_readme_is_true.py` recomputes every numeric table in the README and fails when the page and the code disagree. Four tables were stale for six commits before it existed. |
| NautilusTrader named as the engine but not imported | RESOLVED 2026-08-28 — wired in `backtest.py`. FR-21 met and audited per bar; FR-19 partially met (no partial fills without book data). A test now guards against overclaiming in either direction. |
| FR-19 incomplete: no order-book data | Market orders against daily bars fill in full, so partial fills are not modelled. Pinned by a test that fails if that ever changes. Closing it needs L2/L3 data this project does not have. |

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

