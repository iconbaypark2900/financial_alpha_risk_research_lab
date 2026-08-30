"""Trial-search harness and null-result benchmark — PRD 04 FR-16, criteria 4-5.

The PRD calls criterion 5 "the most valuable acceptance test in this document":
run the same search against reshuffled returns and watch it produce a similarly
attractive raw Sharpe.

The most important test in this file is not either criterion, though — it is
`test_the_strategy_can_find_a_real_signal`. A harness that finds nothing
anywhere would pass every noise test trivially and be worthless. Before
believing "this is noise", the procedure has to be shown capable of saying
"this is signal" when there is one. That is the same discriminating check that
caught a deflated-Sharpe implementation returning a constant.
"""
import math
import re
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research_integrity.search import (  # noqa: E402
    _kurtosis,
    _skew,
    compare_to_null,
    crossover_grid,
    moving_average_crossover,
    null_benchmark,
    run_search,
)
from src.research_integrity.trial_counter import TrialCounter  # noqa: E402


@pytest.fixture()
def counter(tmp_path):
    return TrialCounter(tmp_path / "search.db")


def noise(n=1500, seed=42):
    return np.random.default_rng(seed).standard_t(df=4, size=n) * 0.01


def trending(n=1500, seed=7):
    """Returns with genuine, exploitable momentum: a slow drift the crossover
    rule is designed to catch, plus noise."""
    rng = np.random.default_rng(seed)
    signal = np.sin(np.linspace(0, 12 * np.pi, n)) * 0.004
    return signal + rng.standard_normal(n) * 0.004


SMALL_GRID = [{"fast": f, "slow": s} for f in (5, 10, 20) for s in (30, 50, 80)]


# --- the harness must be capable of finding something ----------------------

def test_the_strategy_can_find_a_real_signal():
    """The discriminating test. If the crossover rule could never detect a
    genuine pattern, every 'this is noise' verdict below would be vacuous."""
    real = max(moving_average_crossover(trending(), f, s)
               for f in (5, 10, 20) for s in (30, 50, 80))
    shuffled_data = trending().copy()
    np.random.default_rng(0).shuffle(shuffled_data)
    shuffled = max(moving_average_crossover(shuffled_data, f, s)
                   for f in (5, 10, 20) for s in (30, 50, 80))
    assert real > shuffled * 2, (
        f"the rule found {real:.4f} on a genuine trend vs {shuffled:.4f} on the "
        "same returns shuffled — it is not detecting the signal it exists for")


def test_moving_averages_are_aligned():
    """Regression: fast and slow MAs have different lengths and both end at the
    final bar, so the fast one must be trimmed from the left. Unaligned, every
    trial in a 7,866-point grid raised and the search reported -inf."""
    for fast, slow in ((2, 3), (5, 50), (10, 149)):
        value = moving_average_crossover(noise(500), fast, slow)
        assert np.isfinite(value)


def test_the_signal_does_not_peek_at_the_bar_it_trades():
    """A rule that trades the bar it formed its signal on shows spectacular,
    entirely fake performance. Feed it returns whose sign is knowable only
    contemporaneously: a look-ahead rule would score enormously."""
    rng = np.random.default_rng(3)
    returns = rng.standard_normal(800) * 0.01
    value = moving_average_crossover(returns, 5, 20)
    assert abs(value) < 0.3, f"suspiciously high Sharpe {value} on white noise"


# --- FR-16 / criterion 4: the search counts, and deflation kills the result -

def test_every_trial_in_the_sweep_is_counted(counter):
    result = run_search(noise(), SMALL_GRID, counter=counter,
                        dataset_id="ds", search_id="s1")
    assert result["trials_run"] == len(SMALL_GRID)
    assert counter.trial_count("ds") == len(SMALL_GRID)


def test_the_whole_sweep_is_registered_before_any_result_exists(counter):
    """A search cannot be truncated at the moment it starts looking good and
    then reported as though it had been that size all along."""
    ids = counter.start_trials("ds", SMALL_GRID, search_id="s1")
    assert counter.trial_count("ds") == len(SMALL_GRID)
    assert counter.deflation_inputs("ds")["trials_with_outcome"] == 0


