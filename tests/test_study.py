"""The seam that makes the controls binding.

Before this existed, three of the four controls in this package constrained
nothing: the holdout guard was called only by its own docstring, no code path
wrote a run record, and `require_point_in_time` — which implements FR-07's
refusal exactly — was never triggered by a caller. Only the trial counter was
wired in.

So these tests are about REACHABILITY, not correctness. Each control's own tests
already prove it works. What was missing was proof that anything invokes it, and
that is what fails here if the seam comes apart.

REACHABLE IS NOT THE SAME AS REACHED

The guard that watched for an orphaned control did it by reading source text,
and it passed for the whole life of `Study.backtest` — a method whose every
statement was uncovered, and which could be replaced by `raise RuntimeError`
without turning a single test red. `_admit` mentions every control that guard
looks for, so the `search` path alone satisfied it while the FR-19/FR-21 half of
the seam ran nothing at all. There is now a second guard that watches public
`Study` methods EXECUTE. Both are kept, they catch different things, and each
says in its own docstring what it can and cannot see.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("duckdb", reason="the study needs the point-in-time store")

from src.research_integrity.holdout import HoldoutViolation, ProtectedHoldout
from src.research_integrity.point_in_time import PointInTimeError, PointInTimeStore
from src.research_integrity.run_record import ExperimentLog, UncommittedCode
from src.research_integrity.study import ORDER, Study, StudyError
from src.research_integrity.trial_counter import TrialCounter

# Per-test, deliberately not module-level. All four of `Study.backtest`'s
# refusals — FR-07, FR-10, FR-06 and FR-24 — land before it resolves the engine,
# so they are testable wherever the store is installed. A module-level
# importorskip would skip them along with the engine and hide the FR-19/FR-21
# seam's control wiring in every install that has duckdb and not
# nautilus_trader, which is a configuration this project supports.
needs_engine = pytest.mark.skipif(
    importlib.util.find_spec("nautilus_trader") is None,
    reason="the engine slice needs nautilus_trader")


@pytest.fixture()
def clean_repo(tmp_path: Path) -> Path:
    """A committed git repo, so FR-24 does not refuse for unrelated reasons."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "strategy.py").write_text("# a strategy\n", encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-q", "-m", "initial"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True)
    return repo


@pytest.fixture()
def study(tmp_path: Path, clean_repo: Path) -> Study:
    """A study over a price path the deflation can actually bite on.

    The path was a fixed three-day cycle, +0.4%, +0.4%, -0.5%, repeated. Every
    (fast, slow) pair in GRID scored exactly 0.0 on it, so `var_trials` was 0.0,
    `deflation_block` took its "the variance across trials is undefined" branch,
    and `deflated_sharpe` came back None from every study-level search. No
    study-level test reached the branch the FR-23 replay fix is about, and the
    two tests whose docstrings say they check a replayed deflated Sharpe were
    asserting None == None — the same shape as the NaN == NaN this suite has
    already shipped once.

    A seeded random walk gives the four trials four different Sharpes. Seeded,
    because the replay tests re-read this data and require a bitwise-identical
    result: a fixture whose numbers move cannot pin a hash comparison.
    """
    store = PointInTimeStore(tmp_path / "facts.duckdb")
    store.register_dataset("sp500", point_in_time=True)
    # A price series long enough for a crossover grid to run over.
    import datetime as _dt

    day = _dt.date(2019, 1, 1)
    facts = []
    price = 100.0
    for step in np.random.default_rng(20240607).normal(0.0004, 0.011, 320):
        while day.weekday() >= 5:
            day += _dt.timedelta(days=1)
        price *= float(np.exp(step))
        facts.append({"entity_id": "PRICE", "field": "close", "value": price,
                      "effective_date": day.isoformat(),
                      "knowledge_date": day.isoformat()})
        day += _dt.timedelta(days=1)
    store.append_facts("sp500", facts)
    return Study(
        dataset_id="sp500",
        store=store,
        counter=TrialCounter(tmp_path / "trials.db"),
        holdout=ProtectedHoldout(tmp_path / "holdout.db"),
        log=ExperimentLog(tmp_path / "runs.db", repo=clean_repo),
    )


@pytest.fixture()
def returns() -> np.ndarray:
    return np.random.default_rng(0).standard_t(df=4, size=400) * 0.01


GRID = [{"fast": f, "slow": s} for f in (5, 10) for s in (20, 30)]


# --- the controls are reachable at all -------------------------------------

def test_the_order_is_declared_and_refusals_come_first():
    """FR-08 counts backtests EXECUTED, so a study refused at the door must not
    reach the counter. The declared order encodes that."""
    assert ORDER.index("require_point_in_time") < ORDER.index("count_trial")
    assert ORDER.index("assert_ordinary_access") < ORDER.index("count_trial")
    assert ORDER.index("open_run_record") < ORDER.index("count_trial")
    assert ORDER.index("count_trial") < ORDER.index("execute")
    assert ORDER.index("execute") < ORDER.index("record_outcome")


