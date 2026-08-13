"""Reproducibility — PRD 04 §5.4, FR-22, FR-23, FR-24, FR-25.

    FR-22  Every run MUST record dataset versions, code commit SHA, full
           parameter set, random seeds, environment specification, and
           start/end timestamps.
    FR-23  Any past run MUST be re-executable from its record and MUST produce
           bitwise-identical results.
    FR-24  Uncommitted code MUST be either rejected or recorded as a full diff.
           A result from unknown code is not a result.
    FR-25  The experiment log MUST be queryable across all runs by strategy,
           factor, date range, and outcome.

WHAT MAKES THIS DIFFERENT FROM LOGGING

A log records that something happened. A run record must be sufficient to make
it happen again — which is a much stronger claim, and one that is almost always
false in practice for a reason that is easy to miss: the missing field is never
the one you thought to record. It is the seed you did not know was consumed, the
package that was upgraded in between, or the three lines you edited and did not
commit.

So FR-23 is enforced rather than asserted. `replay()` re-executes the recorded
call and compares a hash of the output against the hash stored at the time. If
they differ, the run was not reproducible and the record says so — instead of
the reader assuming it was because the fields were all populated.

FR-24 is the one people are tempted to soften. "Reject uncommitted code" feels
harsh during exploration, so the usual compromise is a warning. This module
takes the requirement's other branch: uncommitted code is allowed but the FULL
DIFF is stored, so the result remains attributable. What is not allowed is a
result whose code cannot be reconstructed at all.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import sqlite3
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT PRIMARY KEY,
    strategy          TEXT NOT NULL,
    factors_json      TEXT,
    params_json       TEXT NOT NULL,
    seeds_json        TEXT NOT NULL,
    dataset_versions  TEXT NOT NULL,
    code_sha          TEXT NOT NULL,
    code_dirty        INTEGER NOT NULL,
    code_diff         TEXT,
    environment_json  TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    outcome           TEXT,
    result_json       TEXT,
    result_hash       TEXT,
    replay_verified   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_runs_strategy ON runs(strategy);
CREATE INDEX IF NOT EXISTS idx_runs_started  ON runs(started_at);
CREATE INDEX IF NOT EXISTS idx_runs_outcome  ON runs(outcome);

-- A run record that can be edited after the fact records nothing. The result
-- and the code that produced it are written once.
CREATE TRIGGER IF NOT EXISTS runs_no_delete
BEFORE DELETE ON runs
BEGIN
    SELECT RAISE(ABORT, 'run records are permanent: a deleted run is a result whose provenance no longer exists');
END;

CREATE TRIGGER IF NOT EXISTS runs_result_write_once
BEFORE UPDATE ON runs
BEGIN
    SELECT RAISE(ABORT, 'run identity, code and parameters are immutable')
    WHERE NEW.run_id     IS NOT OLD.run_id
       OR NEW.code_sha   IS NOT OLD.code_sha
       OR NEW.params_json IS NOT OLD.params_json
       OR NEW.seeds_json IS NOT OLD.seeds_json
       OR NEW.started_at IS NOT OLD.started_at;

    SELECT RAISE(ABORT, 'a recorded result cannot be rewritten')
    WHERE OLD.result_hash IS NOT NULL
      AND NEW.result_hash IS NOT OLD.result_hash
      AND NEW.replay_verified IS OLD.replay_verified;
END;
"""


class UncommittedCode(RuntimeError):
    """FR-24: a result from unknown code is not a result."""