def test_criterion_4_a_large_search_on_noise_deflates_to_near_zero(counter):
    """'the best strategy's deflated Sharpe is near zero ... and the researcher
    correctly concludes it is noise.'"""
    grid = crossover_grid(max_fast=25, max_slow=60)
    assert len(grid) > 1000
    result = run_search(noise(2000), grid, counter=counter,
                        dataset_id="ds", search_id="s1")
    assert result["best_raw_sharpe"] > 0        # searching always finds something
    assert result["deflated_sharpe"] < 0.95     # and deflation refuses to be impressed


def test_searching_harder_finds_a_better_looking_result_on_the_same_noise(counter):
    """The mechanism the whole module exists to expose: more trials produce a
    higher raw Sharpe from identical data, because the maximum of more draws is
    larger. Nothing was learned; the number went up."""
    data = noise(1500)
    small = run_search(data, SMALL_GRID, counter=counter,
                       dataset_id="small", search_id="a")
    big = run_search(data, crossover_grid(max_fast=25, max_slow=60),
                     counter=counter, dataset_id="big", search_id="b")
    assert big["best_raw_sharpe"] >= small["best_raw_sharpe"]
    assert big["n_trials"] > small["n_trials"] * 10


# --- criterion 5: the null benchmark ---------------------------------------

def test_criterion_5_reshuffled_returns_produce_a_similar_raw_sharpe(counter):
    """The PRD's most valuable acceptance test. Shuffling destroys every
    temporal relationship while preserving the marginal distribution, so
    anything the search finds is manufactured."""
    grid = crossover_grid(max_fast=20, max_slow=50)
    data = noise(1500)
    real = run_search(data, grid, counter=counter, dataset_id="real", search_id="r")
    null = null_benchmark(data, grid, counter=TrialCounter(counter.db_path),
                          dataset_id="null", search_id="n", seed=7)

    # "similarly attractive" — within a factor of two in either direction.
    assert null["best_raw_sharpe"] > real["best_raw_sharpe"] * 0.5


def test_shuffling_preserves_the_distribution_and_destroys_the_order():
    """Why the benchmark is valid: same mean, same volatility, no sequence."""
    data = trending()
    shuffled = data.copy()
    np.random.default_rng(1).shuffle(shuffled)
    assert shuffled.mean() == pytest.approx(data.mean())
    assert shuffled.std() == pytest.approx(data.std())
    assert not np.array_equal(shuffled, data)


def test_the_null_benchmark_is_reproducible(counter):
    a = null_benchmark(noise(800), SMALL_GRID, counter=counter,
                       dataset_id="a", search_id="a", seed=3)
    b = null_benchmark(noise(800), SMALL_GRID,
                       counter=TrialCounter(counter.db_path),
                       dataset_id="b", search_id="b", seed=3)
    assert a["best_raw_sharpe"] == pytest.approx(b["best_raw_sharpe"])


def test_the_comparison_states_the_conclusion_plainly():
    """A researcher reading two tables will find a reason the real one is
    different. A sentence is harder to argue with.

    Tested on constructed inputs rather than on a live search. An earlier
    version ran one search with one seed and asserted the verdict — and when
    that seed happened to fall the other way, the tempting fix was to try
    seeds until one passed. That is exactly the p-hacking this module exists
    to expose, so the stochastic claim is tested separately, over many seeds,
    below.
    """
    noisy = compare_to_null({"best_raw_sharpe": 0.020, "trials_run": 500,
                             "deflated_sharpe": 0.1},
                            {"best_raw_sharpe": 0.019, "deflated_sharpe": 0.1})
    assert noisy["indistinguishable_from_noise"] is True
    assert "NOISE" in noisy["verdict"]
    assert noisy["trials"] == 500

    real = compare_to_null({"best_raw_sharpe": 0.20, "trials_run": 500,
                            "deflated_sharpe": 0.99},
                           {"best_raw_sharpe": 0.02, "deflated_sharpe": 0.1})
    assert real["indistinguishable_from_noise"] is False
    assert "exceeds the null benchmark" in real["verdict"]


