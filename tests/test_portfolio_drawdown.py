"""Drawdown and risk metrics — checked against the definitions by hand.

The recovery-time test below is the one that matters most. finGuard's version
used log(1+x) where the definition needs -log(1-x), and understated the wait by
41.5% at a 50% drawdown — always in the direction that flatters the strategy.
Its 23 tests did not notice, because none of them worked an example through the
arithmetic independently.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.portfolio.drawdown import (
    DrawdownError,
    drawdown_series,
    historical_var,
    max_drawdown,
    recovery_time,
    risk_metrics,
    throttle,
    ulcer_index,
)


# --- drawdown itself -------------------------------------------------------

def test_drawdown_series_by_hand():
    """100 -> 120 -> 90 -> 150. Peaks 100,120,120,150.
    Drawdowns 0, 0, (90-120)/120 = -0.25, 0."""
    series = drawdown_series([100.0, 120.0, 90.0, 150.0])
    assert series == pytest.approx([0.0, 0.0, -0.25, 0.0])


def test_max_drawdown_is_a_positive_fraction():
    assert max_drawdown([100.0, 120.0, 90.0, 150.0]) == pytest.approx(0.25)


def test_a_monotonically_rising_curve_never_draws_down():
    assert max_drawdown([100.0, 101.0, 102.0, 103.0]) == pytest.approx(0.0)


def test_the_series_is_signed_so_averages_cannot_hide_losses():
    """Returned negative rather than absolute: an absolute series averages to
    something that looks like a gain."""
    assert np.all(drawdown_series([100.0, 80.0, 90.0]) <= 0)


# --- recovery time: t = -log(1-x) / log(1+r) -------------------------------

def test_recovering_a_fifty_percent_drawdown_needs_a_hundred_percent_gain():
    """The one-line sanity check the source failed. At 10% a year that is
    log(2)/log(1.1) = 7.27 years, and finGuard reported 4.25."""
    assert recovery_time(0.5, 0.10) == pytest.approx(math.log(2) / math.log(1.1))
    assert recovery_time(0.5, 0.10) == pytest.approx(7.2725, abs=1e-4)


@pytest.mark.parametrize("drawdown, rate", [(0.10, 0.10), (0.20, 0.10),
                                            (0.50, 0.10), (0.33, 0.07)])
def test_recovery_time_matches_the_definition(drawdown, rate):
    expected = -math.log(1 - drawdown) / math.log(1 + rate)
    assert recovery_time(drawdown, rate) == pytest.approx(expected, rel=1e-12)


def test_recovery_time_always_exceeds_the_wrong_formula():
    """A regression test named after the bug: log(1+x) is smaller than
    -log(1-x) for every x in (0,1), so the old version could only ever be
    optimistic."""
    for drawdown in (0.05, 0.1, 0.2, 0.3, 0.5, 0.7):
        correct = recovery_time(drawdown, 0.10)
        old = math.log(1 + drawdown) / math.log(1.10)
        assert correct > old


def test_a_total_loss_never_recovers():
    assert recovery_time(1.0, 0.10) == math.inf


def test_no_drawdown_takes_no_time():
    assert recovery_time(0.0, 0.10) == 0.0


def test_a_non_positive_expected_return_never_recovers():
    assert recovery_time(0.2, 0.0) == math.inf
    assert recovery_time(0.2, -0.05) == math.inf


# --- VaR, correctly named --------------------------------------------------

def test_historical_var_is_the_loss_quantile():
    """100 returns from -0.50 to 0.49 in steps of 0.01; the 5th percentile is
    a loss of about 0.455, returned positive."""
    returns = np.arange(-50, 50) / 100.0
    assert historical_var(returns, 0.95) == pytest.approx(
        -np.percentile(returns, 5.0))
    assert historical_var(returns, 0.95) > 0


def test_a_higher_confidence_gives_a_larger_var():
    rng = np.random.default_rng(0)
    returns = rng.normal(0.0, 0.01, 5000)
    assert historical_var(returns, 0.99) > historical_var(returns, 0.95)


def test_var_is_far_smaller_than_the_drawdown_it_was_used_to_limit():
    """Why the source's name was the bug. A one-period VaR and a peak-to-trough
    drawdown are different quantities, and using the first as a limit on the
    second understates it by an order of magnitude."""
    rng = np.random.default_rng(1)
    returns = rng.normal(-0.001, 0.01, 1000)
    equity = 100 * np.cumprod(1 + returns)
    assert historical_var(returns, 0.95) < max_drawdown(equity) / 5


# --- Ulcer index -----------------------------------------------------------

def test_ulcer_index_of_a_flat_series_at_a_constant_drawdown():
    """100 then 95 held: drawdowns 0 and -0.05 four times.
    RMS = sqrt((0 + 4*0.0025)/5) = sqrt(0.002) = 0.0447 -> 4.47 in percent."""
    values = [100.0, 95.0, 95.0, 95.0, 95.0]
    assert ulcer_index(values, in_percent=False) == pytest.approx(
        math.sqrt(0.002), rel=1e-12)
    assert ulcer_index(values) == pytest.approx(math.sqrt(0.002) * 100)


def test_ulcer_index_defaults_to_the_published_percentage_convention():
    """Martin & McCann express it in percentage points. finGuard returned the
    fractional form without saying so, and its numbers matched no published
    figure."""
    values = [100.0, 95.0, 95.0, 95.0, 95.0]
    assert ulcer_index(values) == pytest.approx(
        ulcer_index(values, in_percent=False) * 100)
    assert ulcer_index(values) > 1.0


def test_a_curve_that_only_rises_has_no_ulcer():
    assert ulcer_index([100.0, 110.0, 120.0]) == pytest.approx(0.0)


# --- throttle --------------------------------------------------------------

def test_throttle_is_linear_to_the_limit():
    assert throttle(0.0, 0.20) == pytest.approx(1.0)
    assert throttle(0.10, 0.20) == pytest.approx(0.5)
    assert throttle(0.20, 0.20) == pytest.approx(0.0)


def test_throttle_does_not_go_negative_past_the_limit():
    assert throttle(0.50, 0.20) == 0.0


def test_throttle_actually_reduces_risk_unlike_the_version_it_replaces():
    """finGuard's control moved the risky weight from 0.800 to 0.753 at a 25%
    drawdown against a 20% limit, because it renormalised the vector after
    reducing it and partly undid its own adjustment."""
    assert throttle(0.25, 0.20) == 0.0
    assert 0.800 * throttle(0.25, 0.20) < 0.753


def test_a_floor_keeps_a_residual_position():
    assert throttle(0.50, 0.20, floor=0.25) == pytest.approx(0.25)


# --- risk metrics carry their units ----------------------------------------

@pytest.fixture()
def curve() -> np.ndarray:
    rng = np.random.default_rng(0)
    return 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, 500)))


def test_both_frequencies_are_reported_and_named(curve):
    """The source returned an annualised volatility beside a per-period Sharpe,
    both as bare floats named after the quantity rather than the unit — a factor
    of sqrt(252) apart in one dict, with nothing downstream able to tell."""
    m = risk_metrics(curve)
    assert m.volatility_annualised == pytest.approx(
        m.volatility_per_period * math.sqrt(252))
    assert m.sharpe_annualised == pytest.approx(
        m.sharpe_per_period * math.sqrt(252))


def test_the_per_period_sharpe_is_what_the_deflation_will_accept(curve):
    """The join with the V0 controls: deflated_sharpe_ratio rejects a
    per-period Sharpe above 1.0 as an obvious units error."""
    from src.research_integrity import deflated_sharpe_ratio

    m = risk_metrics(curve)
    assert abs(m.sharpe_per_period) <= 1.0
    deflated_sharpe_ratio(observed_sharpe=m.sharpe_per_period, n_trials=10,
                          sample_length=m.n_observations, skewness=0.0,
                          kurtosis=3.0, var_trials=1e-4)


def test_volatility_uses_the_sample_correction_like_the_rest_of_the_repo(curve):
    """finGuard used ddof=0 while factors.realised_volatility uses ddof=1, so
    one series had two volatilities depending on which module you asked."""
    m = risk_metrics(curve)
    returns = np.diff(curve) / curve[:-1]
    assert m.volatility_per_period == pytest.approx(np.std(returns, ddof=1))
    assert m.volatility_per_period != pytest.approx(np.std(returns, ddof=0),
                                                    rel=1e-9)


# --- refusals --------------------------------------------------------------

@pytest.mark.parametrize("bad", [[], [100.0, -5.0], [100.0, 0.0],
                                 [100.0, float("nan")]])
def test_bad_equity_curves_are_refused(bad):
    with pytest.raises(DrawdownError):
        drawdown_series(bad)


def test_too_short_a_curve_for_a_variance_is_refused():
    with pytest.raises(DrawdownError, match="at least 3"):
        risk_metrics([100.0, 101.0])


@pytest.mark.parametrize("dd, limit", [(-0.1, 0.2), (0.1, 0.0), (0.1, 1.5)])
def test_bad_throttle_inputs_are_refused(dd, limit):
    with pytest.raises(DrawdownError):
        throttle(dd, limit)


def test_a_drawdown_outside_zero_to_one_is_refused():
    with pytest.raises(DrawdownError):
        recovery_time(1.5, 0.1)
    with pytest.raises(DrawdownError):
        recovery_time(-0.1, 0.1)
