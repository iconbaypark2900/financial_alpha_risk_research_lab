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
    NON_UTF8_DIFF_MARKER,
    NotReproducible,
    UncommittedCode,
    canonical_hash,
    decode_diff,
    encode_diff,
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


# --- FR-24: untracked source is evidence, not just a flag -------------------
#
# Detecting that an untracked .py is unknown code and then storing an empty
# diff records the DETECTION and discards the EVIDENCE. `git diff HEAD` cannot
# contain a file git has never been told about, so these tests pin the contents,
# not the flag.

def _reconstruct(repo: Path, dest: Path, record: dict) -> Path:
    """Check out the SHA the record names and apply the diff it stored. The only
    test of a diff that matters is whether it reconstructs the code."""
    subprocess.run(["git", "clone", "-q", str(repo), str(dest)], check=True)
    subprocess.run(["git", "checkout", "-q", record["code_sha"]], cwd=dest,
                   check=True)
    patch = dest.parent / "recorded.patch"
    patch.write_bytes(decode_diff(record["code_diff"]))
    subprocess.run(["git", "apply", str(patch)], cwd=dest, check=True)
    return dest


def test_untracked_source_is_recorded_in_the_diff_not_merely_flagged(log, clean_repo):
    """The case the module goes out of its way to detect is exactly the case it
    used to record as code_dirty=1 with an empty diff."""
    (clean_repo / "secret_strategy.py").write_text("EDGE = 42\n")
    run_id = log.start("momentum", allow_uncommitted=True, **BASE)
    rec = log.get(run_id)

    assert rec["code_dirty"] == 1
    assert "EDGE = 42" in rec["code_diff"]


def test_the_recorded_diff_reconstructs_the_untracked_code(log, clean_repo, tmp_path):
    """'A truncated diff cannot reconstruct the code, and reconstructing it is
    the entire purpose.' So: check out the SHA, apply the diff, compare."""
    (clean_repo / "secret_strategy.py").write_text("EDGE = 42\nDEF = 'x'\n")
    (clean_repo / "strategy.py").write_text("VALUE = 2\n")
    run_id = log.start("momentum", allow_uncommitted=True, **BASE)

    dest = _reconstruct(clean_repo, tmp_path / "reconstructed", log.get(run_id))
    assert (dest / "secret_strategy.py").read_text() == "EDGE = 42\nDEF = 'x'\n"
    assert (dest / "strategy.py").read_text() == "VALUE = 2\n"


def test_recording_untracked_code_does_not_touch_the_users_index(log, clean_repo):
    """Both halves at once. Capturing the file by staging it into the real index
    would record the evidence by editing the user's repository as a side effect
    of running a backtest — a control that damages what it observes."""
    (clean_repo / "secret_strategy.py").write_text("EDGE = 42\n")

    def state() -> tuple[str, str]:
        return (subprocess.run(["git", "status", "--porcelain"], cwd=clean_repo,
                               capture_output=True, text=True).stdout,
                subprocess.run(["git", "ls-files", "--stage"], cwd=clean_repo,
                               capture_output=True, text=True).stdout)

    before = state()
    run_id = log.start("momentum", allow_uncommitted=True, **BASE)

    assert "EDGE = 42" in log.get(run_id)["code_diff"]
    assert state() == before
    assert "?? secret_strategy.py" in before[0]


def test_untracked_code_that_cannot_be_captured_is_refused(log, clean_repo,
                                                           monkeypatch):
    """FR-24's other branch. If the contents cannot be recorded, the run is
    refused — allow_uncommitted buys a full diff, not an exemption."""
    from src.research_integrity import run_record

    real = run_record.git_state

    def half_captured(repo):
        state = real(repo)
        state["untracked_source"] = ["secret_strategy.py"]
        state["untracked_unrecorded"] = ["secret_strategy.py"]
        state["dirty"] = True
        return state

    monkeypatch.setattr(run_record, "git_state", half_captured)
    with pytest.raises(UncommittedCode, match="secret_strategy.py"):
        log.start("momentum", allow_uncommitted=True, **BASE)


def test_an_untracked_source_file_with_a_non_ascii_name_is_unknown_code(log,
                                                                        clean_repo):
    """git quotes such a path in its default output, so a suffix test against
    the quoted form ('caf\\303\\251.py') sees no .py and the file was neither
    detected nor recorded."""
    (clean_repo / "café.py").write_text("EDGE = 43\n")
    with pytest.raises(UncommittedCode):
        log.start("momentum", **BASE)

    run_id = log.start("momentum", allow_uncommitted=True, **BASE)
    assert "EDGE = 43" in log.get(run_id)["code_diff"]


