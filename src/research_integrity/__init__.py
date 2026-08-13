"""Research integrity: deflation and minimum backtest length (PRD 04 FR-09, FR-13).

Both formulas are implemented as published and verified against their source
papers' worked examples. See core.py for the provenance note — the first
version invented approximations the papers do not contain, and every invariant
test passed while it did.
"""
from .holdout import HoldoutViolation, ProtectedHoldout
from .search import (
    compare_to_null,
    crossover_grid,
    moving_average_crossover,
    null_benchmark,
    run_search,
)
from .trial_counter import TrialCounter, TrialCounterError
from .core import (
    EULER_MASCHERONI,
    NormalDistribution,
    deflated_sharpe_ratio,
    evaluate,
    expected_max_sharpe,
    minimum_backtest_length,
)

__all__ = [
    "HoldoutViolation",
    "compare_to_null",
    "crossover_grid",
    "moving_average_crossover",
    "null_benchmark",
    "run_search",
    "ProtectedHoldout",
    "TrialCounter",
    "TrialCounterError",
    "EULER_MASCHERONI",
    "NormalDistribution",
    "deflated_sharpe_ratio",
    "evaluate",
    "expected_max_sharpe",
    "minimum_backtest_length",
]
