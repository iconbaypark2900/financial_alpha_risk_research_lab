"""The event-driven engine — FR-19 and FR-21, tested rather than asserted.

These two requirements were previously satisfied by a line in requirements.txt.
The tests here exist because that is exactly how a requirement goes unmet
without anyone noticing: the library genuinely supports the feature, so the
claim reads as true, and nobody checks whether this project actually invokes it.

So each test below either demonstrates the mechanism working on real output, or
pins a limitation as a limitation.
"""
from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

nautilus = pytest.importorskip("nautilus_trader",
                               reason="the engine slice needs nautilus_trader")

from nautilus_trader.backtest.engine import (  # noqa: E402
    BacktestEngine,
    BacktestEngineConfig,
)
from nautilus_trader.backtest.models import FillModel, LatencyModel  # noqa: E402
from nautilus_trader.config import LoggingConfig  # noqa: E402
from nautilus_trader.model.currencies import USD  # noqa: E402
from nautilus_trader.model.data import BarType  # noqa: E402
from nautilus_trader.model.enums import AccountType, OmsType  # noqa: E402
from nautilus_trader.model.identifiers import Venue  # noqa: E402
from nautilus_trader.model.objects import Money  # noqa: E402
from nautilus_trader.test_kit.providers import TestInstrumentProvider  # noqa: E402

from src.research_integrity.backtest import (  # noqa: E402
    AlmgrenFeeModel,
    LookAheadAudit,
    LookAheadDetected,
    MomentumStrategy,
    MomentumStrategyConfig,
    bars_from_prices,
    per_period_sharpe,
    run_backtest,
)
from src.research_integrity.execution_costs import Instrument as CostSpec  # noqa: E402
from src.research_integrity.trial_counter import TrialCounter  # noqa: E402

DAY_NS = 86_400_000_000_000


@pytest.fixture()
def prices() -> np.ndarray:
    rng = np.random.default_rng(0)
    return 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 400)))


@pytest.fixture()
def liquid() -> CostSpec:
    return CostSpec("ACME", price=100.0, adv=1_000_000, daily_volatility=0.02,
                    shares_outstanding=100_000_000)


# --- the engine actually runs ----------------------------------------------

def test_a_backtest_runs_and_reports(prices, liquid):
    result = run_backtest(prices, cost_spec=liquid)
    assert result["n_bars"] == 400
    assert result["n_fills"] > 0, "the strategy never traded; the test proves nothing"
    assert np.isfinite(result["sharpe"])
    assert np.isfinite(result["final_equity"])


def test_the_same_inputs_produce_the_same_result(prices, liquid):
    """No fill model means no randomness, and a backtest that varies run to run
    cannot be replayed by `ExperimentLog` (FR-23)."""
    a = run_backtest(prices, cost_spec=liquid)
    b = run_backtest(prices, cost_spec=liquid)
    assert a["sharpe"] == b["sharpe"]
    assert a["final_equity"] == b["final_equity"]
    assert a["commission_charged"] == b["commission_charged"]


# --- FR-21: look-ahead is structurally impossible, and checked -------------

def test_no_look_ahead_on_an_ordinary_run(prices):
    result = run_backtest(prices)
    audit = result["look_ahead"]
    assert audit["clean"]
    assert audit["bars_audited"] == 400, "the audit must see every bar"
    assert audit["violations"] == []


def test_the_audit_catches_future_data_smuggled_into_the_cache():
    """The teeth test. An audit that has never failed is a decoration.

    A strategy that puts a bar from 120 days ahead into the cache is doing, by
    hand, what an array-indexing backtest does by accident. The audit must
    notice on the very next bar.
    """
    venue = Venue("XNAS")
    instrument = TestInstrumentProvider.equity(symbol="ACME", venue="XNAS")
    bar_type = BarType.from_str(f"{instrument.id}-1-DAY-LAST-EXTERNAL")
    rng = np.random.default_rng(1)
    series = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 200)))
    bars = bars_from_prices(series, bar_type)

    class Cheating(MomentumStrategy):
        def on_bar(self, bar):
            if self._bar_index == 79:
                self.cache.add_bar(bars[-1])
            super().on_bar(bar)

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="BACKTESTER-001", logging=LoggingConfig(bypass_logging=True)))
    try:
        engine.add_venue(venue=venue, oms_type=OmsType.NETTING,
                         account_type=AccountType.CASH, base_currency=USD,
                         starting_balances=[Money(1_000_000, USD)])
        engine.add_instrument(instrument)
        engine.add_data(bars)
        audit = LookAheadAudit()
        engine.add_strategy(Cheating(
            config=MomentumStrategyConfig(bar_type=bar_type,
                                          trade_size=Decimal(100),
                                          lookback=60, skip=5),
            audit=audit))
        engine.run()
    finally:
        engine.dispose()

    assert not audit.clean
    assert audit.violations[0]["bar_index"] == 80, "caught on the very next bar"
    assert audit.violations[0]["reason"] == "future data visible"
    with pytest.raises(LookAheadDetected, match="look-ahead violation"):
        audit.assert_clean()


