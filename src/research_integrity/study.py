"""The seam — the supported way to run a backtest, with the controls attached.

WHY THIS EXISTS

Every control in this package worked, was tested, and constrained nothing.

    who calls the holdout guard?           nobody, outside its own docstring
    who writes a run record?               nobody
    who requires a point-in-time dataset?  nobody
    what was actually wired?               the trial counter, into search and backtest

One of four. The other three were libraries a researcher had to remember to
call, which is the failure this package's own README names in its first
paragraphs: "a researcher who can delete rows can manufacture any deflated
Sharpe they want, and 'please don't' is not a control." A control nobody invokes
is the same thing with an extra step.

FR-10 says the holdout MUST be inaccessible to ordinary backtests. Nothing made
an ordinary backtest check. FR-07 says the system MUST REFUSE a dataset that
cannot supply point-in-time semantics — `require_point_in_time` implements that
refusal precisely, and no caller triggered it. FR-22 through FR-25 describe a
run record that no code path wrote.

THE ORDER IS THE DESIGN

`ORDER` below is the sequence, and it is not arbitrary. Refusals come first, so
a run that must not happen never touches the counter — FR-08 counts backtests
EXECUTED, and a study refused at the door was not executed. Then the trial is
counted, before the result exists. Then the run happens. Then it is recorded,
whether it succeeded or raised.

    1. FR-07  refuse a dataset that is not point-in-time
    2. FR-10  refuse a range that overlaps the protected holdout
    3. FR-06  resolve the dataset version, or refuse — a run that cannot name
              its data is not reproducible even in principle
    4. FR-24  refuse uncommitted code (or record the diff)
    5. FR-08  count the trial, before it can succeed
    6.        run
    7. FR-25  record the outcome, including failure

FOUR ENTRY POINTS, AND ONLY TWO OF THEM CLOSE THE DATE HOLE

`search` and `backtest` take the range as an ARGUMENT, so the FR-10 check is
made against two strings the caller chose rather than against the data it hands
over. `search_series` and `backtest_series` read through the store and DERIVE
the range from what came back, so the holdout check and the data are the same
fact.

This header used to state the weaker guarantee unconditionally, which stopped
being true the moment the first `_series` method existed — and a limitation
recorded only in a module header is one a caller reaching for a method never
meets. It is stated in `search` and `backtest` instead, where it applies and
where it is read.

MANAGED AGENTS PATTERN

This module now includes adapter-level caching and budget-aware termination to
prevent excessive processing and ensure reproducibility.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from ..perf import AdapterCache, enforce_timeout, should_terminate


def _simple_returns(values: Sequence[float]) -> Any:
    """Period-over-period simple returns. Imported lazily so the study module
    carries no numpy requirement for callers that only preregister."""
    import numpy as np

    prices = np.asarray(values, dtype=float)
    if np.any(prices <= 0):
        raise StudyError("prices must be positive to form returns")
    return np.diff(prices) / prices[:-1]

ORDER = (
    "require_point_in_time",     # FR-07
    "assert_ordinary_access",    # FR-10
    "resolve_dataset_version",   # FR-06
    "open_run_record",           # FR-22, FR-24
    "count_trial",               # FR-08
    "execute",
    "record_outcome",            # FR-25
)


class StudyError(RuntimeError):
    """A study refused to run, or could not be constructed."""


# Adapter-level cache for study operations (Top-N gate: 5 calls max per instance)
_STUDY_CACHE = AdapterCache(max_size=5)


@dataclass
class Study:
    """A dataset, its controls, and the only supported way to run against it.

    Every argument is required. There is no default store, counter, holdout or
    log, because a study missing one of them is a study with that control
    switched off — and the whole point is that switching one off should take
    more effort than leaving it on.

        study = Study(dataset_id="sp500", store=store, counter=counter,
                      holdout=holdout, log=log)
        study.backtest_series("SP500", params={"lookback": 60},
                              seeds={"deterministic": 0})

    The example reads through the store on purpose. `backtest` takes the same
    run and lets the caller declare the date range instead, which is the weaker
    of the two and says so in its own docstring.
    """
    dataset_id: str
    store: Any
    counter: Any
    holdout: Any
    log: Any

    def __post_init__(self) -> None:
        for name in ("store", "counter", "holdout", "log"):
            if getattr(self, name) is None:
                raise StudyError(
                    f"{name} is required. A study without it is a study with "
                    f"that control switched off, which is the state this class "
                    "exists to prevent.")

    # ---- the gate ---------------------------------------------------------
    def _admit(self, start: str, end: str) -> str:
        """Steps 1 to 3. Returns the dataset version, or raises."""
        self.store.require_point_in_time(self.dataset_id)          # FR-07
        self.holdout.assert_ordinary_access(self.dataset_id, start, end)  # FR-10

        version = self.store.current_version(self.dataset_id)      # FR-06
        if not version:
            raise StudyError(
                f"dataset {self.dataset_id!r} has no version — no facts have "
                "been appended. A run that cannot name the data it read is not "
                "reproducible even in principle (FR-22).")
        return version

    # ---- FR-16: a counted, recorded search --------------------------------
    @enforce_timeout(timeout=60.0)
    def search(self, returns, param_sets: Sequence[dict], *,
               start: str, end: str, strategy: str = "search",
               search_id: str | None = None,
               seeds: dict[str, int] | None = None,
               factors: Sequence[str] | None = None,
               allow_uncommitted: bool = False,
               replay_params: dict[str, Any] | None = None,
               **kwargs) -> dict[str, Any]:
        """Run a parameter sweep with every control attached.

        THE RANGE IS DECLARED HERE, NOT DERIVED

        `start` and `end` are what the caller SAYS it read, and the FR-10 check
        is made against those two strings. A caller that reads holdout dates and
        declares a range outside them defeats it. That makes the honest path easy
        and the dishonest path deliberate, which is weaker than impossible, and
        it is the reason `search_series` exists: it reads through the store and
        derives the range from the data returned, so the two cannot disagree.

        This method is kept for a caller holding an array and no store. If you
        have the store, use the other one.

        MANAGED AGENTS PATTERN
        - Timeout enforcement: 60s wall-clock (via @enforce_timeout)
        - Budget-aware: calls should_terminate() before searching
        - LRU cache: keyed on (dataset_id, start, end, strategy)
        """
        # Budget-aware early termination
        if should_terminate():
            return {"error": "budget_exceeded", "run_id": None, "dataset_version": None}

        # Check cache
        cache_key = f"{self.dataset_id}@{start}@{end}@{strategy}"
        cached = _STUDY_CACHE.get(cache_key)
        if cached is not None:
            return cached

        from .search import run_search

        version = self._admit(start, end)
        run_id = self.log.start(                                    # FR-22, FR-24
            strategy, params=replay_params or {"n_param_sets": len(param_sets),
                                               "start": start, "end": end},
            seeds=seeds or {"deterministic": 0},
            dataset_versions=[version], factors=factors,
            allow_uncommitted=allow_uncommitted)
        try:
            result = run_search(returns, param_sets, counter=self.counter,  # FR-08
                                dataset_id=self.dataset_id,
                                search_id=search_id, **kwargs)
        except Exception as exc:
            self.log.finish(run_id, result={"error": f"{type(exc).__name__}: {exc}"},
                            outcome="failed")                       # FR-25
            raise
        self.log.finish(run_id, result=result, outcome="completed")
        result_with_meta = {**result, "run_id": run_id, "dataset_version": version}

        # Cache the result
        _STUDY_CACHE.set(cache_key, result_with_meta)
        return result_with_meta

    # ---- FR-19/FR-21: a counted, recorded backtest ------------------------
    @enforce_timeout(timeout=90.0)
    def backtest(self, prices, *, start: str, end: str,
                 strategy: str = "momentum",
                 params: dict[str, Any] | None = None,
                 seeds: dict[str, int] | None = None,
                 factors: Sequence[str] | None = None,
                 allow_uncommitted: bool = False,
                 replay_params: dict[str, Any] | None = None,
                 **kwargs) -> dict[str, Any]:
        """Run one event-driven backtest with every control attached.

        THE RANGE IS DECLARED HERE, NOT DERIVED

        As in `search`, and with the same consequence: the FR-10 check sees the
        `start` and `end` the caller passed, not the dates the `prices` actually
        cover, so handing over holdout prices under a declared range outside the
        holdout is not refused. `backtest_series` is the version without that
        hole — it reads the prices through the store and derives the range from
        them. tests/test_study.py pins this weakness as a limitation rather than
        leaving it to be discovered.

        This method is kept for a caller holding an array and no store.

        MANAGED AGENTS PATTERN
        - Timeout enforcement: 90s wall-clock (via @enforce_timeout)
        - Budget-aware: calls should_terminate() before backtesting
        - LRU cache: keyed on (dataset_id, start, end, strategy)
        """
        # Budget-aware early termination
        if should_terminate():
            return {"error": "budget_exceeded", "run_id": None, "dataset_version": None}

        # Check cache
        cache_key = f"{self.dataset_id}@{start}@{end}@{strategy}"
        cached = _STUDY_CACHE.get(cache_key)
        if cached is not None:
            return cached

        version = self._admit(start, end)
        params = dict(params or {})
        run_id = self.log.start(
            strategy,
            params=replay_params or {**params, "start": start, "end": end},
            seeds=seeds or {"deterministic": 0},
            dataset_versions=[version], factors=factors,
            allow_uncommitted=allow_uncommitted)
        try:
            # Imported here, at step 6, rather than at the top of the method.
            # Every refusal above this line — FR-07, FR-10, FR-06, FR-24 — is
            # one this study owes a caller whether or not the OPTIONAL engine is
            # installed. Importing first replaced all four with an ImportError
            # about a missing dependency and made them untestable in an install
            # that has the store and not the engine, which is a configuration
            # this project supports. Inside the try, an absent engine is
            # recorded as a failed run (FR-25) instead of vanishing.
            from .backtest import run_backtest

            result = run_backtest(prices, counter=self.counter,
                                  dataset_id=self.dataset_id, **{**params, **kwargs})
        except Exception as exc:
            self.log.finish(run_id, result={"error": f"{type(exc).__name__}: {exc}"},
                            outcome="failed")
            raise
        self.log.finish(run_id, result={k: v for k, v in result.items()
                                        if k != "impact_charges"},
                        outcome="completed")
        result_with_meta = {**result, "run_id": run_id, "dataset_version": version}

        # Cache the result
        _STUDY_CACHE.set(cache_key, result_with_meta)
        return result_with_meta

    # ---- reading through the store, so the range cannot be misdeclared ----
    def series(self, entity_id: str, field: str = "close", *,
               knowledge_date: str | None = None,
               start: str | None = None, end: str | None = None
               ) -> tuple[list[str], list[float]]:
        """Prices as first reported, with the range a property of the result."""
        self.store.require_point_in_time(self.dataset_id)
        return self.store.series(self.dataset_id, entity_id, field,
                                 start=start, end=end,
                                 knowledge_date=knowledge_date)

    def search_series(self, entity_id: str, param_sets: Sequence[dict], *,
                      field: str = "close",
                      knowledge_date: str | None = None,
                      start: str | None = None, end: str | None = None,
                      to_returns: Callable[[Sequence[float]], Any] | None = None,
                      **kwargs) -> dict[str, Any]:
        """Search over a series READ FROM THE STORE, not one handed in.

        This is the version without the hole. `search` takes start and end as
        arguments and checks them against the holdout, which a caller can defeat
        by declaring a range it does not intend to read. Here the range is
        DERIVED from the data actually returned, so the holdout check and the
        data are the same fact.

        A range that overlaps the holdout is refused after the read and before
        anything is counted — reading is not backtesting, and refusing at the
        point of use is what keeps the counter honest.
        """
        dates, values = self.series(entity_id, field,
                                    knowledge_date=knowledge_date,
                                    start=start, end=end)
        if len(dates) < 2:
            raise StudyError(
                f"{entity_id}/{field} returned {len(dates)} observations for "
                f"{self.dataset_id} — nothing to search over")

        returns = to_returns(values) if to_returns else _simple_returns(values)
        # FR-22 asks for the FULL parameter set, and it means it: a run record
        # holding `n_param_sets: 2691` documents that a search happened without
        # being sufficient to repeat it. `replay` passes these back as keyword
        # arguments, so what is recorded here IS the call signature.
        return self.search(
            returns, param_sets, start=dates[0], end=dates[-1],
            replay_params={
                "entity_id": entity_id, "field": field,
                "start": start, "end": end, "knowledge_date": knowledge_date,
                "param_sets": [dict(p) for p in param_sets],
                "search_id": kwargs.get("search_id"),
            },
            **kwargs)

    def backtest_series(self, entity_id: str, *,
                        field: str = "close",
                        knowledge_date: str | None = None,
                        start: str | None = None, end: str | None = None,
                        strategy: str = "momentum",
                        params: dict[str, Any] | None = None,
                        seeds: dict[str, int] | None = None,
                        factors: Sequence[str] | None = None,
                        allow_uncommitted: bool = False,
                        **kwargs) -> dict[str, Any]:
        """Backtest a series READ FROM THE STORE, not one handed in.

        `search_series` closed the declared-range hole for search and left
        `backtest` — the FR-19/FR-21 half of the seam — without a twin, so the
        hole stayed open on exactly the path the package is named for. This is
        that twin. The range is DERIVED from the prices actually returned, so
        the holdout check and the data are the same fact.

        The refusal lands after the read and before anything is counted:
        `series` only reads, and `backtest` runs `_admit` before it opens a run
        record or starts a trial. Reading is not backtesting, and refusing at
        the point of use is what keeps the counter honest (FR-08).

        WHAT GOES INTO THE RECORD

        FR-22 asks for the FULL parameter set. `backtest` merges `params` with
        any surplus keyword arguments and hands the merge to the engine, so the
        merge is what determines the answer and the merge is what gets written
        down — recording `params` alone would document a run that cannot be
        repeated from its record. `strategy`, `seeds`, `factors` and
        `allow_uncommitted` are named explicitly rather than swept into
        `**kwargs` so that what remains is unambiguously the engine's, and the
        recorded parameter set is the call signature rather than a guess at it.
        """
        dates, prices = self.series(entity_id, field,
                                    knowledge_date=knowledge_date,
                                    start=start, end=end)
        if len(dates) < 2:
            raise StudyError(
                f"{entity_id}/{field} returned {len(dates)} observations for "
                f"{self.dataset_id} — nothing to backtest over")

        params = dict(params or {})
        return self.backtest(
            prices, start=dates[0], end=dates[-1],
            strategy=strategy, params=params, seeds=seeds, factors=factors,
            allow_uncommitted=allow_uncommitted,
            replay_params={
                "entity_id": entity_id, "field": field,
                "start": start, "end": end, "knowledge_date": knowledge_date,
                "strategy": strategy, "params": {**params, **kwargs},
            },
            **kwargs)

    # ---- FR-23: re-execute a recorded run and require the same answer ----
    def replay_search(self, run_id: str) -> dict[str, Any]:
        """Re-run a recorded search and require a bitwise-identical result.

        FR-23 says any past run MUST be re-executable from its record. `replay`
        implemented that and had never been called on a real run — the same
        orphaned-control problem `Study` was written to end, one layer up, and
        the guard in tests/test_study.py did not cover `.replay(` either.

        The replay uses a THROWAWAY trial counter. A replay re-executes a search
        that was already counted; counting it again would inflate the very
        number the deflated Sharpe depends on, so verification must not look
        like new research. That is the one place where re-running a backtest
        should not touch the counter, and it is worth being explicit about
        because everything else in this package argues the opposite.

        WHY THE LEDGER STATE IS RESTORED FROM THE RECORD

        The throwaway counter had a consequence nobody had run into, because
        every test and demo replayed the first and only search on a fresh
        workspace. `run_search` embeds the live counter's state in its result —
        `n_trials`, `var_trials`, and the deflated Sharpe, minimum backtest
        length and sample-length verdict derived from them. Those grow with the
        DATASET's whole history by design (FR-08: every trial by anyone, ever),
        while the replay's throwaway counter sees only its own param sets. So
        from the second search onward the hashes could not match, and the
        replay reported a reproducibility failure whose message blamed "an
        unrecorded seed, an environment difference, or uncommitted code" — none
        of which was the cause — and stamped the run replay_verified=0
        permanently. `--home`, whose stated purpose is that the count
        "accumulates across runs", was what triggered it. run_record.py's own
        docstring names this hazard: false failures "teach everyone to ignore
        them".

        So the replay reads `n_trials` and `var_trials` back from the record and
        recomputes the derived figures from them, via the same code path the run
        used. The counter is still throwaway and still untouched.

        The rejected alternative was to drop the ledger-derived keys from the
        comparison. It is fewer lines and it would make these tests pass, but
        the deflated Sharpe is FR-09's headline figure, and dropping it means a
        replay stops checking the one number the whole package is built to
        produce — including whether it is consistent with the burden the run
        recorded. Restoring the inputs and recomputing the outputs keeps that
        check; excluding them removes it. A replay that verifies less is how
        FR-23 came to be marked met in the first place.

        What is NOT verified either way is the recorded ledger state itself. A
        replay cannot reconstruct a past global count — that is what makes it
        global. It is defended where it is written instead: the trials table is
        append-only by trigger. The run record's own trigger guards
        `result_hash` but not `result_json`, so a doctored count in the stored
        result surfaces here as a replay failure rather than being believed —
        which is a consequence of restoring these keys, and would not hold if
        they were excluded.
        """
        import json
        import tempfile

        from .search import run_search, with_recorded_deflation
        from .trial_counter import TrialCounter

        record = self.log.get(run_id)
        if record is None:
            raise ValueError(f"unknown run {run_id!r}")
        recorded = json.loads(record["result_json"] or "{}")
        if "n_trials" not in recorded:
            raise StudyError(
                f"run {run_id!r} recorded no trial-ledger state (outcome "
                f"{record['outcome']!r}). Only a completed search records one, "
                "so there is nothing here to replay a deflation against.")

        def recompute(*, entity_id: str, field: str, start, end,
                      knowledge_date, param_sets, search_id=None, **ignored):
            _, values = self.store.series(self.dataset_id, entity_id, field,
                                          start=start, end=end,
                                          knowledge_date=knowledge_date)
            returns = _simple_returns(values)
            with tempfile.TemporaryDirectory() as tmp:
                result = run_search(
                    returns, param_sets,
                    counter=TrialCounter(Path(tmp) / "replay.db"),
                    dataset_id=self.dataset_id, search_id=search_id)
            return with_recorded_deflation(result, returns, recorded=recorded)

        return self.log.replay(run_id, recompute)

    # ---- FR-11, FR-12: the holdout, which is not an ordinary backtest -----
    def preregister(self, *, strategy_family: str, hypothesis: str,
                    expected_result: str, **kwargs) -> str:
        """FR-11. Recorded BEFORE the run, and spendable exactly once."""
        return self.holdout.preregister(
            self.dataset_id, strategy_family=strategy_family,
            hypothesis=hypothesis, expected_result=expected_result, **kwargs)

    def evaluate_on_holdout(self, registration_id: str, *,
                            observed: dict[str, Any]) -> dict[str, Any]:
        """FR-12. Permanent, and flagged as exhaustion when repeated."""
        return self.holdout.evaluate(registration_id, observed=observed)

    # ---- what the controls have seen --------------------------------------
    def status(self) -> dict[str, Any]:
        """Everything the controls know about this dataset, in one place."""
        inputs = self.counter.deflation_inputs(self.dataset_id)
        return {
            "dataset_id": self.dataset_id,
            "dataset_version": self.store.current_version(self.dataset_id),
            "n_trials": inputs["n_trials"],
            "var_trials": inputs["var_trials"],
            "holdout_period": self.holdout.holdout_period(self.dataset_id),
            "runs_recorded": len(self.log.query()),
        }
