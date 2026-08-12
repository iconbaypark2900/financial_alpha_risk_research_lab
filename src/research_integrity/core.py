"""Research integrity core: deflation and minimum backtest length.

Implements PRD 04 §5.2 (FR-09, FR-13).

UNITS — read this before using anything here. Every Sharpe ratio and variance
in this module is **per-period, at the same frequency as `sample_length`**. If
`sample_length` counts daily returns, `observed_sharpe` is a DAILY Sharpe, not
an annualised one. De-annualise before calling: a Sharpe of 2.5 annualised on
250 trading days per year is `2.5 / sqrt(250)` here, and an annualised variance
across trials of 1/2 is `0.5 / 250`.

This is not pedantry. Mixing an annualised Sharpe with a daily sample length
silently answers a different question than the one asked, and answering
mis-scaled questions confidently is the failure this module exists to prevent.

PROVENANCE OF THE FORMULAS

Both were verified line by line against the published papers, and both were
wrong before that check. The previous version used approximations the sources
do not contain, which the spec had explicitly forbidden. Every invariant test
still passed throughout, because a wrong constant in a right-shaped formula
violates no invariant — it stays in [0, 1], stays monotonic, still
discriminates. Only the paper catches it.

  DSR      Bailey & López de Prado (2014), "The Deflated Sharpe Ratio",
           Journal of Portfolio Management. Equations (1), (2) and (5).
  MinBTL   Bailey, Borwein, López de Prado & Zhu (2014), "Pseudo-Mathematics
           and Financial Charlatanism", Notices of the AMS 61(5). Theorem 3.1.

Both papers' worked examples are pinned as tests so the formulas cannot drift
back: DSR reproduces the paper's SR_0 = 0.1132 and DSR = 0.9004, and MinBTL
reproduces "45 independent trials need 5 years at an annualised Sharpe of 1".
"""
from __future__ import annotations

import json
import math
from statistics import NormalDist as _NormalDist

# Euler-Mascheroni constant, as used in Eq. (5) of the DSR paper and Eq. (3.1)
# of the MinBTL paper. Both print it as 0.5772.
EULER_MASCHERONI = 0.5772156649015329

# A per-period Sharpe above this is almost certainly an annualised figure passed
# by mistake: a daily Sharpe of 1.0 is an annualised ~15.8.
MAX_PLAUSIBLE_PER_PERIOD_SHARPE = 1.0


class NormalDistribution:
    """Standard normal CDF and inverse CDF.

    Backed by statistics.NormalDist. A hand-rolled Newton iteration was here and
    diverged: ppf(0.95) returned -32.81 instead of +1.6449, sign inverted and
    magnitude wrong by a factor of twenty. Everything below depends on these two
    functions, and the error propagated into every result while the monotonicity
    and bounds invariants still held. Use the library.
    """

    @staticmethod
    def cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def ppf(p: float) -> float:
        if p <= 0 or p >= 1:
            raise ValueError("p must be in (0, 1)")
        return _NormalDist().inv_cdf(p)


def _check_numeric(**values: float) -> None:
    for name, val in values.items():
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise TypeError(f"{name} must be a numeric type, got {type(val).__name__}")
        if not math.isfinite(val):
            raise ValueError(f"{name} must be a finite number")


