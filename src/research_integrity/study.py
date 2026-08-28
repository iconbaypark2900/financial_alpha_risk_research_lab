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

WHAT THIS DOES NOT DO

The date range is DECLARED by the caller, not derived from the data it hands
over. A caller that reads holdout dates and declares a different range defeats
the FR-10 check. Closing that needs the study to load prices from the store
itself, which needs a price-shaped read the fact table does not yet offer. Said
here rather than left for someone to discover: this makes the honest path easy
and the dishonest path deliberate, which is weaker than impossible.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

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


@dataclass
class Study:
    """A dataset, its controls, and the only supported way to run against it.

    Every argument is required. There is no default store, counter, holdout or
    log, because a study missing one of them is a study with that control
    switched off — and the whole point is that switching one off should take
    more effort than leaving it on.

        study = Study(dataset_id="sp500", store=store, counter=counter,
                      holdout=holdout, log=log)
        study.backtest(prices, start="2015-01-01", end="2019-12-31",
                       strategy="momentum", params={"lookback": 60},
                       seeds={"deterministic": 0})
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
    def search(self, returns, param_sets: Sequence[dict], *,
               start: str, end: str, strategy: str = "search",
               search_id: str | None = None,
               seeds: dict[str, int] | None = None,
               factors: Sequence[str] | None = None,
               allow_uncommitted: bool = False, **kwargs) -> dict[str, Any]:
        """Run a parameter sweep with every control attached."""
        from .search import run_search

        version = self._admit(start, end)
        run_id = self.log.start(                                    # FR-22, FR-24
            strategy, params={"n_param_sets": len(param_sets),
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
        return {**result, "run_id": run_id, "dataset_version": version}

    # ---- FR-19/FR-21: a counted, recorded backtest ------------------------
    def backtest(self, prices, *, start: str, end: str,
                 strategy: str = "momentum",
                 params: dict[str, Any] | None = None,
                 seeds: dict[str, int] | None = None,
                 factors: Sequence[str] | None = None,
                 allow_uncommitted: bool = False, **kwargs) -> dict[str, Any]:
        """Run one event-driven backtest with every control attached."""
        from .backtest import run_backtest

        version = self._admit(start, end)
        params = dict(params or {})
        run_id = self.log.start(
            strategy, params={**params, "start": start, "end": end},
            seeds=seeds or {"deterministic": 0},
            dataset_versions=[version], factors=factors,
            allow_uncommitted=allow_uncommitted)
        try:
            result = run_backtest(prices, counter=self.counter,
                                  dataset_id=self.dataset_id, **{**params, **kwargs})
        except Exception as exc:
            self.log.finish(run_id, result={"error": f"{type(exc).__name__}: {exc}"},
                            outcome="failed")
            raise
        self.log.finish(run_id, result={k: v for k, v in result.items()
                                        if k != "impact_charges"},
                        outcome="completed")
        return {**result, "run_id": run_id, "dataset_version": version}

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