def test_on_noise_the_null_matches_the_real_search_on_average(tmp_path):
    """The stochastic version of criterion 5, over 8 seeds rather than one.

    Any single pair can fall either way — that is what noise means. The claim
    is about the distribution: searched equally hard, reshuffled data scores
    about as well as data that was never anything else.
    """
    grid = crossover_grid(max_fast=12, max_slow=30)
    ratios = []
    for seed in range(8):
        data = noise(1000, seed=seed)
        real = run_search(data, grid, counter=TrialCounter(tmp_path / f"r{seed}.db"),
                          dataset_id="real", search_id="r")
        null = null_benchmark(data, grid, counter=TrialCounter(tmp_path / f"n{seed}.db"),
                              dataset_id="null", search_id="n", seed=seed)
        ratios.append((real["best_raw_sharpe"], null["best_raw_sharpe"]))

    # Compare the two DISTRIBUTIONS, not the mean of per-seed ratios. An
    # earlier version averaged ratios and got -0.96: when a denominator lands
    # near zero the ratio explodes, and averaging exploded values measures the
    # arithmetic rather than the phenomenon.
    real_mean = float(np.mean([r for r, _ in ratios]))
    null_mean = float(np.mean([n for _, n in ratios]))
    assert 0.6 < null_mean / real_mean < 1.6, (
        f"over 8 seeds the real search averaged {real_mean:.4f} and the null "
        f"{null_mean:.4f}; on pure noise these should be comparable")


# --- refusals ---------------------------------------------------------------

def test_a_search_where_everything_fails_refuses_to_report_a_best(counter):
    """Reporting -inf as 'the best' would be a fabricated result from a search
    that evaluated nothing — the very failure this module exposes."""
    with pytest.raises(RuntimeError, match="failed to evaluate"):
        run_search(noise(50), [{"fast": 10, "slow": 300}], counter=counter,
                   dataset_id="ds", search_id="s")


def test_an_empty_grid_is_refused(counter):
    with pytest.raises(ValueError, match="not a search"):
        counter.start_trials("ds", [])


def test_failed_trials_still_count(counter):
    """They consumed a look even though they produced no number."""
    grid = [{"fast": 5, "slow": 20}, {"fast": 10, "slow": 5000}]
    result = run_search(noise(600), grid, counter=counter,
                        dataset_id="ds", search_id="s")
    assert result["trials_run"] == 2
    assert result["trials_evaluated"] == 1
    assert counter.trial_count("ds") == 2


# --- the drift trap, found on real SPY data --------------------------------

def test_long_only_on_a_drifting_asset_scores_well_on_shuffled_data():
    """The trap, reproduced. Shuffling preserves the MEAN exactly, so a
    long-only rule keeps earning the drift even with no sequence left.

    Measured on real SPY 2010-2024, all 7,866 trials were positive on BOTH the
    real and the reshuffled series, and the deflated Sharpe came out at 0.99 on
    data with provably no signal. This asserts the mechanism on synthetic data
    with the same property.
    """
    rng = np.random.default_rng(11)
    drifting = 0.0006 + rng.standard_normal(2000) * 0.01   # positive drift
    shuffled = drifting.copy()
    rng.shuffle(shuffled)

    best_shuffled = max(moving_average_crossover(shuffled, **p, mode="long_only")
                        for p in SMALL_GRID)
    assert best_shuffled > 0, (
        "a long-only rule on shuffled positive-drift returns should still score "
        "positively; if it does not, this fixture no longer demonstrates the trap")


def test_excess_returns_remove_the_drift_the_shuffle_preserves():
    """The fix, and the default. Measuring against buy-and-hold makes a
    long-only equity rule falsifiable, because the passive alternative earns the
    same drift."""
    rng = np.random.default_rng(11)
    drifting = 0.0006 + rng.standard_normal(2000) * 0.01
    shuffled = drifting.copy()
    rng.shuffle(shuffled)

    long_only = max(moving_average_crossover(shuffled, **p, mode="long_only")
                    for p in SMALL_GRID)
    excess = max(moving_average_crossover(shuffled, **p, mode="excess")
                 for p in SMALL_GRID)
    assert excess < long_only


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="unknown mode"):
        moving_average_crossover(noise(500), 5, 20, mode="magic")


