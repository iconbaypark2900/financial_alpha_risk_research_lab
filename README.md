# Financial Alpha & Risk Research Lab *(internal tool)*

A quantitative research platform whose primary design goal is **not** finding
strategies — it is making the strategies it finds *believable*. The specification
is `prd_04_financial_alpha_research_lab.md`, which is **not in this repository**
and is not reachable from it — the link that used to be here resolved two
directories above the repository root and had never worked from a clone. Every
requirement it imposes is quoted at the top of the module that implements it,
and [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) collects all twenty-five into
one page with their status. That is a reconstruction from the code, not a
substitute for the document.

The repository root also held the project's **original** spec in four formats,
unmarked, contradicting this README on Neo4j, Backtrader, Vault, OPA and MLflow.
It is now in [`docs/superseded/`](docs/superseded/) with a note on what it broke:
it is where `requirements.txt`'s 26 unused pins came from, and where the task
backlog got the idea that this project needed semantic retrieval.

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
| Experiment log — queryable across runs | built, **not MLflow** (ratified) | `run_record.py` |
| Backtest engine — NautilusTrader, event-driven, audited | built | `backtest.py` |
| Factor library — small, each factor unit-tested against known values | built | `factors.py` |

453 tests pass, on every push. Two caveats the row labels are too small to hold:

- **The experiment log is SQLite, not MLflow — ratified 2026-08-28.** The PRD
  names MLflow, which *logs* and never checks whether a run reproduces. FR-23
  requires re-execution to produce identical results, and `replay()` enforces
  that by restoring seeds, re-running, and comparing hashes. Adopting MLflow
  would meet the letter of the instruction by weakening the requirement it was
  named to serve. Recorded in `.spark-flow/memory/decisions.md`; revisit as an
  export layer if the team wants the UI.
- **FR-19 is only partially met.** The engine is wired and FR-21 holds and is
  audited, but *partial fills* need order-book depth this project does not have.
  Latency and slippage are demonstrated; partial fills are not. See the engine
  section below — the limitation is pinned by a test, not left to be found.

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[all]'                  # or: -r requirements.txt
.venv/bin/python -m pytest -q                      # 453 passed
.venv/bin/python scripts/null_benchmark_demo.py    # acceptance criteria 4 & 5
.venv/bin/python scripts/readme_tables.py          # regenerate this page's tables
```

Python 3.12 or later — numpy and `nautilus_trader` both require it, and the
latter caps at 3.15. CI runs 3.12, 3.13 and 3.14.

**The optional slices are genuinely optional.** `pip install -e .` gives numpy
alone and runs **338 of the 453 tests**; the point-in-time store and the engine
degrade to `None` and their tests skip. `[store]` adds DuckDB, `[engine]` adds
NautilusTrader, `[all]` adds both plus pytest. A CI job installs the minimal
form and asserts the degradation, because that claim had been checked only by
hand until it wasn't — and when it finally was, it failed.

## Deliberately out of scope

- **Neo4j / knowledge graph.** PRD 04 NG3: *"Not a graph database application.
  Neo4j struck."* Factor research, backtesting and portfolio optimization are
  tabular time-series problems throughout.
- **Multi-tenancy, OPA, Vault, RBAC.** This is an internal tool run by the team
  that trades the strategies; those controls purchase against a threat model that
  does not exist.
- **Portfolio construction and risk analytics** — V1 (§5.5), **in
  `src/portfolio/`**. Kelly sizing, drawdown control and Monte Carlo simulation
  are all migrated or rewritten; the Streamlit UI is not, and will not be. The
  finGuard source is retired to `docs/superseded/finGuard/`. See the V1 section.

## V1 — portfolio construction (§5.5)

`src/portfolio/` is a separate package from `research_integrity` because the two
answer different questions. The research-integrity layer asks whether a result
is believable; this layer asks how much to bet on one. **Nothing here is a
control**, and none of it should be mistaken for one.

```python
from src.portfolio import portfolio_kelly, risk_metrics, recovery_time

