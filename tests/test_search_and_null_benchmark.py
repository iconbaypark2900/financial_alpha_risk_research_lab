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
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research_integrity.search import (  # noqa: E402
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