class NotReproducible(AssertionError):
    """FR-23: re-execution produced a different result."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(obj: Any) -> str:
    """Deterministic hash of a result, for bitwise comparison across runs.

    Uses sorted-key JSON so dict ordering cannot make two identical results look
    different — which would produce false reproducibility failures and, worse,
    teach everyone to ignore them.
    """
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def git_state(repo: str | Path = ".") -> dict[str, Any]:
    """Commit SHA, dirty flag, and the full diff if dirty (FR-22, FR-24)."""
    def run(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", "-C", str(repo), *args],
                                 capture_output=True, text=True, timeout=30)
            return out.stdout.strip() if out.returncode == 0 else None
        except Exception:
            return None

    sha = run("rev-parse", "HEAD")

    # Dirtiness means UNCOMMITTED CODE, not "any file the repo has not seen".
    # Writing the experiment log or a result file inside the repo would
    # otherwise mark every subsequent run as unknown-code and reject it — which
    # is how a well-intentioned control gets switched off wholesale.
    #
    # So: modifications to tracked files always count, and untracked files count
    # only when they are source. An untracked .py can be imported and is
    # genuinely unknown code; an untracked .db is an artifact.
    tracked = run("status", "--porcelain", "--untracked-files=no") or ""
    untracked = run("ls-files", "--others", "--exclude-standard") or ""
    SOURCE_SUFFIXES = (".py", ".pyx", ".sql", ".toml", ".cfg", ".yaml", ".yml")
    untracked_source = [f for f in untracked.splitlines()
                        if f.strip().endswith(SOURCE_SUFFIXES)]
    dirty = bool(tracked.strip()) or bool(untracked_source)
    return {
        "code_sha": sha or "UNKNOWN",
        "dirty": dirty,
        # The full diff, not a summary. A truncated diff cannot reconstruct the
        # code, and reconstructing it is the entire purpose.
        "diff": (run("diff", "HEAD") or "") if dirty else None,
        "untracked_source": untracked_source,
    }


def environment() -> dict[str, Any]:
    """Enough of the environment to explain a difference between two runs."""
    try:
        from importlib.metadata import distributions
        packages = sorted(f"{d.metadata['Name']}=={d.version}"
                          for d in distributions()
                          if d.metadata.get("Name"))
    except Exception:  # pragma: no cover
        packages = []
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
        "env_vars": {k: os.environ[k] for k in ("PYTHONHASHSEED",)
                     if k in os.environ},
    }


class ExperimentLog:
    """The permanent, queryable record of every run (FR-22, FR-25).

        log = ExperimentLog("runs.db")
        with log.run("momentum", params={"lookback": 20}, seeds={"numpy": 42},
                     dataset_versions=["fundamentals@v3"]) as run:
            run.record(backtest(...))
    """

    def __init__(self, db_path: str | Path = "experiment_log.db",
                 repo: str | Path = ".") -> None:
        self.db_path = str(db_path)
        self.repo = str(repo)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- FR-22 / FR-24: starting a run ------------------------------------
    def start(self, strategy: str, *, params: dict[str, Any],
              seeds: dict[str, int], dataset_versions: Sequence[str],
              factors: Sequence[str] | None = None,
              allow_uncommitted: bool = False) -> str:
        """Open a run record. Returns the run id.

        `dataset_versions` is required and must be non-empty: a run that cannot
        say which data it read cannot be re-executed, whatever else was
        recorded. This is the field that connects FR-22 to FR-06.
        """
        if not dataset_versions:
            raise ValueError(
                "dataset_versions is required (FR-22). A run that cannot name "
                "the data it read is not reproducible even in principle — see "
                "PointInTimeStore.current_version().")
        if not seeds:
            raise ValueError(
                "seeds is required (FR-22). If the run is genuinely "
                "deterministic pass {} explicitly via seeds={'deterministic': 0} "
                "so the claim is on record rather than merely omitted.")

        git = git_state(self.repo)
        if git["dirty"] and not allow_uncommitted:
            detail = ""
            if git.get("untracked_source"):
                detail = (f" Untracked source files: "
                          f"{', '.join(git['untracked_source'][:5])}.")
            raise UncommittedCode(
                "the working tree has uncommitted changes." + detail +
                " FR-24: a result from "
                "unknown code is not a result. Either commit, or pass "
                "allow_uncommitted=True — which records the FULL diff so the "
                "result stays attributable.")
        if git["code_sha"] == "UNKNOWN" and not allow_uncommitted:
            raise UncommittedCode(
                "no git commit could be determined for this working tree, so "
                "the code that produced the result cannot be identified.")

        run_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, strategy, factors_json, params_json, "
                "seeds_json, dataset_versions, code_sha, code_dirty, code_diff, "
                "environment_json, started_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, strategy,
                 json.dumps(list(factors or []), sort_keys=True),
                 json.dumps(params, sort_keys=True),
                 json.dumps(seeds, sort_keys=True),
                 json.dumps(list(dataset_versions), sort_keys=True),
                 git["code_sha"], int(git["dirty"]), git["diff"],
                 json.dumps(environment(), sort_keys=True), _utcnow()))
        return run_id

    def finish(self, run_id: str, *, result: Any, outcome: str = "completed") -> str:
        """Close a run, storing the result and its hash. Returns the hash."""
        digest = canonical_hash(result)
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET ended_at = ?, outcome = ?, result_json = ?, "
                "result_hash = ? WHERE run_id = ?",
                (_utcnow(), outcome,
                 json.dumps(result, sort_keys=True, default=str), digest, run_id))
        return digest

    @contextmanager
    def run(self, strategy: str, **kwargs) -> Iterator["_RunHandle"]:
        """Context manager. A run that raises is recorded as failed, not lost.

        An unrecorded failure is how a search quietly becomes smaller than it
        was — the same argument the trial counter makes.
        """
        run_id = self.start(strategy, **kwargs)
        handle = _RunHandle(self, run_id)
        try:
            yield handle
        except Exception as exc:
            self.finish(run_id, result={"error": f"{type(exc).__name__}: {exc}"},
                        outcome="failed")
            raise

    # ---- FR-23: re-execution ----------------------------------------------
    def replay(self, run_id: str, fn: Callable[..., Any]) -> dict[str, Any]:
        """Re-execute a recorded run and require a bitwise-identical result.

        `fn` receives the recorded parameters as keyword arguments. Seeds are
        restored before it is called, which is the part everyone forgets: a
        recorded seed that is never re-applied documents irreproducibility
        rather than preventing it.
        """
        record = self.get(run_id)
        if record is None:
            raise ValueError(f"unknown run {run_id!r}")
        if record["result_hash"] is None:
            raise ValueError(f"run {run_id!r} never recorded a result to compare against")

        seeds = json.loads(record["seeds_json"])
        self.restore_seeds(seeds)
        result = fn(**json.loads(record["params_json"]))
        digest = canonical_hash(result)

        identical = digest == record["result_hash"]
        with self._connect() as conn:
            conn.execute("UPDATE runs SET replay_verified = ? WHERE run_id = ?",
                         (int(identical), run_id))
        if not identical:
            raise NotReproducible(
                f"run {run_id!r} did not reproduce. Recorded result hash "
                f"{record['result_hash'][:16]}..., replay produced "
                f"{digest[:16]}.... The recorded fields were insufficient to "
                "determine the output — an unrecorded seed, an environment "
                "difference, or uncommitted code are the usual causes, in that "
                "order.")
        return {"run_id": run_id, "reproduced": True, "result_hash": digest,
                "result": result}

    @staticmethod
    def restore_seeds(seeds: dict[str, int]) -> None:
        """Re-apply every recorded seed. Unknown generators are refused rather
        than skipped, because a silently unseeded generator is precisely what
        makes a run irreproducible."""
        for name, value in seeds.items():
            if name == "python":
                random.seed(value)
            elif name == "numpy":
                import numpy as np
                np.random.seed(value)
            elif name == "deterministic":
                continue
            else:
                raise ValueError(
                    f"unknown random source {name!r} in the run record. It was "
                    "seeded at run time but cannot be restored, so this run "
                    "cannot be replayed faithfully.")

    # ---- FR-25: querying ---------------------------------------------------
    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?",
                               (run_id,)).fetchone()
        return dict(row) if row else None

    def query(self, *, strategy: str | None = None, factor: str | None = None,
              since: str | None = None, until: str | None = None,
              outcome: str | None = None) -> list[dict[str, Any]]:
        """FR-25: by strategy, factor, date range, and outcome."""
        sql = "SELECT * FROM runs WHERE 1=1"
        args: list[Any] = []
        if strategy:
            sql += " AND strategy = ?"
            args.append(strategy)
        if factor:
            sql += " AND factors_json LIKE ?"
            args.append(f'%"{factor}"%')
        if since:
            sql += " AND started_at >= ?"
            args.append(since)
        if until:
            sql += " AND started_at <= ?"
            args.append(until)
        if outcome:
            sql += " AND outcome = ?"
            args.append(outcome)
        sql += " ORDER BY started_at"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, args).fetchall()]


class _RunHandle:
    def __init__(self, log: ExperimentLog, run_id: str) -> None:
        self.log = log
        self.run_id = run_id

    def record(self, result: Any, outcome: str = "completed") -> str:
        return self.log.finish(self.run_id, result=result, outcome=outcome)