def test_the_audit_notices_more_bars_than_were_delivered():
    """The second property, on its own: data that never came through the bus.

    Future data is the obvious contamination. Extra PAST data is the subtle one
    — a cache pre-loaded with history the strategy was never sent still means
    the run is not the run it claims to be.
    """
    audit = LookAheadAudit()
    audit.observe(bar_index=10, current_ts=1_000, visible_count=25,
                  max_visible_ts=900)
    assert not audit.clean
    assert audit.violations[0]["reason"] == "more bars visible than delivered"
    assert audit.violations[0]["delivered"] == 11


def test_fewer_visible_bars_than_delivered_is_not_a_violation():
    """Nautilus keeps bars in a deque(maxlen=bar_capacity), default 10,000, so
    a long run legitimately sees fewer than it was sent.

    The check was an equality, which turned every bar past the cap into a
    violation and aborted clean runs of more than 10,000 bars — 40 years of
    daily data, or a month of minute bars. A guard that fires on correct
    behaviour gets switched off, and then it guards nothing.
    """
    audit = LookAheadAudit()
    for bar_index in range(60):
        audit.observe(bar_index=bar_index, current_ts=1_000 + bar_index,
                      visible_count=min(bar_index + 1, 50),
                      max_visible_ts=1_000 + bar_index)
    assert audit.clean, audit.violations
    assert audit.observations == 60


def test_a_contaminated_run_does_not_record_an_outcome(tmp_path, monkeypatch):
    """A look-ahead failure must not quietly become a Sharpe ratio.

    The trial is still COUNTED — it was run — but its result is inadmissible,
    so no outcome is recorded against it.
    """
    counter = TrialCounter(tmp_path / "trials.db")

    def contaminated(self, **kwargs):
        self.violations.append({"bar_index": 0, "reason": "planted"})

    monkeypatch.setattr(LookAheadAudit, "observe", contaminated)
    rng = np.random.default_rng(2)
    series = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 150)))

    with pytest.raises(LookAheadDetected):
        run_backtest(series, counter=counter, dataset_id="ds", lookback=30, skip=2)

    assert counter.trial_count("ds") == 1, "the trial must still be counted"
    assert counter.trials("ds")[0]["sharpe"] is None, "but with no outcome"


# --- FR-19: latency and fills are engaged, not merely configured ----------

def test_latency_changes_the_result(prices):
    """If configuring a latency model changed nothing, it would not be wired in.

    Five days of latency is absurd as a market assumption and deliberate as a
    test: it must move the result far enough that the effect cannot be noise.
    """
    base = run_backtest(prices)
    delayed = run_backtest(prices,
                           latency_model=LatencyModel(base_latency_nanos=5 * DAY_NS))
    assert delayed["final_equity"] != base["final_equity"]
    assert delayed["n_fills"] != base["n_fills"]


def test_slippage_changes_the_result(prices):
    base = run_backtest(prices)
    slipped = run_backtest(prices,
                           fill_model=FillModel(prob_slippage=1.0, random_seed=7))
    assert slipped["final_equity"] != base["final_equity"]


def test_market_orders_against_daily_bars_do_not_partially_fill():
    """A LIMITATION, pinned as one rather than glossed.

    FR-19 names partial fills. NautilusTrader models them — against order-book
    depth, or for resting limit orders. It does NOT produce them for market
    orders filled against bars, even at 100x the bar's volume and with
    `liquidity_consumption=True`, because a bar carries no depth to consume.

    This project has no order-book data, so the partial-fill half of FR-19 is
    NOT demonstrated. That is worth a failing-looking test rather than silence:
    if book data is ever added and this assertion starts failing, the situation
    has improved and the docs should say so.
    """
    venue = Venue("XNAS")
    instrument = TestInstrumentProvider.equity(symbol="ACME", venue="XNAS")
    bar_type = BarType.from_str(f"{instrument.id}-1-DAY-LAST-EXTERNAL")
    rng = np.random.default_rng(0)
    series = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 300)))

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="BACKTESTER-001", logging=LoggingConfig(bypass_logging=True)))
    try:
        engine.add_venue(venue=venue, oms_type=OmsType.NETTING,
                         account_type=AccountType.CASH, base_currency=USD,
                         starting_balances=[Money(50_000_000, USD)],
                         liquidity_consumption=True)
        engine.add_instrument(instrument)
        # Orders are 100x each bar's entire volume.
        engine.add_data(bars_from_prices(series, bar_type, volume=1_000))
        engine.add_strategy(MomentumStrategy(
            config=MomentumStrategyConfig(bar_type=bar_type,
                                          trade_size=Decimal(100_000),
                                          lookback=60, skip=5)))
        engine.run()
        orders = engine.trader.generate_orders_report()
    finally:
        engine.dispose()

    assert len(orders) > 0
    quantity = orders["quantity"].astype(float)
    filled = orders["filled_qty"].astype(float)
    partial = ((filled > 0) & (filled < quantity)).sum()
    assert partial == 0, (
        "partial fills now occur — book data must have been added. FR-19's "
        "partial-fill requirement may now be genuinely met; update the docs.")


