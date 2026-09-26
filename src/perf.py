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
