# Financial Alpha & Risk Research Lab *(internal tool)*

A quantitative research platform whose primary design goal is **not** finding
strategies — it is making the strategies it finds *believable*. The specification
is `prd_04_financial_alpha_research_lab.md`, which is **not in this repository**
and is not reachable from it — the link that used to be here resolved two
directories above the repository root and had never worked from a clone. Every
requirement it imposes is quoted at the top of the module that implements it, so
the code is readable without it; nothing here should be taken as a substitute
for the document itself.

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

| Component | Status | Where |
|---|---|---|
| **Research integrity** — trial counter, deflated Sharpe, protected holdout, pre-registration | built | `core.py`, `trial_counter.py`, `holdout.py` |
| Purged, embargoed cross-validation | built | `cross_validation.py` |
| Point-in-time data store — DuckDB over a bitemporal fact table | built | `point_in_time.py` |
| Minimal trial-search harness — enough to demonstrate the null-result benchmark | built | `search.py` |
| Execution costs, borrow, capacity in the primary result | built | `execution_costs.py` |
| Run reproducibility — data version, code SHA, parameters, seeds, environment | built | `run_record.py` |
| Experiment log — queryable across runs | built, **not MLflow** | `run_record.py` |
| Backtest engine — NautilusTrader, partial fills, latency | **dependency only, not wired** | — |
| Factor library — small, each factor unit-tested against known values | **not started** | — |

192 tests pass. Two caveats the row labels are too small to hold:

- **The experiment log is SQLite, not MLflow.** The PRD names MLflow; what is
  built satisfies FR-22 through FR-25 with the same triggers-not-conventions
  approach as the rest of the module. That is a deliberate substitution and it
  should be either ratified or reversed, not left as a silent divergence.
- **NautilusTrader is installed and pinned, and nothing imports it.** So FR-19
  (partial fills, latency) and FR-21 (structural absence of look-ahead) are
  currently **unmet**, not delegated. See the note under execution costs below.

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                      # 192 passed
.venv/bin/python scripts/null_benchmark_demo.py    # acceptance criteria 4 & 5
.venv/bin/python scripts/readme_tables.py          # regenerate this page's tables
```

Verified on CPython 3.14. `nautilus_trader` is the heaviest line in
`requirements.txt` by a wide margin and nothing imports it yet, so
`pip install numpy duckdb pytest` is enough to run the whole suite today.

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

## Global trial counter (FR-08, FR-15)

`TrialCounter` records every backtest run against every dataset, and supplies
the two inputs the deflated Sharpe needs but nothing previously recorded: the
trial count and the variance of Sharpe estimates across trials.

```python
from src.research_integrity import TrialCounter, deflated_sharpe_ratio

counter = TrialCounter("research.db")
trial = counter.start_trial("sp500", strategy="momentum", params={"lookback": 20})
counter.record_outcome(trial, sharpe=0.12, n_observations=1250)

inputs = counter.deflation_inputs("sp500")     # {"n_trials": ..., "var_trials": ...}
```

The effect, on one unchanged result as the search around it grows. Observed
per-period Sharpe **0.0413** — the best of the 7,866-trial sweep in the
null-benchmark section below — held fixed over 1,250 observations at normal skew
and kurtosis, with **V[{SR_n}] = 9.258e-05** as *recorded by the counter* across
that sweep. Only the trial count varies:

| trials run | deflated Sharpe | verdict at 95% |
|---:|---:|---|
| 10 | 0.8220 | **not** significant |
| 100 | 0.7251 | **not** significant |
| 1,000 | 0.6375 | **not** significant |
| 5,000 | 0.5811 | **not** significant |

Searching harder makes the same result less impressive, without anyone having to
choose to be honest.

**The variance is stated because the effect is entirely a function of it.** An
earlier version of this table showed a result crossing from significant to not
between 100 and 1,000 trials, and quoted no V[{SR_n}] at all — which made it
unreproducible, and, at the variance this sweep actually produces, wrong. The
figures above are regenerated by `python3 scripts/readme_tables.py`, and
`tests/test_readme_is_true.py` fails if this page and the code disagree.

A single-family parameter grid produces Sharpe estimates that cluster tightly,
so V[{SR_n}] is small and deflation bites gently — over this range it costs
about 0.24. A search across genuinely different strategy families would spread
those estimates much further and deflate far harder. That is the correct
behaviour and not a knob: the penalty scales with how much of the outcome space
the search actually covered, which is why the variance has to be measured from
recorded trials rather than assumed.

**Why it is append-only.** FR-08 requires counting "runs whose results were
discarded", so trials are recorded when they START, before the result exists,
and the SQLite schema refuses deletes and outcome rewrites by trigger — not by
convention. A researcher who can delete rows can manufacture any deflated Sharpe
they want, and "please don't" is not a control.

## Protected holdout (FR-10, FR-11, FR-12)

A holdout only means anything if looking at it is *hard*. The usual failure is
not dishonesty but drift: one peek to sanity-check a pipeline, another to
compare two variants, and by the tenth it is in-sample data everyone still calls
out-of-sample. No step in that sequence feels wrong at the time, which is why
this refuses rather than advises.

```python
from src.research_integrity import ProtectedHoldout