# --- FR-17 inside the engine ----------------------------------------------

def test_the_impact_model_is_actually_consulted(prices, liquid):
    """The commission has to come from OUR model, not from the engine default."""
    result = run_backtest(prices, cost_spec=liquid)
    assert result["commission_charged"] > 0
    assert len(result["impact_charges"]) == result["n_fills"]
    assert all(c["total_bps"] > 0 for c in result["impact_charges"])


def test_no_cost_spec_means_no_commission(prices):
    """The default must not silently invent a cost."""
    assert run_backtest(prices)["commission_charged"] == 0.0


def test_the_same_order_costs_more_in_an_illiquid_name(prices):
    """FR-17's whole content, surviving the trip through the engine: impact is
    a function of participation, so the identical order costs far more where the
    volume is thinner.

    The order has to be big enough for participation to matter. At the default
    100 shares the two names differ by 7%, not 13x — 100 shares is 0.001% of one
    ADV and 0.1% of the other, and at both of those the participation term is
    swamped by the spread. That is the model behaving correctly: a 100-share
    order moves nothing anywhere. 100,000 shares is 1% of a day in the liquid
    name and a whole day in the thin one, which is the comparison FR-17 is about.
    """
    liquid = CostSpec("ACME", price=100.0, adv=10_000_000, daily_volatility=0.02,
                      shares_outstanding=1_000_000_000)
    thin = CostSpec("ACME", price=100.0, adv=100_000, daily_volatility=0.02,
                    shares_outstanding=10_000_000)
    big = run_backtest(prices, cost_spec=liquid, trade_size=100_000,
                       starting_cash=500_000_000)
    small = run_backtest(prices, cost_spec=thin, trade_size=100_000,
                         starting_cash=500_000_000)
    assert small["n_fills"] == big["n_fills"], "compare like with like"
    assert small["commission_charged"] > big["commission_charged"] * 5


def test_the_fee_model_returns_money_in_the_account_currency(liquid):
    model = AlmgrenFeeModel(liquid)
    money = model.get_commission(order=None, fill_qty=1_000, fill_px=None,
                                 instrument=None)
    assert money.currency == USD
    assert money.as_double() > 0
    assert model.charges[0]["shares"] == 1_000


# --- FR-08: the counter sees every run, including the ones that fail -------

def test_every_run_is_counted_before_it_can_succeed(tmp_path, prices, liquid):
    counter = TrialCounter(tmp_path / "trials.db")
    run_backtest(prices, cost_spec=liquid, counter=counter, dataset_id="sp500")
    run_backtest(prices, cost_spec=liquid, counter=counter, dataset_id="sp500",
                 lookback=90)
    assert counter.trial_count("sp500") == 2
    assert all(t["sharpe"] is not None for t in counter.trials("sp500"))


def test_a_run_that_crashes_is_still_counted(tmp_path):
    """The clause that shapes the whole design: FR-08 counts runs "whose
    results were discarded". A backtest that blows up is the purest case."""
    counter = TrialCounter(tmp_path / "trials.db")
    with pytest.raises(ValueError):
        run_backtest([100.0, -5.0, 102.0], counter=counter, dataset_id="sp500")
    assert counter.trial_count("sp500") == 1
    assert counter.trials("sp500")[0]["sharpe"] is None


def test_the_counted_trials_feed_the_deflation(tmp_path, prices, liquid):
    """The join the counter exists for, end to end through the engine."""
    from src.research_integrity import deflated_sharpe_ratio

    counter = TrialCounter(tmp_path / "trials.db")
    for lookback in (30, 45, 60, 75, 90):
        run_backtest(prices, cost_spec=liquid, counter=counter,
                     dataset_id="sp500", lookback=lookback, search_id="sweep")
    inputs = counter.deflation_inputs("sp500")
    assert inputs["n_trials"] == 5
    dsr = deflated_sharpe_ratio(observed_sharpe=0.02, n_trials=inputs["n_trials"],
                                sample_length=400, skewness=0.0, kurtosis=3.0,
                                var_trials=inputs["var_trials"])
    assert 0.0 <= dsr <= 1.0