def test_a_study_cannot_be_built_with_a_control_missing():
    """A study missing a control is that control switched off."""
    for absent in ("store", "counter", "holdout", "log"):
        kwargs = {"dataset_id": "x", "store": object(), "counter": object(),
                  "holdout": object(), "log": object(), absent: None}
        with pytest.raises(StudyError, match=absent):
            Study(**kwargs)


# --- FR-07: reachable at last ----------------------------------------------

def test_a_non_point_in_time_dataset_is_refused(tmp_path, clean_repo, returns):
    """`require_point_in_time` implements FR-07's refusal precisely and had
    never been called by anything."""
    store = PointInTimeStore(tmp_path / "bad.duckdb")
    store.register_dataset("vendor", point_in_time=False,
                           pit_note="vendor overwrites history in place")
    bad = Study(dataset_id="vendor", store=store,
                counter=TrialCounter(tmp_path / "t.db"),
                holdout=ProtectedHoldout(tmp_path / "h.db"),
                log=ExperimentLog(tmp_path / "r.db", repo=clean_repo))
    with pytest.raises(PointInTimeError):
        bad.search(returns, GRID, start="2015-01-01", end="2019-12-31")


def test_an_unregistered_dataset_is_refused(tmp_path, clean_repo, returns):
    unknown = Study(dataset_id="never_registered",
                    store=PointInTimeStore(tmp_path / "e.duckdb"),
                    counter=TrialCounter(tmp_path / "t.db"),
                    holdout=ProtectedHoldout(tmp_path / "h.db"),
                    log=ExperimentLog(tmp_path / "r.db", repo=clean_repo))
    with pytest.raises(PointInTimeError):
        unknown.search(returns, GRID, start="2015-01-01", end="2019-12-31")


# --- FR-10: the holdout finally guards something ---------------------------

def test_a_range_overlapping_the_holdout_is_refused(study, returns):
    """The guard whose only caller was its own docstring."""
    study.holdout.define("sp500", start="2023-01-01", end="2024-12-31")
    with pytest.raises(HoldoutViolation):
        study.search(returns, GRID, start="2020-01-01", end="2023-06-30")


def test_a_range_outside_the_holdout_is_allowed(study, returns):
    study.holdout.define("sp500", start="2023-01-01", end="2024-12-31")
    result = study.search(returns, GRID, start="2015-01-01", end="2019-12-31")
    assert result["n_trials"] == len(GRID)


def test_a_refused_run_is_not_counted_as_a_trial(study, returns):
    """FR-08 counts backtests EXECUTED. One refused at the door was not."""
    study.holdout.define("sp500", start="2023-01-01", end="2024-12-31")
    with pytest.raises(HoldoutViolation):
        study.search(returns, GRID, start="2020-01-01", end="2023-06-30")
    assert study.counter.trial_count("sp500") == 0
    assert study.log.query() == []


# --- FR-06 / FR-22: a run must be able to name its data --------------------

def test_a_dataset_with_no_version_is_refused(tmp_path, clean_repo, returns):
    store = PointInTimeStore(tmp_path / "empty.duckdb")
    store.register_dataset("empty", point_in_time=True)
    empty = Study(dataset_id="empty", store=store,
                  counter=TrialCounter(tmp_path / "t.db"),
                  holdout=ProtectedHoldout(tmp_path / "h.db"),
                  log=ExperimentLog(tmp_path / "r.db", repo=clean_repo))
    with pytest.raises(StudyError, match="no version"):
        empty.search(returns, GRID, start="2015-01-01", end="2019-12-31")


# --- FR-22..FR-25: something finally writes a run record -------------------

def test_a_successful_search_is_recorded(study, returns):
    """No code path wrote a run record before this seam existed."""
    result = study.search(returns, GRID, start="2015-01-01", end="2019-12-31")
    assert result["run_id"]
    record = study.log.get(result["run_id"])
    assert record["outcome"] == "completed"
    assert record["strategy"] == "search"
    assert result["dataset_version"] in record["dataset_versions"]


def test_the_record_names_the_dataset_version_the_store_reported(study, returns):
    """FR-22 to FR-06: the join that makes a run re-executable."""
    result = study.search(returns, GRID, start="2015-01-01", end="2019-12-31")
    assert result["dataset_version"] == study.store.current_version("sp500")


def test_a_failing_run_is_recorded_as_failed_and_still_counted(study):
    """An unrecorded failure is how a search quietly becomes smaller than it
    was — the same argument the trial counter makes."""
    with pytest.raises(Exception):
        study.search(np.array([]), GRID, start="2015-01-01", end="2019-12-31")
    runs = study.log.query()
    assert len(runs) == 1
    assert runs[0]["outcome"] == "failed"


