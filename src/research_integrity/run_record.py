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

NOT MLFLOW, DELIBERATELY (ratified 2026-08-28)

PRD 04 names MLflow for the experiment log. This is SQLite instead, and the
reason is FR-23 rather than preference: MLflow logs, and never checks whether a
run reproduces. `replay()` below restores the seeds, re-executes, and compares a
canonical hash against the one stored at the time, so a fully-populated record
still fails when an unrecorded seed was consumed. Adopting MLflow would satisfy
the letter of "use MLflow" by weakening the requirement it was named to serve.

If the team wants MLflow's UI and artifact storage, the shape is an EXPORT from
these tables — not moving the system of record into a store that cannot enforce
FR-23. See .spark-flow/memory/decisions.md.

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

UNTRACKED SOURCE WAS DETECTED AND THEN DISCARDED (fixed 2026-08-30)

The paragraph above was false in the case it was written for. `git_state` went
to some trouble to notice that an untracked .py is unknown code — it can be
imported, so it is — and then recorded the run with `git diff HEAD`, which by
construction cannot contain a file git has never been told about. That stored
code_dirty=1 with code_diff='': the module recorded that the code was unknown
and threw away the evidence of what it was, which is the one thing FR-24 asks
for. Two smaller versions of the same mistake sat next to it. The diff was
`.strip()`ed, and a patch missing its final newline is one `git apply` rejects
as corrupt; and a .py holding bytes git reads as binary diffed to "Binary files
differ", which reconstructs nothing.

The diff is now built against a COPY of the index in a temporary directory,
with GIT_INDEX_FILE pointing at the copy and the untracked source files
intent-to-added (`git add -N`) there, so git emits them as ordinary new-file
sections of one unified diff. The user's index, working tree and HEAD are never
written: staging into the real index would mean recording a backtest edits the
repository being measured, and an interrupted run would leave it edited.
`--binary` makes the patch reconstruct bytes git will not diff as text, and the
diff is stored verbatim. Each captured path is then checked against `git diff
--name-only`, and any untracked source file missing from the diff REFUSES the
run — FR-24's reject branch, because recording that unknown code ran without
recording what it was is the state this note exists to describe.

WHAT A RECORDED SEED CAN GUARANTEE (revised 2026-08-30)

`restore_seeds` used to accept seeds={"numpy": N} and call np.random.seed(N).
That seeds numpy's LEGACY global RandomState and has no effect at all on
np.random.default_rng(N), the generator every randomised module here actually
constructs (factors.py, search.py, portfolio/simulator.py). A run recording a
numpy seed therefore replayed with its randomness unrestored while the record
said it had been restored, which is worse than recording nothing: it is a claim.

A Generator's seed is an ARGUMENT, not process state, so nothing this module
does at replay time can install it. It belongs in `params`, where replay()
re-supplies it to the function and it is genuinely restored. So `"numpy"` is
refused rather than accepted and ignored, and the legacy global keeps a name
that says which generator it restores: `"numpy_legacy"`. Refusing follows the
FR-07 precedent — a warning is read once and then filtered out of the logs.

The cost is on record too: a run already logged with seeds={"numpy": N} is now
refused by replay() instead of replaying with its randomness unrestored, and
records are immutable, so those runs cannot be replayed at all. That was already
their condition — the change is that it is said instead of reported as success.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
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
    code_untracked    TEXT,
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


def _seed_python(value: int) -> None:
    random.seed(value)


def _seed_numpy_legacy(value: int) -> None:
    import numpy as np
    np.random.seed(value)


_SEED_RESTORERS: dict[str, Callable[[int], None]] = {
    "python": _seed_python,
    # np.random.seed() sets numpy's LEGACY global RandomState — np.random.normal
    # and its siblings. The name says so, because it cannot reach a Generator.
    "numpy_legacy": _seed_numpy_legacy,
    # A stated claim that nothing random was consumed. There is nothing to put
    # back; recording the claim is the point.
    "deterministic": lambda value: None,
}

