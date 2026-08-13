"""Reproducibility — PRD 04 FR-22, FR-23, FR-24, FR-25.

FR-23 is the only requirement here that can be tested by doing rather than by
inspecting: "any past run MUST be re-executable from its record and MUST produce
bitwise-identical results."

That is why `replay()` re-executes and compares hashes instead of checking that
the fields were populated. A record with every field filled in still fails to
reproduce if an unrecorded seed was consumed — and the whole failure mode is
that the missing field is never the one you thought to record. So the tests
below include a function that consumes an unrecorded source of randomness and
require the replay to catch it.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research_integrity.run_record import (  # noqa: E402
    ExperimentLog,
    NotReproducible,
    UncommittedCode,
    canonical_hash,
    git_state,
)


@pytest.fixture()
def clean_repo(tmp_path) -> Path:
    """A committed git repo, so FR-24 is satisfied by default."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "strategy.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
    return repo


@pytest.fixture()
def log(tmp_path, clean_repo) -> ExperimentLog:
    # The database lives beside the repo, not inside it. Keeping it inside was
    # the first bug found here: writing the log made the tree untracked-dirty
    # and every subsequent run was rejected as unknown code. The second was
    # putting it in a directory SHARED across tests, so runs accumulated and
    # the query counts were wrong — tmp_path is per-test, tmp_path.parent
    # is not.
    return ExperimentLog(tmp_path / "runs.db", repo=clean_repo)


BASE = dict(params={"lookback": 20}, seeds={"python": 42},
            dataset_versions=["fundamentals@v3"])


# --- FR-22: the record is complete -----------------------------------------

def test_a_run_records_everything_the_requirement_names(log):
    run_id = log.start("momentum", factors=["value"], **BASE)
    log.finish(run_id, result={"sharpe": 0.31})
    rec = log.get(run_id)

    assert rec["code_sha"] != "UNKNOWN"
    assert '"lookback": 20' in rec["params_json"]
    assert '"python": 42' in rec["seeds_json"]
    assert "fundamentals@v3" in rec["dataset_versions"]
    assert rec["started_at"] and rec["ended_at"]
    assert "python" in rec["environment_json"]


def test_dataset_versions_are_required(log):
    """A run that cannot name the data it read is not reproducible even in
    principle. This is the field that ties FR-22 to FR-06."""
    with pytest.raises(ValueError, match="dataset_versions"):
        log.start("momentum", params={}, seeds={"python": 1}, dataset_versions=[])


def test_seeds_must_be_stated_even_when_there_is_no_randomness(log):
    """Passing seeds={'deterministic': 0} puts the CLAIM on record. An omitted
    seeds argument records nothing and looks identical to forgetting."""
    with pytest.raises(ValueError, match="seeds"):
        log.start("momentum", params={}, seeds={}, dataset_versions=["v1"])
    log.start("momentum", params={}, seeds={"deterministic": 0},
              dataset_versions=["v1"])


# --- FR-24: uncommitted code -----------------------------------------------

def test_uncommitted_code_is_rejected_by_default(log, clean_repo):
    """'A result from unknown code is not a result.'"""
    (clean_repo / "strategy.py").write_text("VALUE = 2\n")
    with pytest.raises(UncommittedCode, match="not a result"):
        log.start("momentum", **BASE)


def test_uncommitted_code_may_be_recorded_as_a_full_diff(log, clean_repo):
    """The requirement's other branch: allowed, but attributable."""
    (clean_repo / "strategy.py").write_text("VALUE = 2\n")
    run_id = log.start("momentum", allow_uncommitted=True, **BASE)
    rec = log.get(run_id)
    assert rec["code_dirty"] == 1
    assert "VALUE = 2" in rec["code_diff"]
    assert "VALUE = 1" in rec["code_diff"]


def test_the_diff_is_full_not_a_summary(log, clean_repo):
    """A truncated diff cannot reconstruct the code, and reconstructing it is
    the entire purpose."""
    (clean_repo / "strategy.py").write_text("\n".join(f"LINE_{i} = {i}"
                                                      for i in range(200)))
    run_id = log.start("momentum", allow_uncommitted=True, **BASE)
    diff = log.get(run_id)["code_diff"]
    assert "LINE_0" in diff and "LINE_199" in diff


def test_a_clean_tree_records_no_diff(log):
    run_id = log.start("momentum", **BASE)
    rec = log.get(run_id)
    assert rec["code_dirty"] == 0
    assert rec["code_diff"] is None


# --- FR-23: bitwise re-execution -------------------------------------------

def deterministic(lookback: int) -> dict:
    import random
    return {"value": sum(random.random() for _ in range(lookback))}