def test_uncommitted_code_is_refused_before_anything_runs(tmp_path, study, returns):
    """FR-24, reachable at last. The refusal must also leave no trial behind."""
    dirty = Path(study.log.repo) / "strategy.py"
    dirty.write_text("# edited, not committed\n", encoding="utf-8")
    with pytest.raises(UncommittedCode):
        study.search(returns, GRID, start="2015-01-01", end="2019-12-31")
    assert study.counter.trial_count("sp500") == 0


# --- FR-08: still counted, through the seam --------------------------------

def test_every_search_through_the_study_is_counted(study, returns):
    study.search(returns, GRID, start="2015-01-01", end="2019-12-31")
    study.search(returns, GRID, start="2015-01-01", end="2019-12-31")
    assert study.counter.trial_count("sp500") == 2 * len(GRID)


def test_the_counted_trials_feed_the_deflation(study, returns):
    from src.research_integrity import deflated_sharpe_ratio

    study.search(returns, GRID, start="2015-01-01", end="2019-12-31")
    inputs = study.counter.deflation_inputs("sp500")
    assert inputs["n_trials"] == len(GRID)
    assert 0.0 <= deflated_sharpe_ratio(
        observed_sharpe=0.02, n_trials=inputs["n_trials"], sample_length=400,
        skewness=0.0, kurtosis=3.0, var_trials=inputs["var_trials"]) <= 1.0


# --- FR-19/FR-21: the backtest half of the seam, executed at last ----------
#
# `Study.backtest` applies the same ORDER to an event-driven run, and until
# these tests existed not one statement of it ran. Inserting
# `raise RuntimeError("MUTATION")` as its first statement left all 566 tests
# green; a coverage trace showed every line uncovered. The only `.backtest(`
# in the repository outside the method was its own docstring example.
#
# `test_no_control_is_orphaned` below cannot see that, and no amount of
# tightening would make it: it searches the package's text for control call
# strings, and `_admit` satisfies every entry in its dict on the `search` path
# alone. A control can be reachable by grep and dead in practice.

def test_a_backtest_on_a_non_point_in_time_dataset_is_refused(tmp_path, clean_repo):
    """FR-07, on the path that never ran. No engine needed: the refusal lands
    before the engine is resolved, which is why that import moved down to step 6
    of the ORDER instead of sitting at the top of the method."""
    store = PointInTimeStore(tmp_path / "bad.duckdb")
    store.register_dataset("vendor", point_in_time=False,
                           pit_note="vendor overwrites history in place")
    bad = Study(dataset_id="vendor", store=store,
                counter=TrialCounter(tmp_path / "t.db"),
                holdout=ProtectedHoldout(tmp_path / "h.db"),
                log=ExperimentLog(tmp_path / "r.db", repo=clean_repo))
    with pytest.raises(PointInTimeError):
        bad.backtest(np.array([100.0, 101.0, 102.0]),
                     start="2015-01-01", end="2019-12-31")
    assert bad.counter.trial_count("vendor") == 0
    assert bad.log.query() == []


def test_a_backtest_range_overlapping_the_holdout_is_refused(study):
    """FR-10 on the backtest path, and FR-08's ordering with it: a run refused
    at the door was not executed, so it must leave no trial and no record."""
    study.holdout.define("sp500", start="2023-01-01", end="2024-12-31")
    with pytest.raises(HoldoutViolation):
        study.backtest(np.array([100.0, 101.0, 102.0]),
                       start="2020-01-01", end="2023-06-30")
    assert study.counter.trial_count("sp500") == 0
    assert study.log.query() == []


def test_a_backtest_on_a_dataset_with_no_version_is_refused(tmp_path, clean_repo):
    """FR-06/FR-22: a run that cannot name its data is not reproducible even in
    principle, on the backtest path as much as on the search path."""
    store = PointInTimeStore(tmp_path / "empty.duckdb")
    store.register_dataset("empty", point_in_time=True)
    empty = Study(dataset_id="empty", store=store,
                  counter=TrialCounter(tmp_path / "t.db"),
                  holdout=ProtectedHoldout(tmp_path / "h.db"),
                  log=ExperimentLog(tmp_path / "r.db", repo=clean_repo))
    with pytest.raises(StudyError, match="no version"):
        empty.backtest(np.array([100.0, 101.0, 102.0]),
                       start="2015-01-01", end="2019-12-31")


def test_uncommitted_code_is_refused_before_a_backtest_runs(study):
    """FR-24 on the backtest path. The refusal must also leave no trial behind:
    `log.start` is ordered before `count_trial` for exactly this case."""
    dirty = Path(study.log.repo) / "strategy.py"
    dirty.write_text("# edited, not committed\n", encoding="utf-8")
    with pytest.raises(UncommittedCode):
        study.backtest(np.array([100.0, 101.0, 102.0]),
                       start="2015-01-01", end="2019-12-31")
    assert study.counter.trial_count("sp500") == 0


