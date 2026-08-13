"""Protected holdout — PRD 04 §5.2, FR-10, FR-11, FR-12.

WHAT THIS IS FOR

A holdout only means something if looking at it is *hard*. The usual failure is
not dishonesty, it is drift: the holdout gets peeked at once to sanity-check a
pipeline, then again to compare two variants, and by the tenth look it is
in-sample data that everyone still calls out-of-sample. Nothing about that
sequence feels like cheating at the time, which is exactly why it needs a
mechanism rather than a policy.

So the three requirements interlock:

  FR-10  The holdout period is inaccessible to ordinary backtests.
  FR-11  Access requires a pre-registered hypothesis, recorded BEFORE the run,
         stating strategy, parameters and expected result. Immutable.
  FR-12  Every evaluation is recorded permanently, and repeated evaluations of
         the same strategy family are flagged prominently as exhaustion.

THE ORDER IS THE POINT

Pre-registration has to happen before the result is known, or it records what
you found rather than what you predicted. So `preregister()` demands an expected
result and hashes the whole record, `evaluate()` refuses without a registration,
and a registration can be spent exactly once. Wanting a second look means
writing down a second prediction, under your name, before you take it.

WHAT IT DOES NOT CLAIM

It cannot stop someone reading the parquet files directly. It makes the
supported path honest and the unsupported path deliberate, which is the most a
library can do. What it does guarantee is that anything routed through it leaves
a permanent trace: the count of looks is not something you can quietly reset.

Shares the SQLite file used by `TrialCounter` (NFR-06: one person, no ops).
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS holdout_periods (
    dataset_id  TEXT PRIMARY KEY,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    note        TEXT,
    defined_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preregistrations (
    registration_id TEXT PRIMARY KEY,
    dataset_id      TEXT NOT NULL,
    strategy_family TEXT NOT NULL,
    params_json     TEXT,
    hypothesis      TEXT NOT NULL,
    expected_result TEXT NOT NULL,
    researcher      TEXT,
    registered_at   TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    spent_at        TEXT
);

CREATE TABLE IF NOT EXISTS holdout_evaluations (
    evaluation_id   TEXT PRIMARY KEY,
    registration_id TEXT NOT NULL REFERENCES preregistrations(registration_id),
    dataset_id      TEXT NOT NULL,
    strategy_family TEXT NOT NULL,
    observed_json   TEXT NOT NULL,
    evaluated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_eval_family
    ON holdout_evaluations(dataset_id, strategy_family);

-- A holdout you can redefine after seeing results is not a holdout: you would
-- simply move it off the period that disagreed with you.
CREATE TRIGGER IF NOT EXISTS holdout_period_immutable
BEFORE UPDATE ON holdout_periods
BEGIN
    SELECT RAISE(ABORT, 'the holdout period is immutable once defined; moving it after seeing results would defeat its purpose');
END;

CREATE TRIGGER IF NOT EXISTS holdout_period_no_delete
BEFORE DELETE ON holdout_periods
BEGIN
    SELECT RAISE(ABORT, 'the holdout period cannot be deleted');
END;

-- FR-11: "The registration MUST be immutable." Only spending it may be
-- recorded, and only once.
CREATE TRIGGER IF NOT EXISTS prereg_immutable
BEFORE UPDATE ON preregistrations
BEGIN
    SELECT RAISE(ABORT, 'a pre-registration is immutable; register a new hypothesis instead')
    WHERE NEW.registration_id IS NOT OLD.registration_id
       OR NEW.dataset_id      IS NOT OLD.dataset_id
       OR NEW.strategy_family IS NOT OLD.strategy_family
       OR NEW.params_json     IS NOT OLD.params_json
       OR NEW.hypothesis      IS NOT OLD.hypothesis
       OR NEW.expected_result IS NOT OLD.expected_result
       OR NEW.content_hash    IS NOT OLD.content_hash
       OR NEW.registered_at   IS NOT OLD.registered_at;

    SELECT RAISE(ABORT, 'this pre-registration has already been spent; a second look requires a second registration')
    WHERE OLD.spent_at IS NOT NULL;
END;

CREATE TRIGGER IF NOT EXISTS prereg_no_delete
BEFORE DELETE ON preregistrations
BEGIN
    SELECT RAISE(ABORT, 'pre-registrations are permanent: deleting one would hide a look at the holdout');
END;

-- FR-12: "MUST be recorded permanently."
CREATE TRIGGER IF NOT EXISTS holdout_eval_no_delete
BEFORE DELETE ON holdout_evaluations
BEGIN
    SELECT RAISE(ABORT, 'holdout evaluations are permanent: deleting one would reset the exhaustion count');
END;

CREATE TRIGGER IF NOT EXISTS holdout_eval_no_update
BEFORE UPDATE ON holdout_evaluations
BEGIN
    SELECT RAISE(ABORT, 'holdout evaluations are permanent and cannot be edited');
END;
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class HoldoutViolation(RuntimeError):
    """Raised when an operation would compromise the holdout's protection."""


