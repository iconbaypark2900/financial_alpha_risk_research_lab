"""Monte Carlo portfolio simulation — PRD 04 §5.5 (V1).

A REWRITE, NOT A MIGRATION

finGuard's `MonteCarloSimulator` could not be verified, because its output was a
product of defects rather than merely untested. It called
`calculate_portfolio_kelly` — which inverted position signs whenever the raw
weights summed negative — on every rebalance of every path, and
`apply_drawdown_control` on every step. Both are corrected in `kelly.py` and
`drawdown.py`; this module is built on the corrected versions.

Three further defects were specific to the simulator, and none of them needed
finance to catch:

  1. EVERY PATH AFTER THE FIRST STARTED UNDERWATER. One `DrawdownManager`
     instance was shared across all simulations and its `peak_value` was never
     reset, so path 2 inherited path 1's high-water mark:

         path 1 climbs to 200   ->  peak_value 200
         path 2 starts at 100   ->  drawdown -50%, immediately throttled

     The distribution of outcomes was an artefact of iteration order. Here the
     peak is a per-path vector that cannot be shared by construction.

  2. RETURNS WERE MEASURED AGAINST SIMULATION 0's TERMINAL WEALTH.
     `total_returns = (final_values - final_values[0]) / final_values[0]`
     divides by the last element of the first path rather than the initial
     value, so path 0's return was always exactly zero whatever it did. On five
     paths ending at [120, 100, 80, 150, 90] from an initial 100, it reported a
     40% probability of loss as 60%.

  3. NOTHING WAS SEEDED. `np.random.multivariate_normal` with no
     `random_state`, in a repository whose FR-23 requires runs to re-execute
     bitwise-identically. `seed` here is a REQUIRED keyword argument with no
     default, because a distribution nobody can reproduce is an anecdote.

Two smaller ones are corrected in passing. The `volatility` reported alongside a
`sharpe_ratio` was the cross-sectional dispersion of terminal outcomes across
paths, which is not a volatility and does not make that ratio a Sharpe — both
are named for what they are below. And `volatility_multiplier` in the stress
scenarios multiplied the COVARIANCE, so a stated 3x volatility shock was
actually sqrt(3) = 1.73x.

WHAT THE POLICY IS

Between rebalances the holdings drift with the assets. At each rebalance the
portfolio is sized to `target_weights * throttle(drawdown)`, so the drawdown
control acts on rebalance dates rather than continuously. That is a modelling
choice and it is the conservative one: throttling continuously assumes you can
de-risk the instant a threshold is crossed, which is an assumption about
execution, not about risk.

Parameters are NOT re-estimated during the simulation. finGuard recomputed the
covariance from a trailing 22-day window on every rebalance, which is singular
for any portfolio wider than 22 assets and near-singular well before that — and
its Kelly silently returned equal weights on a singular covariance, so the
rebalancing quietly degraded to equal-weight without saying so. Simulating
estimation error is a legitimate and different question; answering it needs an
estimator that degrades honestly, not one that hides.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .drawdown import DrawdownError, max_drawdown
from .kelly import HALF_KELLY, KellyError, portfolio_kelly

TRADING_DAYS = 252


class SimulationError(ValueError):
    """A simulation could not be run from the inputs given."""


@dataclass(frozen=True)
class SimulationResult:
    """Terminal outcomes and per-path drawdowns.

    `initial_value` is carried because every return statistic depends on it, and
    the defect this module was rewritten around was computing those returns
    against something else.
    """
    terminal_values: np.ndarray
    max_drawdowns: np.ndarray
    initial_value: float
    horizon: int
    seed: int
    target_weights: np.ndarray
    ruined: np.ndarray
    paths: np.ndarray | None = field(default=None, repr=False, compare=False)

    @property
    def n_paths(self) -> int:
        return int(self.terminal_values.size)

    @property
    def ruin_probability(self) -> float:
        return float(np.mean(self.ruined))


@dataclass(frozen=True)
class SimulationStatistics:
    """Outcome statistics, each named for what it actually measures.

    `terminal_dispersion` is the standard deviation of annualised returns ACROSS
    paths. finGuard called that `volatility` and divided the mean by it to get
    what it called a `sharpe_ratio`. It is neither: a Sharpe is a mean excess
    return over the volatility of returns THROUGH TIME, and the spread of
    terminal outcomes across Monte Carlo draws is a different quantity that
    happens to have the same units.
    """
    mean_annualised_return: float
    median_annualised_return: float
    terminal_dispersion: float
    probability_of_loss: float
    ruin_probability: float
    var_95: float
    var_99: float
    expected_shortfall_95: float
    expected_shortfall_99: float
    mean_max_drawdown: float
    max_drawdown_95: float
    max_drawdown_99: float
    worst_terminal_return: float
    best_terminal_return: float
    n_paths: int


def _validate(mu: np.ndarray, sigma: np.ndarray) -> None:
    if mu.ndim != 1 or mu.size == 0:
        raise SimulationError(f"expected_returns must be a non-empty 1-D array, "
                              f"got shape {mu.shape}")
    if sigma.ndim != 2 or sigma.shape[0] != sigma.shape[1]:
        raise SimulationError(f"covariance must be square, got {sigma.shape}")
    if mu.size != sigma.shape[0]:
        raise SimulationError(f"expected_returns has {mu.size} assets, "
                              f"covariance has {sigma.shape[0]}")
    if not np.all(np.isfinite(mu)) or not np.all(np.isfinite(sigma)):
        raise SimulationError("expected_returns and covariance must be finite")


def simulate(expected_returns: Sequence[float], covariance, *,
             seed: int,
             initial_value: float = 1_000_000.0,
             n_paths: int = 1_000,
             horizon: int = TRADING_DAYS,
             weights: Sequence[float] | None = None,
             kelly_fraction: float = HALF_KELLY,
             risk_free_rate: float = 0.0,
             rebalance_every: int = 22,
             drawdown_limit: float | None = 0.20,
             throttle_floor: float = 0.0,
             keep_paths: bool = False) -> SimulationResult:
    """Simulate `n_paths` portfolio paths under a Kelly-sized, throttled policy.

    `seed` is required and has no default. Every other Monte Carlo parameter has
    a defensible default; the seed does not, because the failure it prevents is
    silent — an unseeded distribution looks exactly like a seeded one and cannot
    be reproduced, which FR-23 forbids for anything this repository records.

    `expected_returns` and `covariance` are PER PERIOD, at the frequency
    `horizon` counts. A daily horizon wants daily moments.

    When `weights` is None the target is `portfolio_kelly(...)` scaled by
    `kelly_fraction`, defaulting to half — full Kelly is the growth-optimal size
    and is far too volatile to trade, which is Thorp's own standing advice.

    Raises:
        SimulationError: on malformed inputs.
        KellyError: propagated when the Kelly target cannot be computed, rather
            than falling back to equal weights.
    """
    mu = np.asarray(expected_returns, dtype=float)
    sigma = np.asarray(covariance, dtype=float)
    _validate(mu, sigma)

    if initial_value <= 0:
        raise SimulationError(f"initial_value must be positive, got {initial_value}")
    if n_paths < 1:
        raise SimulationError(f"n_paths must be at least 1, got {n_paths}")
    if horizon < 1:
        raise SimulationError(f"horizon must be at least 1, got {horizon}")
    if rebalance_every < 1:
        raise SimulationError(
            f"rebalance_every must be at least 1, got {rebalance_every}")
    if drawdown_limit is not None and not 0 < drawdown_limit <= 1:
        raise SimulationError(
            f"drawdown_limit must be in (0, 1] or None, got {drawdown_limit}")
    if not 0.0 <= throttle_floor <= 1.0:
        raise SimulationError(f"throttle_floor must be in [0, 1], got {throttle_floor}")

    if weights is None:
        target = portfolio_kelly(mu, sigma,
                                 risk_free_rate=risk_free_rate).scaled(kelly_fraction).weights
    else:
        target = np.asarray(weights, dtype=float)
        if target.shape != mu.shape:
            raise SimulationError(
                f"weights has shape {target.shape}, expected {mu.shape}")
        if not np.all(np.isfinite(target)):
            raise SimulationError("weights must be finite")

    rng = np.random.default_rng(seed)
    draws = rng.multivariate_normal(mu, sigma, size=(n_paths, horizon))

    value = np.full(n_paths, float(initial_value))
    peak = value.copy()                       # PER PATH. Never shared.
    running_max_dd = np.zeros(n_paths)
    holdings = target[None, :] * value[:, None]
    cash = value - holdings.sum(axis=1)
    paths = np.zeros((n_paths, horizon + 1)) if keep_paths else None
    if paths is not None:
        paths[:, 0] = value

    for step in range(horizon):
        holdings *= 1.0 + draws[:, step, :]
        value = holdings.sum(axis=1) + cash

        # A path that reaches zero is ruined and stays there; letting it go
        # negative would make the drawdown ratio meaningless rather than large.
        ruined_now = value <= 0.0
        if ruined_now.any():
            value = np.where(ruined_now, 0.0, value)
            holdings[ruined_now] = 0.0
            cash = np.where(ruined_now, 0.0, cash)

        peak = np.maximum(peak, value)
        with np.errstate(divide="ignore", invalid="ignore"):
            drawdown = np.where(peak > 0, (peak - value) / peak, 0.0)
        running_max_dd = np.maximum(running_max_dd, drawdown)
        if paths is not None:
            paths[:, step + 1] = value

        if (step + 1) % rebalance_every == 0:
            if drawdown_limit is None:
                keep = np.ones(n_paths)
            else:
                keep = np.maximum(throttle_floor, 1.0 - drawdown / drawdown_limit)
            holdings = target[None, :] * (value * keep)[:, None]
            cash = value - holdings.sum(axis=1)

    return SimulationResult(
        terminal_values=value,
        max_drawdowns=running_max_dd,
        initial_value=float(initial_value),
        horizon=horizon,
        seed=seed,
        target_weights=target,
        ruined=value <= 0.0,
        paths=paths)


def statistics(result: SimulationResult, *,
               trading_days: int = TRADING_DAYS) -> SimulationStatistics:
    """Outcome statistics, measured against the simulation's INITIAL value.

    Which is the whole point: the version this replaces divided by the terminal
    value of path 0.
    """
    total = (result.terminal_values - result.initial_value) / result.initial_value

    # (1 + r) ** (periods per year / horizon) - 1, guarding total wipeout: a
    # fractional power of a negative base is nan, and a nan here would propagate
    # into every statistic below while still looking like a number.
    growth = np.maximum(1.0 + total, 0.0)
    exponent = trading_days / result.horizon
    annualised = np.where(growth > 0, growth ** exponent, 0.0) - 1.0

    var_95 = float(np.percentile(total, 5))
    var_99 = float(np.percentile(total, 1))
    tail_95 = total[total <= var_95]
    tail_99 = total[total <= var_99]

    return SimulationStatistics(
        mean_annualised_return=float(np.mean(annualised)),
        median_annualised_return=float(np.median(annualised)),
        terminal_dispersion=float(np.std(annualised, ddof=1))
                            if annualised.size > 1 else 0.0,
        probability_of_loss=float(np.mean(total < 0)),
        ruin_probability=result.ruin_probability,
        var_95=var_95,
        var_99=var_99,
        expected_shortfall_95=float(np.mean(tail_95)) if tail_95.size else var_95,
        expected_shortfall_99=float(np.mean(tail_99)) if tail_99.size else var_99,
        mean_max_drawdown=float(np.mean(result.max_drawdowns)),
        max_drawdown_95=float(np.percentile(result.max_drawdowns, 95)),
        max_drawdown_99=float(np.percentile(result.max_drawdowns, 99)),
        worst_terminal_return=float(np.min(total)),
        best_terminal_return=float(np.max(total)),
        n_paths=result.n_paths)


def stress(expected_returns: Sequence[float], covariance, *,
           scenarios: Mapping[str, Mapping[str, float]],
           seed: int, **kwargs) -> dict[str, SimulationResult]:
    """Run `simulate` once per scenario, shocking the moments.

    `volatility_multiplier` multiplies VOLATILITY, so the covariance is scaled
    by its SQUARE. finGuard multiplied the covariance directly, which meant a
    scenario documented as a 3x volatility shock delivered sqrt(3) = 1.73x —
    barely half the stress it claimed, in the scenario that matters most.

    Each scenario gets a distinct derived seed, so they are independent draws
    and both remain reproducible.
    """
    mu = np.asarray(expected_returns, dtype=float)
    sigma = np.asarray(covariance, dtype=float)
    _validate(mu, sigma)
    if not scenarios:
        raise SimulationError("no scenarios given")

    results: dict[str, SimulationResult] = {}
    for offset, (name, params) in enumerate(sorted(scenarios.items())):
        return_multiplier = float(params.get("return_multiplier", 1.0))
        volatility_multiplier = float(params.get("volatility_multiplier", 1.0))
        if volatility_multiplier < 0:
            raise SimulationError(
                f"scenario {name!r}: volatility_multiplier must be non-negative, "
                f"got {volatility_multiplier}")
        results[name] = simulate(
            mu * return_multiplier,
            sigma * volatility_multiplier ** 2,
            seed=seed + offset, **kwargs)
    return results


def sample_scenarios() -> dict[str, dict[str, float]]:
    """A starting set of shocks. The multipliers are conventions, not estimates.

    Kept from finGuard because the shapes are reasonable, with the volatility
    figures now meaning what they say.
    """
    return {
        "market_crash": {"return_multiplier": -2.0, "volatility_multiplier": 3.0},
        "recession": {"return_multiplier": -1.5, "volatility_multiplier": 2.0},
        "high_volatility": {"return_multiplier": 0.8, "volatility_multiplier": 2.5},
        "bull_market": {"return_multiplier": 1.5, "volatility_multiplier": 0.8},
    }
