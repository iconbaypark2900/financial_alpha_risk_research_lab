"""Minimal trial-search harness and the null-result benchmark — PRD 04 FR-16.

WHY THIS IS IN V0 AND NOT V1

The PRD is explicit: "the integrity controls cannot be validated without the
ability to run the search they exist to constrain". A deflated Sharpe that
nobody has watched deflate anything is a formula, not a control — the same
argument that put a mutation canary in front of the gates in dcode-stack.

WHAT IT DEMONSTRATES

Acceptance criteria 4 and 5, which the PRD calls the most valuable acceptance
test in the document:

  4. A 5,000-trial parameter search is run; the best strategy's deflated Sharpe
     is near zero and displayed as the headline, and the researcher correctly
     concludes it is noise.
  5. The SAME search is run against reshuffled returns; it produces a similarly
     attractive raw Sharpe.

Criterion 5 is the one that changes minds. Reshuffling returns destroys every
temporal relationship a trading rule could exploit while leaving the marginal
distribution untouched — same mean, same volatility, same fat tails, no
sequence. Any strategy that still looks good on shuffled data is, by
construction, fitting noise. When the shuffled search produces a raw Sharpe as
attractive as the real one, the raw Sharpe is revealed as a measure of how hard
you searched rather than of what you found.

The deflated Sharpe is what tells the two apart, and it can only do that if the
trial count is real — which is why every trial here goes through TrialCounter
before it is run.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from .core import deflated_sharpe_ratio, minimum_backtest_length
from .trial_counter import TrialCounter


def moving_average_crossover(returns: np.ndarray, fast: int, slow: int,
                             mode: str = "excess") -> float:
    """A deliberately ordinary strategy family: long when fast MA > slow MA.

    THE DRIFT TRAP, found by running this against real SPY data

    `mode="long_only"` scores the raw strategy return, and on any asset with
    positive drift that is a trap. Reshuffling preserves the MEAN exactly, so a
    long-only rule keeps earning the equity risk premium even when every
    temporal relationship has been destroyed. Measured on SPY 2010-2024: all
    7,866 trials were positive on both the real and the shuffled series, the
    variance across trials was ~2.7e-5, and the deflated Sharpe therefore came
    out at 0.99 on data with provably no signal in it.

    The deflated Sharpe was not wrong; it was answering a different question.
    It asks "is this the best of N draws?", not "does this beat holding the
    asset?" Nothing about selection bias can notice that every candidate is
    riding the same risk premium.

    So the default is `mode="excess"`: the strategy's return MINUS buy-and-hold,
    which is the comparison a researcher actually cares about. On SPY the best
    of 7,866 variants scores -0.0194 that way — the best one LOSES to simply
    holding the asset, which is the honest finding and is invisible in
    long-only terms.

    Chosen because it is the kind of rule that fills the practitioner
    literature, and because with two integer parameters it generates thousands
    of trials from a small grid — which is exactly how real searches quietly
    accumulate a multiple-testing burden nobody is counting.

    Returns the PER-PERIOD Sharpe ratio of the strategy, matching the units
    `deflated_sharpe_ratio` requires.
    """
    if fast >= slow:
        raise ValueError(f"fast ({fast}) must be shorter than slow ({slow})")
    if returns.size <= slow + 2:
        raise ValueError(f"need more than {slow + 2} observations for slow={slow}")

    prices = np.cumprod(1.0 + returns)
    fast_ma = _moving_average(prices, fast)
    slow_ma = _moving_average(prices, slow)

    # The two moving averages have different lengths (N-fast+1 and N-slow+1) and
    # both end at the final bar, so the fast one must be trimmed from the LEFT
    # to align. Comparing them unaligned is a broadcast error, which is what
    # this did at first — every trial in a 7,866-point grid raised, and the
    # search dutifully reported a best Sharpe of -inf.
    fast_ma = fast_ma[slow - fast:]
    assert fast_ma.shape == slow_ma.shape

    # Signal formed at bar t is traded at t+1: no peeking at the bar you act on.
    flat = -1.0 if mode == "long_short" else 0.0
    signal = np.where(fast_ma > slow_ma, 1.0, flat)[:-1]
    realised = returns[slow:]
    n = min(signal.size, realised.size)
    signal, realised = signal[:n], realised[:n]
    if n < 2:
        return 0.0

    strategy_returns = signal * realised
    if mode == "excess":
        # Against the passive alternative, which is the only benchmark that
        # makes a long-only equity rule falsifiable.
        strategy_returns = strategy_returns - realised
    elif mode not in ("long_only", "long_short"):
        raise ValueError(f"unknown mode {mode!r}; expected excess, long_only "
                         "or long_short")
    sd = strategy_returns.std(ddof=1)
    if sd < 1e-12:
        return 0.0
    return float(strategy_returns.mean() / sd)


def _moving_average(x: np.ndarray, window: int) -> np.ndarray:
    kernel = np.ones(window) / window
    return np.convolve(x, kernel, mode="valid")


def moving_average_timing(prices, window: int) -> tuple:
    """Faber (2007): hold the asset above its `window`-day mean, cash below.

    Distinct from `moving_average_crossover`, which compares two averages of the
    asset against each other. This compares the asset to ONE average and is
    long-or-flat, so it is a timing rule rather than a trend rule — and the
    difference matters for what it can be scored against. Being long-or-flat, it
    inherits the drift whenever it is invested, which is why the honest
    comparison is against buy-and-hold over the SAME sample rather than against
    zero.

    Source: Faber, M. (2007), "A Quantitative Approach to Tactical Asset
    Allocation", Journal of Wealth Management 9(4). The published rule is
    monthly on a 10-month average; the daily 200-day form used here is the one
    practitioners actually run.

    The signal formed on bar t is traded on t+1. There is no option to trade the
    bar you decided on: that is the look-ahead this package exists to prevent,
    and it is worth about half the reported edge in rules of this shape.

    Returns (strategy_returns, market_returns, exposure) over the aligned
    sample, so a caller cannot accidentally compare the rule against a
    buy-and-hold computed on a longer window.
    """
    import numpy as np

    prices = np.asarray(prices, dtype=float)
    if not isinstance(window, int) or window < 2:
        raise ValueError(f"window must be an integer of at least 2, got {window!r}")
    if prices.size <= window + 1:
        raise ValueError(
            f"need more than {window + 1} prices for window={window}, "
            f"got {prices.size}")
    if np.any(prices <= 0) or not np.all(np.isfinite(prices)):
        raise ValueError("prices must be finite and positive")

    mean = np.convolve(prices, np.ones(window) / window, mode="valid")
    aligned = prices[window - 1:]
    signal = (aligned > mean).astype(float)[:-1]      # decided at t, traded t+1
    market = np.diff(aligned) / aligned[:-1]
    return signal * market, market, float(signal.mean())


def crossover_grid(max_fast: int = 70, max_slow: int = 150) -> list[dict[str, int]]:
    """Every (fast, slow) pair with fast < slow. A small grid, many trials."""
    return [{"fast": f, "slow": s}
            for f in range(2, max_fast + 1)
            for s in range(f + 1, max_slow + 1)]


def run_search(returns: Sequence[float], param_sets: Iterable[dict[str, Any]], *,
               counter: TrialCounter, dataset_id: str,
               search_id: str, strategy: str = "ma_crossover",
               evaluate: Callable[..., float] = moving_average_crossover,
               researcher: str | None = None) -> dict[str, Any]:
    """Run a parameter sweep with every trial counted BEFORE it is evaluated.

    The whole sweep is registered up front, so the trial count is committed
    before any result exists. A search cannot be truncated at the moment it
    starts looking good and then reported as though it had been that size all
    along.
    """
    returns = np.asarray(returns, dtype=float)
    param_sets = list(param_sets)

    trial_ids = counter.start_trials(
        dataset_id, param_sets, strategy=strategy, search_id=search_id,
        researcher=researcher)

    outcomes: dict[str, float] = {}
    best = {"sharpe": -math.inf, "params": None}
    for trial_id, params in zip(trial_ids, param_sets):
        try:
            sharpe = evaluate(returns, **params)
        except Exception:
            # A trial that fails still counts — it consumed a look. It simply
            # contributes no Sharpe to the variance estimate.
            continue
        outcomes[trial_id] = sharpe
        if sharpe > best["sharpe"]:
            best = {"sharpe": sharpe, "params": params}

    if not outcomes:
        # Every trial raised. Reporting a "best" of -inf here would be a
        # fabricated result from a search that evaluated nothing — the exact
        # failure this module is meant to expose, committed by the module.
        raise RuntimeError(
            f"all {len(param_sets)} trials failed to evaluate; the search "
            "produced no results. Check the strategy function against the data "
            "length before trusting any summary of this sweep.")

    counter.record_outcomes(outcomes, n_observations=int(returns.size))

    return {
        "search_id": search_id,
        "dataset_id": dataset_id,
        "trials_run": len(param_sets),
        "trials_evaluated": len(outcomes),
        "best_raw_sharpe": best["sharpe"],
        "best_params": best["params"],
        "n_observations": int(returns.size),
        # FR-09: the deflated Sharpe is the headline, not the raw one.
        **deflation_block(returns, best["sharpe"],
                          counter.deflation_inputs(dataset_id)),
    }


# Every key in a search result whose value comes from the global trial ledger
# rather than from this search's own inputs. `with_recorded_deflation` restores
# exactly these from a run record; the rest a replay must re-derive.
COUNTER_DERIVED_KEYS = frozenset({
    "dataset_id", "n_trials", "var_trials", "trials_with_outcome",
    "trials_without_outcome", "deflated_sharpe", "deflated_sharpe_unavailable",
    "min_backtest_length", "sample_too_short",
})


def deflation_block(returns: np.ndarray, best_sharpe: float,
                    inputs: dict[str, Any]) -> dict[str, Any]:
    """The half of a search result that the GLOBAL trial ledger determines.

    Split out of `run_search` because it is the only half a replay cannot
    re-derive. `inputs` is the counter's state across the dataset's entire
    history — FR-08's "every backtest executed against each dataset, across all
    researchers and all time" — so it grows with every search anyone runs and
    is not a function of THIS search's recorded parameters. Everything above it
    in the result is.
    """
    block = dict(inputs)
    if inputs["var_trials"]:
        block["deflated_sharpe"] = deflated_sharpe_ratio(
            observed_sharpe=best_sharpe,
            n_trials=inputs["n_trials"],
            sample_length=int(returns.size),
            skewness=float(_skew(returns)),
            kurtosis=float(_kurtosis(returns)),
            var_trials=inputs["var_trials"])
        block["min_backtest_length"] = minimum_backtest_length(
            best_sharpe, inputs["n_trials"]) if best_sharpe > 0 else None
        block["sample_too_short"] = (
            block["min_backtest_length"] is not None
            and returns.size < block["min_backtest_length"])
    else:
        block["deflated_sharpe"] = None
        block["deflated_sharpe_unavailable"] = (
            "fewer than two trials reported a Sharpe, so the variance across "
            "trials is undefined; deflation is not possible")
    return block


def with_recorded_deflation(result: dict[str, Any], returns: Sequence[float], *,
                            recorded: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a REPLAYED search's ledger-derived block from the run record.

    For FR-23 replay, and nothing else. `Study.replay_search` explains why the
    alternative — dropping these keys from the comparison — was rejected.

    The trial count and the Sharpe variance are read from `recorded`; the
    deflated Sharpe, minimum backtest length and sample-length verdict are
    RECOMPUTED from them and from the replayed returns. So the derivation is
    still checked bitwise, against the burden the run actually carried, rather
    than copied out of the record.

    What this cannot do is verify the recorded ledger state itself — a replay
    has no way to reconstruct a past global count, which is what makes it
    global. That number is defended where it is written: the trials table is
    append-only by trigger. Note that `runs.result_json` is NOT covered by the
    run record's write-once trigger, which guards `result_hash`; a `result_json`
    edited after the fact therefore surfaces here as a replay FAILURE, because
    the block rebuilt from it no longer hashes to the stored digest. That is the
    behaviour worth having, and it is the concrete reason these keys are
    restored rather than excluded from the comparison.

    This function writes nothing, so a fabricated `recorded` corrupts one
    returned dict and no stored count.
    """
    missing = sorted(k for k in ("n_trials", "var_trials") if k not in recorded)
    if missing:
        raise ValueError(
            f"the recorded result is missing {', '.join(missing)}, so there is "
            "no trial-ledger state to replay the deflation against. Only a "
            "completed search records one.")
    ledger = {k: recorded[k] for k in
              ("dataset_id", "n_trials", "var_trials", "trials_with_outcome",
               "trials_without_outcome") if k in recorded}
    return {**{k: v for k, v in result.items() if k not in COUNTER_DERIVED_KEYS},
            **deflation_block(np.asarray(returns, dtype=float),
                              result["best_raw_sharpe"], ledger)}


