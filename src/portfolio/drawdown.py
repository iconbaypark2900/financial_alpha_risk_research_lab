"""Drawdown and risk metrics — PRD 04 §5.5 (V1), migrated from finGuard.

WHAT WAS WRONG WITH THE SOURCE

`calculate_drawdown` was correct and is kept as-is in substance. The rest had
three defects, all of which flatter the strategy:

  1. RECOVERY TIME USED THE WRONG FORMULA. To recover from a drawdown x you must
     gain 1/(1-x) - 1, so the time at rate r is -log(1-x)/log(1+r). finGuard
     used log(1+x)/log(1+r), which understates the wait, and by more the worse
     the drawdown gets:

         drawdown   correct    finGuard   understated by
            10%     1.105 yr   1.000 yr        9.5%
            20%     2.341 yr   1.913 yr       18.3%
            50%     7.273 yr   4.254 yr       41.5%

     The sanity check is one line: a 50% drawdown needs a 100% gain, so at 10% a
     year it is log(2)/log(1.1) = 7.27 years. Anything reporting 4.25 has not
     answered the question asked.

  2. THE RISK METRICS MIXED UNITS. `volatility` was annualised (x sqrt(252))
     and `sharpe_ratio`, computed two lines below it, was per-period — a factor
     of 15.87 apart in the same returned dict, unlabelled. That is the failure
     `core.py`'s units note exists to prevent, and it is worse in a dict because
     nothing carries the frequency with it. Everything here is labelled, and
     both frequencies are returned where both are useful.

  3. `calculate_var_drawdown` WAS NOT A DRAWDOWN. It computed a one-period
     historical VaR and named it a drawdown limit. VaR is a single-period loss
     quantile; drawdown is peak-to-trough over many periods. Using a daily VaR
     as a drawdown limit understates the thing being limited by an order of
     magnitude. The function is kept, correctly named, and says what it is not.

Also aligned with the rest of this repository: sample standard deviation
(ddof=1), matching `factors.realised_volatility`. finGuard used ddof=0 while
this project used ddof=1, so the same series had two volatilities depending on
which module you asked.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

TRADING_DAYS = 252


class DrawdownError(ValueError):
    """A drawdown metric could not be computed from the inputs given."""


def _equity(values: Sequence[float], *, allow_ruin: bool = False) -> np.ndarray:
    """Validate an equity curve.

    `allow_ruin` permits zeros. A path that reaches zero has a 100% drawdown,
    which is a meaningful answer, and the simulator produces exactly such curves
    when a levered path is wiped out — its own `paths` were being rejected by
    this module's primitives. Negatives stay refused: a ratio against a negative
    equity is meaningless rather than large.

    Ratio-based measures (drawdown, Ulcer) accept ruin because the running peak
    is positive whenever the curve starts positive. `risk_metrics` does not,
    because it differences into per-period returns and a zero denominator there
    is an infinity rather than a fact.
    """
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise DrawdownError(f"values must be 1-D, got shape {arr.shape}")
    if arr.size == 0:
        raise DrawdownError("values is empty")
    if not np.all(np.isfinite(arr)):
        raise DrawdownError("values must be finite")
    if arr[0] <= 0:
        raise DrawdownError("the first value must be positive; there is nothing "
                            "for a drawdown to be measured against otherwise")
    if np.any(arr < 0) or (not allow_ruin and np.any(arr == 0)):
        raise DrawdownError(
            "values must be positive — a drawdown is a ratio against a running "
            "peak, and a non-positive equity makes it meaningless rather than "
            "large")
    return arr


def drawdown_series(values: Sequence[float]) -> np.ndarray:
    """Fractional drawdown from the running peak, at every point.

    Negative or zero throughout: -0.2 is a 20% drawdown. Returned signed, not
    absolute, so that summing or averaging cannot silently turn losses into
    gains.
    """
    arr = _equity(values, allow_ruin=True)
    peak = np.maximum.accumulate(arr)
    return (arr - peak) / peak


def max_drawdown(values: Sequence[float]) -> float:
    """Worst peak-to-trough decline, as a POSITIVE fraction."""
    return float(-np.min(drawdown_series(values)))


def recovery_time(drawdown: float, expected_return: float) -> float:
    """Periods to recover from `drawdown` at a compound rate of `expected_return`.

        t = -log(1 - drawdown) / log(1 + expected_return)

    because recovering a fall of x requires a gain of 1/(1-x) - 1, not x.

    `drawdown` is a positive fraction (0.2 for 20%). Returns inf for a
    non-positive expected return, and for a 100% drawdown — which is not a
    recovery time of "very long" but a statement that there is nothing left to
    compound.
    """
    if not np.isfinite(drawdown) or not np.isfinite(expected_return):
        raise DrawdownError("drawdown and expected_return must be finite")
    if not 0.0 <= drawdown <= 1.0:
        raise DrawdownError(f"drawdown must be in [0, 1], got {drawdown}")
    if expected_return <= 0:
        return math.inf
    if drawdown == 0.0:
        return 0.0
    if drawdown == 1.0:
        return math.inf
    return -math.log1p(-drawdown) / math.log1p(expected_return)


def historical_var(returns: Sequence[float], confidence: float = 0.95) -> float:
    """One-period historical VaR: the loss at the (1 - confidence) quantile.

    Returned as a POSITIVE loss. This is NOT a drawdown and must not be used as
    a drawdown limit, which is what the source function's name invited: VaR is a
    single-period quantile, a drawdown accumulates peak-to-trough over many
    periods, and the second is far larger than the first.
    """
    arr = np.asarray(returns, dtype=float)
    if arr.size == 0:
        raise DrawdownError("returns is empty")
    if not np.all(np.isfinite(arr)):
        raise DrawdownError("returns must be finite")
    if not 0.0 < confidence < 1.0:
        raise DrawdownError(f"confidence must be in (0, 1), got {confidence}")
    # Floored at zero: on an all-gains series the quantile is positive and the
    # negation made this return a NEGATIVE loss, contradicting the docstring
    # directly above it. A VaR of zero is the honest reading — no loss at that
    # confidence — and a negative one invites a sign error downstream.
    return max(0.0, float(-np.percentile(arr, (1.0 - confidence) * 100.0)))


def ulcer_index(values: Sequence[float], *, in_percent: bool = True) -> float:
    """Root-mean-square drawdown — Martin & McCann (1989).

    The published index is in PERCENTAGE POINTS: a series spending its life at a
    5% drawdown has a UI near 5, not 0.05. finGuard returned the fractional
    form, so its numbers could not be compared against any published figure, and
    nothing said so. `in_percent` defaults to the published convention and the
    other is available rather than assumed.
    """
    series = drawdown_series(values)
    rms = float(np.sqrt(np.mean(series ** 2)))
    return rms * 100.0 if in_percent else rms


def throttle(current_drawdown: float, limit: float, *,
             floor: float = 0.0) -> float:
    """Fraction of target risk exposure to keep, given the drawdown so far.

    Linear from 1.0 at no drawdown to `floor` at the limit, and `floor` beyond:

        keep = max(floor, 1 - current_drawdown / limit)

    Deliberately simple, and deliberately NOT the source's version, which added
    the excess drawdown to `allocation[0]` on the undocumented assumption that
    the first asset is the risk-free one, scaled the rest, then renormalised the
    whole vector to sum to 1 — which partly undid the reduction it had just
    made. A 25% drawdown against a 20% limit moved the risky weight from 0.800
    to 0.753 there. This returns a scalar and leaves the caller to apply it,
    because a risk control that silently depends on asset ORDERING is a trap.
    """
    if not np.isfinite(current_drawdown) or current_drawdown < 0:
        raise DrawdownError(
            f"current_drawdown must be a non-negative fraction, got "
            f"{current_drawdown}")
    if not 0.0 < limit <= 1.0:
        raise DrawdownError(f"limit must be in (0, 1], got {limit}")
    if not 0.0 <= floor <= 1.0:
        raise DrawdownError(f"floor must be in [0, 1], got {floor}")
    return max(floor, 1.0 - current_drawdown / limit)


@dataclass(frozen=True)
class RiskMetrics:
    """Risk metrics with their frequency attached to every one of them.

    finGuard returned a dict whose `volatility` was annualised and whose
    `sharpe_ratio`, computed two lines later, was per-period. Both were floats
    named after the quantity and not the unit, so nothing downstream could tell.
    """
    max_drawdown: float
    ulcer_index: float
    volatility_per_period: float
    volatility_annualised: float
    sharpe_per_period: float
    sharpe_annualised: float
    var_95: float
    var_99: float
    n_observations: int
    trading_days: int = TRADING_DAYS
    drawdowns: np.ndarray = field(default_factory=lambda: np.array([]),
                                  repr=False, compare=False)


def risk_metrics(values: Sequence[float], *,
                 trading_days: int = TRADING_DAYS) -> RiskMetrics:
    """Drawdown, volatility, Sharpe and VaR from an equity curve.

    The Sharpe is EXCESS-FREE: it is mean over standard deviation of returns,
    with no risk-free subtraction, and it is named per-period and annualised
    separately so neither can be mistaken for the other. Deflating it for
    multiple testing is `research_integrity.deflated_sharpe_ratio`, which wants
    the PER-PERIOD figure and rejects anything above 1.0 as an obvious units
    error.
    """
    arr = _equity(values)
    if arr.size < 3:
        raise DrawdownError(
            f"need at least 3 values for a variance, got {arr.size}")
    if trading_days <= 0:
        raise DrawdownError(f"trading_days must be positive, got {trading_days}")

    returns = np.diff(arr) / arr[:-1]
    mean = float(np.mean(returns))
    sd = float(np.std(returns, ddof=1))

    # `sd > 0` caught only an exactly-zero deviation, so a constant-growth curve
    # whose sd is float-rounding noise returned a Sharpe of 9.18e12 — unusable,
    # and indistinguishable from a computed figure. Degenerate is now infinite,
    # which is both the true value and unmistakable.
    degenerate = sd <= 1e-12 * max(1.0, abs(mean))
    if degenerate:
        sharpe = 0.0 if mean == 0.0 else math.copysign(math.inf, mean)
    else:
        sharpe = mean / sd
    scale = math.sqrt(trading_days)

    return RiskMetrics(
        max_drawdown=max_drawdown(arr),
        ulcer_index=ulcer_index(arr),
        volatility_per_period=sd,
        volatility_annualised=sd * scale,
        sharpe_per_period=sharpe,
        sharpe_annualised=sharpe * scale,
        var_95=historical_var(returns, 0.95),
        var_99=historical_var(returns, 0.99),
        n_observations=int(returns.size),
        trading_days=trading_days,
        drawdowns=drawdown_series(arr))
