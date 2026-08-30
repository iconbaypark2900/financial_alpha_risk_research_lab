"""The suite's warning filters — scoped to an upstream defect, not to silence.

The suite emitted 50 `Pandas4Warning: Timestamp.utcnow is deprecated` warnings,
every one of them attributed to `engine.run()`. The attribution is misleading
and worth stating, because it is what makes the blanket `ignore` tempting: the
deprecated call is `pd.Timestamp.utcnow()` in nautilus_trader's compiled
`backtest/engine.pyx` (lines 1418 and 1601 of 1.231.0), and nothing in this
repository calls it — this project never imports pandas at all, and its own
`_utcnow()` helpers in holdout.py, trial_counter.py and run_record.py use
`datetime.now(timezone.utc)`. Cython frames are invisible to `sys._getframe`,
so the warnings machinery walks straight past engine.pyx and blames the nearest
Python frame, which is this project's `engine.run()` call site.

That is exactly why the filter matches the MESSAGE and not the module. A
module-scoped filter would have to name `src.research_integrity.backtest` and
`tests.test_backtest` — this project's own modules — and would then hide every
future DeprecationWarning this project's backtest code raises about itself. The
misattribution would have been written into the configuration.

These tests execute the filter stack pytest actually installed rather than
reading pyproject.toml as text, so they fail both ways: if the filter stops
suppressing the upstream warning, and if it is ever widened into something that
also suppresses this project's own.
"""
from __future__ import annotations

import warnings

import pytest

# Transcribed from pandas 3.0.5. `test_the_filter_matches_the_message_pandas
# _really_emits` below is what keeps this honest if upstream rewords it.
UPSTREAM = ("Timestamp.utcnow is deprecated and will be removed in a future "
            "version. Use Timestamp.now('UTC') instead.")

# Where the warnings machinery believes the upstream warning comes from: this
# project's own module, for the Cython reason in the docstring.
BLAMED_MODULE = "src.research_integrity.backtest"
BLAMED_FILE = "src/research_integrity/backtest.py"


def _emitted(message: str, category: type[Warning] = DeprecationWarning,
             module: str = BLAMED_MODULE) -> list[warnings.WarningMessage]:
    """Whether `message` survives the filters pytest has installed for this run.

    `catch_warnings` copies the live filter list rather than resetting it, so
    what is under test is the configuration this suite really runs with — not a
    reconstruction of it parsed back out of pyproject.toml.
    """
    with warnings.catch_warnings(record=True) as seen:
        warnings.warn_explicit(message, category, BLAMED_FILE, 427,
                               module=module, registry=None)
    return list(seen)


def test_the_upstream_pandas_deprecation_is_filtered():
    """A warning about a call this repository does not make is upstream noise."""
    assert _emitted(UPSTREAM) == [], (
        "the Pandas4Warning from nautilus_trader's engine.pyx is not filtered")


def test_a_warning_from_this_projects_own_code_is_still_shown():
    """The reason the filter is scoped rather than blanket.

    Raised from the very module the upstream warning is blamed on, so a filter
    widened to `ignore` — or narrowed by module instead of message — fails here
    while the test above still passes. Silencing this project's own deprecation
    notices is the failure the filter exists to avoid, not a side effect of it.
    """
    ours = "MomentumStrategy.lookback is deprecated; pass it in the config"
    assert [str(w.message) for w in _emitted(ours)] == [ours], (
        "a DeprecationWarning raised by this project's own code was filtered "
        "out; the filter is too broad")


def test_a_different_pandas_deprecation_is_still_shown():
    """Scoped to one upstream call, not to pandas in general.

    If pandas deprecates something this project does depend on, that is a
    warning this suite needs to see.
    """
    other = "DataFrame.append is deprecated and will be removed in a future version."
    assert [str(w.message) for w in _emitted(other)] == [other]


def test_the_filter_matches_the_message_pandas_really_emits():
    """The transcription above, checked against the source rather than trusted.

    A filter written from a remembered message string silently stops matching
    the day upstream rewords it, and the only symptom is 50 warnings coming
    back — which is the state this was added to fix, so nothing would notice.
    """
    pd = pytest.importorskip("pandas", reason="pandas arrives with the engine extra")

    with warnings.catch_warnings(record=True) as raw:
        warnings.simplefilter("always")
        pd.Timestamp.utcnow()
    assert [str(w.message) for w in raw] == [UPSTREAM], (
        "pandas no longer emits the message this filter was written for")

    # And under the real filter stack, the real call is silent.
    with warnings.catch_warnings(record=True) as seen:
        pd.Timestamp.utcnow()
    assert [w for w in seen if "utcnow" in str(w.message)] == []


def test_the_engine_run_that_produced_the_fifty_warnings_is_quiet():
    """End to end: the call the 50 warnings were attributed to.

    The message-level tests above would still pass if the warning reached the
    filters by a route that bypasses them. This one runs the real engine.
    """
    pytest.importorskip("nautilus_trader",
                        reason="the engine slice needs nautilus_trader")
    import numpy as np

    from src.research_integrity.backtest import run_backtest

    prices = 100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 80))
    with warnings.catch_warnings(record=True) as seen:
        run_backtest(prices, lookback=5, skip=1)
    leaked = [str(w.message) for w in seen if "utcnow" in str(w.message)]
    assert leaked == [], f"engine.run() still leaks {len(leaked)} upstream warnings"
