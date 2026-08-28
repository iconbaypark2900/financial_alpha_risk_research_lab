"""Monte Carlo simulation — with a regression test per defect in the original.

finGuard's simulator was rewritten rather than migrated, because its output was
a product of defects rather than merely unverified: it drove every path through
the sign-inverting portfolio Kelly and the self-diluting drawdown control, then
measured the results against the wrong denominator with an unseeded generator
and a shared peak. Each of those has a test below named after it.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.portfolio.drawdown import max_drawdown
from src.portfolio.kelly import KellyError
from src.portfolio.simulator import (
    SimulationError,
    SimulationResult,
    sample_scenarios,
    simulate,
    statistics,
    stress,
)

MU = np.array([0.0004, 0.0003])
COV = np.array([[0.0001, 0.00002], [0.00002, 0.00009]])


# --- FR-23: reproducible, and not by accident -----------------------------

def test_the_seed_is_required():
    """No default. An unseeded distribution looks exactly like a seeded one and
    cannot be reproduced, which is the failure FR-23 exists to prevent — and
    finGuard called np.random.multivariate_normal with no random_state at all."""
    with pytest.raises(TypeError, match="seed"):
        simulate(MU, COV, n_paths=10, horizon=10)      # type: ignore[call-arg]


def test_the_same_seed_gives_identical_results():
    a = simulate(MU, COV, seed=7, n_paths=200, horizon=60)
    b = simulate(MU, COV, seed=7, n_paths=200, horizon=60)
    assert np.array_equal(a.terminal_values, b.terminal_values)
    assert np.array_equal(a.max_drawdowns, b.max_drawdowns)


def test_different_seeds_give_different_results():
    """Otherwise the seed is decorative and the first test proves nothing."""
    a = simulate(MU, COV, seed=1, n_paths=200, horizon=60)
    b = simulate(MU, COV, seed=2, n_paths=200, horizon=60)
    assert not np.array_equal(a.terminal_values, b.terminal_values)


# --- the cross-path state leak --------------------------------------------

def test_each_paths_drawdown_is_computed_from_its_own_peak():
    """THE defect that made the old distribution an artefact of iteration order.

    finGuard shared one DrawdownManager across every simulation and never reset
    its peak_value, so path 2 inherited path 1's high-water mark and began
    already underwater. Checked here by recomputing each path's drawdown
    independently with the primitive from drawdown.py, which is itself tested
    against hand-worked values: if any peak were shared, the reported maxima
    could not match a per-path recomputation.
    """
    result = simulate(MU, COV, seed=3, n_paths=60, horizon=120, keep_paths=True)
    assert result.paths is not None

    for i, path in enumerate(result.paths):
        assert result.max_drawdowns[i] == pytest.approx(max_drawdown(path)), (
            f"path {i}'s reported drawdown disagrees with its own equity curve")


def test_a_rising_path_does_not_throttle_a_falling_one():
    """The consequence, stated directly: outcomes must not depend on how many
    other paths were simulated alongside them, nor on their order."""
    result = simulate(MU, COV, seed=11, n_paths=40, horizon=90, keep_paths=True)
    best = int(np.argmax(result.terminal_values))
    worst = int(np.argmin(result.terminal_values))
    assert result.max_drawdowns[worst] == pytest.approx(
        max_drawdown(result.paths[worst]))
    assert result.max_drawdowns[best] == pytest.approx(
        max_drawdown(result.paths[best]))


# --- statistics measured against the right denominator --------------------

def test_returns_are_measured_against_the_initial_value():
    """Five paths from 100 ending at [120, 100, 80, 150, 90]: two are losses,
    so P(loss) is 0.4. finGuard divided by final_values[0] — the terminal value
    of path 0 — and reported 0.6, with path 0's return always exactly zero.
    """
    result = SimulationResult(
        terminal_values=np.array([120.0, 100.0, 80.0, 150.0, 90.0]),
        max_drawdowns=np.zeros(5), initial_value=100.0, horizon=252, seed=0,
        target_weights=np.array([1.0]), ruined=np.zeros(5, dtype=bool))
    stats = statistics(result)

    assert stats.probability_of_loss == pytest.approx(0.4)
    assert stats.best_terminal_return == pytest.approx(0.50)
    assert stats.worst_terminal_return == pytest.approx(-0.20)


def test_annualisation_over_a_full_year_is_the_identity():
    """horizon == trading_days means the annualised return equals the total."""
    result = SimulationResult(
        terminal_values=np.array([110.0, 90.0]), max_drawdowns=np.zeros(2),
        initial_value=100.0, horizon=252, seed=0,
        target_weights=np.array([1.0]), ruined=np.zeros(2, dtype=bool))
    stats = statistics(result)
    assert stats.mean_annualised_return == pytest.approx(0.0)
    assert stats.best_terminal_return == pytest.approx(0.10)


def test_a_half_year_horizon_annualises_by_squaring():
    """126 periods is half of 252, so a 10% gain annualises to 1.1**2 - 1."""
    result = SimulationResult(
        terminal_values=np.array([110.0]), max_drawdowns=np.zeros(1),
        initial_value=100.0, horizon=126, seed=0,
        target_weights=np.array([1.0]), ruined=np.zeros(1, dtype=bool))
    stats = statistics(result)
    assert stats.mean_annualised_return == pytest.approx(1.1 ** 2 - 1)


def test_terminal_dispersion_is_not_called_a_sharpe_ratio():
    """finGuard reported the cross-path spread of terminal outcomes as
    `volatility` and mean/that as `sharpe_ratio`. It is neither."""
    stats = statistics(simulate(MU, COV, seed=5, n_paths=100, horizon=60))
    assert hasattr(stats, "terminal_dispersion")
    assert not hasattr(stats, "sharpe_ratio")
    assert not hasattr(stats, "volatility")


# --- known values ----------------------------------------------------------

def test_a_zero_variance_simulation_is_exactly_computable():
    """With no covariance every draw equals the mean, so every path is the same
    deterministic compounding and the terminal value has a closed form."""
    mu = np.array([0.001])
    cov = np.zeros((1, 1))
    horizon = 100
    result = simulate(mu, cov, seed=0, n_paths=5, horizon=horizon,
                      weights=[1.0], initial_value=100.0, drawdown_limit=None)

    expected = 100.0 * (1.001 ** horizon)
    assert result.terminal_values == pytest.approx(expected)
    assert result.max_drawdowns == pytest.approx(0.0)


def test_a_zero_return_zero_variance_portfolio_never_moves():
    result = simulate(np.array([0.0]), np.zeros((1, 1)), seed=0, n_paths=3,
                      horizon=50, weights=[1.0], initial_value=1000.0)
    assert result.terminal_values == pytest.approx(1000.0)


def test_holding_only_cash_is_flat():
    """Zero weight in the risky asset means the value cannot change."""
    result = simulate(MU, COV, seed=0, n_paths=10, horizon=60,
                      weights=[0.0, 0.0], initial_value=500.0)
    assert result.terminal_values == pytest.approx(500.0)
    assert result.max_drawdowns == pytest.approx(0.0)


# --- the policy ------------------------------------------------------------

def test_the_drawdown_throttle_reduces_exposure():
    """A tight limit must produce shallower drawdowns than no limit at all."""
    throttled = simulate(MU, COV, seed=9, n_paths=300, horizon=252,
                         weights=[1.5, 1.5], drawdown_limit=0.05,
                         rebalance_every=5)
    unthrottled = simulate(MU, COV, seed=9, n_paths=300, horizon=252,
                           weights=[1.5, 1.5], drawdown_limit=None,
                           rebalance_every=5)
    assert throttled.max_drawdowns.mean() < unthrottled.max_drawdowns.mean()


def test_the_kelly_target_defaults_to_half():
    """Full Kelly is growth-optimal and far too volatile to trade; Thorp says so
    and the default follows him rather than the formula."""
    from src.portfolio.kelly import portfolio_kelly

    full = portfolio_kelly(MU, COV).weights
    result = simulate(MU, COV, seed=0, n_paths=5, horizon=10)
    assert result.target_weights == pytest.approx(full * 0.5)


def test_a_singular_covariance_propagates_rather_than_falling_back():
    """finGuard's Kelly returned equal weights on a singular covariance, so the
    simulator's rebalancing silently degraded to equal-weight."""
    singular = np.array([[0.0001, 0.0001], [0.0001, 0.0001]])
    with pytest.raises(KellyError, match="singular"):
        simulate(MU, singular, seed=0, n_paths=5, horizon=10)