_GENERATOR_SEED_REFUSAL = (
    "np.random.default_rng(seed) takes its seed as an ARGUMENT and never reads "
    "process-wide state, so no call restore_seeds() can make will install it. "
    "Put it in params — replay() passes params back to the function, which is "
    "how a Generator's seed is actually restored — and state what is left with "
    "seeds={'deterministic': 0}.")

_NUMPY_SEED_REFUSAL = (
    "'numpy' does not name one generator. np.random.seed() restores the legacy "
    "global RandomState and nothing else; every randomised module here uses "
    "np.random.default_rng(seed), which it cannot touch. Use 'numpy_legacy' if "
    "the run really consumed np.random.* global state. " + _GENERATOR_SEED_REFUSAL)

# Seed names that read as a promise this module cannot keep. Refused rather than
# accepted and quietly ignored, because a record naming a seed nobody re-applies
# is a claim of reproducibility — and FR-07's precedent is that a warning is read
# once and then filtered out of the logs.
_UNRESTORABLE_SEEDS: dict[str, str] = {
    "numpy": _NUMPY_SEED_REFUSAL,
    "np": _NUMPY_SEED_REFUSAL,
    "numpy_default_rng": _GENERATOR_SEED_REFUSAL,
    "default_rng": _GENERATOR_SEED_REFUSAL,
    "numpy_generator": _GENERATOR_SEED_REFUSAL,
}


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


def _git(repo: str | Path, *args: str,
         env: dict[str, str] | None = None) -> str | None:
    """Run a git command, returning its stdout, or None if git could not run.

    The output is NOT stripped. A diff without its final newline is a patch
    `git apply` rejects as corrupt, which made the stored diff unusable for the
    reconstruction it exists for. `surrogateescape` keeps a path that is not
    valid UTF-8 round-trippable back into a git argument, so such a file is
    still detected instead of taking the whole listing down with it.

    NONE MEANS "GIT DID NOT ANSWER" (2026-08-30)

    None is returned for a nonzero exit as well as for the two exceptions
    caught below, so it means only that this command produced no trustworthy
    answer — never that the answer was "nothing".

    Narrowing the except clause was half the fix and on its own would have been
    a decoration. The danger was never where the None came from but what the
    caller did with it: `git_state` used to read a None from `status` or
    `ls-files` as "nothing is modified" and record `code_dirty=0` beside a real
    commit SHA. A corrupt `.git/index` is enough to produce it — `status` exits
    128 while `rev-parse HEAD` still succeeds — so no exception was needed and
    narrowing this clause would not have touched the likelier route. That is
    the unknown code FR-24 exists to refuse, arriving through the control meant
    to catch it, and it is closed in `git_state` (`state_unknown`) rather than
    here.
    """
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], env=env,
                             capture_output=True, text=True, timeout=30,
                             errors="surrogateescape")
        return out.stdout if out.returncode == 0 else None
    # Swallowed deliberately, and only these: OSError is git absent from the
    # box or unrunnable, SubprocessError is the 30s timeout. Those are facts
    # about the environment and degrading to None is the right answer. A
    # MemoryError buffering `diff --binary` on a large tree, or a TypeError
    # from a mis-built argument list, is not — it must reach the caller rather
    # than be written down as cleanliness.
    except (OSError, subprocess.SubprocessError):
        return None


#: Prefix marking a diff that had to be base64-encoded to survive storage.
#: On its own line at the head of the payload, so a reader that does not know
#: about it sees the reason rather than a wall of base64.
NON_UTF8_DIFF_MARKER = "# non-utf-8 diff, base64 of the original bytes:\n"


