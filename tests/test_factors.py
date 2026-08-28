"""Factor library — known values by hand, and causality checked mechanically.

Every expected value below is derived from the factor's DEFINITION by hand, not
by calling the function and pasting what it said. A test written the second way
pins the behaviour rather than the requirement, and passes forever after the
implementation goes wrong.

The causality tests are the other half. A known-value test proves the arithmetic
at one point; it says nothing about whether the value at time t was computed
from data that arrived at t+1, which is the defect that actually reaches
production.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from src.research_integrity.factors import (
    FACTORS,
    TRADING_DAYS,
    FactorError,
    LookAheadFactor,
    assert_causal,
    book_to_market_as_of,
    momentum,
    realised_volatility,
    reversal,
    size,
)

# Only the fundamental-factor tests need the store. A module-level
# importorskip here skipped all 31 tests without duckdb — including every
# causality test, which depends on nothing but numpy. Skipping tests that would
# have passed is not free: it is coverage that silently is not there, and the
# minimal-install CI job existed to run exactly these.


@pytest.fixture()
def growing() -> np.ndarray:
    """400 prices compounding at exactly 1% a period. Every factor over it has
    a closed form, which is what makes it useful as a fixture."""
    return 100.0 * 1.01 ** np.arange(400)


# --- momentum: known values ------------------------------------------------

def test_momentum_matches_the_closed_form_on_a_geometric_series(growing):
    """At 1% per period, the return from t-252 to t-21 is 1.01**231 - 1,
    independent of t. Computed from the definition, not from the function."""
    expected = 1.01 ** (252 - 21) - 1
    result = momentum(growing)
    assert result[300] == pytest.approx(expected, rel=1e-12)
    assert result[399] == pytest.approx(expected, rel=1e-12)


def test_momentum_on_hand_written_prices():
    """A series short enough to check by eye: lookback 4, skip 1.

    At t=4 the factor is prices[3] / prices[0] - 1 = 130/100 - 1 = 0.30.
    """
    prices = [100.0, 110.0, 120.0, 130.0, 500.0, 600.0]
    result = momentum(prices, lookback=4, skip=1)
    assert result[4] == pytest.approx(0.30)
    # t=5 is prices[4] / prices[1] - 1 = 500/110 - 1
    assert result[5] == pytest.approx(500.0 / 110.0 - 1.0)


def test_momentum_ignores_the_skipped_window_entirely():
    """The skipped month must not enter the value. Move only the last 21
    prices and the factor at the final index must not budge."""
    prices = np.asarray(100.0 * 1.01 ** np.arange(300))
    moved = prices.copy()
    moved[-21:] *= 3.0
    assert momentum(prices)[-1] == pytest.approx(momentum(moved)[-1], rel=1e-12)


def test_momentum_is_nan_exactly_until_it_has_enough_history(growing):
    result = momentum(growing, lookback=252, skip=21)
    assert np.all(np.isnan(result[:252]))
    assert not np.any(np.isnan(result[252:]))


# --- reversal: known values ------------------------------------------------

def test_reversal_is_the_negated_trailing_return():
    """prices rise 20% over the window, so reversal is -0.20."""
    prices = [100.0] * 5 + [120.0]
    assert reversal(prices, lookback=5)[5] == pytest.approx(-0.20)


def test_reversal_is_positive_after_a_fall():
    """The sign convention, as a test: a faller scores HIGH."""
    prices = [100.0] * 5 + [80.0]
    assert reversal(prices, lookback=5)[5] == pytest.approx(0.20)


# --- volatility: known values ----------------------------------------------

def test_realised_volatility_matches_a_hand_computed_sample_deviation():
    """Log returns 0.01, -0.01, 0.02, 0.00 over a 4-period window.

    mean = 0.005; deviations 0.005, -0.015, 0.015, -0.005;
    sum of squares = 5.0e-4; sample variance = 5.0e-4 / 3;
    sigma = sqrt(5.0e-4 / 3); annualised = sigma * sqrt(252).
    """
    log_returns = [0.01, -0.01, 0.02, 0.0]
    prices = [100.0]
    for r in log_returns:
        prices.append(prices[-1] * math.exp(r))

    expected = math.sqrt(5.0e-4 / 3) * math.sqrt(TRADING_DAYS)
    assert realised_volatility(prices, window=4)[4] == pytest.approx(expected, rel=1e-12)
    # Pinned decimal, so a change to either side of the comparison is visible.
    assert realised_volatility(prices, window=4)[4] == pytest.approx(0.204939, abs=1e-6)


def test_realised_volatility_uses_the_sample_correction():
    """ddof=1, not 0. The two differ by sqrt(n/(n-1)) — about 2.5% at a window
    of 21, which is small enough to pass inspection and large enough to reorder
    a decile sort."""
    rng = np.random.default_rng(1)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 200)))
    window = 21
    got = realised_volatility(prices, window=window, annualise=False)[100]
    log_returns = np.diff(np.log(prices))[100 - window:100]
    population = np.std(log_returns, ddof=0)
    assert got == pytest.approx(np.std(log_returns, ddof=1), rel=1e-12)
    assert got != pytest.approx(population, rel=1e-6)


def test_annualisation_is_a_factor_of_sqrt_252():
    rng = np.random.default_rng(2)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 100)))
    raw = realised_volatility(prices, window=21, annualise=False)
    annual = realised_volatility(prices, window=21, annualise=True)
    assert annual[50] == pytest.approx(raw[50] * math.sqrt(252), rel=1e-12)


# --- size ------------------------------------------------------------------

def test_size_is_the_natural_log_of_market_cap():
    assert size([math.e, math.e ** 2])[0] == pytest.approx(1.0)
    assert size([math.e, math.e ** 2])[1] == pytest.approx(2.0)


# --- causality, checked rather than trusted --------------------------------

@pytest.mark.parametrize("factor_fn", [momentum, reversal, realised_volatility])
def test_every_price_factor_is_causal(growing, factor_fn):
    """Split at 350 so the head contains real values for every factor here —
    a head of NaN would compare equal to itself and prove nothing."""
    assert_causal(factor_fn, growing, split=350)


def test_assert_causal_catches_a_forward_looking_window(growing):
    """The off-by-one. It is one character's difference from the correct
    version and produces a backtest that looks excellent."""
    def leaky(prices):
        arr = np.asarray(prices, dtype=float)
        out = np.full(arr.size, np.nan)
        for t in range(21, arr.size - 1):
            out[t] = arr[t + 1] / arr[t - 21] - 1.0      # t+1 is the future
        return out

    with pytest.raises(LookAheadFactor, match="reads the future"):
        assert_causal(leaky, growing, split=350)


def test_assert_causal_catches_normalisation_over_the_whole_series(growing):
    """The subtler leak, and the one that survives review: each value is
    causal, but the mean subtracted from it was computed over data that had
    not happened yet."""
    def centred(prices):
        m = momentum(prices)
        return m - np.nanmean(m)

    with pytest.raises(LookAheadFactor):
        assert_causal(centred, growing, split=350)


def test_assert_causal_refuses_a_vacuous_comparison(growing):
    """The bug this function had before this test existed.

    At the default midpoint split, momentum's 252-period warm-up leaves the
    entire head NaN, NaN compares equal to NaN, and the check passes without
    comparing anything — including for a factor that reads the future. A check
    that cannot fail is worse than no check, because it is recorded as a pass.
    """
    with pytest.raises(FactorError, match="vacuous"):
        assert_causal(momentum, growing)          # split defaults to 200


def test_assert_causal_needs_data_on_both_sides(growing):
    with pytest.raises(FactorError, match="split must leave data"):
        assert_causal(momentum, growing, split=399)
    with pytest.raises(FactorError, match="at least 4 observations"):
        assert_causal(momentum, [1.0, 2.0, 3.0])


# --- fundamentals must respect the reporting lag ---------------------------

@pytest.fixture()
def store(tmp_path: Path):
    """Book equity for one company: the quarter ends 2023-12-31 and the filing
    lands 2024-02-15, which is an ordinary six-week lag, not a pathological one.
    """
    pytest.importorskip("duckdb", reason="the point-in-time store needs duckdb")
    from src.research_integrity.point_in_time import PointInTimeStore

    s = PointInTimeStore(tmp_path / "facts.duckdb")
    s.register_dataset("fundamentals", point_in_time=True)
    s.append_facts("fundamentals", [
        {"entity_id": "ACME", "field": "book_equity", "value": 500.0,
         "effective_date": "2023-12-31", "knowledge_date": "2024-02-15"},
    ])
    return s


def test_the_factor_is_undefined_during_the_reporting_lag(store):
    """On 15 January the filing has not happened. The honest factor value is
    None — not the number that will be published a month later."""
    assert book_to_market_as_of(store, "fundamentals", "ACME",
                                knowledge_date="2024-01-15",
                                market_cap=1000.0) is None


def test_the_factor_is_available_once_the_filing_lands(store):
    """500 / 1000 = 0.5, from the day it was actually knowable."""
    assert book_to_market_as_of(store, "fundamentals", "ACME",
                                knowledge_date="2024-02-15",
                                market_cap=1000.0) == pytest.approx(0.5)


def test_using_the_fiscal_period_end_would_have_leaked(store):
    """The size of the error, stated rather than described.

    Joining on the fiscal period end date makes the factor available from
    31 December. Between then and 15 February it is a factor computed from a
    filing that did not exist — six weeks of free knowledge, in the direction
    that flatters the strategy."""
    lagged = book_to_market_as_of(store, "fundamentals", "ACME",
                                  knowledge_date="2024-01-15", market_cap=1000.0)
    published = book_to_market_as_of(store, "fundamentals", "ACME",
                                     knowledge_date="2024-02-15", market_cap=1000.0)
    assert lagged is None and published is not None


def test_a_restatement_does_not_reach_back(store):
    """FR-02: the value known in February stays the value known in February,
    even after March corrects it."""
    store.append_facts("fundamentals", [
        {"entity_id": "ACME", "field": "book_equity", "value": 400.0,
         "effective_date": "2023-12-31", "knowledge_date": "2024-03-20",
         "is_restatement": True},
    ])
    assert book_to_market_as_of(store, "fundamentals", "ACME",
                                knowledge_date="2024-02-20",
                                market_cap=1000.0) == pytest.approx(0.5)


def test_a_restatement_does_not_reach_forward_either(store):
    """FR-02, on the case the other restatement test does not reach.

    `test_a_restatement_does_not_reach_back` queries at 2024-02-20, BEFORE the
    March restatement exists, so it passes whatever the selection logic does.
    Querying AFTER it — which is when a researcher would actually run — exposed
    the bug: `facts[-1]` from an `as_of` result ordered by (effective_date,
    knowledge_date) takes the highest knowledge_date, i.e. the restatement.
    It returned 0.4 where FR-02 requires the 0.5 that was on the wire.
    """
    store.append_facts("fundamentals", [
        {"entity_id": "ACME", "field": "book_equity", "value": 400.0,
         "effective_date": "2023-12-31", "knowledge_date": "2024-03-20",
         "is_restatement": True},
    ])
    assert book_to_market_as_of(store, "fundamentals", "ACME",
                                knowledge_date="2024-04-01",
                                market_cap=1000.0) == pytest.approx(0.5)


def test_the_latest_known_period_wins_but_its_first_report_is_used(store):
    """Two selections that must not be conflated: the most recent fiscal period
    KNOWN by the date, and within it the value FIRST reported."""
    store.append_facts("fundamentals", [
        # A later period, filed later still.
        {"entity_id": "ACME", "field": "book_equity", "value": 600.0,
         "effective_date": "2024-03-31", "knowledge_date": "2024-05-15"},
        # …and restated.
        {"entity_id": "ACME", "field": "book_equity", "value": 550.0,
         "effective_date": "2024-03-31", "knowledge_date": "2024-06-20",
         "is_restatement": True},
    ])
    # Before Q1 is filed: still the Q4 figure, as first reported.
    assert book_to_market_as_of(store, "fundamentals", "ACME",
                                knowledge_date="2024-04-01",
                                market_cap=1000.0) == pytest.approx(0.5)
    # After Q1 is filed and restated: Q1's FIRST report, not its restatement.
    assert book_to_market_as_of(store, "fundamentals", "ACME",
                                knowledge_date="2024-07-01",
                                market_cap=1000.0) == pytest.approx(0.6)


def test_the_factor_refuses_a_dataset_with_no_point_in_time_guarantee(tmp_path):
    """FR-07 propagates: a factor over a non-PIT dataset must refuse, not warn."""
    pytest.importorskip("duckdb", reason="the point-in-time store needs duckdb")
    from src.research_integrity.point_in_time import PointInTimeError, PointInTimeStore

    s = PointInTimeStore(tmp_path / "bad.duckdb")
    s.register_dataset("vendor_snapshot", point_in_time=False,
                       pit_note="vendor overwrites history in place")
    with pytest.raises(PointInTimeError):
        book_to_market_as_of(s, "vendor_snapshot", "ACME",
                             knowledge_date="2024-02-15", market_cap=1000.0)


# --- input validation ------------------------------------------------------

@pytest.mark.parametrize("bad", [[], [100.0, float("nan"), 102.0],
                                 [100.0, -5.0], [100.0, 0.0]])
def test_bad_price_series_are_refused(bad):
    with pytest.raises(FactorError):
        momentum(bad, lookback=1, skip=0)


def test_a_lookback_that_does_not_exceed_the_skip_is_refused(growing):
    with pytest.raises(FactorError, match="must exceed skip"):
        momentum(growing, lookback=21, skip=21)
    with pytest.raises(FactorError, match="must exceed skip"):
        momentum(growing, lookback=10, skip=21)


def test_a_volatility_window_of_one_is_refused(growing):
    with pytest.raises(FactorError, match="at least 2"):
        realised_volatility(growing, window=1)


def test_market_cap_must_be_positive(store):
    with pytest.raises(FactorError, match="market_cap must be positive"):
        book_to_market_as_of(store, "fundamentals", "ACME",
                             knowledge_date="2024-02-15", market_cap=0.0)


# --- the registry ----------------------------------------------------------

def test_every_factor_states_its_direction_and_source():
    """A factor whose sign convention lives only in someone's head is the
    reason two correct factors combine into a wrong one."""
    assert FACTORS, "the registry is empty"
    for name, factor in FACTORS.items():
        assert factor.name == name
        assert factor.citation.strip(), f"{name} has no citation"
        assert factor.direction.strip(), f"{name} has no stated direction"
        assert any(year in factor.citation for year in
                   ("199", "200", "201", "202")), f"{name}'s citation has no year"


def test_the_registry_covers_what_the_module_exports():
    """A factor that exists but is not registered has no stated direction, which
    is the same as not having one."""
    assert set(FACTORS) == {"momentum", "reversal", "volatility", "size",
                            "book_to_market"}