holdout = ProtectedHoldout("research.db")
holdout.define("sp500", start="2023-01-01", end="2024-12-31")

holdout.assert_ordinary_access("sp500", "2020-01-01", "2023-06-30")
# HoldoutViolation: requested range overlaps the protected holdout

reg = holdout.preregister("sp500", strategy_family="momentum",
                          hypothesis="20-day momentum survives out of sample",
                          expected_result="annualised Sharpe between 0.4 and 0.8")
verdict = holdout.evaluate(reg, observed={"sharpe_annualised": 0.31})
```

The exhaustion warning escalates with the number of looks, because the harm
does:

| looks at the same family | status |
|---:|---|
| 1 | no warning |
| 2–3 | `HOLDOUT EXHAUSTION` — treat the result as optimistic |
| 4+ | `HOLDOUT EXHAUSTED` — in-sample data; a fresh holdout is required |

The period is immutable once defined, registrations are content-hashed and
single-use, and evaluations cannot be deleted or edited — all enforced by SQLite
triggers. A holdout you can move after seeing results is not a holdout, and an
exhaustion count you can reset is not a count.

## Null-result benchmark (FR-16, acceptance criteria 4 & 5)

```bash
python3 scripts/null_benchmark_demo.py
```

The PRD calls criterion 5 "the most valuable acceptance test in this document"
and says to run it early, publicly, in front of everyone who will use the tool.
It runs one parameter sweep against a returns series, then the identical sweep
against those same returns **reshuffled**:

```
                                AS GIVEN    RESHUFFLED
  ----------------------------------------------------
  trials counted                   7,866         7,866
  best raw Sharpe                 0.0413        0.0535
  best parameters               (21, 22)       (9, 16)
  DEFLATED Sharpe                 0.5834        0.7594
```

Reshuffling preserves the marginal distribution exactly — same mean, volatility,
skew and kurtosis — while destroying every temporal relationship a trading rule
could exploit. There is nothing left to find. So the reshuffled column is the
score this *procedure* manufactures from noise at this trial count.

Here it scored **higher** than the real data. The raw Sharpe was measuring
search intensity, not signal. The deflated Sharpe is the headline figure
(FR-09), and both fall below 0.95 — the correct answer, which the raw figure
alone would have obscured in both columns. Note that the *reshuffled* column
deflates to 0.7594, the higher of the two: deflation is not a lie detector, and
a procedure searching 7,866 times over pure noise still lands well above zero.
What it does is put the two columns on a scale where the comparison is possible
at all.

The harness registers the entire sweep before evaluating any of it, so a search
cannot be truncated at the moment it starts looking good and reported as though
it had always been that size.

## Purged, embargoed cross-validation (FR-14)

A financial label resolves in the future: the observation at time *t* is
labelled by what happened over *[t, t+h]*. Two observations less than *h* apart
therefore share outcome information. Standard k-fold ignores that, so training
rows whose label windows overlap the test window have already seen part of the
answer — and every fold has the same leak, so repetition never reveals it.

```python
from src.research_integrity import PurgedKFold, assert_no_leakage

cv = PurgedKFold(n_splits=5, embargo_pct=0.01)
for train_idx, test_idx in cv.split(label_start, label_end):
    assert_no_leakage(train_idx, test_idx, label_start, label_end)