def expected_max_sharpe(n_trials: int, var_trials: float = 1.0,
                        mean_trials: float = 0.0) -> float:
    """Expected maximum Sharpe across `n_trials` independent trials.

    DSR paper Eq. (1) / (5) — the extreme-value result the whole method rests
    on. With N independent trials whose Sharpe estimates have mean E[SR] and
    variance V[SR], the expected best is

        E[max] ~= E[SR] + sqrt(V[SR]) * ( (1-g) Z^-1[1 - 1/N]
                                          + g   Z^-1[1 - (1/N) e^-1] )

    where g is the Euler-Mascheroni constant. This is why a Sharpe of 2 is
    unremarkable after a thousand trials on pure noise.

    N = 1 is outside the paper's N >> 1 regime, and Z^-1[1 - 1/1] = Z^-1[0] is
    undefined. With a single trial there is no selection to correct for, so the
    expected maximum is just the mean. That convention is ours, not the paper's.
    """
    _check_numeric(var_trials=var_trials, mean_trials=mean_trials)
    if isinstance(n_trials, bool) or not isinstance(n_trials, (int, float)):
        raise TypeError(f"n_trials must be a numeric type, got {type(n_trials).__name__}")
    if not math.isfinite(n_trials):
        raise ValueError("n_trials must be a finite number")
    if n_trials <= 0:
        raise ValueError("n_trials must be greater than 0")
    if var_trials < 0:
        raise ValueError("var_trials must be non-negative (it is a variance)")

    if n_trials == 1:
        return float(mean_trials)

    g = EULER_MASCHERONI
    z1 = NormalDistribution.ppf(1.0 - 1.0 / n_trials)
    z2 = NormalDistribution.ppf(1.0 - (1.0 / n_trials) * math.exp(-1.0))
    return float(mean_trials + math.sqrt(var_trials) * ((1.0 - g) * z1 + g * z2))


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    sample_length: int,
    skewness: float,
    kurtosis: float,
    var_trials: float,
) -> float:
    """Deflated Sharpe Ratio — DSR paper Eq. (2), implemented as published.

        DSR = Z[ (SR - SR_0) sqrt(T - 1)
                 / sqrt(1 - g3 SR + ((g4 - 1)/4) SR^2) ]

    where SR_0 = sqrt(V[SR]) ( (1-g) Z^-1[1 - 1/N] + g Z^-1[1 - (1/N)e^-1] ).

    It answers: given that I ran N trials, what is the probability that this
    strategy's true Sharpe exceeds what selection bias alone would produce?

    Args:
        observed_sharpe: per-period Sharpe of the SELECTED strategy (SR).
        n_trials: number of INDEPENDENT trials searched (N).
        sample_length: number of returns in the sample (T).
        skewness: skewness of the returns (g3).
        kurtosis: kurtosis of the returns (g4) — NOT excess kurtosis. A normal
            sample has g4 = 3, which is what the (g4 - 1)/4 term expects.
        var_trials: variance of the Sharpe estimates ACROSS the N trials
            (V[{SR_n}]), per-period. This is a required input of the published
            formula, not an optional refinement: SR_0 cannot be computed without
            it. If you did not record the trial Sharpes you cannot compute a
            DSR — estimate it honestly or do not report one.

    Returns:
        A probability in [0, 1].

    Raises:
        ValueError: on non-finite input, n_trials <= 0, sample_length <= 1,
            negative var_trials, or an implausible per-period Sharpe.
        TypeError: on non-numeric input.
    """
    _check_numeric(observed_sharpe=observed_sharpe, skewness=skewness,
                   kurtosis=kurtosis, var_trials=var_trials)
    for name, val in (("n_trials", n_trials), ("sample_length", sample_length)):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise TypeError(f"{name} must be a numeric type, got {type(val).__name__}")
        if not math.isfinite(val):
            raise ValueError(f"{name} must be a finite number")
    if n_trials <= 0:
        raise ValueError("n_trials must be greater than 0")
    if sample_length <= 1:
        raise ValueError("sample_length must be greater than 1 (Eq. 2 uses sqrt(T-1))")
    if var_trials < 0:
        raise ValueError("var_trials must be non-negative (it is a variance)")
    if abs(observed_sharpe) > MAX_PLAUSIBLE_PER_PERIOD_SHARPE:
        raise ValueError(
            f"|observed_sharpe| = {abs(observed_sharpe):.4f} > "
            f"{MAX_PLAUSIBLE_PER_PERIOD_SHARPE} is implausible as a PER-PERIOD "
            "Sharpe ratio — this is almost always an annualised figure passed by "
            "mistake. Divide by sqrt(periods per year) first; see the module "
            "docstring on UNITS.")

    sr0 = expected_max_sharpe(n_trials, var_trials=var_trials)

    # Denominator of Eq. (2): the non-normality adjustment. The signs and
    # coefficients here are the paper's, and every one of them was wrong before
    # this was checked against it.
    denom_sq = (1.0
                - skewness * observed_sharpe
                + ((kurtosis - 1.0) / 4.0) * observed_sharpe ** 2)
    if denom_sq <= 0:
        raise ValueError(
            "the non-normality adjustment 1 - g3*SR + (g4-1)/4*SR^2 is not "
            f"positive (got {denom_sq}); this skewness/kurtosis pair is "
            "inconsistent with this Sharpe ratio")

    statistic = ((observed_sharpe - sr0) * math.sqrt(sample_length - 1)
                 / math.sqrt(denom_sq))
    return float(NormalDistribution.cdf(statistic))


