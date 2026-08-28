"""Kelly sizing — PRD 04 §5.5 (V1), migrated from `migration_inbox/finGuard/`.

WHAT WAS WRONG WITH THE SOURCE, AND WHY IT MATTERS THAT IT PASSED ITS TESTS

finGuard's `KellyCriterion` arrived with 23 passing tests and a `todo.md` rating
its own gaps as LOW. The single-bet formula was correct. The portfolio version
was wrong in three ways at once, and one of them inverts positions:

  1. IT DISCARDED THE LEVERAGE. `w = inv(S) @ mu` was normalised to sum to 1.
     Kelly's answer is an ABSOLUTE exposure — if the weights sum to 0.3 you hold
     30% and the rest in cash. Normalising forces full investment and throws
     away the only quantity Kelly computes. It converts a sizing rule into a
     direction, and a sizing rule is the whole reason to use Kelly.

  2. IT INVERTED SIGNS WHEN THE WEIGHTS SUMMED NEGATIVE. Dividing by a negative
     sum flips every weight. For mu = [-0.10, 0.02] and S = diag(0.04, 0.01),
     Kelly says short the first (-2.5) and hold the second (+2.0); finGuard
     returned [1.0, 0.0] — fully long the asset it was told to short, and
     nothing in the one it was told to buy. Maximally wrong on both legs, from
     one unguarded division.

  3. IT IGNORED THE RISK-FREE RATE. The optimum is inv(S) @ (mu - r*1), not
     inv(S) @ mu. The class even carried `self.risk_free_rate = 0.02`, set in
     __init__ and read by nothing — the intent was there and the wiring was not.

None of the 23 tests caught any of it. They exercised the functions rather than
checking them against the formula, which is the difference this project keeps
running into: an invariant test constrains the shape of an answer, never its
correctness.

SOURCES

  Kelly, J. L. (1956), "A New Interpretation of Information Rate", Bell System
  Technical Journal 35(4) — the single-bet criterion, f* = (bp - q) / b.

  Thorp, E. O. (2006), "The Kelly Criterion in Blackjack, Sports Betting and the
  Stock Market", Handbook of Asset and Liability Management — §7 for the
  continuous/Gaussian portfolio case, w* = inv(S) @ (mu - r*1), and the standing
  warning that full Kelly is far too volatile to trade in practice.

WHY THERE IS NO LONG-ONLY OPTION

Clipping negative weights and renormalising is not the long-only Kelly solution;
it is a different portfolio with no optimality property, and it is where the
sign inversion above came from. The constrained problem is a quadratic program
and needs a QP solver this project does not depend on. So it is absent rather
than approximated — the same call FR-14 makes about naive k-fold: the wrong
path is not offered with a flag, because the flag is the path people take when
the honest numbers disappoint.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


class KellyError(ValueError):
    """Kelly could not be computed from the inputs given."""


# Thorp's standing recommendation, and the reason `fractional` exists at all.
HALF_KELLY = 0.5


def kelly_fraction(win_prob: float, win_loss_ratio: float) -> float:
    """Single-bet Kelly: f* = (b*p - q) / b, with b the win/loss ratio.

    Returned RAW and unclamped. A negative value is information — the bet has
    negative edge and the correct size is zero, or the other side — and finGuard
    clamped it to 0, which reports "do not bet" and "bet against this at 40% of
    capital" as the same number. Cap deliberately with `fractional` or your own
    policy, at the point where the policy lives.

    Raises:
        KellyError: on a probability outside [0, 1] or a non-positive ratio.
    """
    if not np.isfinite(win_prob) or not np.isfinite(win_loss_ratio):
        raise KellyError("win_prob and win_loss_ratio must be finite")
    if not 0.0 <= win_prob <= 1.0:
        raise KellyError(f"win_prob must be in [0, 1], got {win_prob}")
    if win_loss_ratio <= 0:
        raise KellyError(f"win_loss_ratio must be positive, got {win_loss_ratio}")

    return (win_loss_ratio * win_prob - (1.0 - win_prob)) / win_loss_ratio


def fractional(full_kelly: float, fraction: float = HALF_KELLY) -> float:
    """Scale a Kelly fraction, and floor it at zero.

    Half-Kelly is the standard practice, not a compromise: Kelly maximises the
    long-run growth rate and is brutally volatile on the way — the growth curve
    is flat near the optimum, so half the bet gives about three quarters of the
    growth for a quarter of the variance. Thorp (2006) says so plainly.
    """
    if not 0.0 < fraction <= 1.0:
        raise KellyError(f"fraction must be in (0, 1], got {fraction}")
    # The sign is PRESERVED. This floored at zero, which is the behaviour
    # `kelly_fraction` above criticises finGuard for — and `KellyAllocation
    # .scaled()`, the other way to scale a Kelly, preserved it, so the two
    # disagreed about what half of a negative edge means.
    return full_kelly * fraction


def growth_rate(bet_fraction: float, win_prob: float,
                win_loss_ratio: float) -> float:
    """Expected log growth per bet: g = p*log(1 + f*b) + q*log(1 - f).

    Returns -inf where the bet can wipe out the bankroll (f >= 1 with any chance
    of losing), which is the true answer and the one that makes the Kelly
    optimum a maximum at all.

    finGuard returned `nan` here whenever p = 1, because 0 * log(0) is nan in
    floating point rather than the 0 the limit gives. A nan propagates into
    every comparison silently as False, so a nan growth rate does not look like
    an error — it looks like a bet that is never the best one.
    """
    if not 0.0 <= win_prob <= 1.0:
        raise KellyError(f"win_prob must be in [0, 1], got {win_prob}")
    if win_loss_ratio <= 0:
        raise KellyError(f"win_loss_ratio must be positive, got {win_loss_ratio}")
    if bet_fraction < 0:
        raise KellyError(f"bet_fraction must be non-negative, got {bet_fraction}")

    loss_prob = 1.0 - win_prob
    win_term = win_prob * math.log1p(bet_fraction * win_loss_ratio) if win_prob > 0 else 0.0

    if loss_prob == 0.0:
        return win_term                       # the limit, not 0 * -inf
    if bet_fraction >= 1.0:
        return -math.inf                      # ruin is possible; growth is -inf
    return win_term + loss_prob * math.log1p(-bet_fraction)


@dataclass(frozen=True)
class KellyAllocation:
    """A Kelly portfolio, with the leverage kept rather than normalised away.

    `weights` are absolute fractions of capital. They do NOT sum to 1 and must
    not be made to: `cash_weight` is the remainder, and it is negative exactly
    when the allocation is levered.
    """
    weights: np.ndarray = field(compare=False)
    cash_weight: float
    gross_leverage: float
    risk_free_rate: float

    @property
    def is_levered(self) -> bool:
        return self.cash_weight < 0.0

    def scaled(self, fraction: float = HALF_KELLY) -> "KellyAllocation":
        """The same allocation at a fraction of full Kelly."""
        if not 0.0 < fraction <= 1.0:
            raise KellyError(f"fraction must be in (0, 1], got {fraction}")
        weights = self.weights * fraction
        return KellyAllocation(
            weights=weights, cash_weight=1.0 - float(np.sum(weights)),
            gross_leverage=float(np.sum(np.abs(weights))),
            risk_free_rate=self.risk_free_rate)


def portfolio_kelly(expected_returns, covariance, *,
                    risk_free_rate: float = 0.0) -> KellyAllocation:
    """Gaussian Kelly portfolio: w* = inv(S) @ (mu - r*1).

    Expected returns, the covariance and the risk-free rate must all be at the
    SAME frequency. Mixing an annual mu with a daily covariance overstates the
    optimal position by roughly the number of periods in a year, and the result
    still looks like a portfolio — the same units failure `core.py` exists to
    prevent, one module over.

    The weights are absolute and are not normalised. `cash_weight` carries the
    remainder, so an allocation summing to 0.3 means 30% invested and 70% in
    the risk-free asset rather than a fully-invested portfolio.

    Raises:
        KellyError: on shape mismatch, non-finite input, or a singular
            covariance — which is NOT silently replaced with equal weights, as
            the source did. A singular covariance means the assets are linearly
            dependent and the optimum is undefined; answering anyway hides a
            data problem behind a plausible portfolio.
    """
    mu = np.asarray(expected_returns, dtype=float)
    sigma = np.asarray(covariance, dtype=float)

    if mu.ndim != 1:
        raise KellyError(f"expected_returns must be 1-D, got shape {mu.shape}")
    if sigma.ndim != 2 or sigma.shape[0] != sigma.shape[1]:
        raise KellyError(f"covariance must be square, got shape {sigma.shape}")
    if mu.size != sigma.shape[0]:
        raise KellyError(
            f"expected_returns has {mu.size} assets, covariance has "
            f"{sigma.shape[0]}")
    if mu.size == 0:
        raise KellyError("expected_returns is empty")
    if not np.all(np.isfinite(mu)) or not np.all(np.isfinite(sigma)):
        raise KellyError("expected_returns and covariance must be finite")
    if not np.allclose(sigma, sigma.T, rtol=1e-9, atol=1e-12):
        raise KellyError("covariance must be symmetric")
    if not math.isfinite(risk_free_rate):
        raise KellyError(
            f"risk_free_rate must be finite, got {risk_free_rate} — an unchecked "
            "NaN here produces a NaN allocation that still looks like a portfolio")

    # Symmetry is necessary and not sufficient. A symmetric matrix with a
    # negative eigenvalue is not a covariance, solves without complaint, and
    # returns a plausible-looking portfolio: [[1e-4, 5e-4], [5e-4, 9e-5]] gave
    # weights [0.473, 0.705] at leverage 1.18. np.linalg.solve raises only on
    # EXACT singularity, so the docstring's argument below — that answering
    # anyway hides a data problem behind a plausible portfolio — applies here at
    # least as strongly.
    eigenvalues = np.linalg.eigvalsh(sigma)
    tolerance = -1e-10 * max(1.0, float(np.max(np.abs(eigenvalues))))
    if float(np.min(eigenvalues)) < tolerance:
        raise KellyError(
            f"covariance is not positive semi-definite (smallest eigenvalue "
            f"{float(np.min(eigenvalues)):.3e}), so it is not a covariance "
            "matrix and the Kelly optimum is undefined")

    excess = mu - risk_free_rate
    try:
        weights = np.linalg.solve(sigma, excess)
    except np.linalg.LinAlgError as exc:
        raise KellyError(
            "covariance is singular, so the Kelly optimum is undefined — the "
            "assets are linearly dependent. finGuard fell back to equal weights "
            "here, which turns a data problem into a portfolio."
        ) from exc

    return KellyAllocation(
        weights=weights,
        cash_weight=1.0 - float(np.sum(weights)),
        gross_leverage=float(np.sum(np.abs(weights))),
        risk_free_rate=risk_free_rate)
