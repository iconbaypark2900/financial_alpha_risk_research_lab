"""Transaction costs and capacity — PRD 04 §5.3, FR-17, FR-18, FR-20.

WHAT IS AND IS NOT BUILT HERE, AND WHY

The PRD names **NautilusTrader** as the backtest and execution engine, "given
the intent to trade", for its research-to-live parity. That is the right call
and this module does not reimplement it. Writing an event-driven matching engine
by hand when the spec names one would repeat the mistake made with Mitiq earlier
in this project: the spec named the library, the dependency file pinned it, and
the code hand-rolled it anyway.

NautilusTrader 1.231.0 is installed and supplies FR-19 (partial fills, latency)
and FR-21 (look-ahead is structurally impossible in an event-driven engine,
because data arrives as timestamped messages rather than being indexable).

What it does NOT supply, and what is therefore built here:

  FR-17  a market-impact model as a function of PARTICIPATION RATE
  FR-18  borrow availability as a hard constraint, not a cost adjustment
  FR-20  capacity as a primary output — the AUM at which expected return
         degrades below a threshold

THE IMPACT MODEL, TAKEN FROM THE PAPER RATHER THAN FROM FOLKLORE

Almgren, Thum, Hauptmann & Li (2005), "Direct Estimation of Equity Market
Impact", Risk. Equations (7) and (8), with the coefficients fitted in §4.3.

The widely-repeated "square-root law" is NOT what this paper found. Its abstract
says so explicitly: "We reject the common square-root model for temporary impact
as function of trade rate, in favor of a 3/5 power law." Implementing the folk
version would have been wrong in exactly the way the deflated Sharpe was wrong —
plausible, standard-looking, and not what the cited source says.

    Permanent:  I/sigma = gamma * T * sgn(X) * (X/(V*T))^alpha * (Theta/V)^delta
    Temporary:  (J - I/2)/sigma = eta * sgn(X) * (X/(V*T))^beta

    alpha = 1      (linear; "the only value for which the model is free from
                    arbitrage", §4.2)
    beta  = 3/5    (0.600 +/- 0.038 fitted)
    delta = 1/4    ("very approximately", 0.267 +/- 0.22 fitted)
    gamma = 0.314 +/- 0.041
    eta   = 0.142 +/- 0.0062

Note delta's error bar: 0.267 +/- 0.22 is barely distinguishable from zero. The
paper rounds it to 1/4 and says "very approximately"; that uncertainty is
carried in `liquidity_exponent` rather than hidden behind a constant.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

# Fitted in Almgren et al. (2005) §4.3. Named constants rather than literals so
# a reader can check them against the paper without reading the arithmetic.
GAMMA = 0.314          # permanent impact coefficient
ETA = 0.142            # temporary impact coefficient
ALPHA = 1.0            # permanent exponent
BETA = 0.6             # temporary exponent (3/5, NOT 1/2)
DELTA = 0.25           # liquidity (shares-outstanding) exponent


class BorrowUnavailable(RuntimeError):
    """FR-18: the position cannot be taken, rather than taken at a higher cost."""


@dataclass(frozen=True)
class Instrument:
    """The market parameters the impact model needs.

    All in consistent units: `adv` and `shares_outstanding` in shares,
    `daily_volatility` as a fraction (0.02 = 2%), `price` per share.
    """
    symbol: str
    price: float
    adv: float                    # average daily volume, shares
    daily_volatility: float       # fraction, e.g. 0.02
    shares_outstanding: float
    spread: float = 0.0005        # fraction of price, half-spread applied
    commission: float = 0.0005    # fraction of notional
    borrow_available: float = 0.0     # shares available to short
    borrow_fee_annual: float = 0.0    # fraction of notional per year

    def __post_init__(self) -> None:
        for name in ("price", "adv", "daily_volatility", "shares_outstanding"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive, got {getattr(self, name)}")


def participation_rate(shares: float, instrument: Instrument,
                       days: float = 1.0) -> float:
    """X / (V*T) — the trade rate that both impact terms are functions of.

    This is the quantity FR-17 names. Expressing impact in dollars or in shares
    without dividing by volume produces a model that says a million shares costs
    the same in a liquid megacap as in a microcap, which is the error the whole
    literature exists to correct.
    """
    if days <= 0:
        raise ValueError(f"execution horizon must be positive, got {days}")
    return abs(shares) / (instrument.adv * days)


def permanent_impact(shares: float, instrument: Instrument, days: float = 1.0,
                     liquidity_exponent: float = DELTA) -> float:
    """Equation (7): the price move that does not decay. Fraction of price."""
    rate = participation_rate(shares, instrument, days)
    liquidity = (instrument.shares_outstanding / instrument.adv) ** liquidity_exponent
    return (instrument.daily_volatility * GAMMA * days
            * rate ** ALPHA * liquidity * math.copysign(1.0, shares))


def temporary_impact(shares: float, instrument: Instrument,
                     days: float = 1.0) -> float:
    """Equation (8): the liquidity cost of trading fast. Fraction of price.

    The 3/5 exponent is the paper's central finding and the reason a strategy
    cannot simply scale: doubling size costs 2^0.6 = 1.52x per share, so total
    cost grows as size^1.6.
    """
    rate = participation_rate(shares, instrument, days)
    return (instrument.daily_volatility * ETA * rate ** BETA
            * math.copysign(1.0, shares))


def execution_cost(shares: float, instrument: Instrument, days: float = 1.0,
                   liquidity_exponent: float = DELTA) -> dict[str, float]:
    """Total round-trip-relevant cost of executing `shares`, in currency.

    Combines the paper's realised-impact decomposition (J = I/2 + temporary)
    with the explicit costs FR-17 also requires: commission and spread.
    """
    if shares == 0:
        return {"commission": 0.0, "spread": 0.0, "impact": 0.0, "total": 0.0,
                "total_bps": 0.0, "participation_rate": 0.0}

    notional = abs(shares) * instrument.price
    perm = permanent_impact(shares, instrument, days, liquidity_exponent)
    temp = temporary_impact(shares, instrument, days)
    # Realised impact borne by this order, per Almgren §3: J = I/2 + temporary.
    realised = abs(perm) / 2.0 + abs(temp)

    commission = notional * instrument.commission
    spread_cost = notional * instrument.spread / 2.0     # cross half the spread
    impact_cost = notional * realised
    total = commission + spread_cost + impact_cost
    return {
        "commission": commission,
        "spread": spread_cost,
        "impact": impact_cost,
        "total": total,
        "total_bps": 1e4 * total / notional,
        "participation_rate": participation_rate(shares, instrument, days),
        "permanent_impact": perm,
        "temporary_impact": temp,
    }


def check_borrow(shares: float, instrument: Instrument) -> None:
    """FR-18: unavailable borrow MUST prevent the position, not silently allow it.

    Raises rather than returning a penalty. A short that could not have been
    borrowed did not happen, and pricing it as merely expensive produces a
    backtest of a strategy nobody could have run.
    """
    if shares >= 0:
        return
    needed = abs(shares)
    if needed > instrument.borrow_available:
        raise BorrowUnavailable(
            f"short of {needed:,.0f} shares in {instrument.symbol} requires more "
            f"borrow than the {instrument.borrow_available:,.0f} available. The "
            "position cannot be taken. Reducing size or dropping the name are "
            "the options; charging a higher fee is not, because the shares do "
            "not exist to lend.")


def borrow_cost(shares: float, instrument: Instrument, days_held: float) -> float:
    """Borrow fee for a short held `days_held` days, in currency."""
    if shares >= 0:
        return 0.0
    check_borrow(shares, instrument)
    notional = abs(shares) * instrument.price
    return notional * instrument.borrow_fee_annual * days_held / 365.0


@dataclass
class CapacityResult:
    aum_ceiling: float
    threshold: float
    gross_sharpe: float
    curve: list[tuple[float, float]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"aum_ceiling": self.aum_ceiling, "threshold": self.threshold,
                "gross_sharpe": self.gross_sharpe,
                "curve": [{"aum": a, "net_sharpe": s} for a, s in self.curve]}


def capacity(instrument: Instrument, *, gross_sharpe: float,
             turnover_per_year: float, threshold: float = 0.5,
             trading_days: int = 252, days_to_execute: float = 1.0,
             max_aum: float = 1e11) -> CapacityResult:
    """FR-20: the AUM at which expected return degrades below `threshold`.

    Reported as a PRIMARY output, not a footnote. A strategy with a Sharpe of
    2.0 and a capacity of $8m is not a strategy for a fund that intends to
    deploy $500m — and that is a fact about the strategy, discoverable before
    deployment rather than after.

    `threshold` is the fraction of the gross Sharpe that must survive costs.
    The default of 0.5 is a convention, not a derived value, and is stated as
    such: half the edge eaten by execution is a reasonable place to stop.

    The search is a bisection on a monotone curve — net Sharpe falls with AUM
    because impact grows as size^1.6 while returns grow linearly — so the
    ceiling is well defined wherever the curve crosses.
    """
    if gross_sharpe <= 0:
        raise ValueError(
            f"capacity is undefined for a non-positive gross Sharpe "
            f"({gross_sharpe}): there is no edge to erode")
    if not 0 < threshold < 1:
        raise ValueError(f"threshold must be in (0, 1), got {threshold}")

    def net_sharpe(aum: float) -> float:
        """Gross Sharpe less the annualised cost drag, expressed in Sharpe units."""
        if aum <= 0:
            return gross_sharpe
        shares_per_trade = (aum * turnover_per_year / trading_days) / instrument.price
        cost = execution_cost(shares_per_trade, instrument, days_to_execute)
        daily_notional = aum * turnover_per_year / trading_days
        if daily_notional <= 0:
            return gross_sharpe
        daily_drag = cost["total"] / aum                     # fraction of AUM per day
        annual_drag = daily_drag * trading_days
        # Convert a return drag into Sharpe units using annualised volatility.
        annual_vol = instrument.daily_volatility * math.sqrt(trading_days)
        return gross_sharpe - annual_drag / annual_vol

    target = gross_sharpe * threshold
    if net_sharpe(max_aum) >= target:
        return CapacityResult(aum_ceiling=math.inf, threshold=threshold,
                              gross_sharpe=gross_sharpe)

    lo, hi = 1.0, max_aum
    for _ in range(200):
        mid = math.sqrt(lo * hi)          # geometric bisection: AUM spans decades
        if net_sharpe(mid) >= target:
            lo = mid
        else:
            hi = mid
        if hi / lo < 1.0001:
            break

    curve = []
    aum = 1e5
    while aum <= min(lo * 100, max_aum):
        curve.append((aum, net_sharpe(aum)))
        aum *= 10
    return CapacityResult(aum_ceiling=lo, threshold=threshold,
                          gross_sharpe=gross_sharpe, curve=curve)