def test_untracked_source_git_reads_as_binary_is_still_reconstructable(
        log, clean_repo, tmp_path):
    """A .py holding bytes git calls binary diffs as 'Binary files differ',
    which reconstructs nothing. The recorded form has to survive that."""
    payload = b"X = 1\n\x00\xff\xfe not text\n"
    (clean_repo / "secret_strategy.py").write_bytes(payload)
    run_id = log.start("momentum", allow_uncommitted=True, **BASE)

    dest = _reconstruct(clean_repo, tmp_path / "reconstructed", log.get(run_id))
    assert (dest / "secret_strategy.py").read_bytes() == payload


def test_the_record_names_the_untracked_files_whose_content_it_captured(log,
                                                                        clean_repo):
    """A new-file section in a diff does not say whether git had ever seen the
    file. Which files were unknown code is a fact about the run."""
    (clean_repo / "secret_strategy.py").write_text("EDGE = 42\n")
    run_id = log.start("momentum", allow_uncommitted=True, **BASE)
    assert "secret_strategy.py" in log.get(run_id)["code_untracked"]


def test_a_log_written_before_untracked_capture_still_records(tmp_path, clean_repo):
    """CREATE TABLE IF NOT EXISTS leaves an existing table at its old shape, so
    an old log would otherwise fail every INSERT after this change."""
    import sqlite3
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE runs (run_id TEXT PRIMARY KEY, strategy TEXT NOT NULL,"
            " factors_json TEXT, params_json TEXT NOT NULL, seeds_json TEXT NOT"
            " NULL, dataset_versions TEXT NOT NULL, code_sha TEXT NOT NULL,"
            " code_dirty INTEGER NOT NULL, code_diff TEXT, environment_json TEXT"
            " NOT NULL, started_at TEXT NOT NULL, ended_at TEXT, outcome TEXT,"
            " result_json TEXT, result_hash TEXT, replay_verified INTEGER)")

    reopened = ExperimentLog(db, repo=clean_repo)
    (clean_repo / "secret_strategy.py").write_text("EDGE = 42\n")
    run_id = reopened.start("momentum", allow_uncommitted=True, **BASE)
    assert "secret_strategy.py" in reopened.get(run_id)["code_untracked"]


# --- FR-23: a seed that restores nothing ------------------------------------

def test_a_numpy_seed_is_refused_because_it_restores_nothing_the_code_uses(log):
    """np.random.seed() seeds the legacy global RandomState. Every randomised
    module here uses np.random.default_rng(seed), which never consults it, so
    recording seeds={'numpy': N} recorded a restoration that never happened."""
    with pytest.raises(ValueError, match="numpy"):
        ExperimentLog.restore_seeds({"numpy": 7})


def test_an_unrestorable_seed_is_refused_when_the_run_starts(log):
    """Refusing only at replay means the unusable record already exists, and
    run records are permanent."""
    with pytest.raises(ValueError, match="numpy"):
        log.start("momentum", params={"lookback": 20}, seeds={"numpy": 7},
                  dataset_versions=["fundamentals@v3"])
    assert log.query() == []


def test_the_legacy_numpy_global_is_restorable_under_its_own_name(log):
    """What np.random.seed() actually restores, named as what it is."""
    import numpy as np
    ExperimentLog.restore_seeds({"numpy_legacy": 7})
    first = np.random.normal(size=3).tolist()
    ExperimentLog.restore_seeds({"numpy_legacy": 7})
    assert np.random.normal(size=3).tolist() == first


def legacy_global_draw(lookback: int) -> dict:
    """Consumes numpy's legacy global RandomState, the one np.random.seed sets."""
    import numpy as np
    return {"value": float(np.random.normal(size=lookback).sum())}


def test_replay_restores_the_numpy_legacy_global_rather_than_recording_it(log):
    import numpy as np
    seeds = {"numpy_legacy": 7}
    run_id = log.start("momentum", params={"lookback": 20}, seeds=seeds,
                       dataset_versions=["fundamentals@v3"])
    ExperimentLog.restore_seeds(seeds)
    log.finish(run_id, result=legacy_global_draw(20))

    np.random.seed(999)
    np.random.normal(size=5)
    assert log.replay(run_id, legacy_global_draw)["reproduced"] is True


def generator_draw(lookback: int, seed: int) -> dict:
    """The shape every randomised module here has: the Generator takes its seed
    as an argument, so the seed is a PARAMETER of the run."""
    import numpy as np
    return {"value": float(np.random.default_rng(seed).normal(size=lookback).sum())}


def test_a_generator_seed_is_restored_through_params_not_through_seeds(log):
    """The honest replacement for seeds={'numpy': N}: replay() re-supplies
    params, so a default_rng seed recorded there is genuinely restored, while
    the same seed recorded under 'numpy' would restore nothing."""
    run_id = log.start("momentum", params={"lookback": 20, "seed": 7},
                       seeds={"deterministic": 0},
                       dataset_versions=["fundamentals@v3"])
    log.finish(run_id, result=generator_draw(20, 7))

    import numpy as np
    np.random.seed(999)                        # cannot matter, and must not
    assert log.replay(run_id, generator_draw)["reproduced"] is True

    with pytest.raises(ValueError, match="default_rng"):
        ExperimentLog.restore_seeds({"numpy_default_rng": 7})


