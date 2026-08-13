"""Global trial counter — PRD 04 §5.2, FR-08 and FR-15.

WHAT THIS IS FOR

`deflated_sharpe_ratio` needs two inputs nothing in this system recorded: the
number of independent trials searched (N) and the variance of the Sharpe
estimates across them (V[{SR_n}]). Without them the deflation is either
uncomputable or, worse, computed from a number someone typed in — and a
multiple-testing correction fed a made-up trial count is not a correction, it is
a decoration.

THE DESIGN CONSTRAINT THAT SHAPES EVERYTHING

FR-08: "a global count of every backtest executed against each dataset, across
all researchers and all time, **including runs whose results were discarded**."

That last clause is the whole design. A counter you can avoid by not liking the
answer counts nothing. So:

  - A trial is recorded when it STARTS, before its result exists. You cannot
    look at a Sharpe ratio and then decide whether it counted.
  - There is no delete, no decrement, and no "mark as invalid". The schema
    enforces this with triggers, so it holds against direct SQL as well as
    against this API.
  - The count is per DATASET and global across searches and researchers, not
    per experiment. A per-experiment count is, in the PRD's words, meaningless.

FR-15 follows from the same store: a strategy extracted from a 5,000-trial
search inherits the burden, because the burden is a property of the dataset's
history rather than of the result you chose to keep.

WHAT IT DELIBERATELY DOES NOT DO

It does not judge. It records trials and reports counts and variances; deciding
whether a deflated Sharpe is good enough belongs to the caller. The one opinion
it holds is that the count must be honest, and it enforces that structurally
rather than by asking.

Storage is a single SQLite file (NFR-06: runnable by one person, no dedicated
ops). WAL mode so concurrent researchers do not block each other.
"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    trial_id      TEXT PRIMARY KEY,
    dataset_id    TEXT NOT NULL,
    dataset_version TEXT,
    search_id     TEXT,
    researcher    TEXT,
    strategy      TEXT,
    params_json   TEXT,
    started_at    TEXT NOT NULL,
    -- Outcome fields are nullable ON PURPOSE. A trial that never reports a
    -- result still counts; that is the point of FR-08.
    sharpe        REAL,
    n_observations INTEGER,
    outcome_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_trials_dataset ON trials(dataset_id);
CREATE INDEX IF NOT EXISTS idx_trials_search  ON trials(search_id);

-- Append-only, enforced by the database rather than by convention.
-- A researcher who can delete rows can manufacture any deflated Sharpe they
-- like, so "please don't" is not an adequate control.
CREATE TRIGGER IF NOT EXISTS trials_no_delete
BEFORE DELETE ON trials
BEGIN
    SELECT RAISE(ABORT, 'trials are append-only: deleting a trial would understate the multiple-testing burden, which is the failure FR-08 exists to prevent');
END;

-- Updates are allowed only to fill in a result that was previously absent.
-- Rewriting a recorded Sharpe, or re-parenting a trial to a different dataset,
-- is rejected.
CREATE TRIGGER IF NOT EXISTS trials_outcome_write_once
BEFORE UPDATE ON trials
BEGIN
    SELECT RAISE(ABORT, 'trial identity is immutable')
    WHERE NEW.trial_id   IS NOT OLD.trial_id
       OR NEW.dataset_id IS NOT OLD.dataset_id
       OR NEW.search_id  IS NOT OLD.search_id
       OR NEW.started_at IS NOT OLD.started_at;

    SELECT RAISE(ABORT, 'a recorded outcome cannot be rewritten; record a new trial instead')
    WHERE OLD.sharpe IS NOT NULL AND NEW.sharpe IS NOT OLD.sharpe;
END;
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrialCounterError(RuntimeError):
    """Raised when an operation would compromise the count's honesty."""


