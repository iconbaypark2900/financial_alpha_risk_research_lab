"""Kelly sizing — against Kelly (1956) and Thorp (2006), not against finGuard.

The migrated source shipped with 23 passing tests and a self-assessment calling
its architecture "Perfect". Its portfolio Kelly inverted position signs. So
every expected value here is derived from the published formula by hand, and
each defect found during the migration has a test named after it — because the
useful thing about a fixed bug is the test that stops it coming back, not the
fix.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.portfolio.kelly import (
    HALF_KELLY,
    KellyError,
    fractional,
    growth_rate,
    kelly_fraction,
    portfolio_kelly,
)


# --- single bet: Kelly (1956), f* = (bp - q) / b ---------------------------

@pytest.mark.parametrize("win_prob, ratio, expected", [
    (0.60, 1.0, 0.20),      # (1*0.6 - 0.4) / 1
    (0.50, 2.0, 0.25),      # (2*0.5 - 0.5) / 2
    (0.75, 1.0, 0.50),      # (1*0.75 - 0.25) / 1
    (0.30, 3.0, 0.0666666666666667),   # (3*0.3 - 0.7) / 3 = 0.2/3
])
def test_kelly_fraction_matches_the_published_formula(win_prob, ratio, expected):
    assert kelly_fraction(win_prob, ratio) == pytest.approx(expected)


def test_a_fair_coin_at_even_money_is_not_worth_betting():
    """p = 0.5, b = 1 gives exactly zero. The boundary the formula exists for."""
    assert kelly_fraction(0.5, 1.0) == pytest.approx(0.0)


def test_a_negative_edge_returns_a_negative_fraction():
    """finGuard clamped this to 0, reporting "do not bet" and "bet the other
    side at 40% of capital" as the same number. The sign is information."""
    assert kelly_fraction(0.3, 1.0) == pytest.approx(-0.4)
    assert kelly_fraction(0.4, 1.0) < 0


def test_fractional_kelly_halves_and_keeps_the_sign():
    """Half of a negative edge is a smaller negative edge, not zero.

    This floored at zero — the exact behaviour `kelly_fraction` is criticised
    for two tests above, and the opposite of what `KellyAllocation.scaled()`
    does with the same input, so the two ways to scale a Kelly disagreed.
    """
    assert fractional(0.4) == pytest.approx(0.2)
    assert fractional(0.4, 1.0) == pytest.approx(0.4)
    assert fractional(-0.4) == pytest.approx(-0.2)
    assert HALF_KELLY == 0.5


# --- growth rate: g = p log(1+fb) + q log(1-f) -----------------------------

def test_growth_rate_matches_the_formula_by_hand():
    """p=0.6, b=1, f=0.2: 0.6*log(1.2) + 0.4*log(0.8)."""
    expected = 0.6 * math.log(1.2) + 0.4 * math.log(0.8)
    assert growth_rate(0.2, 0.6, 1.0) == pytest.approx(expected, rel=1e-12)


def test_the_kelly_fraction_maximises_the_growth_rate():
    """The property that makes it the Kelly fraction at all. Checked by search
    rather than assumed: no nearby bet size does better."""
    p, b = 0.6, 1.0
    best = kelly_fraction(p, b)
    at_best = growth_rate(best, p, b)
    for offset in (-0.15, -0.05, -0.01, 0.01, 0.05, 0.15):
        assert growth_rate(best + offset, p, b) < at_best


def test_growth_rate_is_not_nan_when_winning_is_certain():
    """finGuard returned nan for p = 1, because 0 * log(0) is nan rather than
    the 0 the limit gives — and a nan compares False against everything, so it
    does not look like an error, it looks like a bet never worth taking."""
    result = growth_rate(1.0, 1.0, 2.0)
    assert not math.isnan(result)
    assert result == pytest.approx(math.log(3.0))


def test_betting_everything_with_any_chance_of_losing_is_ruin():
    assert growth_rate(1.0, 0.6, 2.0) == -math.inf
    assert growth_rate(1.5, 0.99, 2.0) == -math.inf


# --- portfolio Kelly: w* = inv(S) @ (mu - r*1) -----------------------------