# ---- a diff that is text to git but not valid UTF-8 --------------------------
#
# `_git` decodes with surrogateescape, so these arrive carrying lone surrogates.
# sqlite3 cannot encode those: recording the untracked file used to take the
# whole run down with `UnicodeEncodeError`, which is worse than the empty diff it
# replaced. git only base64s a file as binary when it contains NUL, so a latin-1
# source file is diffed as text and reaches storage raw.

LATIN1_SOURCE = b"# strat\xe9gie\nEDGE = 42\n"


def test_a_non_utf8_untracked_file_does_not_take_the_run_down(log, clean_repo):
    (clean_repo / "secret_strategy.py").write_bytes(LATIN1_SOURCE)
    run_id = log.start("momentum", allow_uncommitted=True, **BASE)

    assert log.get(run_id)["code_dirty"] == 1


def test_a_non_utf8_tracked_modification_does_not_take_the_run_down(log, clean_repo):
    """Not the defect this recording was added for, and it regressed anyway: a
    single latin-1 comment anywhere in the tree made every run unrecordable."""
    (clean_repo / "strategy.py").write_bytes(b"# caf\xe9 comment\nVALUE = 2\n")
    run_id = log.start("momentum", allow_uncommitted=True, **BASE)

    assert log.get(run_id)["code_dirty"] == 1


def test_a_non_utf8_diff_still_reconstructs_the_code(log, clean_repo, tmp_path):
    """The only test of a diff that matters. Byte-for-byte, not str-for-str —
    a replacement character would satisfy a text comparison and fail to apply."""
    (clean_repo / "secret_strategy.py").write_bytes(LATIN1_SOURCE)
    run_id = log.start("momentum", allow_uncommitted=True, **BASE)

    dest = _reconstruct(clean_repo, tmp_path / "reconstructed", log.get(run_id))
    assert (dest / "secret_strategy.py").read_bytes() == LATIN1_SOURCE


def test_an_ordinary_diff_is_stored_as_readable_text(log, clean_repo):
    """The encoding is a fallback, not a format. A diff someone can read in a
    sqlite browser must stay one, or the escape hatch has cost everyone."""
    (clean_repo / "secret_strategy.py").write_text("EDGE = 42\n")
    run_id = log.start("momentum", allow_uncommitted=True, **BASE)

    stored = log.get(run_id)["code_diff"]
    assert "EDGE = 42" in stored
    assert not stored.startswith(NON_UTF8_DIFF_MARKER)


def test_encode_diff_round_trips_arbitrary_bytes():
    raw = b"diff --git a/x b/x\n+# \xe9\xff\xfe not utf-8\n"
    assert decode_diff(encode_diff(raw.decode("utf-8", "surrogateescape"))) == raw


# ---- a working tree git cannot report is not a clean one --------------------

def _corrupt_the_index(repo: Path) -> None:
    """`git status` then exits 128 while `git rev-parse HEAD` still succeeds, so
    the tree looks readable to the SHA probe and is not to the dirtiness one.
    No mocking: this is a state a real repository reaches."""
    (repo / ".git" / "index").write_bytes(b"\x00\x01\x02")


def test_a_tree_git_cannot_report_is_not_recorded_as_clean(log, clean_repo):
    """The strongest claim this module makes is code_dirty=0 beside a real SHA:
    this is exactly the committed code. It must never be made on no evidence."""
    (clean_repo / "strategy.py").write_text("VALUE = 999\n")
    _corrupt_the_index(clean_repo)

    assert git_state(clean_repo)["state_unknown"] is True
    with pytest.raises(UncommittedCode, match="unknown"):
        log.start("momentum", **BASE)


def test_an_unreportable_tree_is_refused_even_with_allow_uncommitted(log, clean_repo):
    """allow_uncommitted trades a refusal for a recorded diff. Here there is no
    diff to record, so there is nothing to trade and the override must not apply."""
    (clean_repo / "strategy.py").write_text("VALUE = 999\n")
    _corrupt_the_index(clean_repo)

    with pytest.raises(UncommittedCode):
        log.start("momentum", allow_uncommitted=True, **BASE)


def test_a_healthy_clean_tree_is_still_reported_as_known(log, clean_repo):
    """The refusal must not fire on the ordinary case it sits next to."""
    assert git_state(clean_repo)["state_unknown"] is False
    assert log.get(log.start("momentum", **BASE))["code_dirty"] == 0
