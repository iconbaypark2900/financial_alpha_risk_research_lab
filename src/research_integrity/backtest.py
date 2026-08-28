"""Event-driven backtest engine — PRD 04 §5.3, FR-19 and FR-21.

    FR-19  The engine MUST model partial fills and latency.
    FR-21  Look-ahead MUST be structurally impossible, not merely avoided.

WHAT CHANGED, AND WHY THE PREVIOUS STATE WAS WORSE THAN NOTHING

`execution_costs.py` used to assert that NautilusTrader "is installed and
supplies FR-19 and FR-21". It was installed. Nothing imported it. Two
requirements were therefore booked as satisfied by a line in a dependency file,
which is the Mitiq mistake in its quieter second form: not hand-rolling a named
library, but taking credit for one that was never called. A requirement is not
met by a package being present on disk.

This module is the wiring that makes the claim true. NautilusTrader runs the
matching engine, the order lifecycle, the account, and the clock. Nothing here
reimplements any of that.

WHY AN EVENT-DRIVEN ENGINE ACTUALLY BUYS FR-21

The usual defence against look-ahead is discipline: index carefully, shift in
the right direction, review the code. That fails silently, and the failure is
the most rewarding kind — a leaky backtest looks like a good one.

An event-driven engine removes the opportunity rather than the temptation. Data
is delivered to the strategy as timestamped messages in time order; there is no
array to index off the end of, because at the moment `on_bar` runs the later
bars have not been sent. A strategy cannot read what it has not been given.

But "cannot" is a claim about an implementation, and this project does not
accept those on trust — the deflated Sharpe formula was wrong for four commits
while every invariant test passed. So `LookAheadAudit` below CHECKS it, on every
bar of every run: nothing visible to the strategy may postdate the bar it is
currently handling, and the number of bars it can see must equal the number it
has been sent. It is cheap, it runs by default, and it turns a design argument
into an assertion.

HOW THIS COMPOSES WITH THE FACTOR LIBRARY

Two different guarantees that only mean something together:

  `assert_causal`     the factor does not read forward WITHIN the array it is
                      given (factors.py)
  `LookAheadAudit`    the array it is given never CONTAINS the future (here)

Either alone is insufficient. A perfectly causal factor over a contaminated
history is contaminated; an honest history fed to a factor that peeks is
leaked. The strategy below computes its signal by calling `momentum` on exactly
the closes that have arrived, so both checks apply to the same number.

WHAT NAUTILUS SUPPLIES AND WHAT THIS ADDS

Supplied: matching, partial fills, latency, order lifecycle, account, position
tracking, and the time-ordered message bus that FR-21 rests on.

Added here, because the engine has no opinion about them:

  - `AlmgrenFeeModel` charges the participation-rate impact from
    `execution_costs.py` on every fill. Nautilus's own `FillModel` slips a fill
    by a TICK with some probability, which is microstructure noise, not market
    impact — it does not grow with order size relative to volume, so a
    100,000-share order in a microcap costs the same tick as in a megacap. That
    is the error FR-17 exists to correct, so the impact model is plugged in
    where the engine charges commission.
  - Every run is registered with the `TrialCounter` BEFORE the engine starts, so
    a backtest that is abandoned, crashes, or produces a disappointing number is
    counted anyway (FR-08). A counter that only sees runs the researcher chose
    to finish is not a count.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Sequence

import numpy as np

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.backtest.models import FeeModel, FillModel, LatencyModel
from nautilus_trader.config import LoggingConfig, StrategyConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.trading.strategy import Strategy

from .execution_costs import Instrument as CostSpec
from .execution_costs import execution_cost
from .factors import momentum

NANOS_PER_DAY = 86_400_000_000_000
DEFAULT_START_NS = 1_600_000_000_000_000_000     # 2020-09-13, an arbitrary epoch


class LookAheadDetected(AssertionError):
    """The strategy could see data that postdates the bar it was handling.

    An AssertionError, like `LeakageError` and `LookAheadFactor`, because it is
    a violated invariant rather than a bad input.
    """


# --- FR-21, checked on every bar rather than argued for --------------------

@dataclass
class LookAheadAudit:
    """Records what was visible to the strategy at each bar, and to when.

    Two properties are checked, and they catch different things:

      NOTHING LATER IS VISIBLE   the newest timestamp the strategy can see must
                                 not exceed the bar it is handling. Catches data
                                 delivered early.

      NOTHING EXTRA IS VISIBLE   the count of bars it can see must not EXCEED
                                 the count it has been handed. Catches a cache
                                 pre-loaded with history that was never sent
                                 through the bus — the same contamination
                                 arriving by a different route. Fewer is legal:
                                 nautilus caps the cache at `bar_capacity`.

    Kept as a record rather than raising on the spot so a failing run can be
    inspected: `violations` names every bar that was wrong, not just the first.
    """
    observations: int = 0
    violations: list[dict[str, Any]] = field(default_factory=list)

    def observe(self, *, bar_index: int, current_ts: int, visible_count: int,
                max_visible_ts: int | None) -> None:
        self.observations += 1
        if max_visible_ts is not None and max_visible_ts > current_ts:
            self.violations.append({
                "bar_index": bar_index, "reason": "future data visible",
                "current_ts": current_ts, "max_visible_ts": max_visible_ts,
                "ahead_by_ns": max_visible_ts - current_ts,
            })
        # MORE than were delivered, not merely different. Nautilus keeps bars in
        # a deque(maxlen=bar_capacity), default 10,000, so a long run legitimately
        # sees FEWER than it was sent — an equality check turned every bar past
        # the cap into a spurious violation and aborted clean runs of more than
        # 10,000 bars (40 years of daily data). The property worth having is that
        # nothing EXTRA is visible: a cache pre-loaded with history that never
        # came through the bus still has more than was delivered.
        if visible_count > bar_index + 1:
            self.violations.append({
                "bar_index": bar_index, "reason": "more bars visible than delivered",
                "visible_count": visible_count, "delivered": bar_index + 1,
            })

    @property
    def clean(self) -> bool:
        return not self.violations

    def assert_clean(self) -> None:
        """Raise unless every bar of the run was clean.

        Raises:
            LookAheadDetected: naming the first offending bar and the count.
        """
        if self.violations:
            first = self.violations[0]
            raise LookAheadDetected(
                f"{len(self.violations)} look-ahead violation(s) across "
                f"{self.observations} bars; first at bar {first['bar_index']}: "
                f"{first['reason']} ({first})")

    def as_dict(self) -> dict[str, Any]:
        return {"bars_audited": self.observations, "clean": self.clean,
                "violations": list(self.violations)}


# --- FR-17 inside the engine ------------------------------------------------

class AlmgrenFeeModel(FeeModel):
    """Charges the participation-rate impact from `execution_costs.py` per fill.

    Nautilus's `FillModel` handles whether and at what tick an order fills.
    That is microstructure. It is not impact: it does not grow with order size
    relative to daily volume, so without this a 100,000-share order costs the
    same in a name that trades 10m a day and one that trades 100k. The second is
    a whole day's volume and moves the price; the first is a rounding error.

    `charges` keeps every commission taken, so a test can assert the model was
    actually consulted rather than silently bypassed — which is exactly the
    failure this whole module exists to correct.
    """

    def __init__(self, spec: CostSpec) -> None:
        super().__init__()
        self.spec = spec
        self.charges: list[dict[str, float]] = []

    def get_commission(self, order, fill_qty, fill_px, instrument) -> Money:
        # Priced at the price it ACTUALLY filled at. Using the static
        # `spec.price` charged every fill at a fixed reference: on a series
        # drifting from 100 to 250, a 100-share fill at 250 was billed on a
        # notional of 100 x 100, about 60% of the true cost — and the
        # understatement grows with every trending backtest, which is the
        # direction that flatters the strategy.
        shares = abs(float(fill_qty))
        spec = self.spec
        if fill_px is not None:
            price = abs(float(fill_px))
            if price > 0:
                spec = replace(self.spec, price=price)
        cost = execution_cost(shares, spec)
        self.charges.append({"shares": shares, "price": spec.price,
                             "total": cost["total"],
                             "total_bps": cost["total_bps"]})
        currency = getattr(instrument, "quote_currency", None) or USD
        return Money(cost["total"], currency)


# --- data -------------------------------------------------------------------

def bars_from_prices(prices: Sequence[float], bar_type: BarType, *,
                     start_ns: int = DEFAULT_START_NS,
                     step_ns: int = NANOS_PER_DAY,
                     volume: float = 1_000_000,
                     price_precision: int = 2) -> list[Bar]:
    """Build daily bars from a close series.

    The high and low are synthesised as close +/- 0.5%, which is a FICTION and
    is named as one: a real bar's range carries information this series does not
    have. It exists so the simulated venue has something to fill against, and no
    strategy here reads it. A strategy that traded the synthetic range would be
    trading an artefact of this function.
    """
    arr = np.asarray(prices, dtype=float)
    if arr.ndim != 1 or arr.size == 0:
        raise ValueError("prices must be a non-empty one-dimensional series")
    if not np.all(np.isfinite(arr)) or np.any(arr <= 0):
        raise ValueError("prices must be finite and positive")

    bars = []
    for i, px in enumerate(arr):
        ts = start_ns + i * step_ns
        bars.append(Bar(
            bar_type=bar_type,
            open=Price(round(float(px), price_precision), price_precision),
            high=Price(round(float(px) * 1.005, price_precision), price_precision),
            low=Price(round(float(px) * 0.995, price_precision), price_precision),
            close=Price(round(float(px), price_precision), price_precision),
            volume=Quantity(volume, 0),
            ts_event=ts, ts_init=ts,
        ))
    return bars


# --- the strategy -----------------------------------------------------------

class MomentumStrategyConfig(StrategyConfig, frozen=True):
    """Parameters for `MomentumStrategy`."""
    bar_type: BarType
    trade_size: Decimal
    lookback: int = 60
    skip: int = 5
    threshold: float = 0.0


class MomentumStrategy(Strategy):
    """Long when trailing momentum is positive, flat otherwise.

    Deliberately unsophisticated. Its job is to exercise the engine and the
    audit, not to make money — and per the null-result benchmark, a rule this
    simple over noise makes none.

    The signal is computed by calling `momentum` from the factor library on the
    closes that have ARRIVED, which is the join that makes both guarantees
    apply: the factor is causality-checked within its array, and the audit
    checks that the array never contains the future.
    """

    def __init__(self, config: MomentumStrategyConfig,
                 audit: LookAheadAudit | None = None) -> None:
        super().__init__(config)
        self.audit = audit
        self.closes: list[float] = []
        self.equity_curve: list[float] = []
        self.signals: list[float] = []
        self.instrument = None
        self._bar_index = -1

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.bar_type.instrument_id)
        if self.instrument is None:
            self.log.error(f"no instrument for {self.config.bar_type.instrument_id}")
            self.stop()
            return
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        self._bar_index += 1
        self.closes.append(float(bar.close))

        if self.audit is not None:
            visible = self.cache.bars(self.config.bar_type)
            max_ts = max((b.ts_event for b in visible), default=None)
            self.audit.observe(bar_index=self._bar_index, current_ts=bar.ts_event,
                               visible_count=len(visible), max_visible_ts=max_ts)

        # `equity` is per-currency (balance + mark value of open positions for a
        # cash account), so the account's own currency is the one to read. Any
        # other choice silently drops positions denominated elsewhere.
        equity = self.portfolio.equity(self.instrument.id.venue) or {}
        money = equity.get(self.instrument.quote_currency)
        self.equity_curve.append(float(money.as_double()) if money is not None
                                 else float("nan"))

        if len(self.closes) <= self.config.lookback:
            self.signals.append(float("nan"))
            return

        # The last value only. Calling momentum() over the whole history on
        # every bar and discarding all but [-1] made the strategy O(n^2): about
        # 50M pure-Python iterations on a 10,000-bar run, all of it repeating
        # work done on the previous bar. The definition is checked against the
        # array implementation in tests/test_backtest.py.
        signal = (self.closes[-1 - self.config.skip]
                  / self.closes[-1 - self.config.lookback] - 1.0)
        self.signals.append(float(signal))

        long_now = self.portfolio.is_net_long(self.instrument.id)
        want_long = signal > self.config.threshold

        if want_long and not long_now:
            self._order(OrderSide.BUY)
        elif not want_long and long_now:
            self._order(OrderSide.SELL)

    def _order(self, side: OrderSide) -> None:
        self.submit_order(self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=side,
            quantity=self.instrument.make_qty(self.config.trade_size),
        ))


# --- the run ----------------------------------------------------------------

def per_period_sharpe(equity: Sequence[float]) -> float:
    """Sharpe of an equity curve, PER PERIOD — the unit `core.py` requires.

    Not annualised. Passing an annualised Sharpe into `deflated_sharpe_ratio`
    alongside a daily sample length asks a different question than the one
    intended, confidently; the units note at the top of core.py is about exactly
    this. De-annualisation is the caller's business and is not done silently.
    """
    arr = np.asarray(equity, dtype=float)
    if arr.size < 3:
        return 0.0
    # Difference FIRST, then drop non-finite returns. Filtering the equity curve
    # beforehand spliced non-adjacent points together and invented a return
    # across the gap — a jump from before an outage to after it, counted as one
    # period's performance.
    with np.errstate(divide="ignore", invalid="ignore"):
        returns = np.diff(arr) / arr[:-1]
    returns = returns[np.isfinite(returns)]
    if returns.size < 2:
        return 0.0
    sd = float(np.std(returns, ddof=1))
    if sd == 0.0:
        return 0.0
    return float(np.mean(returns) / sd)


def run_backtest(prices: Sequence[float], *,
                 lookback: int = 60,
                 skip: int = 5,
                 trade_size: int = 100,
                 starting_cash: float = 1_000_000,
                 symbol: str = "ACME",
                 venue_name: str = "XNAS",
                 cost_spec: CostSpec | None = None,
                 fill_model: FillModel | None = None,
                 latency_model: LatencyModel | None = None,
                 counter: Any | None = None,
                 dataset_id: str = "backtest",
                 search_id: str | None = None,
                 audit: bool = True) -> dict[str, Any]:
    """Run one event-driven backtest and return its result.

    The trial is registered with `counter` BEFORE the engine starts, so a run
    that raises is still counted (FR-08). That ordering is the requirement, not
    an implementation detail: a count you can dodge by not liking the answer
    counts nothing.

    Returns a dict carrying the per-period Sharpe, the fills, the commission
    charged by the impact model, and the look-ahead audit.
    """
    venue = Venue(venue_name)
    instrument = TestInstrumentProvider.equity(symbol=symbol, venue=venue_name)
    bar_type = BarType.from_str(f"{instrument.id}-1-DAY-LAST-EXTERNAL")

    trial_id = None
    if counter is not None:
        trial_id = counter.start_trial(
            dataset_id, strategy="momentum",
            params={"lookback": lookback, "skip": skip, "trade_size": trade_size},
            search_id=search_id)

    fee_model = AlmgrenFeeModel(cost_spec) if cost_spec is not None else None
    the_audit = LookAheadAudit() if audit else None

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="BACKTESTER-001",
        logging=LoggingConfig(bypass_logging=True),
    ))
    try:
        engine.add_venue(
            venue=venue, oms_type=OmsType.NETTING, account_type=AccountType.CASH,
            base_currency=USD, starting_balances=[Money(starting_cash, USD)],
            fill_model=fill_model, latency_model=latency_model,
            fee_model=fee_model,
        )
        engine.add_instrument(instrument)
        engine.add_data(bars_from_prices(prices, bar_type))

        strategy = MomentumStrategy(
            config=MomentumStrategyConfig(
                bar_type=bar_type, trade_size=Decimal(trade_size),
                lookback=lookback, skip=skip),
            audit=the_audit)
        engine.add_strategy(strategy)
        engine.run()

        fills = engine.trader.generate_order_fills_report()
        sharpe = per_period_sharpe(strategy.equity_curve)
        result = {
            "sharpe": sharpe,
            "n_bars": len(strategy.closes),
            "n_fills": len(fills),
            "final_equity": (strategy.equity_curve[-1]
                             if strategy.equity_curve else float("nan")),
            "commission_charged": sum(c["total"] for c in fee_model.charges)
                                  if fee_model else 0.0,
            "impact_charges": list(fee_model.charges) if fee_model else [],
            "look_ahead": the_audit.as_dict() if the_audit else None,
            "params": {"lookback": lookback, "skip": skip},
            "trial_id": trial_id,
        }
        if the_audit is not None:
            the_audit.assert_clean()
        if counter is not None and trial_id is not None:
            counter.record_outcome(trial_id, sharpe=sharpe,
                                   n_observations=len(strategy.closes))
        return result
    finally:
        engine.dispose()