def minimum_backtest_length(observed_sharpe: float, n_trials: int) -> float:
    """Minimum backtest length — MinBTL paper Theorem 3.1, as published.

        MinBTL ~= ( ( (1-g) Z^-1[1 - 1/N] + g Z^-1[1 - (1/N)e^-1] )
                    / E[max_N] )^2
                < 2 ln[N] / E[max_N]^2

    Note the second half: `2 ln(N) / SR^2` is the paper's stated UPPER BOUND,
    not the formula. It is loose exactly where it matters — at N = 45 it gives
    7.6 against the exact 5.0 — so this returns the exact left-hand side.

    Args:
        observed_sharpe: the Sharpe ratio to be distinguishable from zero
            (E[max_N] in the theorem). Must be positive.
        n_trials: number of independent trials (N).

    Returns:
        The minimum sample length, in the SAME period as `observed_sharpe`:
        pass an annualised Sharpe and the answer is years; pass a daily Sharpe
        and it is days. May be fractional; it is not rounded.

    Raises:
        ValueError: on non-finite input, n_trials <= 0, or observed_sharpe <= 0.
        TypeError: on non-numeric input.
    """
    _check_numeric(observed_sharpe=observed_sharpe)
    if isinstance(n_trials, bool) or not isinstance(n_trials, (int, float)):
        raise TypeError(f"n_trials must be a numeric type, got {type(n_trials).__name__}")
    if not math.isfinite(n_trials):
        raise ValueError("n_trials must be a finite number")
    if n_trials <= 0:
        raise ValueError("n_trials must be greater than 0")
    if observed_sharpe <= 0:
        raise ValueError("observed_sharpe must be positive to require a length "
                         "for a positive signal")

    # Standardised expected maximum: Eq. (3.1) with unit variance.
    e_max = expected_max_sharpe(n_trials, var_trials=1.0)
    return float((e_max / observed_sharpe) ** 2)


def evaluate(
    observed_sharpe: float,
    n_trials: int,
    sample_length: int,
    skewness: float,
    kurtosis: float,
    var_trials: float,
    threshold: float = 0.95,
) -> dict:
    """A result that carries its own verdict (spec R3).

    `threshold` is the paper's 95% confidence level: its worked example declines
    the strategy precisely because DSR = 0.9004 < 0.95.
    """
    dsr = deflated_sharpe_ratio(observed_sharpe, n_trials, sample_length,
                                skewness, kurtosis, var_trials)
    t_min = minimum_backtest_length(observed_sharpe, n_trials)
    return {
        "deflated_sharpe": dsr,
        "min_backtest_length": t_min,
        "sample_length": sample_length,
        "sample_too_short": sample_length < t_min,
        "n_trials": n_trials,
        "threshold": threshold,
        "significant": dsr >= threshold and sample_length >= t_min,
    }


if __name__ == "__main__":
    # The DSR paper's worked example (p.10), in this module's per-period units:
    # N=100, V[SR]=1/2 annualised, T=1250, g3=-3, g4=10, SR=2.5 annualised.
    # The paper reports DSR = 0.9004, below the 0.95 threshold, so the investor
    # declines. Running this file reproduces that number.
    PERIODS_PER_YEAR = 250
    print(json.dumps(evaluate(
        observed_sharpe=2.5 / math.sqrt(PERIODS_PER_YEAR),
        n_trials=100,
        sample_length=1250,
        skewness=-3.0,
        kurtosis=10.0,
        var_trials=0.5 / PERIODS_PER_YEAR,
    ), indent=2))