class TrialCounter:
    """Append-only record of every backtest run against every dataset.

    Usage follows the order the integrity argument requires — register first,
    then run, then (optionally) report:

        counter = TrialCounter("research.db")
        trial = counter.start_trial("sp500-2010-2020", strategy="mean_reversion",
                                    params={"lookback": 20})
        sharpe = run_backtest(...)
        counter.record_outcome(trial, sharpe=sharpe, n_observations=2517)

        counter.deflation_inputs("sp500-2010-2020")
        # -> {"n_trials": 431, "var_trials": 0.0043, ...}
    """

    def __init__(self, db_path: str | Path = "research_integrity.db") -> None:
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- recording --------------------------------------------------------
    def start_trial(self, dataset_id: str, *, strategy: str | None = None,
                    params: dict[str, Any] | None = None,
                    search_id: str | None = None,
                    researcher: str | None = None,
                    dataset_version: str | None = None) -> str:
        """Register a trial BEFORE its result is known. Returns the trial id.

        Call this before running the backtest, not after. Recording afterwards
        reintroduces exactly the bias the counter exists to remove: the trials
        that get counted become the ones the researcher liked.
        """
        if not dataset_id or not str(dataset_id).strip():
            raise ValueError(
                "dataset_id is required: the count is per dataset, and an "
                "unattributed trial cannot contribute to any dataset's burden")

        trial_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO trials (trial_id, dataset_id, dataset_version, "
                "search_id, researcher, strategy, params_json, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (trial_id, dataset_id, dataset_version, search_id, researcher,
                 strategy, json.dumps(params, sort_keys=True) if params else None,
                 _utcnow()))
        return trial_id

    def record_outcome(self, trial_id: str, *, sharpe: float,
                       n_observations: int | None = None) -> None:
        """Attach a result to a trial that has already been counted.

        Optional by design. A trial with no outcome still counts toward the
        burden — it only drops out of the variance estimate, which needs a
        Sharpe to be meaningful.
        """
        if not isinstance(sharpe, (int, float)) or isinstance(sharpe, bool):
            raise TypeError(f"sharpe must be numeric, got {type(sharpe).__name__}")
        if not math.isfinite(sharpe):
            raise ValueError("sharpe must be finite")

        with self._connect() as conn:
            cur = conn.execute("SELECT sharpe FROM trials WHERE trial_id = ?",
                               (trial_id,))
            row = cur.fetchone()
            if row is None:
                raise TrialCounterError(
                    f"unknown trial {trial_id!r}. Call start_trial() before "
                    "running the backtest, so the trial is counted whatever the "
                    "result turns out to be.")
            if row[0] is not None:
                raise TrialCounterError(
                    f"trial {trial_id!r} already has an outcome. Record a new "
                    "trial rather than revising one — a re-run is another draw "
                    "from the same search and carries its own burden.")
            conn.execute(
                "UPDATE trials SET sharpe = ?, n_observations = ?, outcome_at = ? "
                "WHERE trial_id = ?",
                (float(sharpe), n_observations, _utcnow(), trial_id))

    def start_trials(self, dataset_id: str, param_sets: list[dict[str, Any]], *,
                     strategy: str | None = None, search_id: str | None = None,
                     researcher: str | None = None,
                     dataset_version: str | None = None) -> list[str]:
        """Register an entire sweep up front, in one transaction.

        For a parameter search this is not merely faster, it is *stricter*: the
        full trial count is committed before a single result exists, so the
        search cannot be quietly truncated at the point it starts looking good.
        You declare how hard you are about to look, then look.
        """
        if not dataset_id or not str(dataset_id).strip():
            raise ValueError("dataset_id is required")
        if not param_sets:
            raise ValueError("a search with no parameter sets is not a search")

        now = _utcnow()
        rows = []
        ids = []
        for params in param_sets:
            trial_id = str(uuid.uuid4())
            ids.append(trial_id)
            rows.append((trial_id, dataset_id, dataset_version, search_id,
                         researcher, strategy,
                         json.dumps(params, sort_keys=True) if params else None,
                         now))
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO trials (trial_id, dataset_id, dataset_version, "
                "search_id, researcher, strategy, params_json, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        return ids

    def record_outcomes(self, outcomes: dict[str, float], *,
                        n_observations: int | None = None) -> None:
        """Attach results to many already-counted trials, in one transaction.

        Trials absent from `outcomes` keep their NULL sharpe and still count —
        a sweep whose members failed to evaluate has still consumed those looks.
        """
        now = _utcnow()
        rows = [(float(v), n_observations, now, k) for k, v in outcomes.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v)]
        with self._connect() as conn:
            conn.executemany(
                "UPDATE trials SET sharpe = ?, n_observations = ?, outcome_at = ? "
                "WHERE trial_id = ? AND sharpe IS NULL", rows)

    @contextmanager
    def trial(self, dataset_id: str, **kwargs) -> Iterator["_TrialHandle"]:
        """Context manager that counts the trial even if the body raises.

        A backtest that crashes, or one the researcher interrupts on seeing an
        early number, has still consumed a look at the data.
        """
        trial_id = self.start_trial(dataset_id, **kwargs)
        handle = _TrialHandle(self, trial_id)
        yield handle

    # ---- reporting --------------------------------------------------------
    def trial_count(self, dataset_id: str) -> int:
        """FR-08: every trial ever run against this dataset, by anyone."""
        with self._connect() as conn:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM trials WHERE dataset_id = ?",
                (dataset_id,)).fetchone()
        return int(n)

    def search_trial_count(self, search_id: str) -> int:
        """FR-15: the burden a search imposes on every result drawn from it."""
        with self._connect() as conn:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM trials WHERE search_id = ?",
                (search_id,)).fetchone()
        return int(n)

    def sharpe_variance(self, dataset_id: str) -> float | None:
        """V[{SR_n}] — the variance of Sharpe estimates across trials.

        The second input the deflated Sharpe needs, and the one most likely to
        be guessed if it is not recorded. Returns None when fewer than two
        trials have reported an outcome, because a variance over one point is
        not a variance; the caller must then supply an estimate explicitly
        rather than receive a fabricated zero.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT sharpe FROM trials WHERE dataset_id = ? AND sharpe IS NOT NULL",
                (dataset_id,)).fetchall()
        values = [r[0] for r in rows]
        if len(values) < 2:
            return None
        mean = sum(values) / len(values)
        # Sample variance (n-1): these trials are a sample of the search space
        # that could have been run, not the entire population of it.
        return sum((v - mean) ** 2 for v in values) / (len(values) - 1)

    def deflation_inputs(self, dataset_id: str) -> dict[str, Any]:
        """Exactly what `deflated_sharpe_ratio` needs, from recorded history.

        Returned with the counts it was derived from, so a reviewer can see
        whether the variance rests on 3 trials or 3,000.
        """
        with self._connect() as conn:
            (n_total, n_outcome) = conn.execute(
                "SELECT COUNT(*), COUNT(sharpe) FROM trials WHERE dataset_id = ?",
                (dataset_id,)).fetchone()
        return {
            "dataset_id": dataset_id,
            "n_trials": int(n_total),
            "var_trials": self.sharpe_variance(dataset_id),
            "trials_with_outcome": int(n_outcome),
            "trials_without_outcome": int(n_total) - int(n_outcome),
        }

    def trials(self, dataset_id: str | None = None) -> list[dict[str, Any]]:
        """The full record. Auditability is the point of keeping it."""
        sql = ("SELECT trial_id, dataset_id, dataset_version, search_id, "
               "researcher, strategy, params_json, started_at, sharpe, "
               "n_observations, outcome_at FROM trials")
        args: tuple = ()
        if dataset_id is not None:
            sql += " WHERE dataset_id = ?"
            args = (dataset_id,)
        sql += " ORDER BY started_at"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def datasets(self) -> list[str]:
        with self._connect() as conn:
            return [r[0] for r in conn.execute(
                "SELECT DISTINCT dataset_id FROM trials ORDER BY dataset_id")]


class _TrialHandle:
    """Handle yielded by `TrialCounter.trial`, for reporting the outcome."""

    def __init__(self, counter: TrialCounter, trial_id: str) -> None:
        self.counter = counter
        self.trial_id = trial_id

    def record(self, sharpe: float, n_observations: int | None = None) -> None:
        self.counter.record_outcome(self.trial_id, sharpe=sharpe,
                                    n_observations=n_observations)
