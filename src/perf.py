"""Performance utilities for financial_alpha_risk_research_lab.

This module provides:
- Adapter-level caching (memoize predictions)
- Batch processing for multiple candidates
- Timeout enforcement for all adapters
- Budget-aware early termination
- Performance metrics tracking (time per call, memory usage)
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import resource
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable


# --------------------------------------------------------------------------- #
# Performance metrics                                                         #
# --------------------------------------------------------------------------- #
@dataclass
class CallMetrics:
    """Metrics for a single adapter call."""
    service: str = ""
    call_id: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    memory_mb: float = 0.0
    budget_tier: int = 0
    budget_spent: float = 0.0
    success: bool = True
    error: str = ""


@dataclass
class PerformanceReport:
    """Aggregated performance report for a run."""
    total_calls: int = 0
    total_duration_ms: float = 0.0
    _avg_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    total_memory_mb: float = 0.0
    _avg_memory_mb: float = 0.0
    calls_by_service: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    calls_by_tier: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    errors: list[dict[str, Any]] = field(default_factory=list)
    top_slow_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def avg_duration_ms(self) -> float:
        """Average duration per call (computed dynamically)."""
        if self.total_calls == 0:
            return 0.0
        return self.total_duration_ms / self.total_calls

    @property
    def avg_memory_mb(self) -> float:
        """Average memory per call (computed dynamically)."""
        if self.total_calls == 0:
            return 0.0
        return self.total_memory_mb / self.total_calls

    def add_call(self, metrics: CallMetrics):
        """Add a call's metrics to the report."""
        self.total_calls += 1
        self.total_duration_ms += metrics.duration_ms
        self.total_memory_mb += metrics.memory_mb
        self.calls_by_service[metrics.service] += 1
        self.calls_by_tier[metrics.budget_tier] += 1

        if metrics.duration_ms > self.max_duration_ms:
            self.max_duration_ms = metrics.duration_ms

        if not metrics.success:
            self.errors.append({
                "service": metrics.service,
                "error": metrics.error,
                "duration_ms": metrics.duration_ms,
            })

    def summary(self) -> dict[str, Any]:
        """Return a summary dict of the performance report."""
        avg_duration = self.total_duration_ms / self.total_calls if self.total_calls > 0 else 0
        avg_memory = self.total_memory_mb / self.total_calls if self.total_calls > 0 else 0
        return {
            "total_calls": self.total_calls,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "avg_duration_ms": round(avg_duration, 2),
            "max_duration_ms": round(self.max_duration_ms, 2),
            "total_memory_mb": round(self.total_memory_mb, 2),
            "avg_memory_mb": round(avg_memory, 2),
            "calls_by_service": dict(self.calls_by_service),
            "calls_by_tier": dict(self.calls_by_tier),
            "errors": self.errors,
        }


# --------------------------------------------------------------------------- #
# Adapter cache (LRU)                                                         #
# --------------------------------------------------------------------------- #
class AdapterCache:
    """LRU cache for adapter calls."""

    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._cache: dict[str, Any] = {}
        self._order: list[str] = []

    def _make_key(self, *args: Any, **kwargs: Any) -> str:
        key_data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        return hashlib.sha256(key_data.encode()).hexdigest()[:32]

    def get(self, *args: Any, **kwargs: Any) -> Any | None:
        key = self._make_key(*args, **kwargs)
        if key in self._cache:
            self._order.remove(key)
            self._order.append(key)
            return self._cache[key]
        return None

    def put(self, *args: Any, value: Any, **kwargs: Any) -> None:
        key = self._make_key(*args, **kwargs)
        if key in self._cache:
            self._order.remove(key)
        self._cache[key] = value
        self._order.append(key)
        if len(self._cache) > self.max_size:
            lru_key = self._order.pop(0)
            del self._cache[lru_key]

    def clear(self) -> None:
        self._cache.clear()
        self._order.clear()