allocation = portfolio_kelly([0.10, 0.05], cov, risk_free_rate=0.02)
allocation.weights          # absolute exposure, NOT normalised to 1
allocation.cash_weight      # the remainder; negative means levered
allocation.scaled()         # half-Kelly, the size anyone should actually trade
```

### It was migrated formula by formula, not module by module

finGuard arrived with **23 passing tests** and a `todo.md` calling its
architecture "Perfect" and rating its own gaps as LOW. The tests covered
`kelly.py` and `drawdown.py` — 302 of 968 lines. `simulator.py` (231 lines) is
untested; `visualizer.py` (426 lines) is untested and does not even import,
because it needs `plotly`, which is not a dependency here.

Checking all three modules against their sources found this — **thirteen
defects**, every one of which flatters the strategy:

| defect | effect |
|---|---|
| Portfolio Kelly divided by the sum of the weights | **Sign inversion** whenever that sum was negative |
| …then normalised the result to sum to 1 | Discarded the leverage — the only quantity Kelly computes |
| …and ignored the risk-free rate | `self.risk_free_rate = 0.02` was set in `__init__` and read by nothing |
| `calculate_recovery_time` used `log(1+x)` | Understates recovery by **41.5%** at a 50% drawdown |
| `calculate_growth_rate` at `p = 1` | Returned `nan`, which compares False against everything |
| Singular covariance | Silently returned equal weights |
| `get_risk_metrics` | Annualised volatility beside a per-period Sharpe, in one dict |
| `calculate_var_drawdown` | A one-period VaR named as a drawdown limit |
| `kelly_leverage_adjustment` | Dead code — capped at 2.0 downstream of a cap at 1.0 |
| One `DrawdownManager` shared by every simulated path | Path 2 inherited path 1's peak and **began 50% underwater** |
| `total_returns` divided by `final_values[0]` | Returns measured against **path 0's terminal wealth**; P(loss) of 0.4 reported as 0.6 |
| `np.random.multivariate_normal` with no seed | The whole simulation was irreproducible |
| `volatility_multiplier` scaled the covariance | A stated 3x volatility shock delivered √3 = 1.73x |

**The sign inversion is the one worth dwelling on.** For `mu = [-0.10, 0.02]`
and `S = diag(0.04, 0.01)`, Kelly says short the first (−2.5) and hold the
second (+2.0). The raw weights sum to −0.5; dividing by that flips both signs,
and after clipping and renormalising finGuard returned `[1.0, 0.0]` — fully long
the asset it was told to short, nothing in the one it was told to buy. Wrong on
both legs, from one unguarded division, and none of the 23 tests saw it.

**The recovery-time error is the instructive one**, because it needs no
finance to catch. A 50% drawdown requires a 100% gain, so at 10% a year the
answer is `log(2)/log(1.1)` = 7.27 years. finGuard reported 4.25. One line of
arithmetic settles it, and the error ran in the flattering direction:

| drawdown | correct | finGuard | understated by |
|---:|---:|---:|---:|
| 10% | 1.105 yr | 1.000 yr | 9.5% |
| 20% | 2.341 yr | 1.913 yr | 18.3% |
| 50% | 7.273 yr | 4.254 yr | 41.5% |

Every defect above has a test named after it, because the useful residue of a
fixed bug is the test that stops it returning.

### Kelly returns an exposure, not a direction

`portfolio_kelly` gives `w* = inv(S) @ (mu - r·1)` and **does not normalise**.
Weights summing to 0.3 mean 30% invested and 70% in cash; summing to 7.5 means
650% borrowed. `cash_weight` carries the remainder and goes negative exactly
when the allocation is levered. Normalising converts a sizing rule into a
direction, and sizing is the only reason to use Kelly at all.

There is **no long-only option**. Clipping negative weights and renormalising is
not the constrained solution — it is a different portfolio with no optimality
property, and it is precisely where the sign inversion came from. The real
problem is a QP and needs a solver this project does not depend on, so it is
absent rather than approximated. Same call FR-14 makes about naive k-fold: the
wrong path does not get offered behind a flag.

### The simulator was rewritten, not migrated

It could not be verified, because its output was a *product* of the defects
above: it called the sign-inverting `calculate_portfolio_kelly` on every
rebalance and `apply_drawdown_control` on every step of every path. Three more
defects were its own, and none needed finance to catch.

**Every path after the first started underwater.** One `DrawdownManager`
instance was shared across all simulations and its peak was never reset:

```
path 1 climbs to 200   ->  peak_value 200
path 2 starts at 100   ->  drawdown -50%, immediately throttled
```

The distribution of outcomes was an artefact of iteration order. Here the peak
is a per-path vector, and a test recomputes each path's drawdown independently
with the primitive from `drawdown.py` — if any peak were shared, the reported
maxima could not match.

**Returns were measured against path 0's terminal wealth.** On five paths from
100 ending at `[120, 100, 80, 150, 90]`, two are losses, so P(loss) is 0.4. It
reported 0.6, and path 0's return was always exactly zero whatever it did.

**Nothing was seeded**, in a repository whose FR-23 requires bitwise-identical
re-execution. `seed` is now a *required* keyword argument with no default: every
other Monte Carlo parameter has a defensible default, and the seed does not,
because an unseeded distribution looks exactly like a seeded one.

Parameters are deliberately not re-estimated mid-simulation. finGuard recomputed
the covariance from a trailing 22-day window, which is singular for any portfolio
wider than 22 assets — and its Kelly returned equal weights on a singular
covariance, so rebalancing quietly degraded to equal-weight without saying so.

### What is not migrated

`visualizer.py` and `app.py` are **not being migrated at all** — a 426-line
Plotly/Streamlit UI is not portfolio construction, and this README already
declines UI work for an internal tool. With the simulator rewritten,
`migration_inbox/finGuard/` has nothing left that this project wants.

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

## Pointing it at a strategy someone believes in

```bash
python3 scripts/believed_strategy.py
```

Declaring noise to be noise is a demo. This is the product: take a rule a large
number of practitioners commit real money to, pre-register the claim its
believers make, and report which half survives.

**Faber (2007)**, *A Quantitative Approach to Tactical Asset Allocation* — hold
the index above its long moving average, cash below. Its claim is specific:
equity-like returns with materially smaller drawdowns.

This is the case pre-registration exists for and had never been used on. The
rule was specified in public in 2007, before this sample existed, so the
multiple-testing burden really is N=1 — unlike the 2,691-variant sweep, which
has to be punished for what it is.

### Is it the rule, or is it the number 200?

```
Sharpe across 9 windows:   +0.559 to +0.783   (spread 0.224)
drawdown across the same:   19.2% to 25.7%    vs buy-and-hold 33.9%
best window is 250, not 200
```

Every window cuts the drawdown, by a lot. The Sharpe varies by **0.224** across
windows — wider than the **0.021** gap between the rule and buy-and-hold. So the
drawdown claim is a property of the rule; any Sharpe claim for one window sits
inside the noise of having picked that window.

### What pre-registration is actually worth

| | trials | deflated |
|---|---:|---:|
| committed to 200 in advance | 1 | 0.9704 |
| best of 9 windows | 9 | 0.9651 |
| the sweep from the other script | 2,691 | 0.9152 |

Worth being precise about the size: at N=9 the penalty is **0.005**, which is
almost nothing. Nine windows is not a fishing expedition. The deflation is built
to punish the third line, and does — the burden scales with how much of the
space you swept, not with the fact that you looked more than once.

### The holdout, spent once

```
                        buy & hold       MA rule
  annualised Sharpe         +1.073        +1.106
  max drawdown               18.9%         10.1%

  'drawdown below two thirds of buy-and-hold'     HELD
  'Sharpe no worse than buy-and-hold less 0.05'   HELD
