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

- **508 tests pass** (`pytest -q`), 338 of them on a minimal install, and now on every push: `.github/workflows/tests.yml` runs a 3.12/3.13/3.14 matrix plus a minimal-install job.
- **V0 is feature-complete.** NautilusTrader is wired (`backtest.py`, added
  2026-08-28). FR-21 is met and audited on every bar of every run. FR-19 is
  PARTIALLY met: latency and slippage are demonstrated, partial fills are not —
  they need order-book depth this project has no data for, and the limitation is
  pinned by a test rather than left to be discovered.
- **V1 has started** (2026-08-28). `src/portfolio/` holds Kelly sizing and
  drawdown control, migrated from finGuard formula by formula against Kelly
  (1956), Thorp (2006) and Martin & McCann (1989). Nine defects were found in
  the 302 lines that shipped with 23 passing tests, including a SIGN INVERSION
  in the portfolio Kelly (dividing by a negative weight sum flipped every
  position) and a recovery-time formula understating the wait by 41.5% at a 50%
  drawdown. Each has a regression test named after it.
- The MLflow-vs-SQLite divergence is RATIFIED (see decisions.md): SQLite stays,
  because FR-23 requires enforced reproducibility and MLflow only logs.
- **Packaging and CI landed 2026-08-28.** `pyproject.toml` makes the project
  installable (`pip install -e '.[all]'`), moves the pytest config off
  `pytest.ini`, and adds `pythonpath` — without which the suite ran only when
  pytest was invoked from the repository root, which is not how CI invokes it.
  duckdb and nautilus_trader are modelled as extras because the package really
  does work without them: 272 of 325 tests pass on numpy alone.
- **V1's migration is complete** (2026-08-28). `simulator.py` was REWRITTEN
  rather than migrated: its output was a product of the two defective functions
  plus three of its own — one shared drawdown peak across all paths (path 2
  began 50% underwater), returns measured against path 0's terminal wealth
  (P(loss) 0.4 reported as 0.6), and no seed at all. Thirteen defects across
  the three finGuard modules in total.
- `migration_inbox/` is **retired** (2026-08-28) to `docs/superseded/finGuard/`
  with a RETIRED.md naming the thirteen defects. Its own 23 tests still pass
  from there, which is the hazard rather than a reassurance; a test now fails if
  anything imports `finguard` or if the inbox reappears.
- An independent review of the 9-commit diff (2026-08-28) found **15 defects in
  code written this session**, two of them severe: `stress()` re-optimised the
  portfolio for each scenario, so a market crash reported +8.99% annualised;
  and `book_to_market_as_of` returned the RESTATEMENT, a direct FR-02 violation.
  All fixed, each with a regression test. The lesson is the one already in this
  file about finGuard: tests that exercise code do not check it.
- **The controls are now binding** (2026-08-28, `study.py`). Three of the four
  constrained nothing before it: the holdout guard was called only by its own
  docstring, no code path wrote a run record, and FR-07's refusal was never
  triggered by a caller. Each was correct and each was unreachable — a suite
  organised per-module cannot see that, because the gap is between the modules.
  `Study` invokes them in an order where the refusals precede the trial count,
  and a test now fails, by name, if any control is orphaned again.
- **Real data now runs end to end** (2026-08-28, `ingest.py` +
  `scripts/real_data_pipeline.py`). FRED SP500 for prices, ALFRED GDPC1 by
  vintage for genuine as-first-reported semantics — two vintages four months
  apart contain a real revision (22,672.859 -> 22,679.255) and a quarter the
  earlier vintage could not contain. The result on the S&P 500: not one of
  2,691 moving-average variants beat buy-and-hold, and the reshuffled series
  scored higher than the real one. FR-03/04/05 are STILL not implemented —
  index levels are a survivorship-adjusted composite, not a universe.
- **The machine has now been pointed at a believed strategy** (2026-08-28,
  `scripts/believed_strategy.py`): Faber's 200-day timing rule, pre-registered
  before evaluation, the first real use of the holdout machinery. Verdict: the
  DRAWDOWN claim is durable (all 9 windows cut it, in and out of sample); the
  SHARPE claim sits inside the 0.224 spread of window choice against a 0.021
  gap to buy-and-hold. Both legs held on a 414-day holdout, which is a result
  and not a vindication.
- **FR-23 is now demonstrated, not asserted** (2026-08-28). `replay()` was
  correct, tested 14 times in its own file, and called by nothing — the orphan
  problem again, and the orphan guard did not cover `.replay(`. The real-data
  pipeline now replays its own recorded run: reproduced, hash identical, trial
  count unchanged at 2,691 (a replay is verification, not new research).
- **The workspace persists** (2026-08-28, `workspace.py`). Every script built
  its counter, holdout and run log in a TemporaryDirectory, so FR-08's count
  reset every run and holdout exhaustion never escalated. Measured effect of
  fixing it: the same sweep run twice now deflates 0.1366 -> 0.1279, because the
  counter remembers. Default home `~/.financial-alpha-research-lab`, outside any
  checkout.