def test_an_absent_engine_is_recorded_as_a_failed_run(study, monkeypatch):
    """The engine is optional. The controls in front of it are not.

    `backtest` imported the engine as its FIRST statement, so in an install with
    the store and without nautilus_trader — a configuration this project
    supports and CI exercises — every refusal the method owes was replaced by an
    ImportError about a missing dependency, and not one of them could be
    reached. The import now happens at step 6, inside the run, so the four
    refusals above it hold in any install and an absent engine is a run that
    FAILED rather than a run that never opened (FR-25).

    Simulated here rather than skipped, because the install that would exercise
    it for real is the one where this file's engine tests do not run.
    """
    monkeypatch.setitem(sys.modules, "src.research_integrity.backtest", None)
    with pytest.raises(ImportError):
        study.backtest(np.array([100.0, 101.0, 102.0]),
                       start="2015-01-01", end="2019-12-31")

    runs = study.log.query()
    assert len(runs) == 1, (
        "the run record was never opened, so the engine was resolved before "
        "FR-22/FR-24 rather than after")
    assert runs[0]["outcome"] == "failed"
    # Either name: this simulation raises ModuleNotFoundError, an install
    # genuinely lacking nautilus_trader raises it too, and both are ImportError.
    error = json.loads(runs[0]["result_json"])["error"]
    assert error.startswith(("ImportError", "ModuleNotFoundError")), error


@needs_engine
def test_a_backtest_through_the_study_is_counted_and_recorded(study):
    """The whole ORDER, executed once, on the real engine.

    FR-08 counts it, FR-22 to FR-25 record it, and the result names the dataset
    version the store reported. None of that had ever run.
    """
    dates, prices = study.series("PRICE", "close")
    result = study.backtest(prices, start=dates[0], end=dates[-1],
                            params={"lookback": 20, "skip": 2})

    assert result["n_bars"] == len(dates)
    assert study.counter.trial_count("sp500") == 1
    record = study.log.get(result["run_id"])
    assert record["outcome"] == "completed"
    assert record["strategy"] == "momentum"
    assert result["dataset_version"] in record["dataset_versions"]

    stored = json.loads(record["result_json"])
    # `backtest` strips the per-fill impact charges out of the record on
    # purpose; the total stays. Asserted so the stripping cannot quietly widen.
    assert "impact_charges" in result and "impact_charges" not in stored
    assert stored["n_bars"] == result["n_bars"]


@needs_engine
def test_a_failing_backtest_is_recorded_as_failed_and_still_counted(study):
    """FR-25. An unrecorded failure is how a search quietly becomes smaller than
    it was, and the engine raising is the case most likely to go unwritten."""
    with pytest.raises(Exception):
        study.backtest(np.array([]), start="2015-01-01", end="2019-12-31")

    runs = study.log.query()
    assert len(runs) == 1
    assert runs[0]["outcome"] == "failed"
    assert "ValueError" in json.loads(runs[0]["result_json"])["error"]
    # Counted anyway: run_backtest registers the trial before the engine starts,
    # and a count you can dodge by not liking the answer counts nothing.
    assert study.counter.trial_count("sp500") == 1


# --- the declared-range hole, on the backtest path -------------------------

def test_backtest_series_refuses_the_range_the_data_actually_spans(study):
    """`backtest_series` is `search_series` for the engine: the range is a
    property of what was read, so there is no second string to disagree with it.

    Refused after the read and before anything is counted — `series` only reads,
    and `_admit` runs before the run record is opened. No engine is needed to
    reach this, and none should be: the refusal is the point.
    """
    dates, _ = study.series("PRICE", "close")
    study.holdout.define("sp500", start=dates[200], end=dates[-1])

    with pytest.raises(HoldoutViolation):
        study.backtest_series("PRICE", params={"lookback": 20, "skip": 2})
    assert study.counter.trial_count("sp500") == 0
    assert study.log.query() == []


def test_backtest_series_refuses_a_series_too_short_to_backtest(study):
    """Refusing, not warning: a one-observation read is not a backtest, and a
    warning about it is read once and then filtered out of the logs."""
    dates, _ = study.series("PRICE", "close")
    with pytest.raises(StudyError, match="nothing to backtest over"):
        study.backtest_series("PRICE", start=dates[0], end=dates[0])
    assert study.log.query() == []


@needs_engine
def test_the_raw_backtest_checks_the_declared_range_not_the_prices(study):
    """The limitation `backtest_series` exists to close, pinned as a limitation.

    The same prices, spanning the protected holdout, are accepted by `backtest`
    under a declared range that does not — because FR-10 is checked against two
    strings the caller chose. This is not a defect in `assert_ordinary_access`;
    it is what "declared, not derived" means, and it is why the method above
    reads through the store instead. If this ever starts refusing, `backtest`
    has gained a guarantee its docstring does not claim, and that is worth
    noticing rather than absorbing.
    """
    dates, prices = study.series("PRICE", "close")
    study.holdout.define("sp500", start=dates[200], end=dates[-1])

    result = study.backtest(prices, start=dates[0], end=dates[10],
                            params={"lookback": 20, "skip": 2})
    assert result["run_id"], "the holdout prices went through under a clean range"