def test_explicit_weights_bypass_kelly_entirely():
    result = simulate(MU, COV, seed=0, n_paths=5, horizon=10, weights=[0.3, 0.2])
    assert result.target_weights == pytest.approx([0.3, 0.2])


# --- ruin ------------------------------------------------------------------

def test_a_ruined_path_stops_at_zero_rather_than_going_negative():
    """A drawdown ratio against a negative equity is meaningless, not large."""
    catastrophic = np.array([-0.5])
    cov = np.array([[0.25]])
    result = simulate(catastrophic, cov, seed=0, n_paths=50, horizon=100,
                      weights=[3.0], initial_value=100.0)
    assert np.all(result.terminal_values >= 0.0)
    assert result.ruin_probability > 0
    assert np.all(np.isfinite(result.max_drawdowns))


# --- stress ----------------------------------------------------------------

def test_the_volatility_multiplier_multiplies_volatility_not_variance():
    """finGuard scaled the covariance directly, so a scenario documented as a
    3x volatility shock delivered sqrt(3) = 1.73x — barely half the stress it
    claimed, in the scenario that matters most.

    Measured with the throttle OFF. With it on, the shocked paths draw down
    further and are de-risked harder, which compresses the terminal spread to
    about 2x and hides the difference between the two scalings — see the test
    below, which pins that compression deliberately. A test of the scaling has
    to isolate the scaling.
    """
    kwargs = dict(n_paths=2000, horizon=252, weights=[1.0, 1.0],
                  drawdown_limit=None)
    base = simulate(MU, COV, seed=4, **kwargs)
    shocked = stress(MU, COV, scenarios={"triple": {"volatility_multiplier": 3.0}},
                     seed=4, **kwargs)["triple"]
    correct = float(np.std(shocked.terminal_values) / np.std(base.terminal_values))

    # What the old covariance-scaling would have produced, for contrast.
    buggy_equivalent = simulate(MU, COV * 3.0, seed=4, **kwargs)
    buggy = float(np.std(buggy_equivalent.terminal_values)
                  / np.std(base.terminal_values))

    assert correct > 2.5, f"a 3x volatility shock only widened the spread {correct:.2f}x"
    assert buggy < 2.0, "the contrast case should reproduce the old behaviour"
    assert correct > buggy * 1.5