```

Both legs held, which is an uncommon result here and is **not** vindication. The
holdout is 414 trading days — one period, one regime, and no drawdown in it deep
enough to be the test the rule exists for. The drawdown claim is the durable
half, because all nine windows cut it in and out of sample. The Sharpe claim
held, but a result smaller than the spread of the choices that produced it is
not yet evidence about the rule.

The registration is now spent. A second look at this family is flagged, and the
warning escalates:

```
look 1:  no warning
look 2:  HOLDOUT EXHAUSTION — treat the result as optimistic
look 4:  HOLDOUT EXHAUSTED — in-sample data; a fresh holdout is required
```

## Real data, end to end

```bash
python3 scripts/real_data_pipeline.py            # cached in data/
python3 scripts/real_data_pipeline.py --fetch    # re-download
```

Every component here had only ever seen `standard_t` noise or hand-built
fixtures. This runs the whole machine once on real market data.

**The source has to satisfy one constraint the obvious ones do not.** FR-01
needs data with a real *knowledge* date, distinct from the date the fact refers
to. A price scraper gives you today's view of history and nothing else — you
cannot ask it what was on the wire in February, so as-first-reported is
unavailable and FR-02 can only be simulated. So:

| source | what it gives |
|---|---|
| **FRED** `SP500` | 2,513 real daily closes; a close is known at the close, so effective and knowledge dates coincide honestly |
| **ALFRED** `GDPC1` | the same series *by vintage* — what the number looked like on a given date, with the real publication lag |

Two GDP vintages four months apart contain a genuine revision:

```
GDP 2023-10-01   first reported 22,672.859   (vintage 2024-02-15)
                 restated to    22,679.255   (vintage 2024-06-15)