- Also fixed: `believed_strategy.py` read `exhaustion_status`, a key that has
  never existed, with a plausible default — so it reported "first look" however
  exhausted the holdout was. A contract test now pins the keys evaluate()
  returns.
- A workspace is **installed** at `~/.financial-alpha-research-lab` with the
  real FRED/ALFRED data and the holdout defined, zero trials — via
  `scripts/install_workspace.py`, which is separate from the demos so a
  2,691-trial demonstration sweep is not baked into the global count forever.
- `believed_strategy.py` now persists too; four runs walk the holdout from first
  look to EXHAUSTED. `null_benchmark_demo.py` and `readme_tables.py` stay
  ephemeral deliberately (their output is asserted by the README tests) and a
  test pins that split in both directions.
- Demo scripts are **ephemeral by default**; `--home` opts in. For a short
  while they defaulted to the production workspace, so a bare
  `real_data_pipeline.py` would have added 2,691 demo trials to the global count
  and `believed_strategy.py` would have spent a look at the real holdout. Two
  tests now assert the fallback is a scratch path, and that only the installer
  targets the default home.
- **A real cross-section ran for the first time** (2026-08-28). Six FRED index
  series through the factor library, panel read and purged CV. Found: an O(n)
  query in `load` that never finished at 58,699 facts (now one query, 56s); WTI
  crude at -36.98 on 2020-04-20, which the factor library correctly refuses and
  `store.non_positive()` now screens for at load; and 88% ragged dates, handled
  with NaN rather than forward-fill. Cross-sectional momentum scored +0.01361
  against +0.06118 for equal-weighting — five times worse than doing nothing.
- **A real multi-company universe builds from the mirror** (`universe.py`).
  Selection is by CIK order and nothing else, because history length, data
  completeness and balance-sheet size all condition on survival. Measured
  result on 672 companies: 10.2% restated, rank correlation 0.999687, and the
  effect depends on granularity — 0.96% of names change DECILE but 7.35% change
  PERCENTILE. The median revision (1.0%) equals the median gap between adjacent
  ranks (1.0%), which is exactly why. Look-ahead is severe in a time-series
  claim, worth ~7% of names on a fine sort, and nearly nothing on a coarse one.
- **The EDGAR bulk archive is mirrored** at
  `~/.financial-alpha-research-lab/mirrors/companyfacts.zip` — 1,407,496,523
  bytes, 20,281 companies, sha256 314ebb31...  Reads are offline; the digest is
  what a run record names, so FR-23 covers the DATA and not just the code.
  Measured with it: 38.3% of filers restate a period of stockholders' equity.
- **FR-03 moved to PARTIAL via SEC EDGAR** (2026-08-28). EDGAR retains delisted
  companies (BBBY returns full history, empty tickers, post-bankruptcy name) and
  carries both `end` and `filed` on every record, so as-first-reported is a
  property of the source. Demonstrated FR-02 on Apple's real 13.68% FY2009
  restatement. Still partial: no delisting DATE, and fundamentals not prices.
  FR-04 has not moved.
- Found by it: `load` marked restatements only against what was already stored,
  so EDGAR's single-payload vintages went entirely unmarked (0 -> 9).
- **FR-03/FR-04 were NOT closed by the index cross-section.** An index has constituent changes baked
  in and no name in it was ever delisted; that data is not free anywhere.
  Recorded explicitly in docs/REQUIREMENTS.md.
- The Beta gate cannot be run here: the `liaison` CLI is not installed and
  `~/spark/agent-system/registry/repos.yaml` does not exist.
- **The engineering backlog is empty.** What remains is procurement (order-book
  data for FR-19's partial fills) and process (the Beta gate) — neither is code.
- **Nothing is pushed.** `origin/main` is behind by every commit made on
  2026-08-28; CI will not run until it is.
- The factor library landed 2026-08-28: `factors.py`, five factors, each tested
  against hand-derived values, plus `assert_causal` — a mechanical look-ahead
  check that perturbs the future and requires the past not to move. It composes
  with the engine's `LookAheadAudit`: the first guarantees the factor does not
  read forward within its array, the second that the array never contains the
  future.
- The experiment log is SQLite, not the MLflow the PRD names. Deliberate; owed a
  ratify-or-reverse decision.

## Latest debrief

- `.spark-flow/memory/debriefs/2026-08-28T212432.md`
- Prior: `.spark-flow/memory/debriefs/2026-05-31T000038.md` — predates the V0
  rebuild, and its six recommendations came from the template backlog since
  replaced. Read as a dated record, not as guidance.

## Next recommended action

- Ack the 2026-08-28 debrief and run the Beta gate; all three Alpha exit
  criteria are met and recorded with evidence in `PROJECT_PHASE.md`.
- Do NOT run `liaison debrief` expecting new engineering options: the backlog
  deliberately has no `recommended` entry, because both open items are blocked
  on data and process rather than code.

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

