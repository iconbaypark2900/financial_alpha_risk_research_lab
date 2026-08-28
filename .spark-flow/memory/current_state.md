# Current state

- Project: `/home/iconbaypark2900/dataScience/financial_alpha_risk_research_lab`
- Updated: 2026-08-28
- Project phase: Alpha (`alpha`)
- After task: V0 research-integrity build (commits `6eb543f`..`6d39c2a`), then a
  documentation truth-up

## What is actually in the tree

The finGuard integration recorded below was **reverted** by commit `6eb543f`,
which removed the template scaffolding — `src/portfolio_risk_service/` included —
and rebuilt against the revised PRD 04. finGuard is back in `migration_inbox/`
as V1 input. The closed-slice log further down is a record of what happened, not
of what is present.

Present now, all under `src/research_integrity/`: `core.py` (deflated Sharpe,
minimum backtest length), `trial_counter.py`, `holdout.py`, `cross_validation.py`,
`point_in_time.py`, `execution_costs.py`, `run_record.py`, `search.py`.

- **248 tests pass** (`.venv/bin/python -m pytest -q`).
- **V0 is feature-complete.** NautilusTrader is wired (`backtest.py`, added
  2026-08-28). FR-21 is met and audited on every bar of every run. FR-19 is
  PARTIALLY met: latency and slippage are demonstrated, partial fills are not —
  they need order-book depth this project has no data for, and the limitation is
  pinned by a test rather than left to be discovered.
- Outstanding, in rough priority order: order-book data to close FR-19; the
  MLflow-vs-SQLite decision below; then V1 (portfolio construction, the finGuard
  material in `migration_inbox/`).
- The factor library landed 2026-08-28: `factors.py`, five factors, each tested
  against hand-derived values, plus `assert_causal` — a mechanical look-ahead
  check that perturbs the future and requires the past not to move. It composes
  with the engine's `LookAheadAudit`: the first guarantees the factor does not
  read forward within its array, the second that the array never contains the
  future.
- The experiment log is SQLite, not the MLflow the PRD names. Deliberate; owed a
  ratify-or-reverse decision.

## Latest debrief

- `.spark-flow/memory/debriefs/2026-05-31T000038.md`

## Next recommended action

- Run `liaison debrief --show` to generate ranked options.

## Built (closed slices)

- 2026-05-31T00:01:38 `finguard-proof-001`: Proof slice complete (L1). finGuard inbox assets verified: kelly, drawdown, simulator, visualizer all importable; 23/23 finGuard unit tests pass; 28/28 repo tests pass (required pytest-asyncio + pandas + yfinance installs). Merge deferred to L4 after L2 profile enrichment and operator approval. Requirements: add pytest-asyncio, pandas, numpy, yfinance to requirements.txt for future venv setups.
- 2026-05-31T01:10:11 `finguard-integration-001`: finGuard → financial_alpha_risk_research_lab integration complete; 23 tests green; KellyCriterion, DrawdownManager, MonteCarloSimulator wired into portfolio_risk_service; execution owner Hermes

## Open recommendations / todo

- See `tasks/backlog.yaml`

## Repo git status

Recorded 2026-05-31, before the rebuild. The files listed were either committed
or removed by `6eb543f`; run `git status` for the live answer rather than
trusting this block.

```text
?? .spark-flow/
?? docs/LIAISON_PROJECT_BRIEF.md
?? pytest.ini
?? src/portfolio_risk_service/drawdown.py
?? src/portfolio_risk_service/kelly.py
?? src/portfolio_risk_service/simulator.py
?? tests/test_drawdown.py
?? tests/test_kelly.py
```