class ProtectedHoldout:
    """A period of data that ordinary backtests cannot reach.

        holdout = ProtectedHoldout("research.db")
        holdout.define("sp500", start="2023-01-01", end="2024-12-31")

        # ordinary research: refused
        holdout.assert_ordinary_access("sp500", "2020-01-01", "2023-06-30")

        # deliberate access: predict first
        reg = holdout.preregister(
            "sp500", strategy_family="momentum", params={"lookback": 20},
            hypothesis="20-day momentum survives out of sample",
            expected_result="Sharpe between 0.4 and 0.8 annualised",
            researcher="alice")
        verdict = holdout.evaluate(reg, observed={"sharpe": 0.31})
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

    # ---- FR-10: defining and defending the period -------------------------
    def define(self, dataset_id: str, *, start: str, end: str,
               note: str | None = None) -> dict[str, Any]:
        """Declare the protected period. Immutable once set.

        Dates are ISO-8601 strings (YYYY-MM-DD), which compare correctly as
        text — no timezone ambiguity, and no dependency on how the caller's
        datetime objects were constructed.
        """
        if not (start and end) or start >= end:
            raise ValueError(f"holdout needs start < end, got {start!r}..{end!r}")

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT start_date, end_date FROM holdout_periods WHERE dataset_id = ?",
                (dataset_id,)).fetchone()
            if existing:
                if (existing[0], existing[1]) == (start, end):
                    return {"dataset_id": dataset_id, "start": start, "end": end,
                            "already_defined": True}
                raise HoldoutViolation(
                    f"{dataset_id} already has a holdout of {existing[0]}..{existing[1]}. "
                    "It cannot be redefined — a holdout that moves after you have "
                    "seen results is not a holdout.")
            conn.execute(
                "INSERT INTO holdout_periods (dataset_id, start_date, end_date, "
                "note, defined_at) VALUES (?, ?, ?, ?, ?)",
                (dataset_id, start, end, note, _utcnow()))
        return {"dataset_id": dataset_id, "start": start, "end": end,
                "already_defined": False}

    def holdout_period(self, dataset_id: str) -> tuple[str, str] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT start_date, end_date FROM holdout_periods WHERE dataset_id = ?",
                (dataset_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def overlaps_holdout(self, dataset_id: str, start: str, end: str) -> bool:
        period = self.holdout_period(dataset_id)
        if period is None:
            return False
        h_start, h_end = period
        return start <= h_end and end >= h_start

    def assert_ordinary_access(self, dataset_id: str, start: str, end: str) -> None:
        """FR-10. Call this from the ordinary backtest path.

        Raises rather than warns, and rather than silently trimming the range.
        Trimming would be worse than either: the backtest would quietly run on
        less data than it asked for, and its Sharpe would be computed over a
        window nobody chose.
        """
        if self.overlaps_holdout(dataset_id, start, end):
            h_start, h_end = self.holdout_period(dataset_id)  # type: ignore[misc]
            raise HoldoutViolation(
                f"requested range {start}..{end} overlaps the protected holdout "
                f"{h_start}..{h_end} for {dataset_id}. Ordinary backtests cannot "
                "read the holdout. If you intend to spend a look at it, "
                "pre-register a hypothesis with preregister() first.")

    # ---- FR-11: pre-registration ------------------------------------------
    def preregister(self, dataset_id: str, *, strategy_family: str,
                    hypothesis: str, expected_result: str,
                    params: dict[str, Any] | None = None,
                    researcher: str | None = None) -> str:
        """Record a prediction BEFORE looking. Returns a single-use token.

        `expected_result` is required and must be substantive. A registration
        that predicts nothing ("we will see what happens") provides no
        constraint at evaluation time, which is the entire function of writing
        it down beforehand.
        """
        for name, value in (("strategy_family", strategy_family),
                            ("hypothesis", hypothesis),
                            ("expected_result", expected_result)):
            if not value or not str(value).strip():
                raise ValueError(
                    f"{name} is required. Pre-registration exists so the "
                    "prediction is fixed before the result is known; an empty "
                    f"{name} records nothing to be held to.")
        if len(str(expected_result).strip()) < 10:
            raise ValueError(
                "expected_result must state something falsifiable — a prediction "
                "you could be wrong about. Give the expected direction and rough "
                "magnitude, not a placeholder.")

        params_json = json.dumps(params, sort_keys=True) if params else None
        registered_at = _utcnow()
        payload = json.dumps({
            "dataset_id": dataset_id, "strategy_family": strategy_family,
            "params": params_json, "hypothesis": hypothesis,
            "expected_result": expected_result, "researcher": researcher,
            "registered_at": registered_at}, sort_keys=True)
        content_hash = hashlib.sha256(payload.encode()).hexdigest()
        registration_id = str(uuid.uuid4())

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO preregistrations (registration_id, dataset_id, "
                "strategy_family, params_json, hypothesis, expected_result, "
                "researcher, registered_at, content_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (registration_id, dataset_id, strategy_family, params_json,
                 hypothesis, expected_result, researcher, registered_at,
                 content_hash))
        return registration_id

    def registration(self, registration_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM preregistrations WHERE registration_id = ?",
                (registration_id,)).fetchone()
        return dict(row) if row else None

    # ---- FR-12: evaluation and exhaustion ---------------------------------
    def evaluate(self, registration_id: str, *,
                 observed: dict[str, Any]) -> dict[str, Any]:
        """Spend a registration to record one look at the holdout.

        Returns the observed result alongside the exhaustion status, so a caller
        that displays the result cannot avoid also having the warning in hand.
        """
        if not isinstance(observed, dict) or not observed:
            raise ValueError("observed results are required to record an evaluation")

        reg = self.registration(registration_id)
        if reg is None:
            raise HoldoutViolation(
                f"unknown pre-registration {registration_id!r}. The holdout "
                "cannot be evaluated without one — that is FR-11, and it is the "
                "difference between a prediction and a post-hoc description.")
        if reg["spent_at"] is not None:
            raise HoldoutViolation(
                f"pre-registration {registration_id!r} was already spent at "
                f"{reg['spent_at']}. Each registration buys exactly one look; a "
                "second look requires a second prediction, written down first.")

        evaluation_id = str(uuid.uuid4())
        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO holdout_evaluations (evaluation_id, registration_id, "
                "dataset_id, strategy_family, observed_json, evaluated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (evaluation_id, registration_id, reg["dataset_id"],
                 reg["strategy_family"], json.dumps(observed, sort_keys=True), now))
            conn.execute(
                "UPDATE preregistrations SET spent_at = ? WHERE registration_id = ?",
                (now, registration_id))

        status = self.exhaustion(reg["dataset_id"], reg["strategy_family"])
        return {
            "evaluation_id": evaluation_id,
            "registration_id": registration_id,
            "dataset_id": reg["dataset_id"],
            "strategy_family": reg["strategy_family"],
            "hypothesis": reg["hypothesis"],
            "expected_result": reg["expected_result"],
            "observed": observed,
            "evaluated_at": now,
            **status,
        }

    def exhaustion(self, dataset_id: str, strategy_family: str) -> dict[str, Any]:
        """FR-12. How many times this family has been tested against this holdout.

        The warning escalates with the count rather than being a flat boolean,
        because the harm does: a second look is a caveat, a tenth means the
        holdout is in-sample data that is still being described as out-of-sample.
        """
        with self._connect() as conn:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM holdout_evaluations "
                "WHERE dataset_id = ? AND strategy_family = ?",
                (dataset_id, strategy_family)).fetchone()
        n = int(n)
        if n <= 1:
            warning = None
        elif n <= 3:
            warning = (f"HOLDOUT EXHAUSTION: '{strategy_family}' has now been "
                       f"evaluated against this holdout {n} times. The holdout is "
                       "no longer fully out-of-sample for this family; treat the "
                       "result as optimistic.")
        else:
            warning = (f"HOLDOUT EXHAUSTED: '{strategy_family}' has been evaluated "
                       f"{n} times against this holdout. It is in-sample data for "
                       "this family. Reporting these results as out-of-sample "
                       "would be misleading; a fresh holdout is required.")
        return {"evaluations": n, "exhausted": n > 1, "warning": warning}

    def evaluations(self, dataset_id: str | None = None) -> list[dict[str, Any]]:
        """The permanent record of every look ever taken."""
        sql = "SELECT * FROM holdout_evaluations"
        args: tuple = ()
        if dataset_id is not None:
            sql += " WHERE dataset_id = ?"
            args = (dataset_id,)
        sql += " ORDER BY evaluated_at"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, args).fetchall()]