def test_portfolio_kelly_matches_the_closed_form_on_a_diagonal_covariance():
    """Independent assets: w_i = mu_i / var_i, computable by hand.
    0.10/0.04 = 2.5 and 0.05/0.01 = 5.0."""
    allocation = portfolio_kelly([0.10, 0.05], np.diag([0.04, 0.01]))
    assert allocation.weights == pytest.approx([2.5, 5.0])


def test_the_leverage_is_kept_rather_than_normalised_away():
    """The defect that made the source's portfolio Kelly useless.

    Kelly returns an ABSOLUTE exposure. finGuard divided by the sum, so weights
    of [2.5, 5.0] — 750% of capital, wildly levered and worth knowing — came
    back as [0.333, 0.667], indistinguishable from a modest fully-invested
    portfolio.
    """
    allocation = portfolio_kelly([0.10, 0.05], np.diag([0.04, 0.01]))
    assert float(np.sum(allocation.weights)) == pytest.approx(7.5)
    assert allocation.cash_weight == pytest.approx(-6.5)
    assert allocation.is_levered
    assert allocation.gross_leverage == pytest.approx(7.5)


def test_an_unlevered_allocation_leaves_the_remainder_in_cash():
    """Weights summing below 1 mean cash, not a portfolio to be scaled up."""
    allocation = portfolio_kelly([0.02, 0.01], np.diag([0.25, 0.25]))
    assert float(np.sum(allocation.weights)) < 1.0
    assert allocation.cash_weight > 0
    assert not allocation.is_levered
    assert allocation.cash_weight == pytest.approx(1.0 - np.sum(allocation.weights))


def test_negative_weights_are_not_sign_flipped():
    """THE inversion. mu = [-0.10, 0.02], S = diag(0.04, 0.01).

    Kelly says short the first (-2.5) and hold the second (+2.0). The raw
    weights sum to -0.5, and finGuard divided by that sum — flipping every
    sign — then clipped negatives and renormalised, returning [1.0, 0.0]:
    fully long the asset it was told to short, and nothing in the one it was
    told to buy. Wrong on both legs, from one unguarded division.
    """
    allocation = portfolio_kelly([-0.10, 0.02], np.diag([0.04, 0.01]))
    assert allocation.weights == pytest.approx([-2.5, 2.0])
    assert allocation.weights[0] < 0, "the short must stay a short"
    assert allocation.weights[1] > 0, "the long must stay a long"


def test_the_risk_free_rate_is_subtracted():
    """The optimum is inv(S) @ (mu - r*1). finGuard used inv(S) @ mu, and
    carried an unused `self.risk_free_rate = 0.02` — the intent was there and
    the wiring was not."""
    without = portfolio_kelly([0.10, 0.05], np.diag([0.04, 0.01]))
    with_rate = portfolio_kelly([0.10, 0.05], np.diag([0.04, 0.01]),
                                risk_free_rate=0.02)
    assert with_rate.weights == pytest.approx([(0.10 - 0.02) / 0.04,
                                               (0.05 - 0.02) / 0.01])
    assert np.all(with_rate.weights < without.weights)


def test_an_asset_earning_exactly_the_risk_free_rate_gets_no_weight():
    allocation = portfolio_kelly([0.02, 0.06], np.diag([0.04, 0.04]),
                                 risk_free_rate=0.02)
    assert allocation.weights[0] == pytest.approx(0.0)
    assert allocation.weights[1] > 0


def test_correlation_reduces_the_position_in_two_similar_assets():
    """The reason a covariance is used rather than variances: two assets that
    move together are one bet, and Kelly must not size them as two."""
    mu = [0.05, 0.05]
    independent = portfolio_kelly(mu, np.array([[0.04, 0.0], [0.0, 0.04]]))
    correlated = portfolio_kelly(mu, np.array([[0.04, 0.036], [0.036, 0.04]]))
    assert float(np.sum(correlated.weights)) < float(np.sum(independent.weights))