@needs_engine
def test_backtest_series_records_the_full_call_signature(study):
    """FR-22 asks for the full parameter set and means it here too.

    `backtest` merges `params` with any surplus keyword arguments before handing
    them to the engine, so a record holding only `params` documents a run it
    cannot reproduce. The recorded set is the call signature.
    """
    result = study.backtest_series("PRICE", params={"lookback": 20},
                                   skip=2, trade_size=50)
    params = json.loads(study.log.get(result["run_id"])["params_json"])

    assert params["entity_id"] == "PRICE"
    assert params["field"] == "close"
    assert params["knowledge_date"] is None
    # The arguments as passed, not the derived range: a replay re-reads through
    # the store and derives the range again, exactly as this call did.
    assert params["start"] is None and params["end"] is None
    assert params["params"] == {"lookback": 20, "skip": 2, "trade_size": 50}


@needs_engine
def test_backtest_series_derives_the_range_from_the_data_it_read(study):
    """The holdout check and the data are the same fact.

    Nothing declares a range, and the run is still checked against — and
    recorded over — the dates the store returned.
    """
    dates, _ = study.series("PRICE", "close")
    study.holdout.define("sp500", start="2023-01-01", end="2024-12-31")

    result = study.backtest_series("PRICE", params={"lookback": 20, "skip": 2})
    assert result["n_bars"] == len(dates)
    assert study.log.get(result["run_id"])["outcome"] == "completed"
    assert study.counter.trial_count("sp500") == 1


# --- FR-11 / FR-12: the holdout is not an ordinary backtest ----------------

def test_the_holdout_is_reachable_only_through_pre_registration(study):
    study.holdout.define("sp500", start="2023-01-01", end="2024-12-31")
    registration = study.preregister(
        strategy_family="momentum",
        hypothesis="20-day momentum survives out of sample",
        expected_result="annualised Sharpe between 0.4 and 0.8")
    verdict = study.evaluate_on_holdout(registration,
                                        observed={"sharpe_annualised": 0.31})
    assert verdict["registration_id"] == registration


def test_status_reports_what_every_control_has_seen(study, returns):
    study.holdout.define("sp500", start="2023-01-01", end="2024-12-31")
    study.search(returns, GRID, start="2015-01-01", end="2019-12-31")
    status = study.status()
    assert status["n_trials"] == len(GRID)
    assert status["runs_recorded"] == 1
    assert status["holdout_period"] == ("2023-01-01", "2024-12-31")
    assert status["dataset_version"] == study.store.current_version("sp500")


# --- FR-23: a recorded run, actually re-executed ---------------------------

def test_a_recorded_search_replays_to_an_identical_result(study, returns):
    """The first thing to call replay() on a real run.

    FR-23 was marked met on the strength of unit tests for a control nothing
    reached. This exercises it through the seam: record, then re-execute from
    the record alone and require the same hash.
    """
    from src.research_integrity.run_record import NotReproducible  # noqa: F401

    result = study.search_series("PRICE", GRID, allow_uncommitted=True)
    verified = study.replay_search(result["run_id"])
    assert verified["reproduced"] is True
    assert study.log.get(result["run_id"])["replay_verified"] == 1


def test_a_replay_does_not_inflate_the_trial_count(study, returns):
    """The one place re-running a backtest must NOT touch the counter.

    A replay re-executes a search that was already counted; counting it again
    would inflate the number the deflated Sharpe depends on. Everything else in
    this package argues the opposite, so the exception is worth pinning.
    """
    result = study.search_series("PRICE", GRID, allow_uncommitted=True)
    before = study.counter.trial_count("sp500")
    study.replay_search(result["run_id"])
    assert study.counter.trial_count("sp500") == before


def test_a_restatement_does_not_break_a_replay(study):
    """Discovered by writing the failure test below and having it pass.

    Appending a revised value for a period already loaded does NOT change what
    the replay reads, because `series` returns as-first-reported. That is the
    point-in-time store doing its job: a run stays reproducible across
    revisions, which is a stronger guarantee than FR-23 asks for and follows
    from FR-02 rather than from anything in the run record.
    """
    result = study.search_series("PRICE", GRID, allow_uncommitted=True)
    existing = study.store.series("sp500", "PRICE", "close")[0][10]
    study.store.append_facts("sp500", [
        {"entity_id": "PRICE", "field": "close", "value": 999.0,
         "effective_date": existing, "knowledge_date": "2030-01-01",
         "is_restatement": True},
    ])
    assert study.replay_search(result["run_id"])["reproduced"] is True


def test_a_replay_fails_when_new_data_lands_inside_the_range(study):
    """The teeth. A replay that cannot fail verifies nothing.

    A period that was not there when the run executed genuinely changes what the
    query returns, and no amount of point-in-time discipline can make the old
    result reproduce — which is exactly what FR-23 exists to surface.
    """
    from src.research_integrity.run_record import NotReproducible

    result = study.search_series("PRICE", GRID, allow_uncommitted=True)
    dates = study.store.series("sp500", "PRICE", "close")[0]
    gap = "2019-01-05"                       # a weekend the fixture skipped
    assert gap not in dates and dates[0] < gap < dates[-1]
    study.store.append_facts("sp500", [
        {"entity_id": "PRICE", "field": "close", "value": 123.45,
         "effective_date": gap, "knowledge_date": gap},
    ])
    with pytest.raises(NotReproducible, match="did not reproduce"):
        study.replay_search(result["run_id"])