```

What naive k-fold would leak on 1,000 observations across 5 folds:

| label horizon | observations leaked | leak rate |
|---:|---:|---:|
| 1 | 8 | 0.16% |
| 10 | 80 | 1.60% |
| 25 | 200 | 4.00% |
| 50 | 400 | 8.00% |

**Purging** drops training rows whose label interval overlaps the test window —
the defining property, checkable directly via `assert_no_leakage`, which works
on splits from any splitter rather than requiring trust. **Embargo** then drops
rows starting just *after* the test window, since serial correlation leaks
through adjacency even when the windows do not touch.

There is no option to disable purging. FR-14 says naive k-fold must not be
offered, and a flag would be exactly that with an extra step — the leaky path
would become the one people take when the honest numbers disappoint.

## Execution costs and capacity (FR-17, FR-18, FR-20)

**The engine is to be NautilusTrader** (1.231.0, pinned and installed), as the
PRD specifies, and reimplementing an event-driven matching engine by hand when
the spec names one would repeat the Mitiq mistake made earlier in this project.

**It is not wired in yet, and nothing here imports it.** That matters more than
it sounds: FR-19 (partial fills, latency) and FR-21 (look-ahead structurally
impossible, because data arrives as timestamped messages rather than being
indexable) are therefore **unmet**, not delegated. An earlier version of this
paragraph said the library "supplies" both — but a dependency nothing calls
supplies nothing, and the sentence was the only thing in the repository
asserting otherwise. `tests/test_readme_is_true.py` now fails if that claim
reappears while no module imports the package.

What NautilusTrader would not supply even once wired, and is built here:

```python
from src.research_integrity import Instrument, capacity, execution_cost

big = Instrument("BIG", price=50.0, adv=10_000_000,
                 daily_volatility=0.02, shares_outstanding=1_000_000_000)
execution_cost(100_000, big)["total_bps"]        # 10.3 bps
capacity(big, gross_sharpe=2.0, turnover_per_year=12).aum_ceiling
```

| | large cap (10m ADV) | microcap (100k ADV) |
|---|---:|---:|
| cost of 100,000 shares | 10.3 bps | 135.2 bps |
| participation rate | 1.0% | 100.0% |
| AUM ceiling @ Sharpe 2.0 | $22,446m | $224m |

### The impact model is the paper's, not the folklore

Almgren, Thum, Hauptmann & Li (2005), equations (7) and (8), coefficients from
§4.3: **γ = 0.314, η = 0.142, α = 1, β = 3/5, δ = 1/4**.

The widely-quoted "square-root law" is **not** what that paper found. Its
abstract says: *"We reject the common square-root model for temporary impact as
function of trade rate, in favor of a 3/5 power law."* Doubling the trade rate
multiplies temporary impact by 2^0.6 = 1.516, not 2^0.5 = 1.414 — a 7% error,
exactly the size that survives every sanity check and quietly misprices a
strategy. There is a test that fails if β is set to 0.5.

**Borrow is a constraint, not a price** (FR-18): an unborrowable short raises
rather than costing more. Charging a higher fee for shares that do not exist to
lend produces a backtest of a strategy nobody could have run.

## Reproducibility (FR-22, FR-23, FR-24, FR-25)

```python
from src.research_integrity import ExperimentLog

log = ExperimentLog("runs.db", repo=".")
with log.run("momentum", params={"lookback": 20}, seeds={"numpy": 42},
             dataset_versions=["fundamentals@v3"], factors=["value"]) as run:
    run.record(backtest(lookback=20))

log.replay(run_id, backtest)     # re-executes and requires an identical hash
log.query(strategy="momentum", since="2024-01-01", outcome="completed")
```

**FR-23 is enforced, not asserted.** `replay()` restores the recorded seeds,
re-executes, and compares a canonical hash of the output against the one stored
at the time. A record with every field populated still fails to reproduce if an
unrecorded seed was consumed — and the whole failure mode is that *the missing
field is never the one you thought to record*. There is a test that consumes an
unrecorded random source and requires the replay to catch it.

**FR-24** rejects uncommitted code by default, or records the **full diff** with
`allow_uncommitted=True`. Dirtiness means uncommitted *code*: modifications to
tracked files always count, and untracked files count only when they are source.
Writing the experiment log into the repo would otherwise mark every subsequent
run as unknown-code and get the control switched off wholesale.

Run records are permanent, and identity, code and parameters are immutable —
SQLite triggers, as elsewhere in this module.
