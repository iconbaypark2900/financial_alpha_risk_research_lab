"""The README's numbers must be the numbers the code produces.

Every figure in the README was checked once, by hand, at the moment it was
written. Four tables then went stale across commit be80a74 and stayed on the
page for six commits, because nothing in the repository had an opinion about
whether the documentation was still true.

That is the same failure mode the module itself exists to catch — a claim that
survives on the strength of having been correct once — so it gets the same
treatment as the rest: a mechanism, not a habit. These tests recompute each
table and require the README to contain the result.

They are deliberately literal. A test that recomputes a number and compares it
to another recomputation of the same number proves nothing; the assertion has to
be against the bytes a reader will actually see.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.research_integrity import (
    Instrument,
    TrialCounter,
    capacity,
    deflated_sharpe_ratio,
    execution_cost,
)
from src.research_integrity.cross_validation import leakage_report
from src.research_integrity.search import crossover_grid, null_benchmark, run_search

README = Path(__file__).resolve().parent.parent / "README.md"

SAMPLE_SEED = 42
SAMPLE_SIZE = 2000
SHUFFLE_SEED = 7
SAMPLE_LENGTH = 1250
DSR_THRESHOLD = 0.95


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def returns() -> np.ndarray:
    return np.random.default_rng(SAMPLE_SEED).standard_t(df=4, size=SAMPLE_SIZE) * 0.01


@pytest.fixture(scope="module")
def sweep(returns):
    """The recorded sweep both the deflation and null-benchmark tables come from."""
    grid = crossover_grid(max_fast=70, max_slow=150)
    with tempfile.TemporaryDirectory() as tmp:
        counter = TrialCounter(Path(tmp) / "real.db")
        real = run_search(returns, grid, counter=counter,
                          dataset_id="returns", search_id="sweep-real")
        null = null_benchmark(returns, grid,
                              counter=TrialCounter(Path(tmp) / "null.db"),
                              dataset_id="returns-shuffled",
                              search_id="sweep-null", seed=SHUFFLE_SEED)
        return real, null, counter.deflation_inputs("returns")


def test_the_deflation_table_matches_the_code(readme, sweep):
    real, _, inputs = sweep
    for n_trials in (10, 100, 1000, 5000):
        dsr = deflated_sharpe_ratio(observed_sharpe=real["best_raw_sharpe"],
                                    n_trials=n_trials, sample_length=SAMPLE_LENGTH,
                                    skewness=0.0, kurtosis=3.0,
                                    var_trials=inputs["var_trials"])
        verdict = "significant" if dsr >= DSR_THRESHOLD else "**not** significant"
        row = f"| {n_trials:,} | {dsr:.4f} | {verdict} |"
        assert row in readme, f"README is stale; expected row {row!r}"


def test_the_deflation_tables_stated_inputs_match_the_code(readme, sweep):
    """The inputs are quoted too. A reproducible table whose stated variance is
    not the one used is worse than no table: it invites a reader to check it and
    rewards them with a number that does not reconcile."""
    real, _, inputs = sweep
    assert f"{real['best_raw_sharpe']:.4f}" in readme
    assert f"{inputs['var_trials']:.3e}" in readme
    assert f"{inputs['n_trials']:,}" in readme


def test_the_null_benchmark_table_matches_the_code(readme, sweep):
    real, null, _ = sweep
    for key, fmt in (("best_raw_sharpe", "{:.4f}"), ("deflated_sharpe", "{:.4f}")):
        assert fmt.format(real[key]) in readme
        assert fmt.format(null[key]) in readme
    assert str(tuple(real["best_params"].values())) in readme
    assert str(tuple(null["best_params"].values())) in readme


def test_the_leakage_table_matches_the_code(readme):
    for horizon in (1, 10, 25, 50):
        start = np.arange(1000)
        report = leakage_report(start, start + horizon, n_splits=5)
        row = (f"| {horizon} | {report['would_leak_under_naive_kfold']} "
               f"| {report['leak_rate_naive'] * 100:.2f}% |")
        assert row in readme, f"README is stale; expected row {row!r}"


def test_the_cost_and_capacity_table_matches_the_code(readme):
    large = Instrument(symbol="BIG", price=50.0, adv=10_000_000,
                       daily_volatility=0.02, shares_outstanding=1_000_000_000,
                       borrow_available=5_000_000, borrow_fee_annual=0.005)
    small = Instrument(symbol="SMALL", price=50.0, adv=100_000,
                       daily_volatility=0.02, shares_outstanding=10_000_000)

    big_cost = execution_cost(100_000, large)
    small_cost = execution_cost(100_000, small)
    big_cap = capacity(large, gross_sharpe=2.0, turnover_per_year=12).aum_ceiling
    small_cap = capacity(small, gross_sharpe=2.0, turnover_per_year=12).aum_ceiling

    assert (f"| cost of 100,000 shares | {big_cost['total_bps']:.1f} bps "
            f"| {small_cost['total_bps']:.1f} bps |") in readme
    assert (f"| participation rate | {big_cost['participation_rate'] * 100:.1f}% "
            f"| {small_cost['participation_rate'] * 100:.1f}% |") in readme
    assert (f"| AUM ceiling @ Sharpe 2.0 | ${big_cap / 1e6:,.0f}m "
            f"| ${small_cap / 1e6:,.0f}m |") in readme


def test_the_v1_recovery_time_table_matches_both_formulas(readme):
    """The V1 section quotes the correct recovery times AND the wrong ones the
    migrated source produced. Both sides are recomputed here: a table that
    contrasts a fix with the bug it replaced is only worth reading if both
    columns are still accurate."""
    import math

    from src.portfolio.drawdown import recovery_time

    rate = 0.10
    for drawdown in (0.10, 0.20, 0.50):
        correct = recovery_time(drawdown, rate)
        wrong = math.log(1 + drawdown) / math.log(1 + rate)
        understated = (1 - wrong / correct) * 100
        row = (f"| {drawdown:.0%} | {correct:.3f} yr | {wrong:.3f} yr "
               f"| {understated:.1f}% |")
        assert row in readme, f"V1 recovery table is stale; expected {row!r}"


def test_the_engine_sections_numbers_match_the_code(readme):
    """The engine section quotes concrete figures, so they get the same
    treatment as every other table on the page.

    Skipped rather than failed when nautilus_trader is absent: the claim is
    about what the engine does, and with no engine there is nothing to check.
    """
    pytest.importorskip("nautilus_trader")
    from nautilus_trader.backtest.models import LatencyModel

    from src.research_integrity.backtest import run_backtest

    day_ns = 86_400_000_000_000
    rng = np.random.default_rng(0)
    prices = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 400)))

    base = run_backtest(prices)
    delayed = run_backtest(prices,
                           latency_model=LatencyModel(base_latency_nanos=5 * day_ns))
    drop = base["final_equity"] - delayed["final_equity"]

    assert (f"moves fills from {base['n_fills']} to {delayed['n_fills']} "
            f"and equity by ${drop:,.0f}") in readme, (
        "the engine section's latency figures no longer match the code")


def test_the_readme_does_not_claim_nautilus_supplies_what_nothing_imports():
    """The claim that cost me the most to verify, kept as a test.

    `execution_costs.py` credited NautilusTrader with FR-19 and FR-21 while no
    module in the repository imported it. A dependency that nothing calls
    supplies nothing, and the docstring was the only place that said otherwise.

    The check is a POSITIVE assertion — the file must state the requirements are
    unmet — rather than a ban on the old phrase. A ban cannot tell a claim apart
    from a quotation of the claim it replaced, which is exactly how the first
    version of this test failed: on the sentence explaining the correction.

    The wiring has since landed (backtest.py), so the test now runs in the
    other direction: the prose must no longer say "unmet", and must still admit
    the half of FR-19 that is not demonstrated. A correction that overshoots
    into a fresh overclaim is the same defect wearing the opposite sign."""
    import importlib.util
    import re

    source = (Path(__file__).resolve().parent.parent / "src" / "research_integrity")
    # Both spellings. The first version of this check looked for the literal
    # "import nautilus_trader" and so did not see `from nautilus_trader.x import
    # y` — it reported the package as unimported on the very commit that wired
    # it in. A detector that cannot see the thing it guards is worse than none.
    imports = re.compile(r"^\s*(?:from|import)\s+nautilus_trader\b", re.MULTILINE)
    imports_it = any(imports.search(path.read_text(encoding="utf-8"))
                     for path in source.glob("*.py"))
    installed = importlib.util.find_spec("nautilus_trader") is not None

    text = (source / "execution_costs.py").read_text(encoding="utf-8")
    if imports_it:
        assert "are currently UNMET" not in text, (
            "nautilus_trader is now imported and wired (see backtest.py), so "
            "execution_costs.py must stop saying FR-19 and FR-21 are unmet.")
        assert "PARTIALLY met" in text, (
            "FR-19's partial-fill half is not demonstrated — market orders "
            "against daily bars fill in full. Say so, or prove otherwise.")
    else:
        assert "are currently UNMET" in text, (
            "No module imports nautilus_trader, so FR-19 and FR-21 are unmet. "
            "execution_costs.py must say so. Wire the engine in, or restore the "
            "sentence stating the requirements are unmet rather than delegated.")
    assert installed or not imports_it, (
        "a module imports nautilus_trader but it is not installed")