def test_the_record_holds_the_full_parameter_set_not_a_count(study):
    """FR-22 asks for the full parameter set and means it: a record saying
    `n_param_sets: 441` documents that a search happened without being
    sufficient to repeat it."""
    import json

    result = study.search_series("PRICE", GRID, allow_uncommitted=True)
    params = json.loads(study.log.get(result["run_id"])["params_json"])
    assert params["param_sets"] == [dict(p) for p in GRID]
    assert params["entity_id"] == "PRICE"


# --- the guard that would have caught the original problem -----------------

def test_no_control_is_orphaned():
    """Every control must be invoked by something other than itself.

    This is the check whose absence let three of four controls sit unreachable
    while all their own tests passed. Each control was correct; nothing called
    it. A test suite organised per-module cannot see that, because every module
    is exercised by its own file — the gap is in the space BETWEEN them.

    WHAT IT SEES: a caller for each control somewhere in the package other than
    the module that defines it. It runs in any install, needs no fixture and no
    engine, and it names the control and its requirement when it fails.

    WHAT IT CANNOT SEE: whether that caller ever RUNS. It is a text search, and
    `_admit` contains every string in the dict below, so the `search` path alone
    satisfied all six entries for the whole period in which `Study.backtest` —
    the FR-19/FR-21 half of the same seam — executed no statement in the entire
    suite. A control can be reachable by grep and dead in practice.
    `test_every_public_study_method_is_executed_by_the_suite` is the half that
    watches execution; the two catch different things and both are kept.

    It also cannot be extended to `Study`'s own methods. The dict maps a call
    string to the module that defines it and asserts some OTHER file in the
    package contains that string — and nothing in the package calls a `Study`
    method, so an entry for one fails unconditionally. `search_series` and
    `backtest_series` are deliberately absent for that reason, not by oversight.
    """
    package = Path(__file__).resolve().parent.parent / "src" / "research_integrity"
    controls = {
        ".require_point_in_time(": ("point_in_time.py", "FR-07"),
        ".assert_ordinary_access(": ("holdout.py", "FR-10"),
        ".start_trial(": ("trial_counter.py", "FR-08"),
        ".log.start(": ("run_record.py", "FR-22/FR-24"),
        ".current_version(": ("point_in_time.py", "FR-06"),
        # Added after this guard missed it: replay() was correct, tested 14
        # times in its own file, and called by nothing. FR-23 was marked met on
        # the strength of unit tests for a control no real run ever reached.
        ".log.replay(": ("run_record.py", "FR-23"),
    }
    for call, (home, requirement) in controls.items():
        callers = sorted(
            path.name for path in package.glob("*.py")
            if path.name not in (home, "__init__.py")
            and call in path.read_text(encoding="utf-8"))
        assert callers, (
            f"{requirement}: nothing outside {home} calls {call!r}. The control "
            "exists, its own tests pass, and it constrains nothing — which is "
            "the state src/research_integrity/study.py was written to end.")


# --- the guard that EXECUTES, beside the one that reads text ---------------

# Run in a subprocess with `sys.monitoring` watching one PY_START event per
# public `Study` method. PY_START on a specific code object costs nothing when
# it never fires and disables itself the first time it does, so this is a
# question about execution rather than a coverage run.
_EXECUTION_PROBE = """
import json, os, sys

sys.path.insert(0, os.environ["RI_STUDY_GUARD_ROOT"])

import pytest
from src.research_integrity.study import Study

mon = sys.monitoring
TOOL = mon.PROFILER_ID
mon.use_tool_id(TOOL, "study-execution-guard")

names = {fn.__code__: name for name, fn in vars(Study).items()
         if not name.startswith("_") and callable(fn)}
entered = set()

def _entered(code, offset):
    entered.add(names[code])
    return mon.DISABLE          # whether it ran at all is the whole question

mon.register_callback(TOOL, mon.events.PY_START, _entered)
for code in names:
    mon.set_local_events(TOOL, code, mon.events.PY_START)

status = pytest.main(["-q", "-p", "no:cacheprovider", *sys.argv[1:]])
print("DECLARED " + json.dumps(sorted(names.values())))
print("ENTERED " + json.dumps(sorted(entered)))
sys.exit(0 if status == 0 else 2)
"""


def _tagged(stdout: str, tag: str) -> list[str]:
    for line in stdout.splitlines():
        if line.startswith(tag + " "):
            return json.loads(line[len(tag) + 1:])
    raise AssertionError(f"the probe printed no {tag} line:\n{stdout[-4000:]}")


