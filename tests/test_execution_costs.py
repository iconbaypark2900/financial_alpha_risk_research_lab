"""Transaction costs and capacity — PRD 04 FR-17, FR-18, FR-20.

The impact model is taken from Almgren, Thum, Hauptmann & Li (2005), and the
tests pin the paper's exponents rather than the folklore. The paper's abstract
is explicit: "We reject the common square-root model for temporary impact as
function of trade rate, in favor of a 3/5 power law." Implementing the
square-root version would have been wrong in exactly the way the deflated Sharpe
was wrong — plausible, standard-looking, and not what the source says.

So `test_temporary_impact_follows_the_papers_three_fifths_power` is the oracle
here: it would pass for a square-root model only if 2**0.6 equalled 2**0.5,
which it does not.
"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research_integrity.execution_costs import (  # noqa: E402
    ALPHA,
    BETA,
    BorrowUnavailable,
    ETA,
    GAMMA,
    Instrument,
    borrow_cost,
    capacity,
    check_borrow,
    execution_cost,
    participation_rate,
    permanent_impact,
    temporary_impact,
)


@pytest.fixture()
def liquid() -> Instrument:
    """A large-cap: $50, 10m shares a day, 2% daily vol, 1bn shares out."""
    return Instrument(symbol="BIG", price=50.0, adv=10_000_000,
                      daily_volatility=0.02, shares_outstanding=1_000_000_000,
                      borrow_available=5_000_000, borrow_fee_annual=0.005)


@pytest.fixture()
def illiquid() -> Instrument:
    """A microcap: same price and vol, a hundredth of the volume."""
    return Instrument(symbol="SMALL", price=50.0, adv=100_000,
                      daily_volatility=0.02, shares_outstanding=10_000_000)


# --- the paper's coefficients, pinned --------------------------------------

def test_the_fitted_coefficients_match_the_paper():
    """Almgren et al. (2005) §4.3: gamma = 0.314, eta = 0.142, alpha = 1,
    beta = 0.600."""
    assert GAMMA == 0.314
    assert ETA == 0.142
    assert ALPHA == 1.0
    assert BETA == 0.6


def test_temporary_impact_follows_the_papers_three_fifths_power(liquid):
    """THE ORACLE. Doubling the trade rate must multiply temporary impact by
    2**0.6 = 1.5157, not by 2**0.5 = 1.4142.

    A square-root implementation — the model everyone quotes and the paper
    explicitly rejects — fails this by 7%, which is exactly the size of error
    that survives every sanity check and quietly misprices a strategy.
    """
    small = temporary_impact(100_000, liquid)
    double = temporary_impact(200_000, liquid)
    assert double / small == pytest.approx(2 ** 0.6, rel=1e-9)
    assert double / small != pytest.approx(2 ** 0.5, rel=1e-3)


def test_permanent_impact_is_linear_in_participation(liquid):
    """alpha = 1 — "the only value for which the model is free from arbitrage"."""
    assert (permanent_impact(200_000, liquid) / permanent_impact(100_000, liquid)
            == pytest.approx(2.0))


def test_impact_scales_with_volatility(liquid):
    """Both terms are expressed as a fraction of daily volatility."""
    vol_double = Instrument(**{**liquid.__dict__, "daily_volatility": 0.04})
    assert (temporary_impact(100_000, vol_double)
            == pytest.approx(2 * temporary_impact(100_000, liquid)))


def test_impact_has_the_sign_of_the_trade(liquid):
    """Buying pushes the price up, selling down. A model returning a positive
    cost for both would understate short-side impact."""
    assert temporary_impact(100_000, liquid) > 0
    assert temporary_impact(-100_000, liquid) < 0


# --- FR-17: impact is a function of participation, not size ----------------

def test_the_same_share_count_costs_far_more_in_an_illiquid_name(liquid, illiquid):
    """The error the whole literature exists to correct: 100,000 shares is 1%
    of a day in the megacap and 100% of a day in the microcap."""
    big = execution_cost(100_000, liquid)["total_bps"]
    small = execution_cost(100_000, illiquid)["total_bps"]
    assert small > big * 5


def test_trading_more_slowly_reduces_temporary_impact(liquid):
    """Temporary impact depends on the RATE. Spreading an order over five days
    cuts the rate fivefold, and the cost by 5**0.6."""
    fast = temporary_impact(1_000_000, liquid, days=1.0)
    slow = temporary_impact(1_000_000, liquid, days=5.0)
    assert slow == pytest.approx(fast / 5 ** 0.6, rel=1e-9)


def test_participation_rate_is_shares_over_volume_time(liquid):
    assert participation_rate(1_000_000, liquid, days=1.0) == pytest.approx(0.1)
    assert participation_rate(1_000_000, liquid, days=2.0) == pytest.approx(0.05)


def test_costs_are_decomposed_not_lumped(liquid):
    """FR-17 names commission, spread and impact separately; a single number
    cannot be checked against a broker invoice."""
    cost = execution_cost(500_000, liquid)
    assert cost["commission"] > 0 and cost["spread"] > 0 and cost["impact"] > 0
    assert cost["total"] == pytest.approx(
        cost["commission"] + cost["spread"] + cost["impact"])


def test_zero_shares_costs_nothing(liquid):
    assert execution_cost(0, liquid)["total"] == 0.0


# --- FR-18: borrow is a constraint, not a price ----------------------------

def test_an_unborrowable_short_is_prevented_not_priced(liquid):
    """'unavailable borrow MUST prevent the position, not silently allow it.'
    Charging more for shares that do not exist to lend produces a backtest of a
    strategy nobody could have run."""
    with pytest.raises(BorrowUnavailable, match="cannot be taken"):
        check_borrow(-10_000_000, liquid)     # only 5m available


def test_a_borrowable_short_is_allowed(liquid):
    check_borrow(-1_000_000, liquid)
    assert borrow_cost(-1_000_000, liquid, days_held=365) == pytest.approx(
        1_000_000 * 50.0 * 0.005)


def test_longs_are_never_borrow_constrained(liquid):
    check_borrow(50_000_000, liquid)
    assert borrow_cost(1_000, liquid, days_held=30) == 0.0


def test_borrow_cost_accrues_with_holding_period(liquid):
    assert (borrow_cost(-100_000, liquid, days_held=60)
            == pytest.approx(2 * borrow_cost(-100_000, liquid, days_held=30)))


# --- FR-20: capacity as a primary output -----------------------------------

def test_capacity_is_finite_for_a_real_strategy(liquid):
    result = capacity(liquid, gross_sharpe=2.0, turnover_per_year=12)
    assert 0 < result.aum_ceiling < math.inf


def test_capacity_is_smaller_in_an_illiquid_name(liquid, illiquid):
    """The point of the number: the same edge supports far less money in a
    microcap."""
    big = capacity(liquid, gross_sharpe=2.0, turnover_per_year=12).aum_ceiling
    small = capacity(illiquid, gross_sharpe=2.0, turnover_per_year=12).aum_ceiling
    assert small < big


def test_higher_turnover_reduces_capacity(liquid):
    """Trading more often pays impact more often."""
    slow = capacity(liquid, gross_sharpe=2.0, turnover_per_year=4).aum_ceiling
    fast = capacity(liquid, gross_sharpe=2.0, turnover_per_year=52).aum_ceiling
    assert fast < slow


def test_net_sharpe_falls_monotonically_with_aum(liquid):
    """The curve must be monotone or the ceiling is not well defined."""
    result = capacity(liquid, gross_sharpe=2.0, turnover_per_year=12)
    sharpes = [s for _, s in result.curve]
    assert sharpes == sorted(sharpes, reverse=True)


def test_at_the_ceiling_the_threshold_is_met_and_just_beyond_it_is_not(liquid):
    result = capacity(liquid, gross_sharpe=2.0, turnover_per_year=12,
                      threshold=0.5)
    target = 2.0 * 0.5

    def net(aum):
        shares = (aum * 12 / 252) / liquid.price
        cost = execution_cost(shares, liquid)
        drag = (cost["total"] / aum) * 252
        return 2.0 - drag / (liquid.daily_volatility * math.sqrt(252))

    assert net(result.aum_ceiling * 0.99) >= target
    assert net(result.aum_ceiling * 1.05) < target


def test_capacity_is_undefined_without_an_edge(liquid):
    """There is nothing for costs to erode."""
    with pytest.raises(ValueError, match="no edge"):
        capacity(liquid, gross_sharpe=0.0, turnover_per_year=12)


def test_an_invalid_threshold_is_refused(liquid):
    with pytest.raises(ValueError, match="threshold"):
        capacity(liquid, gross_sharpe=2.0, turnover_per_year=12, threshold=1.5)


def test_instrument_requires_positive_market_parameters():
    with pytest.raises(ValueError, match="adv"):
        Instrument(symbol="X", price=10.0, adv=0, daily_volatility=0.02,
                   shares_outstanding=1e6)