# --- units and inputs ------------------------------------------------------

def test_the_sharpe_is_in_units_core_will_accept(prices, liquid):
    """The units join, tested where it actually breaks.

    `deflated_sharpe_ratio` REJECTS a per-period Sharpe above 1.0, on the
    grounds that it is almost always an annualised figure passed by mistake. So
    the engine handing it an annualised number would not be a silent error, it
    would be a loud one — but only if something ever passes one to the other.
    This is that something.
    """
    from src.research_integrity import deflated_sharpe_ratio

    result = run_backtest(prices, cost_spec=liquid)
    assert abs(result["sharpe"]) <= 1.0, "this looks annualised"
    deflated_sharpe_ratio(observed_sharpe=result["sharpe"], n_trials=10,
                          sample_length=result["n_bars"], skewness=0.0,
                          kurtosis=3.0, var_trials=1e-4)


def test_sharpe_of_a_noiseless_curve_is_finite():
    """Constant compound growth has near-zero return variance, so the ratio is
    enormous and meaningless. It must at least stay finite rather than becoming
    inf or nan and poisoning everything downstream."""
    equity = [100.0 * 1.001 ** i for i in range(300)]
    sharpe = per_period_sharpe(equity)
    assert np.isfinite(sharpe)
    assert sharpe > 0


def test_sharpe_of_a_flat_curve_is_zero():
    assert per_period_sharpe([100.0] * 50) == 0.0


def test_sharpe_of_too_short_a_curve_is_zero():
    assert per_period_sharpe([100.0, 101.0]) == 0.0


@pytest.mark.parametrize("bad", [[], [100.0, float("nan")], [100.0, -1.0],
                                 [100.0, 0.0]])
def test_bad_price_series_are_refused(bad):
    instrument = TestInstrumentProvider.equity(symbol="ACME", venue="XNAS")
    bar_type = BarType.from_str(f"{instrument.id}-1-DAY-LAST-EXTERNAL")
    with pytest.raises(ValueError):
        bars_from_prices(bad, bar_type)


def test_bars_are_strictly_increasing_in_time():
    """The property the engine's ordering guarantee rests on."""
    instrument = TestInstrumentProvider.equity(symbol="ACME", venue="XNAS")
    bar_type = BarType.from_str(f"{instrument.id}-1-DAY-LAST-EXTERNAL")
    bars = bars_from_prices([100.0, 101.0, 102.0, 103.0], bar_type)
    stamps = [b.ts_event for b in bars]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)


# --- found by review, 2026-08-28 -------------------------------------------

def test_the_strategys_signal_matches_the_factor_library(prices):
    """The O(1) form must equal what momentum() computes over the same history.

    on_bar called momentum() across the whole history every bar and kept only
    [-1] — O(n^2), ~50M pure-Python iterations on a 10,000-bar run. The
    replacement is the definition applied directly, and this pins the two
    together so the shortcut cannot drift from the library.
    """
    from src.research_integrity.factors import momentum

    lookback, skip = 60, 5
    closes = list(prices[:200])
    expected = momentum(closes, lookback=lookback, skip=skip)[-1]
    direct = closes[-1 - skip] / closes[-1 - lookback] - 1.0
    assert direct == pytest.approx(expected, rel=1e-12)


def test_the_fee_is_charged_at_the_price_the_order_filled_at(liquid):
    """It was priced off the static spec.price, so on a series drifting from 100
    to 250 a fill at 250 was billed on a notional of 100 x 100 — about 60% of
    the true cost, and the understatement grows with every trending backtest."""
    model = AlmgrenFeeModel(liquid)
    cheap = model.get_commission(order=None, fill_qty=10_000, fill_px=50.0,
                                 instrument=None)
    dear = model.get_commission(order=None, fill_qty=10_000, fill_px=250.0,
                                instrument=None)
    assert dear.as_double() > cheap.as_double()
    assert model.charges[0]["price"] == 50.0
    assert model.charges[1]["price"] == 250.0


def test_the_fee_falls_back_to_the_spec_price_when_no_fill_price_is_given(liquid):
    model = AlmgrenFeeModel(liquid)
    model.get_commission(order=None, fill_qty=1_000, fill_px=None, instrument=None)
    assert model.charges[0]["price"] == liquid.price