# --- moving_average_timing: a rule people actually believe in ---------------

def test_timing_rule_is_long_only_when_price_is_above_its_mean():
    """Hand-checkable: a series that rises then falls through its own mean."""
    from src.research_integrity.search import moving_average_timing

    prices = np.array([10.0, 10.0, 10.0, 12.0, 14.0, 8.0, 6.0, 6.0])
    strategy, market, exposure = moving_average_timing(prices, window=3)
    means = np.convolve(prices, np.ones(3) / 3, mode="valid")
    aligned = prices[2:]
    expected_signal = (aligned > means).astype(float)[:-1]
    assert exposure == pytest.approx(expected_signal.mean())
    assert strategy == pytest.approx(expected_signal * market)


def test_the_signal_is_traded_the_day_after_it_is_formed():
    """The look-ahead that is worth about half the edge in rules of this shape.

    Moving only the FINAL price cannot change any return the rule already
    earned, because the last signal is acted on a bar that does not exist yet.
    """
    from src.research_integrity.search import moving_average_timing

    prices = np.asarray(100 * 1.001 ** np.arange(60))
    base, _, _ = moving_average_timing(prices, window=10)
    moved = prices.copy()
    moved[-1] *= 3.0
    after, _, _ = moving_average_timing(moved, window=10)
    assert base[:-1] == pytest.approx(after[:-1])


def test_the_timing_rule_reads_no_further_forward_than_that():
    """Checked with the factor library's own causality harness rather than by
    argument: perturb the future, require the past not to move."""
    from src.research_integrity.factors import assert_causal
    from src.research_integrity.search import moving_average_timing

    prices = np.asarray(100 * np.exp(np.cumsum(
        np.random.default_rng(0).normal(0, 0.01, 400))))

    def signal_path(series):
        strategy, _, _ = moving_average_timing(series, window=50)
        # Pad back to the input length so the harness can compare positions.
        return np.concatenate([np.full(series.size - strategy.size, np.nan),
                               strategy])

    assert_causal(signal_path, prices, split=350)


def test_market_returns_cover_the_same_sample_as_the_strategy():
    """Returned together so a caller cannot compare the rule against a
    buy-and-hold computed over a longer window — which flatters whichever of
    the two saw the better period."""
    from src.research_integrity.search import moving_average_timing

    prices = np.asarray(100 * 1.001 ** np.arange(100))
    strategy, market, _ = moving_average_timing(prices, window=20)
    assert strategy.shape == market.shape


def test_a_fully_invested_rule_equals_buy_and_hold():
    """A monotonically rising series is always above its trailing mean."""
    from src.research_integrity.search import moving_average_timing

    prices = np.asarray(100 * 1.01 ** np.arange(80))
    strategy, market, exposure = moving_average_timing(prices, window=20)
    assert exposure == pytest.approx(1.0)
    assert strategy == pytest.approx(market)


@pytest.mark.parametrize("prices, window", [
    (np.array([1.0, 2.0, 3.0]), 10),          # too short
    (np.array([1.0, -2.0, 3.0, 4.0, 5.0]), 2),  # non-positive
    (np.asarray(100 * 1.01 ** np.arange(50)), 1),  # degenerate window
])
def test_bad_timing_inputs_are_refused(prices, window):
    from src.research_integrity.search import moving_average_timing

    with pytest.raises(ValueError):
        moving_average_timing(prices, window)


# --- the verdict must survive a sign change --------------------------------
#
# Every test above this line uses a POSITIVE Sharpe, and that is how the
# multiplicative `null_s >= real_s * 0.8` rule survived: a 0.8 multiplier moves
# a positive number down and a negative number UP, so for a losing search the
# threshold sat above the real Sharpe and the verdict came out inverted. The
# module's own defaults live in that regime — `moving_average_crossover` scores
# excess-over-buy-and-hold, and its docstring reports the best of 7,866 SPY
# variants at -0.0194.

