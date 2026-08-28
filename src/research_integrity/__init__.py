"""Research integrity — the V0 controls, and the search they exist to constrain.

    core.py              deflated Sharpe, minimum backtest length (FR-09, FR-13)
    trial_counter.py     every trial, counted, append-only  (FR-08, FR-15)
    holdout.py           protected holdout and pre-registration (FR-10..FR-12)
    cross_validation.py  purged, embargoed splits (FR-14)
    point_in_time.py     as-of and as-reported queries (FR-01, FR-02, FR-06, FR-07)
    factors.py           a small factor library, each one causality-checked
    backtest.py          the NautilusTrader engine, audited (FR-19, FR-21)
    execution_costs.py   impact, borrow, capacity (FR-17, FR-18, FR-20)
    run_record.py        enforced reproducibility (FR-22..FR-25)
    search.py            the trial harness and null benchmark (FR-16)

The formulas in core.py are implemented as published and verified against their
source papers' worked examples. See that module's provenance note — the first
version invented approximations the papers do not contain, and every invariant
test passed while it did. That is the recurring lesson here: an invariant test
constrains the shape of an answer, never its correctness, so anything with a
published source is checked against the source.
"""
from .cross_validation import (
    LeakageError,
    PurgedKFold,
    assert_no_leakage,
    leakage_report,
)
from .factors import (
    FACTORS,
    Factor,
    FactorError,
    LookAheadFactor,
    assert_causal,
    book_to_market_as_of,
    momentum,
    realised_volatility,
    reversal,
    size,
)
from .execution_costs import (
    BorrowUnavailable,
    Instrument,
    borrow_cost,
    capacity,
    check_borrow,
    execution_cost,
)
from .holdout import HoldoutViolation, ProtectedHoldout
from .run_record import (
    ExperimentLog,
    NotReproducible,
    UncommittedCode,
    canonical_hash,
)
try:  # duckdb is optional; the rest of the module does not need it
    from .point_in_time import (
        LookAheadContamination,
        PointInTimeError,
        PointInTimeStore,
    )
except ImportError:  # pragma: no cover
    # Every name __all__ promises must exist, or `import *` raises AttributeError
    # in precisely the minimal install this package advertises and CI exercises.
    PointInTimeStore = None  # type: ignore[assignment]
    LookAheadContamination = None  # type: ignore[assignment]
    PointInTimeError = None  # type: ignore[assignment]
try:  # nautilus_trader is heavy and optional; the controls do not need it
    from .backtest import (
        AlmgrenFeeModel,
        LookAheadAudit,
        LookAheadDetected,
        MomentumStrategy,
        bars_from_prices,
        per_period_sharpe,
        run_backtest,
    )
except ImportError:  # pragma: no cover
    AlmgrenFeeModel = None  # type: ignore[assignment]
    LookAheadAudit = None  # type: ignore[assignment]
    LookAheadDetected = None  # type: ignore[assignment]
    MomentumStrategy = None  # type: ignore[assignment]
    bars_from_prices = None  # type: ignore[assignment]
    per_period_sharpe = None  # type: ignore[assignment]
    run_backtest = None  # type: ignore[assignment]
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
    "AlmgrenFeeModel",
    "LookAheadAudit",
    "LookAheadDetected",
    "MomentumStrategy",
    "bars_from_prices",
    "per_period_sharpe",
    "run_backtest",
    "FACTORS",
    "Factor",
    "FactorError",
    "LookAheadFactor",
    "assert_causal",
    "book_to_market_as_of",
    "momentum",
    "realised_volatility",
    "reversal",
    "size",
    "BorrowUnavailable",
    "ExperimentLog",
    "HoldoutViolation",
    "NotReproducible",
    "UncommittedCode",
    "canonical_hash",
    "Instrument",
    "borrow_cost",
    "capacity",
    "check_borrow",
    "execution_cost",
    "LookAheadContamination",
    "PointInTimeError",
    "PointInTimeStore",
    "LeakageError",
    "PurgedKFold",
    "assert_no_leakage",
    "leakage_report",
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