2024-01-01       does not exist in the February vintage at all
```

A query as of June still returns **22,672.859** for that quarter — the figure
that was on the wire — and the restatement is reachable only through
`latest_including_restatements(acknowledge_contamination=True)`. That is FR-01
and FR-02 demonstrated against a source rather than a fixture.

### What the machine says about the S&P 500

```
                              REAL S&P 500      RESHUFFLED
  --------------------------------------------------------
  trials counted                     2,691           2,691
  best excess Sharpe               -0.0064          0.0015
  DEFLATED Sharpe                   0.1366          0.0542
```

The Sharpe is **excess over buy-and-hold**, which is what
`moving_average_crossover` scores by default — the drift trap, found the first
time this was run against real data. Buy-and-hold over the period is `+0.0468`.

So: **not one of 2,691 moving-average variants beat simply holding the index**,
and the reshuffled series — real returns with every temporal relationship
destroyed — scored *higher* than the real one. Deflated Sharpe 0.1366. Noise.

A sweep whose range reached into the protected holdout was refused before
anything was counted, and the run was recorded with the code SHA that produced
it — then **replayed from that record alone**:

```
FR-23  replayed from the record alone: reproduced=True, hash c33b4a091570...
       trial count 2,691 before, 2,691 after
```

That is the first time FR-23 has been demonstrated rather than asserted.
`replay()` was correct, tested fourteen times in its own file, and called by
nothing — the same orphaned-control problem the seam was built to end, one layer
up, and the orphan guard itself did not cover `.replay(`. It does now.

The trial count is unchanged across the replay, and that exception matters: a
replay re-executes a search that was **already counted**, so counting it again
would inflate the very number the deflated Sharpe depends on. It is the one
place in this package where re-running a backtest must not touch the counter.

A run also stays reproducible across **restatements**, which is stronger than
FR-23 asks for and falls out of FR-02: the replay reads as-first-reported, so a
later revision cannot change what it sees. New data landing inside the range
does break it, correctly, and there is a test for each.

### What real data did not fix

**FR-03, FR-04 and FR-05 are still not implemented**, and index levels do not
help: an index has its constituent changes baked in, so this is a
survivorship-adjusted composite, not a survivorship-free universe. Anyone
reaching for a cross-section still needs vendor data nobody here has. The
temptation is to treat "we have real data now" as having closed those
requirements. It has not, and `docs/REQUIREMENTS.md` still says so.

## The workspace: a control that accumulates is absent if it is ephemeral

```bash
python3 scripts/real_data_pipeline.py                    # throwaway; touches nothing
python3 scripts/real_data_pipeline.py --home ~/lab       # persist into a workspace
```

FR-08 asks for "a global count of every backtest executed against each dataset,
across all researchers and all time". The counter that implements it is
append-only and refuses deletes by SQLite trigger — and every script here built
it inside a `TemporaryDirectory` and destroyed it on exit.

So the count reset to zero on every run. The deflated Sharpe was computed
against one script's search intensity rather than the team's cumulative one,
which is the smallest it could be and therefore the most flattering. Holdout
exhaustion reset with it, so every run began with a fresh, never-peeked
holdout — *"an exhaustion count you can reset is not a count"* is this project's
own line, and it was being reset every few minutes.

None of those controls were wrong. They were ephemeral, which for a control that
works by **accumulating** is the same as being absent.

### What persistence actually buys, measured

The same pipeline, run twice against one workspace:

| run | trials on record | deflated Sharpe |
|---|---:|---:|
| first | 2,691 | 0.1366 |
| second | 5,382 | **0.1279** |

The same search, on the same data, is **less impressive the second time** —
because the counter remembered the first. That is the sentence at the top of
this README finally being true of the system rather than of a formula:
*searching harder makes it less impressive, without anyone having to choose to
be honest.* Before persistence it could not happen, because every run started
from zero.

### A directory is the honest ceiling

Nothing here can stop someone deleting the workspace. Triggers defend rows
against SQL; they cannot defend a file against `rm`. So the workspace records
when it was created and `provenance()` reports that age **beside** the count:

```
workspace ~/.financial-alpha-research-lab (0.0 days old): 5,382 trials …
```

A workspace claiming to have vetted a strategy family while being four hours old
is visibly wrong in the report rather than silently wrong in the arithmetic.
That is weaker than prevention, and it is what a file allows. Back it up, and
treat deleting it the way you would treat deleting the trade blotter.

The default home is `~/.financial-alpha-research-lab`, outside any checkout,
because a workspace tied to a clone loses its accumulated count the first time
someone clones fresh — the one number that must not reset.

### Installing one

```bash
python3 scripts/install_workspace.py            # load data, define the holdout
python3 scripts/install_workspace.py --status   # report, change nothing
```

Installation is **separate from the demos on purpose**. Seeding a workspace by
running `real_data_pipeline.py` would work and would be wrong: that script
executes a 2,691-trial sweep, those are real searches against the dataset, and
FR-08 requires counting them. Every genuine result anyone later produced against
`sp500` would be deflated against 2,691 trials nobody had an interest in — a
permanent, invisible tax on the count, paid for a demonstration.

So the installer loads data, registers the datasets and defines the holdout, and
runs no search. It is idempotent: ingestion skips a load whose content hash
already exists, so repeating it does not accumulate identical versions or make
two runs over the same data cite different ones.

A fresh workspace has a trial count of zero because nothing has been searched —
not because nothing persists.

### Which scripts persist, and which must not

| script | default | `--home` |
|---|---|---|
| `install_workspace.py` | **the real workspace** — it *is* the installation, and runs no search | n/a |
| `real_data_pipeline.py` | throwaway | opts in to persisting |
| `believed_strategy.py` | throwaway | opts in to persisting |
| `null_benchmark_demo.py` | throwaway, always — output pinned by the README tests | none |
| `readme_tables.py` | throwaway, always — it *generates* those tables | none |

**Demonstrations are ephemeral by default and must opt in to touching real
state.** For a short while they were the other way round, and the consequence
was concrete: the documented bare invocation of `real_data_pipeline.py` added
2,691 demo trials to the production count, and `believed_strategy.py` spent one
of the four looks a family gets before its holdout is exhausted. The seeding
path had been fixed and the running path left open. A test now asserts the
fallback is a scratch path rather than the default home, in both scripts.

`believed_strategy.py` was on the wrong side of that line until now. It printed
*"the registration is spent"* while building its holdout in a temporary
directory, so the next run got a fresh, unspent one — the demonstration of
exhaustion was the thing defeating exhaustion. Four consecutive runs now walk it
from `first look` to `HOLDOUT EXHAUSTED`, which is what that output was
describing all along.

The two ephemeral ones are deliberate and say so in their own docstrings, with a
test asserting they keep saying it — the workspace change makes their temp
directories look like an oversight, and they are not.

## The seam: making the controls binding

Every control in this package worked, was tested, and — for three of the four —
constrained nothing:

```
who calls the holdout guard?           nobody, outside its own docstring
who writes a run record?               nobody
who requires a point-in-time dataset?  nobody
what was actually wired?               the trial counter, into search and backtest
```

FR-10 says the holdout MUST be inaccessible to ordinary backtests, and nothing
made an ordinary backtest check. FR-07 says the system MUST REFUSE a dataset
that cannot supply point-in-time semantics; `require_point_in_time` implements
that refusal exactly, and no caller ever triggered it. FR-22 through FR-25
describe a run record that no code path wrote.

That is this README's own argument turned on itself. It says of the trial
counter that *"a researcher who can delete rows can manufacture any deflated
Sharpe they want, and 'please don't' is not a control."* A control nobody
invokes is the same thing with an extra step.

```python
from src.research_integrity import Study

study = Study(dataset_id="sp500", store=store, counter=counter,
              holdout=holdout, log=log)

study.search(returns, grid, start="2015-01-01", end="2019-12-31")
study.status()      # trials counted, holdout period, dataset version, runs recorded
```

**The order is the design**, and `ORDER` states it:

| # | step | requirement |
|---|---|---|
| 1 | refuse a dataset that is not point-in-time | FR-07 |
| 2 | refuse a range overlapping the protected holdout | FR-10 |
| 3 | resolve the dataset version, or refuse | FR-06 |
| 4 | refuse uncommitted code, or record the diff | FR-24 |
| 5 | count the trial, before it can succeed | FR-08 |
| 6 | run | |
| 7 | record the outcome, including failure | FR-25 |

Refusals come first so a run that must not happen never touches the counter —
FR-08 counts backtests *executed*, and one refused at the door was not. Every
argument is required: a `Study` missing a control is a study with that control
switched off, which is the state the class exists to prevent.

### A test that catches an orphaned control

The reason three controls sat unreachable while all their tests passed is that a
suite organised per-module cannot see it — every module is exercised by its own
file, and the gap is in the space *between* them. So there is now a test that
asserts each control has a caller outside its defining module:

```
FR-10: nothing outside holdout.py calls '.assert_ordinary_access('. The control
exists, its own tests pass, and it constrains nothing.
```

That is its output when the wiring is removed, which is how it was verified.

### What it does not do

The date range is **declared by the caller**, not derived from the data handed
over. A caller who reads holdout dates and declares a different range defeats the
FR-10 check. Closing that needs the study to load prices from the store itself,
which needs a price-shaped read the fact table does not yet offer. This makes the
honest path easy and the dishonest path deliberate, which is weaker than
impossible — and is stated here rather than left to be discovered.

## Point-in-time data store (FR-01, FR-02, FR-06, FR-07)

Two time axes, kept separately, because collapsing them is how look-ahead gets
in: `effective_date` is when a fact was true, `knowledge_date` is when anyone
learned it. A fiscal quarter ends on 31 December and the filing lands in
mid-February; a query as of 15 January must not see it.

```python
from src.research_integrity import PointInTimeStore

store = PointInTimeStore("research.duckdb")
store.register_dataset("fundamentals", point_in_time=True)
store.append_facts("fundamentals", [
    {"entity_id": "ACME", "field": "book_equity", "value": 500.0,
     "effective_date": "2023-12-31", "knowledge_date": "2024-02-15"},
])

store.as_of("fundamentals", "2024-01-15")          # [] — not published yet
store.latest_including_restatements(...)           # LookAheadContamination
```

`register_dataset` requires `point_in_time` explicitly rather than defaulting
it, and a dataset declared not point-in-time must carry a note saying what is
missing — otherwise the limitation is invisible at exactly the moment someone is
refused. FR-07 says refuse rather than warn, and `require_point_in_time` does;
a warning is read once and then filtered out of the logs.

**On the PRD's claim that Iceberg supplies this.** For FR-06 it does — immutable
addressable versions are what a table format is for. For FR-01 it does not:
table time travel answers "what did this table look like at snapshot N", which
equals knowledge time only if you never backfill, never load history and never
correct a load. Iceberg belongs *under* this module as storage, not instead of it.
See the module docstring for the full argument.

FR-03 (delisted securities), FR-04 (index membership) and FR-05 (corporate
actions) are data-*content* requirements. The schema carries them as ordinary
facts with effective dates, but nobody has loaded the vendor data, and calling
the store survivorship-free because it *could* hold delisted names would be a
claim about data that is not there.

## Factor library

Small on purpose. The PRD asks for a handful of factors each *known* to be
right, not a catalogue of hundreds each of which is plausible — a wrong factor
does not announce itself, it produces a backtest.

```python
from src.research_integrity import assert_causal, momentum, FACTORS

signal = momentum(prices)                  # 12-1: t-252 to t-21, month skipped
assert_causal(momentum, prices, split=350) # LookAheadFactor if it peeks
FACTORS["volatility"].direction            # 'NEGATIVE — low-volatility ...'
```

| factor | definition | premium direction |
|---|---|---|
| `momentum` | return from t-252 to t-21 | positive |
| `reversal` | negative of the trailing 1-month return | positive |
| `volatility` | annualised sd of trailing log returns, ddof=1 | **negative** |
| `size` | log market capitalisation | **negative** |
| `book_to_market` | as-reported book equity known at the date / market cap | positive |

Sign conventions are recorded in `FACTORS[name].direction` rather than absorbed
into the functions. Negating inside a factor so that "high is good" everywhere
is convenient exactly once, and then someone compares two factors whose
conventions differ and cannot work out why the spread inverted.

### The causality check is the point

`assert_causal` perturbs the data after time *t*, recomputes, and requires every
value at or before *t* to be unchanged. It works on any callable, including one
this library did not write, and it needs no cooperation from the factor being
tested — the same move `assert_no_leakage` makes for CV splits.

| what it is given | result |
|---|---|
| a correct factor | passes |
| a window reading `prices[t+1]` | `LookAheadFactor` at the first moved index |
| a factor centred on `nanmean` of the whole series | `LookAheadFactor` |
| a comparison whose head is entirely NaN | `FactorError` — refuses to pass vacuously |

That last row was a real bug in this function. At the default midpoint split,
momentum's 252-period warm-up leaves the whole head NaN; NaN compares equal to
NaN, so the check passed without comparing anything — including for a factor
that openly read the future. It now refuses. A check that cannot fail is worse
than no check, because it is recorded as a pass.

### Fundamentals are read through the store, never joined on the period end

`book_to_market_as_of` takes a **knowledge** date and reads `store.as_of`, so
during the reporting lag it returns `None`. That is the honest answer: the
factor is genuinely undefined before the filing exists. Joining book equity to
prices on the fiscal period end date instead hands the strategy six weeks of
knowledge it did not have, and the resulting value factor works beautifully —
which is the problem. A restatement published in March does not reach back into
February either, because `as_of` returns as-first-reported values (FR-02).

## Execution costs and capacity (FR-17, FR-18, FR-20)

**The engine is to be NautilusTrader** (1.231.0, pinned and installed), as the
PRD specifies, and reimplementing an event-driven matching engine by hand when
the spec names one would repeat the Mitiq mistake made earlier in this project.

It is now wired — see [the engine section](#the-backtest-engine-fr-19-fr-21).
An earlier version of this paragraph said the library "supplies" FR-19 and FR-21
while nothing in the repository imported it; a dependency nothing calls supplies
nothing. `tests/test_readme_is_true.py` fails if that claim reappears without
the import, and now also fails if the prose overshoots the other way.

What NautilusTrader does not supply even now that it is wired, and is built here:

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

## The backtest engine (FR-19, FR-21)

```python
from src.research_integrity import run_backtest, Instrument, TrialCounter

result = run_backtest(prices, cost_spec=Instrument("ACME", price=100.0,
                                                   adv=1_000_000,
                                                   daily_volatility=0.02,
                                                   shares_outstanding=100_000_000),
                      counter=TrialCounter("research.db"), dataset_id="sp500")

result["look_ahead"]    # {'bars_audited': 400, 'clean': True, 'violations': []}
result["sharpe"]        # per-period, the unit core.py requires
```

NautilusTrader runs the matching engine, order lifecycle, account and clock.
Nothing here reimplements any of that.

### Why event-driven actually buys FR-21

The usual defence against look-ahead is discipline — index carefully, shift the
right way, review the code. It fails silently, and the failure is the rewarding
kind: a leaky backtest looks like a good one.

An event-driven engine removes the opportunity rather than the temptation. Data
arrives as timestamped messages in time order, so there is no array to index off
the end of; at the moment `on_bar` runs, the later bars have not been sent.

**But "cannot" is a claim about an implementation, and this project does not take
those on trust** — the deflated Sharpe formula was wrong for four commits while
every invariant test passed. So `LookAheadAudit` checks it on every bar of every
run:

| property | catches |
|---|---|
| nothing visible postdates the current bar | data delivered early |
| visible bar count equals bars delivered | a cache pre-loaded with history that never came through the bus |

A strategy that puts a bar from 120 days ahead into the cache — doing by hand
what an array-indexing backtest does by accident — is caught on the very next
bar, with all 239 subsequent violations recorded. There is a test for that,
because an audit that has never failed is a decoration.

### FR-19, at the precision the evidence supports

| | status |
|---|---|
| latency | **met** — five days of latency moves fills from 33 to 62 and equity by $4,204 |
| slippage | **met** — `prob_slippage=1.0` changes final equity |
| partial fills | **NOT met** — needs order-book depth |

Market orders against daily bars fill in full even at 100x the bar's volume and
with `liquidity_consumption=True`, because a bar carries no depth to consume.
This project has no book data, so that half of FR-19 is not demonstrated.

It would have been easy to book FR-19 as met: NautilusTrader models partial
fills, so the claim would read as true and nobody would check whether this
project ever invokes it. That is precisely how the previous overclaim happened,
so the limitation gets a test that fails if partial fills ever start occurring —
telling whoever added book data that the docs can now be strengthened.

### Impact goes in where the engine charges commission

`AlmgrenFeeModel` plugs the participation-rate model from `execution_costs.py`
into the engine as a `FeeModel`. Nautilus's own `FillModel` slips a fill by a
**tick** with some probability — microstructure noise, not impact. It does not
grow with order size relative to volume, so without this a 100,000-share order
costs the same in a name trading 10m a day as in one trading 100k. The second is
a whole day's volume; the first is a rounding error. That is the error FR-17
exists to correct.

The size at which it matters is worth stating: at 100 shares the liquid and thin
names differ by 7%, not 13x, because 100 shares moves nothing anywhere and the
spread dominates. The model is behaving correctly; the comparison only becomes
interesting at sizes that are a real fraction of a day.

### Every run is counted, including the ones that fail

The trial is registered with the `TrialCounter` **before** the engine starts, so
a backtest that crashes is counted anyway. FR-08 asks for runs "whose results
were discarded", and the crash is the purest case. A run whose look-ahead audit
fails is counted as a trial but records **no outcome** — it happened, and its
number is inadmissible.

### How this composes with the factor library

Two guarantees that only mean something together:

| check | guarantees |
|---|---|
| `assert_causal` (`factors.py`) | the factor does not read forward **within** the array it is given |
| `LookAheadAudit` (`backtest.py`) | the array it is given never **contains** the future |

Either alone is insufficient — a perfectly causal factor over a contaminated
history is contaminated, and an honest history fed to a peeking factor is
leaked. `MomentumStrategy` computes its signal by calling `momentum` on exactly
the closes that have arrived, so both apply to the same number.

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
