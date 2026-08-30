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
    MAX_CONDITION_NUMBER,
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
    """The PSD check must not reject real covariances.

    The docstring here claimed this fixture covered "singular-ish ones that are
    merely ill-conditioned but genuinely PSD". Its condition number is 1.55, so
    it never did, and the claim mattered once there was a conditioning bound to
    be wrong about. The ill-conditioned case is
    `test_an_ill_conditioned_but_estimable_covariance_is_still_accepted` below,
    which states the condition number it is pinning. The assertion is unchanged.
    """
    fine = np.array([[1e-4, 2e-5], [2e-5, 9e-5]])
    assert portfolio_kelly(MU_OK, fine).weights.shape == (2,)


def test_allocations_can_be_compared_and_are_not_ambiguous():
    """Frozen dataclasses holding ndarrays raise on `==` unless the array fields
    are excluded from comparison. RiskMetrics did this and these did not."""
    a = portfolio_kelly(MU_OK, COV_OK)
    b = portfolio_kelly(MU_OK, COV_OK)
    assert a == b                      # would raise ValueError before
    assert a != portfolio_kelly(MU_OK, COV_OK, risk_free_rate=0.0001)


# --- found by review, 2026-08-30 -------------------------------------------

def test_a_rank_deficient_sample_covariance_is_refused():
    """THE way a covariance actually goes singular: two assets that move alike.

    `x` and `x + 1e-9 noise` give a sample covariance with eigenvalues
    [4.6e-19, 2.06e-4] — rank 1 to fifteen digits. It was ACCEPTED and returned
    weights [+1.05e14, -1.05e14] at 2.1e14 gross leverage, the long/short pair
    the degenerate direction makes look free. Nothing caught it: the matrix is
    positive definite on paper so the PSD test passes, and `np.linalg.solve`
    raises only on EXACT singularity, which this is not.
    """
    rng = np.random.default_rng(0)
    x = rng.normal(0.0, 0.01, 500)
    sigma = np.cov([x, x + rng.normal(0.0, 1e-9, 500)])
    assert np.min(np.linalg.eigvalsh(sigma)) > 0, (
        "the fixture must be PSD — the refusal has to come from the "
        "conditioning, not from a negative eigenvalue")

    with pytest.raises(KellyError, match="singular"):
        portfolio_kelly([0.0005, 0.0004], sigma)


@pytest.mark.parametrize("scale", [1e-8, 1e-6, 1e-4, 1e-2, 1.0, 1e4])
def test_the_psd_tolerance_is_relative_to_the_eigenvalue_scale(scale):
    """The tolerance was `-1e-10 * max(1.0, max|eig|)`, and that `max(1.0, ...)`
    floor pinned it to an ABSOLUTE -1e-10 for every matrix whose eigenvalues sit
    below 1 — which is every covariance of returns.

    So one matrix got two answers depending on the units it was quoted in:
    refused at scale 1, accepted at 1e-4 where its smallest eigenvalue is
    -5.0e-11. Whether a matrix is a covariance is a property of the matrix, not
    of whether its entries are daily or annual.
    """
    non_psd = np.array([[1.0, 1.0000005], [1.0000005, 1.0]]) * scale
    assert np.min(np.linalg.eigvalsh(non_psd)) < 0, "the fixture must be non-PSD"

    with pytest.raises(KellyError, match="positive semi-definite"):
        portfolio_kelly([0.0005, 0.0004], non_psd)


@pytest.mark.parametrize("scale", [1e-8, 1e-6, 1e-4, 1e-2, 1.0, 1e4])
def test_a_sound_covariance_is_accepted_at_every_scale(scale):
    """The other direction, and what stops the two refusals above from being
    answered with "refuse more": a well-conditioned PSD matrix has to survive
    being quoted in any units, including the 1e-8 of squared basis points."""
    sound = np.array([[4.0, 1.0], [1.0, 2.0]]) * scale
    assert np.all(np.isfinite(portfolio_kelly([0.0005, 0.0004], sound).weights))


