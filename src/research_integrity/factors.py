"""Factor library — PRD 04 §5.1, V0 scope: "small, each factor unit-tested
against known values".

WHAT A FACTOR LIBRARY IS FOR, AND THE TWO WAYS IT GOES WRONG

A factor is a number computed per security per date that a strategy sorts on.
The library is small on purpose: the PRD asks for a handful of factors that are
each *known* to be right, not a catalogue of hundreds that are each plausible.
A wrong factor does not announce itself. It produces a backtest.

There are exactly two ways a factor computation is wrong in a way that survives
review, and both are addressed structurally here rather than by care:

  1. THE FACTOR SEES THE FUTURE. The value at time t is computed from data that
     arrived after t. This is almost never written deliberately; it arrives
     through an off-by-one in a rolling window, a series normalised over its
     whole length, or a `.shift()` in the wrong direction. It is invisible in
     the output — a leaky factor looks exactly like a good one, only better —
     and it is the single most common defect in published factor research.

     `assert_causal` below CHECKS it rather than asking you to be careful:
     perturb the data after time t, recompute, and require every value at or
     before t to be unchanged. A factor that peeks cannot pass. This is the same
     move `assert_no_leakage` makes for cross-validation splits, for the same
     reason — the property is mechanically checkable, so checking it is not
     optional.

  2. THE FUNDAMENTAL WAS NOT PUBLISHED YET. A fiscal quarter ends on 31 December
     and the filing lands in the middle of February. Joining book equity to
     prices on the fiscal period end date gives the strategy six weeks of
     knowledge it did not have, and the resulting value factor works beautifully.
     This is why the fundamental factors here take a KNOWLEDGE date and read
     through `PointInTimeStore.as_of` rather than taking a number: during the
     reporting lag the honest answer is that the factor is undefined, and this
     module returns None rather than the figure that had not been published.

SIGN CONVENTIONS ARE STATED, NOT ASSUMED

Every factor returns the raw quantity, and `FACTORS[name].direction` records
which sign has historically earned the premium. Silently negating inside the
function — so that "high is good" for every factor — is convenient exactly once,
and then someone compares two factors whose conventions differ and cannot see
why the spread inverted.

WHAT IS NOT HERE

No cross-sectional standardisation, no factor combination, no neutralisation
against market beta or sector. Those are portfolio-construction steps, which the
README places in V1, and each would need its own known-value tests. A factor
library that quietly grew a portfolio optimiser would be the scope drift the
rebuild in `6eb543f` already corrected once.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

import numpy as np

# Trading days in a year. Stated once, here, because a factor library with three
# different implicit year lengths in it produces three incomparable factors.
TRADING_DAYS = 252


class FactorError(ValueError):
    """A factor could not be computed from the inputs given."""


class LookAheadFactor(AssertionError):
    """A factor's value at time t changed when data after t changed.

    An AssertionError rather than a FactorError because it is a failed
    invariant, not a bad input — the same choice `LeakageError` makes in
    cross_validation.py.
    """


@dataclass(frozen=True)
class Factor:
    """What a factor is, beside the function that computes it.

    `direction` exists so that the sign convention lives next to the factor
    rather than in the memory of whoever wrote it.
    """
    name: str
    description: str
    direction: str
    citation: str


# --- price factors ---------------------------------------------------------

def _as_prices(prices: Sequence[float]) -> np.ndarray:
    arr = np.asarray(prices, dtype=float)
    if arr.ndim != 1:
        raise FactorError(f"prices must be one-dimensional, got shape {arr.shape}")
    if arr.size == 0:
        raise FactorError("prices is empty")
    if not np.all(np.isfinite(arr)):
        raise FactorError("prices contains non-finite values; a NaN price "
                          "propagates into every window that touches it")
    if np.any(arr <= 0):
        raise FactorError("prices must be positive — a ratio against a "
                          "non-positive price is not a return")
    return arr


def momentum(prices: Sequence[float], lookback: int = TRADING_DAYS,
             skip: int = 21) -> np.ndarray:
    """12-1 momentum: the return from t-`lookback` to t-`skip`.

    The skipped month is not an optional refinement. Jegadeesh & Titman (1993)
    and every credible replication since exclude the most recent month, because
    short-horizon returns REVERSE — including them mixes a reversal signal into
    a momentum signal with the opposite sign, and the combination looks weaker
    than either. `reversal` below is that effect on its own.

    Returns an array the length of `prices`, NaN before enough history exists.
    Uses no data after t-`skip`, so it is causal with a margin.
    """
    arr = _as_prices(prices)
    if not isinstance(lookback, int) or not isinstance(skip, int):
        raise FactorError("lookback and skip must be integers (they are offsets)")
    if skip < 0:
        raise FactorError(f"skip must be non-negative, got {skip}")
    if lookback <= skip:
        raise FactorError(
            f"lookback ({lookback}) must exceed skip ({skip}) — otherwise the "
            "window is empty or reversed")

    out = np.full(arr.size, np.nan)
    for t in range(lookback, arr.size):
        out[t] = arr[t - skip] / arr[t - lookback] - 1.0
    return out


def reversal(prices: Sequence[float], lookback: int = 21) -> np.ndarray:
    """Short-term reversal: the NEGATIVE of the trailing `lookback` return.

    Negated in the definition rather than by the caller because the factor is
    the reversal, not the return — a high value means the security fell and is
    expected to recover. The negation is the factor's content, so it is stated
    in `FACTORS['reversal'].direction` as well.
    """
    arr = _as_prices(prices)
    if not isinstance(lookback, int) or lookback < 1:
        raise FactorError(f"lookback must be a positive integer, got {lookback!r}")

    out = np.full(arr.size, np.nan)
    for t in range(lookback, arr.size):
        out[t] = -(arr[t] / arr[t - lookback] - 1.0)
    return out


def realised_volatility(prices: Sequence[float], window: int = 21, *,
                        annualise: bool = True) -> np.ndarray:
    """Trailing standard deviation of log returns over `window` periods.

    Sample standard deviation (ddof=1), because the window is a sample and the
    population correction is not optional at a window of 21: ddof=0 understates
    volatility by about 2.5% there, which is small enough to survive inspection
    and large enough to reorder a decile sort.

    The low-volatility premium is in the NEGATIVE direction — this returns
    volatility, not the factor's expected sign. See `FACTORS`.
    """
    arr = _as_prices(prices)
    if not isinstance(window, int) or window < 2:
        raise FactorError(
            f"window must be an integer of at least 2, got {window!r} — a "
            "standard deviation over one observation is not defined")

    log_returns = np.diff(np.log(arr))          # length n - 1, index i is t=i+1
    out = np.full(arr.size, np.nan)
    scale = np.sqrt(TRADING_DAYS) if annualise else 1.0
    for t in range(window, arr.size):
        out[t] = np.std(log_returns[t - window:t], ddof=1) * scale
    return out


def size(market_cap: Sequence[float]) -> np.ndarray:
    """Log market capitalisation.

    Logged because market cap spans four orders of magnitude and a raw sort on
    it is a sort on the largest few names. The size premium is historically in
    the NEGATIVE direction (small beats large); this returns the size itself.
    """
    arr = np.asarray(market_cap, dtype=float)
    if arr.size == 0:
        raise FactorError("market_cap is empty")
    if not np.all(np.isfinite(arr)):
        raise FactorError("market_cap contains non-finite values")
    if np.any(arr <= 0):
        raise FactorError("market_cap must be positive to be logged")
    return np.log(arr)


# --- fundamental factors, which must read through the point-in-time store ---

def book_to_market_as_of(store: Any, dataset_id: str, entity_id: str, *,
                         knowledge_date: str, market_cap: float,
                         field: str = "book_equity") -> float | None:
    """Book-to-market from the book equity KNOWN as of `knowledge_date`.

    Returns None when no book equity had been published yet. That is the point:
    during the reporting lag the factor is genuinely undefined, and None is the
    only answer that does not invent knowledge. Filling it forward from a filing
    that had not happened is the look-ahead this whole store exists to prevent,
    and it is invisible afterwards — the contaminated factor is simply better.

    Reads `store.as_of`, which filters on knowledge_date and returns
    as-first-reported values, so a restatement published later is not visible
    either (FR-02).
    """
    if market_cap <= 0:
        raise FactorError(f"market_cap must be positive, got {market_cap}")

    facts = store.as_of(dataset_id, knowledge_date,
                        entity_id=entity_id, field=field)
    if not facts:
        return None

    # Two selections, and taking facts[-1] conflated them. `as_of` orders by
    # (effective_date, knowledge_date), so the last row is the LATEST-KNOWN
    # value for the latest period — which is the restatement whenever one has
    # been published by `knowledge_date`. FR-02 asks for as-FIRST-reported.
    #
    # It read correctly and returned a look-ahead-contaminated number: with book
    # equity of 500 filed 2024-02-15 and restated to 400 on 2024-03-20, a query
    # at 2024-04-01 returned 0.4 where the honest answer is 0.5. The test that
    # was supposed to guard this only queried at 2024-02-20, before the
    # restatement existed, so it never reached the failing case.
    latest_period = max(fact["effective_date"] for fact in facts)
    for_period = [f for f in facts if f["effective_date"] == latest_period]
    first_reported = min(for_period, key=lambda f: f["knowledge_date"])
    return float(first_reported["value"]) / float(market_cap)


# --- the invariant, checked rather than trusted ----------------------------

def assert_causal(factor_fn: Callable[[np.ndarray], np.ndarray],
                  data: Sequence[float], *, split: int | None = None,
                  seed: int = 0) -> None:
    """Require that `factor_fn`'s values up to `split` ignore data after it.

    Replaces everything after `split` with different values, recomputes, and
    compares the head of both results. A factor that reads the future produces a
    different head and fails here.

    This is checkable directly, which is why it is a function rather than a
    convention: it works on any callable, including one this library did not
    write, and it requires no cooperation from the factor being tested.

    `split` defaults to the midpoint, which is wrong for any factor whose
    warm-up exceeds half the series — the head is then all NaN and the check
    passes without comparing anything. That case raises rather than passing;
    pass a `split` after the warm-up, or a longer series.

    Raises:
        LookAheadFactor: naming the first index whose value moved.
        FactorError: if the comparison would be vacuous.
    """
    arr = np.asarray(data, dtype=float)
    if arr.size < 4:
        raise FactorError("need at least 4 observations to split meaningfully")
    if split is None:
        split = arr.size // 2
    if not 0 < split < arr.size - 1:
        raise FactorError(
            f"split must leave data on both sides (0 < split < {arr.size - 1}), "
            f"got {split}")

    baseline = np.asarray(factor_fn(arr), dtype=float)

    # A head that is entirely NaN compares equal to itself no matter what the
    # factor does, so the check would pass without testing anything. This is not
    # a hypothetical: at the default midpoint split, every factor here with a
    # 252-period lookback warms up entirely inside the tail, and the first
    # version of this function silently approved a factor that normalised over
    # the whole series. A vacuous pass is worse than no check, because it is
    # recorded as a pass.
    head = slice(None, split + 1)
    if baseline.size and np.all(np.isnan(baseline[head])):
        raise FactorError(
            f"vacuous check: every value at or before split={split} is NaN, so "
            "the comparison cannot fail. The factor's warm-up period is longer "
            f"than the head. Use a longer series or a later split (the input "
            f"has {arr.size} observations).")

    # The perturbation has to be a real change and must not violate the
    # factor's own preconditions — prices stay positive, so it scales rather
    # than replaces.
    rng = np.random.default_rng(seed)
    perturbed_input = arr.copy()
    tail = slice(split + 1, None)
    perturbed_input[tail] = arr[tail] * rng.uniform(1.5, 2.5, size=arr[tail].size)
    perturbed = np.asarray(factor_fn(perturbed_input), dtype=float)

    if baseline.shape != perturbed.shape:
        raise LookAheadFactor(
            f"factor returned shape {baseline.shape} then {perturbed.shape} for "
            "inputs of the same length; it depends on the data's values, not "
            "only its length")

    if not np.array_equal(baseline[head], perturbed[head], equal_nan=True):
        differing = np.flatnonzero(
            ~((baseline[head] == perturbed[head])
              | (np.isnan(baseline[head]) & np.isnan(perturbed[head]))))
        first = int(differing[0])
        raise LookAheadFactor(
            f"value at index {first} changed from {baseline[first]!r} to "
            f"{perturbed[first]!r} when data AFTER index {split} was altered. "
            "The factor reads the future.")


# --- registry --------------------------------------------------------------

FACTORS: dict[str, Factor] = {
    "momentum": Factor(
        name="momentum",
        description="Return from t-252 to t-21; the most recent month skipped.",
        direction="positive — past winners have historically continued",
        citation="Jegadeesh & Titman (1993), Journal of Finance 48(1)."),
    "reversal": Factor(
        name="reversal",
        description="Negative of the trailing one-month return.",
        direction="positive — recent losers have historically rebounded",
        citation="Jegadeesh (1990), Journal of Finance 45(3)."),
    "volatility": Factor(
        name="volatility",
        description="Annualised standard deviation of trailing log returns.",
        direction="NEGATIVE — low-volatility names have historically outperformed",
        citation="Ang, Hodrick, Xing & Zhang (2006), Journal of Finance 61(1)."),
    "size": Factor(
        name="size",
        description="Log market capitalisation.",
        direction="NEGATIVE — small has historically beaten large",
        citation="Fama & French (1993), Journal of Financial Economics 33(1)."),
    "book_to_market": Factor(
        name="book_to_market",
        description="As-reported book equity known at the date, over market cap.",
        direction="positive — high book-to-market has historically outperformed",
        citation="Fama & French (1992), Journal of Finance 47(2)."),
}
