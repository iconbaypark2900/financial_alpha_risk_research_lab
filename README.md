# Financial Alpha & Risk Research Lab *(internal tool)*

A quantitative research platform whose primary design goal is **not** finding
strategies — it is making the strategies it finds *believable*. The specification
is [`prd_04_financial_alpha_research_lab.md`](../../prd_04_financial_alpha_research_lab.md).

## Why this is built the way it is

From PRD 04 §0, on what will actually kill this project:

> Run a large number of trials against historical data and keep the ones that
> scored best. That procedure reliably manufactures strategies with excellent
> backtests and zero forward performance. With enough trials, a Sharpe ratio
> above 2 on in-sample data is achievable on pure noise, and the expected
> out-of-sample Sharpe of the selected strategy is approximately zero. **The more
> thoroughly you search, the more confidently wrong you become.**

Every component below exists to make that failure visible rather than invisible.
This is why the research-integrity module is built first, before any search
capability: the controls must exist before the thing they constrain.

## V0 scope — Trustworthy Backtests

| Component | Status |
|---|---|
| **Research integrity** — trial counter, deflated Sharpe, protected holdout, pre-registration | in progress |
| Point-in-time data store — Iceberg over Parquet, DuckDB query engine | not started |
| Factor library — small, each factor unit-tested against known values | not started |
| Backtest engine — NautilusTrader, with costs, borrow, partial fills, impact | not started |
| Minimal trial-search harness — enough to demonstrate the null-result benchmark | not started |
| Capacity analysis in the primary result | not started |
| Run reproducibility — data version, code SHA, parameters, environment | not started |
| Experiment log — MLflow | not started |

## Deliberately out of scope

- **Neo4j / knowledge graph.** PRD 04 NG3: *"Not a graph database application.
  Neo4j struck."* Factor research, backtesting and portfolio optimization are
  tabular time-series problems throughout.
- **Multi-tenancy, OPA, Vault, RBAC.** This is an internal tool run by the team
  that trades the strategies; those controls purchase against a threat model that
  does not exist.
- **Portfolio construction and risk analytics** — V1 (§5.5). Prior work staged in
  `migration_inbox/finGuard/` is the input to that phase, not to V0.

## History

The previous contents of this repository were template scaffolding inherited
from a shared project generator, not a considered implementation. It was removed
in favour of a build against the revised PRD. The prior state is recoverable at
the tag `template-before-v0-rebuild`.