def encode_diff(diff: str | None) -> str | None:
    """A diff as SQLite can store it, losslessly.

    `_git` decodes with `surrogateescape`, so a source file that is text to git
    but not valid UTF-8 — a latin-1 comment, say — arrives carrying lone
    surrogates. sqlite3 cannot encode those, and `start()` died with
    `UnicodeEncodeError` on any tree containing one. That is worse than the
    defect this recording was added to fix: before it, an untracked file gave an
    empty diff; after it, the run could not be recorded at all.

    Truncating or replacing the offending bytes is not available here. FR-24
    wants the full diff because reconstructing the code is the entire purpose,
    and a diff with a byte swapped for U+FFFD does not apply.

    So the common case is stored unchanged and stays readable, and only a diff
    that genuinely cannot round-trip is base64-encoded behind a marker naming
    what happened. `decode_diff` is the inverse.
    """
    if not diff:
        return diff
    try:
        diff.encode("utf-8")
        return diff
    except UnicodeEncodeError:
        raw = diff.encode("utf-8", "surrogateescape")
        return NON_UTF8_DIFF_MARKER + base64.b64encode(raw).decode("ascii")


def decode_diff(stored: str | None) -> bytes:
    """The bytes `git apply` needs, from whatever `encode_diff` stored."""
    if not stored:
        return b""
    if stored.startswith(NON_UTF8_DIFF_MARKER):
        return base64.b64decode(stored[len(NON_UTF8_DIFF_MARKER):])
    return stored.encode("utf-8", "surrogateescape")


def _full_diff(repo: str, untracked_source: Sequence[str]) -> tuple[str, list[str]]:
    """The full diff — untracked source included — and what it failed to hold.

    The full diff, not a summary. A truncated diff cannot reconstruct the code,
    and reconstructing it is the entire purpose.

    `git diff HEAD` cannot contain an untracked file, because git has no entry
    for one. So the files are intent-to-added (`git add -N`) into a COPY of the
    index inside a temporary directory, addressed by GIT_INDEX_FILE. Staging
    them in the real index would make recording a run edit the repository the
    run is measuring, and a run that died in between would leave it edited; the
    copy is deleted with the temporary directory, and the working tree, HEAD and
    the real index are untouched. Starting from a copy rather than an empty
    index keeps anything already staged in the diff.

    Returns (diff, unrecorded) where `unrecorded` names untracked source files
    whose content did not make it in — checked against git's own file list
    rather than assumed from an exit status. A non-empty list refuses the run.
    """
    plain = _git(repo, "diff", "HEAD", "--binary")
    if not untracked_source:
        return (plain or ""), []

    with tempfile.TemporaryDirectory(prefix="run_record_index_") as tmp:
        index = os.path.join(tmp, "index")
        named = (_git(repo, "rev-parse", "--git-path", "index") or "").strip()
        real_index = Path(repo, named) if named else None
        if real_index is not None and real_index.is_file():
            try:
                shutil.copyfile(real_index, index)
            except OSError:
                return (plain or ""), list(untracked_source)

        env = {**os.environ, "GIT_INDEX_FILE": index}
        if _git(repo, "add", "-N", "--", *untracked_source, env=env) is None:
            return (plain or ""), list(untracked_source)
        # --binary: a .py git reads as binary otherwise diffs to "Binary files
        # differ", which names the file and reconstructs nothing.
        diff = _git(repo, "diff", "HEAD", "--binary", env=env)
        names = _git(repo, "diff", "HEAD", "--name-only", "-z", env=env)

    if diff is None or names is None:
        return (plain or ""), list(untracked_source)
    in_diff = {n for n in names.split("\0") if n}
    return diff, [f for f in untracked_source if f not in in_diff]