@pytest.mark.skipif(os.environ.get("RI_STUDY_EXECUTION_GUARD") == "1",
                    reason="this IS the subprocess; running it again recurses")
def test_every_public_study_method_is_executed_by_the_suite(tmp_path):
    """Every public `Study` method must actually RUN somewhere in the tests.

    WHAT THIS SEES THAT test_no_control_is_orphaned CANNOT

    That test greps the package for control call strings. It passed throughout
    the period when `Study.backtest` was dead: `_admit` contains every string in
    its dict, so the `search` path alone satisfied all six entries while the
    FR-19/FR-21 half of the seam ran zero statements in the whole suite. A
    control can be reachable by grep and dead in practice, and the only way to
    tell the difference is to watch it execute.

    So this one executes. It re-runs, in a subprocess, every test file that
    mentions the study, with `sys.monitoring` reporting the first entry into
    each public method's code object, and fails naming any method nothing
    entered.

    WHAT IT CANNOT SEE

    Reachability again, not correctness, and a weaker form of it than it looks:
    a method entered by one test that asserts nothing about it counts as
    executed. It also says nothing about the branches INSIDE a method — the
    `study` fixture spent a long time making `deflation_block` take the same
    branch every time while every method above it ran. And it watches `Study`
    only; the other modules are covered by their own files, which is the gap
    that let this happen in the first place.
    """
    root = Path(__file__).resolve().parent.parent
    probe = tmp_path / "execution_probe.py"
    probe.write_text(_EXECUTION_PROBE, encoding="utf-8")

    # Every test file that names the study, rather than a fixed pair: a method
    # exercised from a file added later should count, and one whose only caller
    # is deleted should stop counting.
    targets = sorted(str(path) for path in (root / "tests").glob("test_*.py")
                     if "study" in path.read_text(encoding="utf-8").lower())
    assert targets, "no test file mentions the study at all"

    outcome = subprocess.run(
        [sys.executable, str(probe), *targets],
        capture_output=True, text=True, cwd=root, timeout=1800,
        env={**os.environ, "RI_STUDY_GUARD_ROOT": str(root),
             "RI_STUDY_EXECUTION_GUARD": "1"})
    assert outcome.returncode == 0, (
        f"the probe's own pytest run failed:\n{outcome.stdout[-4000:]}"
        f"\n{outcome.stderr[-4000:]}")

    declared = _tagged(outcome.stdout, "DECLARED")
    entered = _tagged(outcome.stdout, "ENTERED")
    assert declared, "no public Study methods were found, so this asserts nothing"

    unexecuted = sorted(set(declared) - set(entered))
    assert not unexecuted, (
        f"{', '.join(unexecuted)}: declared on Study and executed by no test. "
        "The method may still be found by test_no_control_is_orphaned, which "
        "reads text; this one watched it not run. That is the state "
        "src/research_integrity/study.py was written to end, and `backtest` "
        "was in it for the whole life of the file.")


# --- FR-23 in the regime FR-08 creates: a workspace that accumulates --------
#
# Every replay test above this line replays the FIRST and ONLY search on a fresh
# workspace, where the live counter and a throwaway one happen to agree. The
# `--home` flag exists precisely so the count does NOT reset between runs
# (FR-08: "across all researchers and all time"), and from the second search
# onward the recorded counter state and a replay-local one cannot agree.

def test_a_second_search_on_the_same_workspace_still_replays(study):
    """The workspace's whole purpose, and what it used to cost.

    The trial count grows with the dataset's history BY DESIGN, so the second
    search records a larger `n_trials`, a different `var_trials` and therefore
    a different deflated Sharpe. None of that is a reproducibility failure: it
    is FR-08 working. The replay used to report it as one, blaming "an
    unrecorded seed, an environment difference, or uncommitted code" — none of
    which was the cause — and stamp the run replay_verified=0 permanently.
    """
    first = study.search_series("PRICE", GRID, allow_uncommitted=True)
    assert study.replay_search(first["run_id"])["reproduced"] is True

    second = study.search_series("PRICE", GRID, allow_uncommitted=True)
    assert second["n_trials"] > first["n_trials"], (
        "the counter did not accumulate, so this fixture no longer exercises "
        "the regime the --home flag exists for")
    # The claim in the docstring, asserted rather than described. With a
    # degenerate price path every trial scores the same Sharpe, `var_trials` is
    # zero, `deflation_block` takes its "variance undefined" branch and
    # `deflated_sharpe` is None on both runs — and this test then says nothing
    # about the deflation the FR-23 fix is about.
    assert first["deflated_sharpe"] is not None, (
        "the fixture deflated nothing: var_trials is "
        f"{first['var_trials']!r}, so no deflated Sharpe was computed")
    assert second["var_trials"] != first["var_trials"]
    assert second["deflated_sharpe"] != first["deflated_sharpe"]

    assert study.replay_search(second["run_id"])["reproduced"] is True
    assert study.log.get(second["run_id"])["replay_verified"] == 1