def null_benchmark(returns: Sequence[float], param_sets: Iterable[dict[str, Any]], *,
                   counter: TrialCounter, dataset_id: str, search_id: str,
                   seed: int = 0, **kwargs) -> dict[str, Any]:
    """Acceptance criterion 5: the same search, against reshuffled returns.

    Shuffling destroys every temporal relationship a trading rule could exploit
    while preserving the marginal distribution exactly — same mean, same
    volatility, same skew and kurtosis, no sequence. There is therefore nothing
    to find, and whatever the search reports is the score this PROCEDURE
    produces on noise.

    Run this before trusting any search result. If the real search and the null
    search produce similar raw Sharpes, the raw Sharpe is measuring search
    intensity rather than signal.
    """
    rng = np.random.default_rng(seed)
    shuffled = np.asarray(returns, dtype=float).copy()
    rng.shuffle(shuffled)

    result = run_search(shuffled, param_sets, counter=counter,
                        dataset_id=dataset_id, search_id=search_id, **kwargs)
    result["null_benchmark"] = True
    result["shuffle_seed"] = seed
    result["interpretation"] = (
        "Returns were reshuffled, so no strategy can hold real predictive "
        "power. Any raw Sharpe here is the score this search procedure "
        "manufactures from noise at this trial count.")
    return result