def git_state(repo: str | Path = ".") -> dict[str, Any]:
    """Commit SHA, dirty flag, and the full diff if dirty (FR-22, FR-24)."""
    # Resolve the top level once: `ls-files` reports paths relative to the
    # directory git was run in while `diff` reports them from the root, and the
    # two lists are compared below.
    top = (_git(repo, "rev-parse", "--show-toplevel") or "").strip() or str(repo)
    sha = (_git(top, "rev-parse", "HEAD") or "").strip()

    # Dirtiness means UNCOMMITTED CODE, not "any file the repo has not seen".
    # Writing the experiment log or a result file inside the repo would
    # otherwise mark every subsequent run as unknown-code and reject it — which
    # is how a well-intentioned control gets switched off wholesale.
    #
    # So: modifications to tracked files always count, and untracked files count
    # only when they are source. An untracked .py can be imported and is
    # genuinely unknown code; an untracked .db is an artifact.
    tracked = _git(top, "status", "--porcelain", "--untracked-files=no")
    # -z, because git's default output QUOTES a path outside ASCII
    # ("caf\303\251.py"). That form ends in a quote rather than .py, so such a
    # file was neither counted as source nor passed back to git intelligibly.
    untracked_raw = _git(top, "ls-files", "--others", "--exclude-standard", "-z")

    # NEITHER PROBE MAY DEGRADE TO "CLEAN".
    #
    # `_git` returns None when git could not answer — a nonzero exit, a timeout,
    # a box where it will not run. A corrupt .git/index is enough: `status`
    # exits 128 while `rev-parse HEAD` still succeeds, so the old
    # `_git(...) or ""` recorded a genuinely modified tree as code_dirty=0
    # beside a real commit SHA, and accepted the run with the default
    # allow_uncommitted=False. The control reported the strongest thing it can
    # say about a tree — this is exactly the committed code — on no evidence.
    #
    # Unknown is not clean. FR-24: "A result from unknown code is not a result."
    #
    # Scoped to a tree that IS a repository: no repo at all makes every probe
    # fail, and that case is already refused one level up by code_sha ==
    # "UNKNOWN". Conflating the two would refuse the supported "no repo, pass
    # allow_uncommitted" path — the control firing on a case it was not built
    # for, which is how a control gets switched off.
    unknown = bool(sha) and (tracked is None or untracked_raw is None)

    untracked = (untracked_raw or "").split("\0")
    SOURCE_SUFFIXES = (".py", ".pyx", ".sql", ".toml", ".cfg", ".yaml", ".yml")
    untracked_source = [f for f in untracked if f.endswith(SOURCE_SUFFIXES)]
    dirty = bool((tracked or "").strip()) or bool(untracked_source)

    diff, unrecorded = _full_diff(top, untracked_source) if dirty else (None, [])
    return {
        "code_sha": sha or "UNKNOWN",
        "dirty": dirty,
        # True when git could not report the working tree at all. Distinct from
        # `dirty`, which is a claim; this is the absence of one.
        "state_unknown": unknown,
        "diff": diff,
        "untracked_source": untracked_source,
        # Which untracked source the diff actually holds, and which it does not.
        # The second list is the difference between recording unknown code and
        # merely noting that some ran.
        "untracked_recorded": [f for f in untracked_source if f not in unrecorded],
        "untracked_unrecorded": unrecorded,
    }