def test_scaling_to_half_kelly_scales_the_weights_and_the_cash():
    full = portfolio_kelly([0.10, 0.05], np.diag([0.04, 0.01]))
    half = full.scaled()
    assert half.weights == pytest.approx(full.weights * 0.5)
    assert half.cash_weight == pytest.approx(1.0 - np.sum(full.weights) * 0.5)


# --- refusals --------------------------------------------------------------

def test_a_singular_covariance_raises_rather_than_returning_equal_weights():
    """finGuard caught LinAlgError and returned equal weights, which turns a
    linear dependence in the data into a plausible-looking portfolio."""
    singular = np.array([[0.04, 0.04], [0.04, 0.04]])
    with pytest.raises(KellyError, match="singular"):
        portfolio_kelly([0.10, 0.05], singular)


def test_an_asymmetric_covariance_is_refused():
    with pytest.raises(KellyError, match="symmetric"):
        portfolio_kelly([0.1, 0.1], np.array([[0.04, 0.01], [0.02, 0.04]]))


@pytest.mark.parametrize("mu, cov", [
    ([0.1, 0.1, 0.1], np.diag([0.04, 0.04])),          # shape mismatch
    ([], np.zeros((0, 0))),                             # empty
    ([float("nan"), 0.1], np.diag([0.04, 0.04])),       # non-finite
])
def test_bad_portfolio_inputs_are_refused(mu, cov):
    with pytest.raises(KellyError):
        portfolio_kelly(mu, cov)


@pytest.mark.parametrize("p, b", [(-0.1, 1.0), (1.1, 1.0), (0.5, 0.0),
                                  (0.5, -1.0), (float("nan"), 1.0)])
def test_bad_single_bet_inputs_are_refused(p, b):
    with pytest.raises(KellyError):
        kelly_fraction(p, b)


# --- found by review, 2026-08-28 -------------------------------------------

def test_a_non_finite_risk_free_rate_is_refused():
    """It was unvalidated, so a NaN rate produced a NaN allocation with no
    error — and a NaN portfolio still looks like a portfolio, which is the
    failure mode `growth_rate`'s docstring calls out one function earlier."""
    with pytest.raises(KellyError, match="risk_free_rate must be finite"):
        portfolio_kelly(MU_OK, COV_OK, risk_free_rate=float("nan"))
    with pytest.raises(KellyError, match="risk_free_rate must be finite"):
        portfolio_kelly(MU_OK, COV_OK, risk_free_rate=float("inf"))


def test_a_symmetric_but_non_psd_covariance_is_refused():
    """Symmetry is necessary and not sufficient.

    [[1e-4, 5e-4], [5e-4, 9e-5]] is symmetric with a negative eigenvalue — not a
    covariance — and solved fine, returning weights [0.473, 0.705] at leverage
    1.18 with no complaint. np.linalg.solve raises only on exact singularity.
    """
    not_psd = np.array([[1e-4, 5e-4], [5e-4, 9e-5]])
    assert np.allclose(not_psd, not_psd.T), "the fixture must be symmetric"
    assert np.min(np.linalg.eigvalsh(not_psd)) < 0
    with pytest.raises(KellyError, match="positive semi-definite"):
        portfolio_kelly(MU_OK, not_psd)


def test_a_valid_covariance_is_still_accepted():
    """The PSD check must not reject real covariances, including singular-ish
    ones that are merely ill-conditioned but genuinely PSD."""
    fine = np.array([[1e-4, 2e-5], [2e-5, 9e-5]])
    assert portfolio_kelly(MU_OK, fine).weights.shape == (2,)


def test_allocations_can_be_compared_and_are_not_ambiguous():
    """Frozen dataclasses holding ndarrays raise on `==` unless the array fields
    are excluded from comparison. RiskMetrics did this and these did not."""
    a = portfolio_kelly(MU_OK, COV_OK)
    b = portfolio_kelly(MU_OK, COV_OK)
    assert a == b                      # would raise ValueError before
    assert a != portfolio_kelly(MU_OK, COV_OK, risk_free_rate=0.0001)


MU_OK = np.array([0.0004, 0.0003])
COV_OK = np.array([[0.0001, 0.00002], [0.00002, 0.00009]])