def compare_to_null(real: dict[str, Any], null: dict[str, Any]) -> dict[str, Any]:
    """Put the two searches side by side and state the conclusion plainly.

    The verdict is deliberately blunt. A researcher reading two tables of
    numbers will find a reason the real one is different; a sentence saying the
    raw Sharpe is indistinguishable from noise is harder to argue with.

    WHAT REPLACED `null_s >= real_s * 0.8`, AND WHY

    That rule read "the null got within 20% of the real search", and it assumed
    a positive Sharpe without saying so. This module's default does not produce
    one: `moving_average_crossover` scores excess over buy-and-hold, and the
    best of 7,866 SPY variants scores -0.0194 that way. Multiplying a negative
    number by 0.8 moves it UP, so the threshold sat ABOVE the real Sharpe and
    the two branches swapped. A real search of -0.0194 against a null of -0.0190
    — noise strictly winning — was reported as "meaningfully exceeds the null
    benchmark, 1.0x", and that ratio was two negatives divided, which is
    positive and means nothing. The README's own headline real-data result,
    -0.0064, is in the same regime, and every test in this file used a positive
    Sharpe, so nothing caught it.

    The comparison is now on the DIFFERENCE, `real - null`. That is the quantity
    the question is actually about, and it does not change meaning when the sign
    does. A multiplicative threshold cannot survive a sign change; it also
    collapses at zero, where 0.0002 against 0.0001 is "2x" and is nothing. So
    the sign was only half of what was wrong with it, and a signed variant of
    the same multiplication would have left the other half in place.

    WHAT THE DIFFERENCE IS JUDGED AGAINST

    The WIDER of two margins, because "not meaningfully different" has two
    senses and a result should have to clear both:

      - the sampling variability of a Sharpe estimate over the sample the
        searches ran on — one standard error, sqrt((1 + SR^2 / 2) / n), Lo
        (2002), "The Statistics of Sharpe Ratios", eq. (9) for iid returns. A
        difference smaller than this is one the data cannot resolve, whatever
        its sign and whatever its size relative to either Sharpe. This is the
        absolute floor the multiplicative rule never had.
      - 20% of |real|, which is the old rule's magnitude with the sign removed.
        Kept because its judgement was sound where it applied: a fifth of the
        thing you are measuring is not an edge. Taking the wider of the two
        means no positive-Sharpe comparison becomes easier to win than it was.

    The first is a SCALE, not a test statistic, and no p-value is claimed for
    it. It is deliberately conservative: each side is the MAXIMUM of many
    trials, and the spread of a maximum is tighter than that of a single
    estimate, so a real difference has to clear a wider bar here than a sharper
    test would set. For a tool that exists to stop people announcing they beat
    noise, "indistinguishable" is the direction to err in.

    A caller passing bare dicts rather than `run_search` output records no
    sample length, so only the relative margin is available and the
    collapse-at-zero weakness returns. That is why `run_search` records
    `n_observations`, and why this is a fallback rather than the design.
    """
    real_s = real["best_raw_sharpe"]
    null_s = null["best_raw_sharpe"]
    n_obs = _shared_sample_length(real, null)

    excess = real_s - null_s
    margin, scale = _indistinguishable_margin(real_s, n_obs)
    indistinguishable = excess <= margin

    if indistinguishable:
        # Which way it fell has to be stated. A near-miss and a loss to noise
        # read identically once both are called NOISE, and only one of them
        # means the search was beaten by returns with no sequence in them.
        detail = (f"The reshuffled series scored HIGHER, by {-excess:.4f}."
                  if excess < 0 else
                  f"The real search led by {excess:.4f}, inside the "
                  f"{margin:.4f} that is {scale}.")
        verdict = (
            f"NOISE. The same search on reshuffled data reached a raw Sharpe "
            f"of {null_s:.4f} against {real_s:.4f} on the real data. {detail} "
            "The raw figure is measuring how hard you searched, not what you "
            "found.")
    else:
        verdict = (
            f"The real search ({real_s:.4f}) exceeds the null benchmark "
            f"({null_s:.4f}) by {excess:.4f}, clear of the {margin:.4f} that "
            f"is {scale}. That is necessary but not sufficient: check the "
            "deflated Sharpe below, which accounts for the trial count.")

    return {
        "real_best_raw_sharpe": real_s,
        "null_best_raw_sharpe": null_s,
        "excess_over_null": excess,
        "indistinguishable_margin": margin,
        "sample_length": n_obs,
        # A ratio of two Sharpes is a fraction only when both are positive. For
        # two negatives it comes out positive and reads like near-agreement
        # when the null in fact won; across a sign change it comes out negative
        # and reads like nothing at all. Reported as None rather than as a
        # number no reader can interpret — `excess_over_null` is the figure
        # that holds in every regime.
        "null_as_fraction_of_real": ((null_s / real_s)
                                     if real_s > 0 and null_s > 0 else None),
        "real_deflated_sharpe": real.get("deflated_sharpe"),
        "null_deflated_sharpe": null.get("deflated_sharpe"),
        "trials": real["trials_run"],
        "indistinguishable_from_noise": indistinguishable,
        "verdict": verdict,
    }