def environment() -> dict[str, Any]:
    """Enough of the environment to explain a difference between two runs."""
    try:
        from importlib.metadata import distributions
        packages = sorted(f"{d.metadata['Name']}=={d.version}"
                          for d in distributions()
                          if d.metadata.get("Name"))
    # Swallowed deliberately, and this one stays broad: enumerating
    # site-packages reads metadata this project did not write, and one
    # distribution with an unreadable METADATA raises anything from KeyError to
    # UnicodeDecodeError. The package list is context for explaining a
    # difference between two runs; the reproducibility contract is the SHA, the
    # diff, the seeds and the dataset versions. Losing the context must not
    # cost the record.
    except Exception:
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
        with log.run("momentum", params={"lookback": 20, "seed": 7},
                     seeds={"python": 42},
                     dataset_versions=["fundamentals@v3"]) as run:
            run.record(backtest(...))

    A np.random.default_rng seed goes in `params` (the "seed" above), not in
    `seeds`: replay() re-supplies params, which is the only way a Generator's
    seed is ever put back. See restore_seeds().
    """

    def __init__(self, db_path: str | Path = "experiment_log.db",
                 repo: str | Path = ".") -> None:
        self.db_path = str(db_path)
        self.repo = str(repo)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add columns a log written by an earlier version does not have.

        CREATE TABLE IF NOT EXISTS leaves an existing table at its old shape, so
        without this every INSERT into an older log would fail — and the records
        already in it cannot be rewritten by design, only read.
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
        if "code_untracked" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN code_untracked TEXT")

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
        self.check_seeds(seeds)

        git = git_state(self.repo)
        if git.get("untracked_unrecorded"):
            raise UncommittedCode(
                "untracked source files are present and their contents could "
                "not be captured into the diff: "
                f"{', '.join(git['untracked_unrecorded'][:5])}. FR-24 allows "
                "uncommitted code only when it is recorded as a full diff, and "
                "allow_uncommitted buys that diff rather than an exemption from "
                "it. A run stored as dirty with the evidence missing is the "
                "unknown code the requirement refuses. Commit them, or move "
                "them out of the tree.")
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
        # An unreadable working tree is refused even with allow_uncommitted,
        # because that flag trades a refusal for a RECORDED DIFF, and there is
        # no diff to record: git could not say what changed. Accepting here
        # would write code_dirty=0 beside a real SHA — the strongest claim this
        # module makes, on no evidence.
        if git.get("state_unknown"):
            raise UncommittedCode(
                "git could not report the state of this working tree, so "
                "whether the code is committed is unknown. FR-24: a result "
                "from unknown code is not a result. This is not the same as a "
                "clean tree and is not overridable by allow_uncommitted — fix "
                "the repository (a corrupt .git/index will do it) and re-run.")

        run_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, strategy, factors_json, params_json, "
                "seeds_json, dataset_versions, code_sha, code_dirty, code_diff, "
                "code_untracked, environment_json, started_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, strategy,
                 json.dumps(list(factors or []), sort_keys=True),
                 json.dumps(params, sort_keys=True),
                 json.dumps(seeds, sort_keys=True),
                 json.dumps(list(dataset_versions), sort_keys=True),
                 git["code_sha"], int(git["dirty"]), encode_diff(git["diff"]),
                 # Which files were unknown code is a fact about the run: a
                 # new-file section in a diff does not say whether git had ever
                 # seen the file.
                 json.dumps(git.get("untracked_recorded"))
                 if git.get("untracked_recorded") else None,
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
        # Broad because the outcome is being RECORDED, not diagnosed: FR-25
        # asks the log to be queryable by outcome, and a failure the log never
        # saw is a run it still has as running. Nothing is hidden — the record
        # is a side effect and the exception is re-raised unchanged. Note the
        # boundary is Exception, not BaseException: a Ctrl-C is an interrupted
        # run rather than a failed one, and it leaves `outcome` NULL instead of
        # answering an FR-25 query with the wrong word.
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
    def check_seeds(seeds: dict[str, int]) -> None:
        """Refuse a seed source that cannot actually be restored (FR-23).

        Applied when the run STARTS as well as when it is replayed. Run records
        are permanent, so a record naming a seed nobody can re-apply is a false
        claim that cannot be corrected afterwards, and the person who would
        discover it is the one trying to reproduce the result — which is the
        reader the record exists for.
        """
        for name in seeds:
            if name in _UNRESTORABLE_SEEDS:
                raise ValueError(
                    f"seed source {name!r} cannot be restored, so recording it "
                    "would document reproducibility instead of providing it. "
                    + _UNRESTORABLE_SEEDS[name])
            if name not in _SEED_RESTORERS:
                raise ValueError(
                    f"unknown random source {name!r} in the run record. It was "
                    "seeded at run time but cannot be restored, so this run "
                    "cannot be replayed faithfully.")

    @staticmethod
    def restore_seeds(seeds: dict[str, int]) -> None:
        """Re-apply every recorded seed. Unknown generators are refused rather
        than skipped, because a silently unseeded generator is precisely what
        makes a run irreproducible.

        What this can and cannot guarantee: it restores PROCESS-WIDE generator
        state — `random`, and numpy's legacy global RandomState under the name
        `numpy_legacy`. It cannot reach a np.random.default_rng(seed), whose
        seed is an argument rather than state; that one is restored by being
        re-supplied out of `params`. Randomness that arrives through neither
        route is not restored here, and replay() is what catches it.
        """
        ExperimentLog.check_seeds(seeds)
        for name, value in seeds.items():
            _SEED_RESTORERS[name](value)

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
