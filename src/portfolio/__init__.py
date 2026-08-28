"""Portfolio construction and risk — PRD 04 §5.5, V1.

Separate from `research_integrity` because the two answer different questions.
The research-integrity layer asks whether a result is believable; this layer
asks how much to bet on one. Nothing here is a control, and none of it should be
mistaken for one.

Migrated from `migration_inbox/finGuard/` on 2026-08-28, formula by formula
against the sources rather than by trusting the 23 tests that shipped with it.
Those tests exercised the functions without checking them against the papers,
and the portfolio Kelly inverted position signs whenever the raw weights summed
negative. See each module's docstring for what was wrong and what it cost.

`simulator.py` is a REWRITE rather than a migration: its predecessor drove every
path through both defective functions, shared one drawdown peak across all
simulations, and measured returns against the terminal value of path 0.
Thirteen defects were found across the three modules in total.
"""
from .drawdown import (
    DrawdownError,
    RiskMetrics,
    drawdown_series,
    historical_var,
    max_drawdown,
    recovery_time,
    risk_metrics,
    throttle,
    ulcer_index,
)
from .simulator import (
    SimulationError,
    SimulationResult,
    SimulationStatistics,
    sample_scenarios,
    simulate,
    statistics,
    stress,
)
from .kelly import (
    HALF_KELLY,
    KellyAllocation,
    KellyError,
    fractional,
    growth_rate,
    kelly_fraction,
    portfolio_kelly,
)

__all__ = [
    "DrawdownError", "RiskMetrics", "drawdown_series", "historical_var",
    "max_drawdown", "recovery_time", "risk_metrics", "throttle", "ulcer_index",
    "HALF_KELLY", "KellyAllocation", "KellyError", "fractional", "growth_rate",
    "kelly_fraction", "portfolio_kelly",
    "SimulationError", "SimulationResult", "SimulationStatistics",
    "sample_scenarios", "simulate", "statistics", "stress",
]