def _shared_sample_length(real: dict[str, Any], null: dict[str, Any]) -> int | None:
    """The sample both searches ran on, or None if neither recorded one.

    Refused rather than reconciled when they disagree: `null_benchmark` shuffles
    a copy of the same array, so two different lengths mean the null was not the
    same experiment, and the gap between the Sharpes is then attributable to the
    sample as much as to the shuffle.
    """
    a, b = real.get("n_observations"), null.get("n_observations")
    if a is not None and b is not None and int(a) != int(b):
        raise ValueError(
            f"the real search ran on {int(a):,} observations and the null on "
            f"{int(b):,}. A null benchmark is the same search over the same "
            "sample, reshuffled; over a different sample the gap between the "
            "two Sharpes is not attributable to the shuffle. Re-run the null "
            "against the same returns.")
    n = a if a is not None else b
    return int(n) if n is not None and int(n) > 1 else None


def _indistinguishable_margin(sharpe: float, n_observations: int | None
                              ) -> tuple[float, str]:
    """The margin, and the phrase naming which of the two terms is binding.

    The sampling term is one standard error of a Sharpe estimate,
    sqrt((1 + SR^2 / 2) / n) — Lo (2002) eq. (9), for iid returns. The SR^2 / 2
    part is negligible at the per-period Sharpes this module produces and is
    kept because dropping it would be a second approximation nobody wrote down.

    Which term binds is worth reporting: "inside one standard error" and
    "inside a fifth of the Sharpe itself" are different reasons to disbelieve a
    result, and a reader who is told only the number cannot tell them apart.
    """
    relative = 0.2 * abs(sharpe)
    if n_observations is None:
        return relative, ("20% of the real search's own Sharpe, no sample "
                          "length having been recorded")
    sampling = math.sqrt((1.0 + 0.5 * sharpe ** 2) / n_observations)
    if sampling >= relative:
        return sampling, (f"one standard error of a Sharpe over "
                          f"{n_observations:,} observations")
    return relative, (f"20% of the real search's own Sharpe, wider than the "
                      f"{sampling:.4f} that {n_observations:,} observations "
                      f"can resolve")


def _skew(x: np.ndarray) -> float:
    m = x.mean()
    sd = x.std(ddof=0)
    return 0.0 if sd < 1e-15 else float(((x - m) ** 3).mean() / sd ** 3)


def _kurtosis(x: np.ndarray) -> float:
    """NON-excess kurtosis: a normal sample gives 3.0, which is what Eq. (2) of
    the DSR paper expects."""
    m = x.mean()
    sd = x.std(ddof=0)
    return 3.0 if sd < 1e-15 else float(((x - m) ** 4).mean() / sd ** 4)