def test_two_negative_sharpes_are_not_a_win_for_the_real_search():
    """The reproduction, with the module's own documented SPY figure.

    Noise reached -0.0190 and the real search -0.0194: the reshuffled series
    STRICTLY OUTPERFORMED, and the tool reported the opposite.
    """
    out = compare_to_null(
        {"best_raw_sharpe": -0.0194, "trials_run": 7866, "n_observations": 3770,
         "deflated_sharpe": 0.0},
        {"best_raw_sharpe": -0.0190, "n_observations": 3770,
         "deflated_sharpe": 0.0})
    assert out["indistinguishable_from_noise"] is True, out["verdict"]
    assert "NOISE" in out["verdict"]
    assert "exceeds the null benchmark" not in out["verdict"]


def test_the_verdict_says_so_when_noise_actually_won():
    """A verdict that reports 98% when the null was BETTER reads as a near-miss.
    The reader has to be told which way round it fell."""
    out = compare_to_null(
        {"best_raw_sharpe": -0.0194, "trials_run": 7866, "n_observations": 3770},
        {"best_raw_sharpe": -0.0190, "n_observations": 3770})
    assert "higher" in out["verdict"].lower()
    assert not re.search(r"\d\.\dx", out["verdict"]), (
        "the verdict still reports a multiple of two negative Sharpes")


def test_a_losing_search_that_still_beats_noise_is_not_called_noise():
    """The other half of the negative regime, and the reason this cannot be
    fixed by flipping the comparison. A rule that loses to buy-and-hold by
    0.01 while the reshuffled sweep loses by 0.50 did beat its null.

    (This one also passes against the unfixed code — it is here so a fix that
    merely inverts the sign is caught.)
    """
    out = compare_to_null(
        {"best_raw_sharpe": -0.01, "trials_run": 100, "n_observations": 400},
        {"best_raw_sharpe": -0.50, "n_observations": 400})
    assert out["indistinguishable_from_noise"] is False, out["verdict"]
    assert "exceeds the null benchmark" in out["verdict"]


def test_a_hair_of_a_difference_near_zero_is_not_an_edge():
    """The same failure at the other end of the scale, and the reason a
    multiplicative threshold is the wrong shape rather than merely mis-signed.

    0.0002 against 0.0001 is 2x, and 2x of nothing is nothing. A margin
    proportional to the real Sharpe shrinks to zero exactly where the real
    Sharpe does, so it certifies noise as signal at the near-zero Sharpes this
    module's own searches produce.
    """
    out = compare_to_null(
        {"best_raw_sharpe": 0.0002, "trials_run": 7866, "n_observations": 2000},
        {"best_raw_sharpe": 0.0001, "n_observations": 2000})
    assert out["indistinguishable_from_noise"] is True, out["verdict"]


def test_the_margin_is_measured_in_sampling_variability_not_in_percent():
    """What replaces the 0.8: the same gap is or is not a difference depending
    on how much data was behind it. Four hundred observations cannot resolve a
    0.05 difference in per-period Sharpe; forty thousand can."""
    real = {"best_raw_sharpe": 0.10, "trials_run": 500}
    null = {"best_raw_sharpe": 0.05}
    short = compare_to_null({**real, "n_observations": 400},
                            {**null, "n_observations": 400})
    long = compare_to_null({**real, "n_observations": 40_000},
                           {**null, "n_observations": 40_000})
    assert short["indistinguishable_from_noise"] is True, short["verdict"]
    assert long["indistinguishable_from_noise"] is False, long["verdict"]


def test_a_null_run_over_a_different_sample_is_refused():
    """A null benchmark is the SAME search over the SAME returns, reshuffled.
    Two different sample lengths are two different experiments, and the
    difference between their Sharpes is not attributable to the shuffle."""
    with pytest.raises(ValueError, match="same sample"):
        compare_to_null(
            {"best_raw_sharpe": 0.02, "trials_run": 500, "n_observations": 2000},
            {"best_raw_sharpe": 0.01, "n_observations": 1000})