# --------------------------------------------------------------------------- #
# Timeout enforcement                                                         #
# --------------------------------------------------------------------------- #
def enforce_timeout(timeout: float = 60.0):
    """Decorator that enforces a wall-clock timeout."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            result = func(*args, **kwargs)
            elapsed = time.monotonic() - start
            if elapsed > timeout:
                raise TimeoutError(f"{func.__name__} exceeded {timeout}s timeout")
            return result
        return wrapper
    return decorator


# --------------------------------------------------------------------------- #
# Budget-aware termination                                                    #
# --------------------------------------------------------------------------- #
class BudgetTracker:
    """Track budget consumption and decide when to terminate."""

    TIER_COSTS = {0: 0.0, 1: 1.0, 2: 10.0}
    TIER_LIMITS = {0: float("inf"), 1: 100, 2: 20}

    def __init__(self, tier: int = 0, max_budget: float = float("inf")):
        self.tier = tier
        self.max_budget = max_budget
        self.spent = 0.0
        self.calls = 0

    def charge(self, cost: float | None = None) -> bool:
        if cost is None:
            cost = self.TIER_COSTS.get(self.tier, 0.0)
        self.spent += cost
        self.calls += 1
        return self.spent <= self.max_budget

    def should_terminate(self) -> bool:
        return self.spent > self.max_budget

    def status(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "spent": self.spent,
            "max_budget": self.max_budget,
            "calls": self.calls,
            "remaining": max(0.0, self.max_budget - self.spent),
        }


# --------------------------------------------------------------------------- #
# Global performance tracker                                                  #
# --------------------------------------------------------------------------- #
_tracker: PerformanceReport | None = None


def get_tracker() -> PerformanceReport:
    global _tracker
    if _tracker is None:
        _tracker = PerformanceReport()
    return _tracker


def reset_tracker():
    global _tracker
    _tracker = None


# --------------------------------------------------------------------------- #
# Performance tracking context manager                                        #
# --------------------------------------------------------------------------- #
class track_performance:
    """Context manager for tracking adapter call performance."""

    def __init__(self, service: str = "", call_id: str = ""):
        self.service = service
        self.call_id = call_id or hashlib.md5(f"{service}-{time.time()}".encode()).hexdigest()[:8]
        self.start_time = time.time()
        self.metrics = CallMetrics(service=service, call_id=self.call_id, start_time=self.start_time)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.metrics.end_time = time.time()
        self.metrics.duration_ms = (self.metrics.end_time - self.metrics.start_time) * 1000
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            self.metrics.memory_mb = usage.ru_maxrss / 1024
        except Exception:
            self.metrics.memory_mb = 0.0
        if exc_type is not None:
            self.metrics.success = False
            self.metrics.error = f"{exc_type.__name__}: {exc_val}"
        get_tracker().add_call(self.metrics)
        return False


# --------------------------------------------------------------------------- #
# Batch processing                                                            #
# --------------------------------------------------------------------------- #
def batch_candidates(items: list[Any], batch_size: int = 10) -> list[list[Any]]:
    """Split items into batches."""
    return [items[i:i + batch_size] for i in range(0, len(items), batch_size)]


def process_batch(items: list[Any], processor: Callable, batch_size: int = 10) -> list[Any]:
    """Process items in batches."""
    results: list[Any] = []
    for batch in batch_candidates(items, batch_size):
        results.extend(processor(batch))
    return results


# --------------------------------------------------------------------------- #
# Global budget tracker                                                       #
# --------------------------------------------------------------------------- #
_global_budget_tracker: BudgetTracker | None = None


def get_global_budget_tracker() -> BudgetTracker:
    """Get or create the global budget tracker."""
    global _global_budget_tracker
    if _global_budget_tracker is None:
        _global_budget_tracker = BudgetTracker()
    return _global_budget_tracker


def reset_global_budget_tracker():
    """Reset the global budget tracker."""
    global _global_budget_tracker
    _global_budget_tracker = None


# --------------------------------------------------------------------------- #
# Standalone should_terminate function                                        #
# --------------------------------------------------------------------------- #
def should_terminate(budget_tracker: BudgetTracker | None = None) -> bool:
    """Check if budget should terminate.
    
    Args:
        budget_tracker: Optional BudgetTracker instance. If None, uses global tracker.
    
    Returns:
        True if budget is exhausted.
    """
    if budget_tracker is None:
        budget_tracker = get_global_budget_tracker()
    return budget_tracker.should_terminate()