def test_an_ill_conditioned_but_estimable_covariance_is_still_accepted():
    """The conditioning threshold has to separate two regimes, not clear one case.

    A covariance at 1e6 must be answered however unattractive the answer is: a
    control that fires on ordinary estimated data is not a control. 1e6 is
    nearly two orders below the limit and above anything an N/T <= 0.95
    estimate reaches, so it is accepted by both of the arguments the limit is
    made of — see `test_the_conditioning_limit_is_a_convention_in_a_wide_band`.

    This docstring used to place the choice by claiming an estimated covariance
    "reaches a condition number of only ~3.6e5 at N/T = 0.996". That is
    measurably false; the same test measures it. Deleted rather than softened,
    and the assertion below is unchanged.
    """
    angle = 0.7
    rotation = np.array([[math.cos(angle), -math.sin(angle)],
                         [math.sin(angle), math.cos(angle)]])
    ill_conditioned = rotation @ np.diag([1e-4, 1e-10]) @ rotation.T
    assert np.linalg.cond(ill_conditioned) == pytest.approx(1e6, rel=1e-6)

    assert np.all(np.isfinite(
        portfolio_kelly([0.0005, 0.0004], ill_conditioned).weights))


def test_an_all_zero_covariance_is_refused_for_the_right_reason():
    """Every asset riskless is not a sizing problem with a large answer, it is
    an unbounded one.

    It was refused, by reaching `np.linalg.solve` and coming back as
    LinAlgError, and then reported as "the assets are linearly dependent" — true
    but not the point. Nothing here has any risk to size against, and the fix is
    to move the riskless asset into `risk_free_rate`, not to drop a column.
    """
    with pytest.raises(KellyError, match="riskless"):
        portfolio_kelly([0.0005, 0.0004], np.zeros((2, 2)))


MU_OK = np.array([0.0004, 0.0003])
COV_OK = np.array([[0.0001, 0.00002], [0.00002, 0.00009]])


# --- the prose has to be as checkable as the formulas -----------------------