def test_a_replay_reports_the_trial_count_the_run_was_deflated_against(study):
    """The recorded burden is what the replay must attest to, not a smaller one.

    Dropping the counter block from the comparison would also make a replay
    silently agree with a run deflated against 24 trials when 7,866 were
    recorded. The replayed result carries the RECORDED ledger state.
    """
    study.search_series("PRICE", GRID, allow_uncommitted=True)
    second = study.search_series("PRICE", GRID, allow_uncommitted=True)
    replayed = study.replay_search(second["run_id"])["result"]
    assert replayed["n_trials"] == second["n_trials"] == 2 * len(GRID)
    assert replayed["var_trials"] == second["var_trials"]
    # Checked before the comparison below, because None == None would pass it
    # while proving nothing — which is what this assertion did for as long as
    # the fixture's trials all scored an identical Sharpe.
    assert second["deflated_sharpe"] is not None, (
        "the fixture deflated nothing, so the line below compares None to None")
    assert replayed["deflated_sharpe"] == second["deflated_sharpe"]


def test_the_second_search_still_fails_its_replay_when_the_data_changes(study):
    """The teeth, in the regime the fix touches.

    A replay that cannot fail verifies nothing, so the accumulated case must
    still break on data that genuinely changed — otherwise the fix bought a
    clean replay by removing the check.
    """
    from src.research_integrity.run_record import NotReproducible

    study.search_series("PRICE", GRID, allow_uncommitted=True)
    second = study.search_series("PRICE", GRID, allow_uncommitted=True)
    gap = "2019-01-05"                       # a weekend the fixture skipped
    dates = study.store.series("sp500", "PRICE", "close")[0]
    assert gap not in dates and dates[0] < gap < dates[-1]
    study.store.append_facts("sp500", [
        {"entity_id": "PRICE", "field": "close", "value": 123.45,
         "effective_date": gap, "knowledge_date": gap},
    ])
    with pytest.raises(NotReproducible, match="did not reproduce"):
        study.replay_search(second["run_id"])


def test_a_replay_still_does_not_inflate_the_count_on_a_used_workspace(study):
    """The reason the throwaway counter exists, re-pinned for the second search.

    A replay re-executes a search that was already counted. If restoring the
    recorded ledger state had been done by writing to the live counter, this is
    the test that would catch it.
    """
    study.search_series("PRICE", GRID, allow_uncommitted=True)
    second = study.search_series("PRICE", GRID, allow_uncommitted=True)
    before = study.counter.trial_count("sp500")
    study.replay_search(second["run_id"])
    assert study.counter.trial_count("sp500") == before


def test_a_doctored_trial_count_in_the_record_still_fails_the_replay(study):
    """Why the ledger block is RESTORED from the record rather than excluded
    from the comparison.

    Understating the burden is the one edit that flatters a result: the deflated
    Sharpe rises as the trial count falls. Excluding the counter-derived keys
    would have made a replay blind to exactly that. Restoring `n_trials` and
    re-deriving the deflated Sharpe from it means a record claiming a deflated
    Sharpe its own trial count does not support no longer reproduces.

    (This one also passes against the unfixed code, where the second search's
    replay failed for its own reason. It is here so the fix cannot be weakened
    into the excluding version without something going red.)
    """
    import json
    import sqlite3

    from src.research_integrity.run_record import NotReproducible

    study.search_series("PRICE", GRID, allow_uncommitted=True)
    second = study.search_series("PRICE", GRID, allow_uncommitted=True)
    assert study.replay_search(second["run_id"])["reproduced"] is True
    # Without a deflated Sharpe in the result, the only thing the doctoring
    # below changes is the `n_trials` key itself, and the argument this test
    # makes — that understating the burden flatters the figure derived from it
    # — would not be the reason it goes red.
    assert second["deflated_sharpe"] is not None

    # The write-once trigger guards result_hash, not result_json, so the stored
    # result and the hash of the real one can be made to disagree.
    conn = sqlite3.connect(study.log.db_path)
    stored = json.loads(conn.execute(
        "SELECT result_json FROM runs WHERE run_id = ?",
        (second["run_id"],)).fetchone()[0])
    conn.execute("UPDATE runs SET result_json = ? WHERE run_id = ?",
                 (json.dumps({**stored, "n_trials": len(GRID)}, sort_keys=True),
                  second["run_id"]))
    conn.commit()
    conn.close()

    with pytest.raises(NotReproducible, match="did not reproduce"):
        study.replay_search(second["run_id"])


def test_a_run_with_no_recorded_ledger_state_is_refused(study):
    """FR-07's precedent: refuse rather than warn. Falling back to the replay's
    own throwaway counter for a run that recorded no trial count is how the
    original bug would come back silently."""
    with pytest.raises(Exception):
        study.search(np.array([]), GRID, start="2015-01-01", end="2019-12-31")
    failed = study.log.query(outcome="failed")[0]["run_id"]
    with pytest.raises(StudyError, match="no trial-ledger state"):
        study.replay_search(failed)