def test_the_ratio_is_reported_only_where_it_means_something():
    """`null / real` is a fraction only when both are positive. For two
    negatives it is a positive number that reads like agreement, and across a
    sign change it is negative and reads like nothing at all."""
    both_positive = compare_to_null(
        {"best_raw_sharpe": 0.020, "trials_run": 500},
        {"best_raw_sharpe": 0.019})
    assert both_positive["null_as_fraction_of_real"] == pytest.approx(0.95)

    for real_s, null_s in ((-0.0194, -0.0190), (-0.0064, 0.0015), (0.02, -0.01)):
        out = compare_to_null({"best_raw_sharpe": real_s, "trials_run": 500},
                              {"best_raw_sharpe": null_s})
        assert out["null_as_fraction_of_real"] is None, (real_s, null_s)
        assert out["excess_over_null"] == pytest.approx(real_s - null_s)


# --- the seam FR-23 replay verifies its deflation through ------------------

def test_the_replay_block_recomputes_the_deflation_rather_than_copying_it(counter):
    """What keeps FR-09's headline inside FR-23's comparison.

    `with_recorded_deflation` restores the recorded trial count and variance —
    which a replay cannot re-derive, because they belong to the dataset's whole
    history — and then RE-DERIVES the deflated Sharpe from them. Handed the same
    ledger, it must still move when the search's own Sharpe moves, or it is
    copying the answer out of the record and verifying nothing.
    """
    from src.research_integrity.core import deflated_sharpe_ratio
    from src.research_integrity.search import with_recorded_deflation

    data = noise(1200)
    result = run_search(data, SMALL_GRID, counter=counter,
                        dataset_id="ds", search_id="s")
    recorded = {**result, "n_trials": 50_000, "var_trials": 0.004}

    restored = with_recorded_deflation(result, data, recorded=recorded)
    assert restored["n_trials"] == 50_000
    assert restored["deflated_sharpe"] != result["deflated_sharpe"]
    assert restored["deflated_sharpe"] == pytest.approx(deflated_sharpe_ratio(
        observed_sharpe=result["best_raw_sharpe"], n_trials=50_000,
        sample_length=data.size, skewness=float(_skew(data)),
        kurtosis=float(_kurtosis(data)), var_trials=0.004))

    # The derivation, not a lookup: a different best Sharpe under the same
    # ledger must produce a different deflated Sharpe.
    moved = with_recorded_deflation({**result, "best_raw_sharpe": 0.5}, data,
                                    recorded=recorded)
    assert moved["deflated_sharpe"] != restored["deflated_sharpe"]


def test_the_replay_block_leaves_no_stale_key_from_the_replayed_run(counter):
    """The two branches of the deflation emit different keys, so restoring one
    over the other by merging would leave the replayed run's keys behind and
    the hash could not match — the same false failure, one layer down."""
    from src.research_integrity.search import with_recorded_deflation

    data = noise(1200)
    result = run_search(data, SMALL_GRID, counter=counter,
                        dataset_id="ds", search_id="s")
    assert "min_backtest_length" in result and "sample_too_short" in result

    # A run recorded before its variance was estimable takes the other branch.
    restored = with_recorded_deflation(
        result, data, recorded={**result, "n_trials": 1, "var_trials": None})
    assert restored["deflated_sharpe"] is None
    assert "deflated_sharpe_unavailable" in restored
    assert "min_backtest_length" not in restored
    assert "sample_too_short" not in restored


def test_a_result_with_no_ledger_state_is_refused_not_silently_replayed(counter):
    """A failed run records `{"error": ...}`. Falling back to the replay's own
    throwaway counter there would reintroduce the bug quietly."""
    from src.research_integrity.search import with_recorded_deflation

    data = noise(600)
    result = run_search(data, SMALL_GRID, counter=counter,
                        dataset_id="ds", search_id="s")
    with pytest.raises(ValueError, match="no trial-ledger state"):
        with_recorded_deflation(result, data, recorded={"error": "boom"})


def test_no_positive_sharpe_comparison_got_easier_to_win():
    """The margin is the WIDER of the two terms, not the sampling one alone.

    At a large per-period Sharpe on a long sample, one standard error is small
    and a 10% gap clears it — so a sampling-variability margin ON ITS OWN would
    have called this a result where the old multiplicative rule called it
    noise. Fixing an inverted verdict must not quietly relax a correct one.

    (This one also passes against the unfixed code; it exists so that the
    relative term cannot be dropped as redundant.)
    """
    out = compare_to_null(
        {"best_raw_sharpe": 0.50, "trials_run": 500, "n_observations": 2000},
        {"best_raw_sharpe": 0.45, "n_observations": 2000})
    assert out["indistinguishable_from_noise"] is True, out["verdict"]
    assert out["indistinguishable_margin"] == pytest.approx(0.10)
    assert "20% of the real search's own Sharpe" in out["verdict"]


