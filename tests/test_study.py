"""The seam that makes the controls binding.

Before this existed, three of the four controls in this package constrained
nothing: the holdout guard was called only by its own docstring, no code path
wrote a run record, and `require_point_in_time` — which implements FR-07's
refusal exactly — was never triggered by a caller. Only the trial counter was
wired in.

So these tests are about REACHABILITY, not correctness. Each control's own tests
already prove it works. What was missing was proof that anything invokes it, and
that is what fails here if the seam comes apart.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("duckdb", reason="the study needs the point-in-time store")

from src.research_integrity.holdout import HoldoutViolation, ProtectedHoldout
from src.research_integrity.point_in_time import PointInTimeError, PointInTimeStore
from src.research_integrity.run_record import ExperimentLog, UncommittedCode
from src.research_integrity.study import ORDER, Study, StudyError
from src.research_integrity.trial_counter import TrialCounter


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
    store = PointInTimeStore(tmp_path / "facts.duckdb")
    store.register_dataset("sp500", point_in_time=True)
    # A price series long enough for a crossover grid to run over.
    import datetime as _dt

    day = _dt.date(2019, 1, 1)
    facts = []
    price = 100.0
    for i in range(320):
        while day.weekday() >= 5:
            day += _dt.timedelta(days=1)
        price *= 1.0 + (0.004 if i % 3 else -0.005)
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

    Reachability, not correctness: it asserts only that a caller exists outside
    the defining module. If a control is ever unwired again, this fails, and it
    names which one.
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
