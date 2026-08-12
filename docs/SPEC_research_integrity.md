# Research Integrity Core — deflation and minimum backtest length

Implements PRD 04 §5.2, **FR-09** and **FR-13**. Pure computation: no I/O, no
global state, no database. A later slice adds the trial counter and holdout.

## Why this exists

A parameter search over historical data reliably produces high in-sample Sharpe
ratios on pure noise. The more trials you run, the higher the best observed
Sharpe, and the closer its true out-of-sample expectation gets to zero. These two
functions make that visible: they answer *"given that I tried N times, how
impressed should I be by this Sharpe?"* and *"is my sample even long enough for
this Sharpe to be distinguishable from luck?"*

## Deliverables

Create `research_integrity.py` and `test_research_integrity.py` in this
directory.

## Requirements

### R1 — `deflated_sharpe_ratio(...)` (FR-09)

Compute the Deflated Sharpe Ratio: the probability that the observed Sharpe
ratio exceeds what would be expected as the maximum across `n_trials`
independent trials, given the sample's length, skewness and kurtosis.

- **Source of the formula: Bailey & López de Prado (2014), "The Deflated Sharpe
  Ratio: Correcting for Selection Bias, Backtest Overfitting and
  Non-Normality."** Implement the formula as published. The docstring MUST cite
  the source and state the formula used, so a reviewer can check it against the
  paper. Do not invent an approximation.
- Inputs MUST include: observed Sharpe ratio, number of trials, sample length
  (number of returns), skewness, kurtosis. Non-normality (skew and kurtosis)
  MUST be used, not assumed away.
- **UNITS — the Sharpe ratio MUST be per-period, at the same frequency as
  `sample_length`.** If `sample_length` counts daily returns, the Sharpe is a
  daily Sharpe, not an annualised one. This is not a detail: passing an
  annualised Sharpe of 1.5 with 250 daily observations implies a per-period
  Sharpe of 1.5, i.e. an annualised ~24, and the function will correctly report
  near-certainty for an input that is nonsense. The docstring MUST state this,
  and the function SHOULD reject an implausible per-period Sharpe (|SR| > 1) by
  raising `ValueError` naming the likely units error, because silently answering
  a mis-scaled question is the failure this whole module exists to prevent.
- The return value is a **probability in [0, 1]**.

### R2 — `minimum_backtest_length(...)` (FR-13)

Compute the minimum sample length required for an observed Sharpe to be
statistically distinguishable from zero given the number of trials.

- **Source: Bailey, Borwein, López de Prado & Zhu (2014), "Pseudo-Mathematics
  and Financial Charlatanism" / "The Probability of Backtest Overfitting."**
  Cite it in the docstring and state the formula used.
- Returns a length in the same unit as the input sample length. It MAY be
  fractional; do not round.

### R3 — a result MUST carry its own verdict

Provide `evaluate(...)` returning a JSON-serialisable dict with at least:

- `deflated_sharpe` — the R1 value
- `min_backtest_length` — the R2 value
- `sample_length` — as supplied
- `sample_too_short` — boolean, true when `sample_length < min_backtest_length`
- `n_trials` — as supplied

FR-13 requires results with insufficient samples to be **flagged**, so
`sample_too_short` is not optional and MUST NOT be silently omitted.

## Edge cases — these are requirements, not suggestions

- **`n_trials` of 1** MUST be accepted and means no multiple-testing burden. It
  MUST NOT raise, and MUST NOT be treated as zero trials.
- **`n_trials` of 0 or negative** MUST raise `ValueError`.
- **`sample_length` of 0 or 1** MUST raise `ValueError` — a Sharpe ratio over
  fewer than two observations is undefined.
- **Non-finite inputs** (NaN or infinity) in any numeric argument MUST raise
  `ValueError` rather than propagating NaN into a result. A NaN verdict that
  looks like a number is worse than an error.
- **Invalid or malformed argument types** — a string, `None`, or any non-numeric
  value where a number is required — MUST raise `TypeError` or `ValueError`.
  They MUST NOT be silently coerced: `float("nan")` from a bad string is exactly
  the failure the rule above exists to prevent.
- **Ordering and ties do not apply** to this slice: every function returns a
  scalar or a flat dict, and no collection is ranked or sorted. If you find
  yourself ordering something, the design has drifted from this spec.
- **A negative observed Sharpe** MUST be accepted and produce a low deflated
  Sharpe. It MUST NOT raise and MUST NOT be clamped to zero.
- **Zero kurtosis excess or zero skew** MUST be accepted (a normal sample is a
  legitimate input, not a special case).

## Properties that MUST hold

These are invariants, checked mechanically. They hold regardless of the
formula's details:

- **P1 — Monotonic in trials.** Holding everything else fixed, increasing
  `n_trials` MUST NOT increase the deflated Sharpe. More searching cannot make a
  result more credible.
- **P2 — Monotonic in observed Sharpe.** Holding everything else fixed,
  increasing the observed Sharpe MUST NOT decrease the deflated Sharpe.
- **P3 — Bounded.** The deflated Sharpe is always in [0, 1].
- **P4 — Trials raise the bar.** Holding everything else fixed, increasing
  `n_trials` MUST NOT decrease `minimum_backtest_length`.
- **P5 — Deterministic.** Identical inputs produce identical outputs; no
  randomness, no global state.

## Definition of done

- `pytest -q` passes.
- Tests include at least one case per edge case above, and one test per property
  P1–P5.
- `python3 research_integrity.py` prints a JSON `evaluate(...)` example to stdout
  so the module is runnable for inspection.