def test_the_portfolio_modules_cite_paths_that_exist():
    """A source citation nobody executes is a claim, and claims here rot.

    Both modules said they were migrated from `migration_inbox/finGuard/`.
    That directory was retired to `docs/superseded/finGuard/` on 2026-08-28
    and `tests/test_requirements_map.py::test_the_migration_inbox_is_gone`
    asserts it must never come back — so the two statements in the tree
    disagreed, and the one a reader of `src/portfolio/` meets first was the
    wrong one.

    Resolved against the filesystem rather than matched against the old
    string, so this catches the NEXT path that moves as well as the one that
    already did.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    dangling = []
    for name in ("src/portfolio/__init__.py", "src/portfolio/kelly.py"):
        source = (root / name).read_text(encoding="utf-8")
        for span in re.findall(r"`([^`\n]+)`", source):
            if "/" in span and re.fullmatch(r"[\w.\-/]+", span):
                if not (root / span).exists():
                    dangling.append(f"{name} cites `{span}`")

    assert not dangling, (
        f"{dangling} — the cited path is not in the tree. finGuard now lives "
        "at docs/superseded/finGuard/.")


# --- MAX_CONDITION_NUMBER's justification, run rather than quoted -----------
#
# The comment above the constant used to end "ten orders of magnitude separate
# ordinary estimation from rank deficiency, and 6.7e7 sits in the empty middle
# of them". Written down as an assertion, that claim fails: four of forty
# full-rank draws land above the limit. These two tests produce every figure
# the replacement comment states, so the next reader can check it in a second
# rather than take it.

def test_the_conditioning_limit_is_a_convention_in_a_wide_band():
    """The empirical half: where estimated covariances actually sit.

    `np.cov` removes a degree of freedom, so N = T - 1 is the LAST full-rank
    case — at T = 250 that is N/T = 0.996, the exact configuration the old
    comment quoted 3.6e5 for. The smallest eigenvalue there is heavy-tailed,
    so the condition number is not a ceiling but a distribution, and this limit
    cuts through the middle of it. That is not a flaw in the limit; it is the
    reason the limit cannot be presented as a measured boundary.

    The half that does survive is the lower bound, and it is the one that
    matters for not firing on real data: at N/T = 0.95 nothing comes within
    four orders of magnitude.
    """
    T = 250

    def sample_cov(n_assets: int, seed: int) -> np.ndarray:
        return np.cov(np.random.default_rng(seed).standard_normal((n_assets, T)))

    edge = np.array([np.linalg.cond(sample_cov(T - 1, s)) for s in range(40)])
    over = int((edge > MAX_CONDITION_NUMBER).sum())
    assert np.median(edge) < MAX_CONDITION_NUMBER < edge.max(), (
        f"the limit must lie INSIDE this distribution for the point to hold: "
        f"median {np.median(edge):.3e}, max {edge.max():.3e}")
    assert over >= 2, f"only {over} of 40 draws exceed the limit"

    # And the draws above it are full rank, which is what makes the middle
    # occupied rather than merely noisy: this is not a rank-deficient matrix
    # being caught, it is an estimate the researcher was entitled to form.
    worst = sample_cov(T - 1, int(np.argmax(edge)))
    assert np.linalg.matrix_rank(worst) == T - 1
    assert np.linalg.cond(worst) > MAX_CONDITION_NUMBER

    ordinary = np.array([np.linalg.cond(sample_cov(int(0.95 * T), s))
                         for s in range(40)])
    assert ordinary.max() < 1e4 < MAX_CONDITION_NUMBER, (
        f"the limit fires on ordinary estimation: {ordinary.max():.3e}")


def test_precision_is_not_what_sets_the_conditioning_limit():
    """The derivable half, and the reason it does not pick 6.7e7 on its own.

    A solve loses about log10(cond) of a float64's ~15.7 significant digits.
    Measured against an EXACT rational solve of the same system — not against
    another float64 answer, which would measure agreement rather than accuracy
    — the weights still carry about eight digits at the limit and four at 1e13.
    A weight quoted to the basis point needs four, so precision alone licenses
    a limit five orders of magnitude looser than this one.

    What actually goes wrong first is measured alongside: gross leverage grows
    in exact proportion to the condition number, so at the limit the answer is
    eight good digits of a position nobody can hold. The refusal is economic.
    """
    from fractions import Fraction

    angle = 0.7
    rotation = np.array([[math.cos(angle), -math.sin(angle)],
                         [math.sin(angle), math.cos(angle)]])
    mu = np.array([0.0005, 0.0004])

    def probe(target_condition: float) -> tuple[float, float, float]:
        sigma = rotation @ np.diag([1e-4, 1e-4 / target_condition]) @ rotation.T
        sigma = 0.5 * (sigma + sigma.T)
        weights = np.linalg.solve(sigma, mu)
        s = [[Fraction(sigma[i][j]) for j in range(2)] for i in range(2)]
        b = [Fraction(mu[0]), Fraction(mu[1])]
        det = s[0][0] * s[1][1] - s[0][1] * s[1][0]
        exact = np.array([float((b[0] * s[1][1] - s[0][1] * b[1]) / det),
                          float((s[0][0] * b[1] - b[0] * s[1][0]) / det)])
        error = float(np.linalg.norm(weights - exact) / np.linalg.norm(exact))
        return np.linalg.cond(sigma), error, float(np.abs(weights).sum())

    cond_mid, err_mid, lev_mid = probe(1e6)
    cond_lim, err_lim, lev_lim = probe(MAX_CONDITION_NUMBER)
    _, err_1e13, _ = probe(1e13)
    _, err_none, lev_none = probe(1.0 / np.finfo(float).eps)

    # Digits are genuinely being lost on the way up — without this the two
    # bounds below could both hold on a solve that was simply exact.
    assert err_mid < err_lim < err_1e13 < err_none

    # Eight digits at the limit: enough that precision is not the binding
    # constraint, and not so many that nothing is being lost.
    assert 1e-12 < err_lim < 1e-7, err_lim
    # Four still survive at 1e13, which is what a weight is quoted to.
    assert 1e-7 < err_1e13 < 1e-3, err_1e13
    # And essentially none at 1/eps, which is why 1/eps cannot be the line.
    assert err_none > 1e-3, err_none

    # Leverage tracks the condition number one for one. This is the quantity
    # that makes the answer unusable while the arithmetic is still fine.
    assert lev_lim > 1e6
    assert lev_lim / lev_mid == pytest.approx(cond_lim / cond_mid, rel=1e-3)
    assert lev_none > 1e14
