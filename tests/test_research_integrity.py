"""Tests for the research-integrity core.

The most important tests here are the ORACLE tests: the two source papers each
publish a worked example with a stated answer, and those answers are pinned
below. Everything else in this file is an invariant, and invariants were not
enough — the previous implementation used formulas the papers do not contain,
and passed every invariant test while doing so. A wrong constant in a
right-shaped formula stays in [0, 1], stays monotonic, and still discriminates.

Mutation testing made the gap concrete: changing `2` to `3` inside the old
benchmark-Sharpe formula was invisible to 23 invariant checks. The fixed values
below are what closes it.
"""
import math

import pytest

import src.research_integrity.core as ri

PERIODS_PER_YEAR = 250

# The DSR paper's worked example (p.10): a strategist reports an annualised
# Sharpe of 2.5 over 5 daily years, after N=100 trials with V[SR]=1/2 annualised
# and returns with skew -3, kurtosis 10.
PAPER_DSR = dict(
    observed_sharpe=2.5 / math.sqrt(PERIODS_PER_YEAR),
    n_trials=100,
    sample_length=1250,
    skewness=-3.0,
    kurtosis=10.0,
    var_trials=0.5 / PERIODS_PER_YEAR,
)

# A per-period base case for the invariant tests. Per-period, matching
# sample_length — an annualised figure here is the units bug this module exists
# to prevent, and the function now rejects it.
BASE = dict(observed_sharpe=0.09, n_trials=10, sample_length=1000,
            skewness=-0.3, kurtosis=4.0, var_trials=0.01)


# --- oracle: values published in the papers ---------------------------------

def test_reproduces_the_papers_rejection_threshold():
    """SR_0 = 0.1132, printed in the DSR paper's worked example."""
    sr0 = ri.expected_max_sharpe(100, var_trials=0.5 / PERIODS_PER_YEAR)
    assert sr0 == pytest.approx(0.1132, abs=5e-5)


def test_reproduces_the_papers_deflated_sharpe():
    """DSR = 0.9004, printed in the DSR paper's worked example."""
    assert ri.deflated_sharpe_ratio(**PAPER_DSR) == pytest.approx(0.9004, abs=5e-5)


def test_reproduces_the_papers_investment_decision():
    """The example exists to show the investor DECLINING at 95% confidence.

    Getting the number right but the verdict wrong would defeat the purpose.
    The previous implementation returned 0.9960 here, which would have said
    'accept' — the exact opposite of the paper's conclusion.
    """
    out = ri.evaluate(**PAPER_DSR)
    assert out["deflated_sharpe"] < 0.95
    assert out["significant"] is False


def test_reproduces_the_minbtl_papers_headline_result():
    """'If only 5 years of data are available, no more than 45 independent
    model configurations should be tried' — MinBTL paper, Theorem 3.1."""
    assert ri.minimum_backtest_length(1.0, 45) == pytest.approx(5.0, abs=0.01)


def test_minbtl_stays_below_the_papers_stated_upper_bound():
    """Theorem 3.1 states MinBTL < 2 ln[N] / SR^2. The bound is loose, and
    returning the bound instead of the formula was one of the original bugs."""
    for n in (10, 45, 100, 1000):
        assert ri.minimum_backtest_length(1.0, n) < 2 * math.log(n)


def test_expected_max_sharpe_grows_with_trials():
    """'After only 1,000 independent backtests, the expected maximum Sharpe
    Ratio is 3.26, even if the true SR is zero.'"""
    assert ri.expected_max_sharpe(1000, var_trials=1.0) == pytest.approx(3.26, abs=0.01)


# --- invariants (necessary, and demonstrably not sufficient) ----------------

def test_p1_monotonic_in_trials():
    assert ri.deflated_sharpe_ratio(**{**BASE, "n_trials": 1000}) <= \
           ri.deflated_sharpe_ratio(**{**BASE, "n_trials": 10}) + 1e-12


def test_p2_monotonic_in_observed_sharpe():
    assert ri.deflated_sharpe_ratio(**{**BASE, "observed_sharpe": 0.2}) >= \
           ri.deflated_sharpe_ratio(**{**BASE, "observed_sharpe": 0.09}) - 1e-12


def test_p3_bounded():
    for s in (-0.2, 0.0, 0.09, 0.3):
        for n in (1, 10, 5000):
            v = ri.deflated_sharpe_ratio(**{**BASE, "observed_sharpe": s, "n_trials": n})
            assert 0.0 <= v <= 1.0


def test_p4_minbtl_monotonic_in_trials():
    assert ri.minimum_backtest_length(0.09, 1000) >= ri.minimum_backtest_length(0.09, 10)


def test_p5_deterministic():
    a = ri.deflated_sharpe_ratio(**BASE)
    assert a == ri.deflated_sharpe_ratio(**BASE) == ri.deflated_sharpe_ratio(**BASE)


def test_single_trial_carries_no_selection_burden():
    """N=1 is outside the paper's N >> 1 regime; the module's convention is that
    one trial means nothing to correct for."""
    assert ri.expected_max_sharpe(1, var_trials=0.5) == 0.0
    assert 0.0 <= ri.deflated_sharpe_ratio(**{**BASE, "n_trials": 1}) <= 1.0


# --- units: the defect the spec and its gate once shared --------------------

def test_annualised_sharpe_is_rejected_not_silently_answered():
    with pytest.raises(ValueError, match="PER-PERIOD"):
        ri.deflated_sharpe_ratio(**{**BASE, "observed_sharpe": 1.5})


def test_variance_of_trials_is_required():
    """SR_0 cannot be computed without V[{SR_n}]. Defaulting it would invent an
    answer, which is exactly what the previous version did."""
    with pytest.raises(TypeError):
        ri.deflated_sharpe_ratio(0.09, 10, 1000, -0.3, 4.0)


# --- edges ------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    {"n_trials": 0}, {"n_trials": -5}, {"sample_length": 1},
    {"var_trials": -1.0}, {"observed_sharpe": float("nan")},
    {"observed_sharpe": float("inf")},
])
def test_invalid_input_raises(bad):
    with pytest.raises(ValueError):
        ri.deflated_sharpe_ratio(**{**BASE, **bad})


def test_non_numeric_input_raises():
    with pytest.raises(TypeError):
        ri.deflated_sharpe_ratio(**{**BASE, "observed_sharpe": "1.5"})


def test_inconsistent_moments_raise_rather_than_return_nan():
    """If 1 - g3*SR + (g4-1)/4*SR^2 goes non-positive the statistic is
    undefined. Refusing is a feature; returning nan is not."""
    with pytest.raises(ValueError):
        ri.deflated_sharpe_ratio(**{**BASE, "observed_sharpe": 0.9,
                                    "skewness": 1.0, "kurtosis": -50.0})


# --- the normal helpers, whose failure once propagated everywhere -----------

def test_ppf_sign_and_magnitude():
    """The -32.81 regression: sign inverted, magnitude wrong by ~20x."""
    assert ri.NormalDistribution.ppf(0.95) == pytest.approx(1.6448536, abs=1e-6)
    assert ri.NormalDistribution.ppf(0.5) == pytest.approx(0.0, abs=1e-12)


def test_ppf_rejects_its_domain_boundary():
    for p in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            ri.NormalDistribution.ppf(p)


def test_cdf_ppf_round_trip():
    for p in (0.05, 0.5, 0.95, 0.999):
        assert ri.NormalDistribution.cdf(ri.NormalDistribution.ppf(p)) == pytest.approx(p)
