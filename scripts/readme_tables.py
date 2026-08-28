#!/usr/bin/env python3
"""Regenerate every numeric table in README.md from the code that produces them.

    python3 scripts/readme_tables.py

A README that quotes figures the code no longer produces is the same failure
this project exists to catch, one level up: a claim that was checked once,
stayed on the page, and stopped being true without anyone deciding it should.
Four of the README's tables were carrying numbers from before commit be80a74
until this script was written, and nothing complained.

So the tables are generated rather than transcribed, every input is stated in
the output rather than living in someone's shell history, and
`tests/test_readme_is_true.py` fails when the README and this script disagree.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research_integrity import (  # noqa: E402
    Instrument,
    TrialCounter,
    capacity,
    deflated_sharpe_ratio,
    execution_cost,
)
from src.research_integrity.cross_validation import leakage_report  # noqa: E402
from src.research_integrity.search import (  # noqa: E402
    crossover_grid,
    null_benchmark,
    run_search,
)

# The single sample every table that needs returns is built from. Eight years of
# fat-tailed daily noise with no exploitable structure, fixed seed.
SAMPLE_SEED = 42
SAMPLE_SIZE = 2000
SHUFFLE_SEED = 7
SAMPLE_LENGTH = 1250          # the T used for the deflation table
DSR_THRESHOLD = 0.95


def _returns() -> np.ndarray:
    return np.random.default_rng(SAMPLE_SEED).standard_t(df=4, size=SAMPLE_SIZE) * 0.01


def _recorded_sweep() -> tuple[dict, dict]:
    """Run the real sweep and return (result, deflation inputs) from the counter.

    `var_trials` is taken from recorded history rather than chosen, which is the
    whole point of the trial counter: a multiple-testing correction fed a
    made-up variance is a decoration, not a correction.
    """
    grid = crossover_grid(max_fast=70, max_slow=150)
    with tempfile.TemporaryDirectory() as tmp:
        counter = TrialCounter(Path(tmp) / "real.db")
        result = run_search(_returns(), grid, counter=counter,
                            dataset_id="returns", search_id="sweep-real")
        return result, counter.deflation_inputs("returns")


def deflation_table() -> None:
    """How one unchanged result deflates as the search around it grows."""
    result, inputs = _recorded_sweep()
    observed = result["best_raw_sharpe"]
    var_trials = inputs["var_trials"]

    print("## Global trial counter\n")
    print(f"Observed per-period Sharpe {observed:.4f} — the best of the "
          f"{inputs['n_trials']:,}-trial")
    print(f"sweep below — held fixed over {SAMPLE_LENGTH:,} observations, normal "
          "skew and kurtosis,")
    print(f"and V[{{SR_n}}] = {var_trials:.3e} as RECORDED by the counter across "
          "that sweep.")
    print("Only the trial count varies.\n")
    print("| trials run | deflated Sharpe | verdict at 95% |")
    print("|---:|---:|---|")
    for n_trials in (10, 100, 1000, 5000):
        dsr = deflated_sharpe_ratio(observed_sharpe=observed, n_trials=n_trials,
                                    sample_length=SAMPLE_LENGTH, skewness=0.0,
                                    kurtosis=3.0, var_trials=var_trials)
        verdict = ("significant" if dsr >= DSR_THRESHOLD
                   else "**not** significant")
        print(f"| {n_trials:,} | {dsr:.4f} | {verdict} |")
    print()


def null_benchmark_table() -> None:
    """The same sweep against the returns as given and reshuffled."""
    grid = crossover_grid(max_fast=70, max_slow=150)
    returns = _returns()
    with tempfile.TemporaryDirectory() as tmp:
        real = run_search(returns, grid, counter=TrialCounter(Path(tmp) / "real.db"),
                          dataset_id="returns", search_id="sweep-real")
        null = null_benchmark(returns, grid,
                              counter=TrialCounter(Path(tmp) / "null.db"),
                              dataset_id="returns-shuffled",
                              search_id="sweep-null", seed=SHUFFLE_SEED)

    print("## Null-result benchmark\n")
    print("```")
    print(f"  {'':24}{'AS GIVEN':>14}{'RESHUFFLED':>14}")
    print(f"  {'-' * 52}")
    print(f"  {'trials counted':24}{real['n_trials']:>14,}{null['n_trials']:>14,}")
    print(f"  {'best raw Sharpe':24}{real['best_raw_sharpe']:>14.4f}"
          f"{null['best_raw_sharpe']:>14.4f}")
    print(f"  {'best parameters':24}"
          f"{str(tuple(real['best_params'].values())):>14}"
          f"{str(tuple(null['best_params'].values())):>14}")
    print(f"  {'DEFLATED Sharpe':24}{real['deflated_sharpe']:>14.4f}"
          f"{null['deflated_sharpe']:>14.4f}")
    print("```\n")


def leakage_table() -> None:
    """What naive k-fold would leak, by label horizon."""
    n_obs, n_splits = 1000, 5
    print(f"## Purged, embargoed cross-validation\n")
    print(f"{n_obs:,} observations across {n_splits} folds.\n")
    print("| label horizon | observations leaked | leak rate |")
    print("|---:|---:|---:|")
    for horizon in (1, 10, 25, 50):
        start = np.arange(n_obs)
        report = leakage_report(start, start + horizon, n_splits=n_splits)
        print(f"| {horizon} | {report['would_leak_under_naive_kfold']} "
              f"| {report['leak_rate_naive'] * 100:.2f}% |")
    print()


def cost_and_capacity_table() -> None:
    """Cost and capacity for the same order in two liquidity regimes."""
    shares = 100_000
    large = Instrument(symbol="BIG", price=50.0, adv=10_000_000,
                       daily_volatility=0.02, shares_outstanding=1_000_000_000,
                       borrow_available=5_000_000, borrow_fee_annual=0.005)
    small = Instrument(symbol="SMALL", price=50.0, adv=100_000,
                       daily_volatility=0.02, shares_outstanding=10_000_000)

    rows = []
    for instrument in (large, small):
        cost = execution_cost(shares, instrument)
        ceiling = capacity(instrument, gross_sharpe=2.0,
                           turnover_per_year=12).aum_ceiling
        rows.append((cost, ceiling))
    (big_cost, big_cap), (small_cost, small_cap) = rows

    print("## Execution costs and capacity\n")
    print("| | large cap (10m ADV) | microcap (100k ADV) |")
    print("|---|---:|---:|")
    print(f"| cost of {shares:,} shares | {big_cost['total_bps']:.1f} bps "
          f"| {small_cost['total_bps']:.1f} bps |")
    print(f"| participation rate | {big_cost['participation_rate'] * 100:.1f}% "
          f"| {small_cost['participation_rate'] * 100:.1f}% |")
    print(f"| AUM ceiling @ Sharpe 2.0 | ${big_cap / 1e6:,.0f}m "
          f"| ${small_cap / 1e6:,.0f}m |")
    print()


def main() -> int:
    print("Regenerated from the code. Paste into README.md; "
          "tests/test_readme_is_true.py checks they agree.\n")
    deflation_table()
    null_benchmark_table()
    leakage_table()
    cost_and_capacity_table()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