def test_the_throttle_compresses_a_volatility_shock():
    """Why the test above turns the throttle off, kept as a property.

    A drawdown control does its job under stress: the shocked paths fall further,
    get de-risked harder, and their terminal spread grows by noticeably less
    than the shock itself. That is the control working, and it is also why it
    must not be left on when measuring the shock.
    """
    kwargs = dict(n_paths=2000, horizon=252, weights=[1.0, 1.0])
    scenario = {"triple": {"volatility_multiplier": 3.0}}

    free = (np.std(stress(MU, COV, scenarios=scenario, seed=4,
                          drawdown_limit=None, **kwargs)["triple"].terminal_values)
            / np.std(simulate(MU, COV, seed=4, drawdown_limit=None,
                              **kwargs).terminal_values))
    throttled = (np.std(stress(MU, COV, scenarios=scenario, seed=4,
                               drawdown_limit=0.20, **kwargs)["triple"].terminal_values)
                 / np.std(simulate(MU, COV, seed=4, drawdown_limit=0.20,
                                   **kwargs).terminal_values))
    assert throttled < free


def test_every_scenario_gets_its_own_seed_and_stays_reproducible():
    scenarios = sample_scenarios()
    first = stress(MU, COV, scenarios=scenarios, seed=1, n_paths=50, horizon=30)
    again = stress(MU, COV, scenarios=scenarios, seed=1, n_paths=50, horizon=30)

    assert set(first) == set(scenarios)
    for name in scenarios:
        assert np.array_equal(first[name].terminal_values,
                              again[name].terminal_values)
    seeds = {r.seed for r in first.values()}
    assert len(seeds) == len(scenarios), "scenarios must be independent draws"


def test_the_crash_scenario_is_worse_than_the_bull_scenario():
    results = stress(MU, COV, scenarios=sample_scenarios(), seed=2,
                     n_paths=300, horizon=126, weights=[1.0, 1.0])
    crash = statistics(results["market_crash"])
    bull = statistics(results["bull_market"])
    assert crash.probability_of_loss > bull.probability_of_loss
    assert crash.mean_max_drawdown > bull.mean_max_drawdown


def test_a_negative_volatility_multiplier_is_refused():
    with pytest.raises(SimulationError, match="volatility_multiplier"):
        stress(MU, COV, scenarios={"bad": {"volatility_multiplier": -1.0}}, seed=0)


def test_no_scenarios_is_refused():
    with pytest.raises(SimulationError, match="no scenarios"):
        stress(MU, COV, scenarios={}, seed=0)


# --- refusals --------------------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    {"initial_value": 0.0}, {"n_paths": 0}, {"horizon": 0},
    {"rebalance_every": 0}, {"drawdown_limit": 0.0}, {"drawdown_limit": 1.5},
    {"throttle_floor": -0.1}, {"weights": [1.0]},
])
def test_bad_simulation_inputs_are_refused(kwargs):
    with pytest.raises(SimulationError):
        simulate(MU, COV, seed=0, **{"n_paths": 5, "horizon": 10, **kwargs})


@pytest.mark.parametrize("mu, cov", [
    ([0.1, 0.1, 0.1], COV),
    ([], np.zeros((0, 0))),
    ([float("nan"), 0.1], COV),
])
def test_malformed_moments_are_refused(mu, cov):
    with pytest.raises(SimulationError):
        simulate(mu, cov, seed=0, n_paths=5, horizon=10)