def leaks_unrecorded_randomness(lookback: int) -> dict:
    """Consumes a source of randomness the record never mentions."""
    import secrets
    return {"value": secrets.randbelow(10 ** 9)}


def test_a_reproducible_run_replays_bitwise_identically(log):
    run_id = log.start("momentum", **BASE)
    ExperimentLog.restore_seeds({"python": 42})
    log.finish(run_id, result=deterministic(20))

    outcome = log.replay(run_id, deterministic)
    assert outcome["reproduced"] is True
    assert log.get(run_id)["replay_verified"] == 1


def test_an_unrecorded_random_source_is_caught_by_replay(log):
    """The failure mode the requirement exists for: every field populated, and
    the run still does not reproduce, because the missing field is never the
    one you thought to record."""
    run_id = log.start("momentum", **BASE)
    log.finish(run_id, result=leaks_unrecorded_randomness(20))

    with pytest.raises(NotReproducible, match="did not reproduce"):
        log.replay(run_id, leaks_unrecorded_randomness)
    assert log.get(run_id)["replay_verified"] == 0


def test_replay_restores_the_seed_rather_than_merely_recording_it(log):
    """A recorded seed that is never re-applied documents irreproducibility
    instead of preventing it."""
    run_id = log.start("momentum", **BASE)
    ExperimentLog.restore_seeds({"python": 42})
    log.finish(run_id, result=deterministic(20))

    # Disturb the global RNG; replay must reset it.
    import random
    random.seed(999)
    random.random()
    assert log.replay(run_id, deterministic)["reproduced"] is True


def test_an_unknown_random_source_is_refused_not_skipped(log):
    """Skipping it would let a replay 'succeed' without restoring state."""
    with pytest.raises(ValueError, match="unknown random source"):
        ExperimentLog.restore_seeds({"cupy": 7})


def test_replaying_a_run_with_no_result_is_refused(log):
    run_id = log.start("momentum", **BASE)
    with pytest.raises(ValueError, match="never recorded a result"):
        log.replay(run_id, deterministic)


def test_the_result_hash_is_order_independent():
    """Dict ordering must not make identical results look different, or the
    false alarms would teach everyone to ignore real ones."""
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


# --- FR-25: the log is queryable -------------------------------------------

def test_runs_are_queryable_by_strategy_factor_date_and_outcome(log):
    a = log.start("momentum", factors=["value", "size"], **BASE)
    log.finish(a, result={"sharpe": 0.3})
    b = log.start("reversal", factors=["quality"], **BASE)
    log.finish(b, result={"sharpe": 0.1}, outcome="rejected")

    assert len(log.query(strategy="momentum")) == 1
    assert len(log.query(factor="value")) == 1
    assert len(log.query(factor="quality")) == 1
    assert len(log.query(outcome="rejected")) == 1
    assert len(log.query(since="2000-01-01")) == 2
    assert len(log.query(until="2000-01-01")) == 0


def test_a_failed_run_is_recorded_not_lost(log):
    """An unrecorded failure is how a search quietly becomes smaller than it
    was — the same argument the trial counter makes."""
    with pytest.raises(ZeroDivisionError):
        with log.run("momentum", **BASE):
            1 / 0
    failures = log.query(outcome="failed")
    assert len(failures) == 1
    assert "ZeroDivisionError" in failures[0]["result_json"]


# --- permanence --------------------------------------------------------------

def test_run_records_cannot_be_deleted(log):
    import sqlite3
    run_id = log.start("momentum", **BASE)
    log.finish(run_id, result={"x": 1})
    with sqlite3.connect(log.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="permanent"):
            conn.execute("DELETE FROM runs")


def test_code_and_parameters_are_immutable(log):
    import sqlite3
    run_id = log.start("momentum", **BASE)
    with sqlite3.connect(log.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE runs SET code_sha = 'faked' WHERE run_id = ?",
                         (run_id,))


def test_git_state_reports_a_real_sha(clean_repo):
    state = git_state(clean_repo)
    assert len(state["code_sha"]) == 40
    assert state["dirty"] is False


def test_an_untracked_artifact_does_not_count_as_uncommitted_code(log, clean_repo):
    """Writing a database or a result file into the repo must not make every
    subsequent run unknown-code — that is how a control gets switched off."""
    (clean_repo / "results.db").write_bytes(b"artifact")
    log.start("momentum", **BASE)


def test_an_untracked_source_file_does_count(log, clean_repo):
    """An untracked .py can be imported, so it is genuinely unknown code."""
    (clean_repo / "secret_strategy.py").write_text("EDGE = 42\n")
    with pytest.raises(UncommittedCode, match="secret_strategy.py"):
        log.start("momentum", **BASE)