# --- the null has to have swept the same space, not just the same sample ----

def test_a_null_run_over_a_different_number_of_trials_is_refused():
    """The twin of `test_a_null_run_over_a_different_sample_is_refused`.

    The best of N trials grows with N whether or not anything is there, so a
    ten-trial null against a 7,866-trial search scores lower for its size
    alone. `compare_to_null` read `real["trials_run"]` and never looked at the
    null's, so it charged the whole of that difference to the shuffle and
    reported the sweep-size gap as an edge over noise.
    """
    with pytest.raises(ValueError, match="same parameter grid"):
        compare_to_null(
            {"best_raw_sharpe": 0.20, "trials_run": 7866, "n_observations": 3770},
            {"best_raw_sharpe": 0.02, "trials_run": 10, "n_observations": 3770})


def test_a_matched_null_still_reports_the_count_both_searches_ran():
    """The other direction, and what stops the refusal being answered with
    "refuse more": two halves of one benchmark agree to the trial, and the
    `trials` key still has to come back."""
    out = compare_to_null(
        {"best_raw_sharpe": 0.20, "trials_run": 7866, "n_observations": 3770},
        {"best_raw_sharpe": 0.02, "trials_run": 7866, "n_observations": 3770})
    assert out["trials"] == 7866
    assert out["indistinguishable_from_noise"] is False


def test_a_null_that_recorded_no_trial_count_is_compared_unverified():
    """The named gap, pinned so it is a decision rather than an oversight.

    A bare dict records nothing to check, and refusing it would break every
    caller comparing hand-built summaries — the same fallback `n_observations`
    already has. Every `null_benchmark` result carries `trials_run`, so the
    unchecked case is exactly the one that did not come from a search.

    (This one passes against the unfixed code too. It is here so the fallback
    cannot be tightened into a refusal without someone deciding to.)
    """
    out = compare_to_null({"best_raw_sharpe": 0.020, "trials_run": 500},
                          {"best_raw_sharpe": 0.019})
    assert out["trials"] == 500


def test_the_best_of_n_grows_with_n_which_is_what_the_check_protects():
    """The number `_shared_trial_count` justifies itself with, computed.

    E[max of N iid N(0,1)] by quadrature on 1 - F(x)^N, so the docstring's
    1.5387 at N = 10 and 3.7921 at N = 7,866 are derived here rather than
    asserted there. The ratio is what a mismatched null costs: sweep 786 times
    less of the space and score 2.46x lower for that reason alone, which
    `compare_to_null` would otherwise read as the real search beating noise.
    """
    x = np.linspace(-12.0, 14.0, 400_001)
    cdf = 0.5 * (1.0 + np.vectorize(math.erf)(x / math.sqrt(2.0)))
    upper, lower = x >= 0, x < 0

    def trapezoid(y: np.ndarray, at: np.ndarray) -> float:
        # Spelled out rather than np.trapezoid, which is numpy 2 only, and
        # np.trapz, which numpy 2 deprecates. This package declares numpy>=1.21
        # and the minimal install is a supported configuration.
        return float(np.sum(0.5 * (y[1:] + y[:-1]) * np.diff(at)))

    def expected_max(n_trials: int) -> float:
        # E[max] = int_0^inf (1 - F^N) dx - int_-inf^0 F^N dx.
        best_below = cdf ** n_trials
        return (trapezoid(1.0 - best_below[upper], x[upper])
                - trapezoid(best_below[lower], x[lower]))

    small, large = expected_max(10), expected_max(7866)
    assert small == pytest.approx(1.5387, abs=5e-4)
    assert large == pytest.approx(3.7921, abs=5e-4)
    assert large / small == pytest.approx(2.46, abs=0.01)
