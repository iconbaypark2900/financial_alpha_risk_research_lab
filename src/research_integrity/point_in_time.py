"""Point-in-time data store — PRD 04 §5.1, FR-01, FR-02, FR-06, FR-07.

    FR-01  All research data MUST be point-in-time: the store MUST answer
           "what was known as of date D" for every field.
    FR-02  Fundamentals MUST be stored as-first-reported with restatements as
           separate versioned records. Research defaults to as-reported. Any run
           that reads restated values MUST be blocked or explicitly flagged as
           look-ahead-contaminated.
    FR-06  Every dataset MUST be immutably versioned; a backtest MUST record the
           exact version it used.
    FR-07  The system MUST REFUSE to run a backtest against a dataset that
           cannot supply point-in-time semantics, rather than warning.

A NOTE ON THE PRD'S DESIGN CLAIM, BECAUSE IT IS PARTLY WRONG

§6 argues that Iceberg's snapshot isolation and time travel "*are* point-in-time
semantics — FR-01 and FR-06 become native table features rather than application
logic that must be gotten right", and calls this the strongest tool-to-
requirement fit in the project.

For FR-06 that is exactly right: immutable, addressable versions are precisely
what a table format gives you, and re-implementing them would be foolish.

For FR-01 it does not hold, and the distinction matters enough to state plainly.
Table time travel answers "what did this TABLE look like at snapshot N" — the
*ingestion* timeline. Point-in-time research needs "what was KNOWN about period
P as of date D" — two independent time axes:

  effective_date  the period the fact describes   (Q3 2023 earnings)
  knowledge_date  when we learned it              (reported 2023-11-15,
                                                   restated 2024-02-20)

Ingestion time equals knowledge time only if you never backfill, never load
history, and never correct a load — that is, only if the store has never been
operated normally. And FR-02 requires restatements be kept as separate records
with the original still readable, which is a data-model property no snapshot
mechanism supplies.

So this module keeps both axes explicitly. Iceberg would sit UNDER it as the
storage and versioning layer, not replace it. DuckDB is the query engine the PRD
names, used here directly over the fact table.

WHAT IS NOT BUILT

FR-03 (delisted securities), FR-04 (index membership with effective dates) and
FR-05 (corporate actions) are data-CONTENT requirements: the schema below
carries them as ordinary facts with effective dates, but populating them needs
vendor data that is not present. They are not implemented, and saying the store
is "survivorship-free" because it *could* hold delisted names would be a claim
about data nobody has loaded.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id       VARCHAR PRIMARY KEY,
    description      VARCHAR,
    point_in_time    BOOLEAN NOT NULL,
    pit_note         VARCHAR,
    created_at       TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_versions (
    version_id     VARCHAR PRIMARY KEY,
    dataset_id     VARCHAR NOT NULL,
    version_number INTEGER NOT NULL,
    content_hash   VARCHAR NOT NULL,
    row_count      BIGINT NOT NULL,
    knowledge_date DATE NOT NULL,
    created_at     TIMESTAMP NOT NULL,
    note           VARCHAR
);

CREATE TABLE IF NOT EXISTS facts (
    fact_id        VARCHAR PRIMARY KEY,
    dataset_id     VARCHAR NOT NULL,
    version_id     VARCHAR NOT NULL,
    entity_id      VARCHAR NOT NULL,
    field          VARCHAR NOT NULL,
    value          DOUBLE,
    -- The two time axes. Keeping them separate is the whole point.
    effective_date DATE NOT NULL,   -- the period the fact describes
    knowledge_date DATE NOT NULL,   -- when we learned it
    is_restatement BOOLEAN NOT NULL,
    source         VARCHAR
);
"""


class PointInTimeError(RuntimeError):
    """Raised when a query would return information that was not yet known."""


class LookAheadContamination(PointInTimeError):
    """Raised when a run reads restated values without acknowledging it."""


class PointInTimeStore:
    """Bitemporal fact store with immutable dataset versions.

        store = PointInTimeStore("research.duckdb")
        store.register_dataset("fundamentals", point_in_time=True)

        version = store.append_facts("fundamentals", [
            {"entity_id": "AAPL", "field": "eps", "value": 1.29,
             "effective_date": "2023-09-30", "knowledge_date": "2023-11-02"},
        ])

        store.as_of("fundamentals", "2023-12-01")   # sees the 1.29
        store.as_of("fundamentals", "2023-10-01")   # sees nothing: not yet known
    """

    def __init__(self, db_path: str | Path = "research_data.duckdb") -> None:
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.execute(SCHEMA)

    def _connect(self):
        return duckdb.connect(self.db_path)

    # ---- FR-06/FR-07: datasets and their guarantees -----------------------
    def register_dataset(self, dataset_id: str, *, point_in_time: bool,
                         description: str | None = None,
                         pit_note: str | None = None) -> None:
        """Declare a dataset and whether it can answer as-of queries.

        `point_in_time` is required rather than defaulted, because a default of
        True would let an unexamined dataset claim a guarantee nobody checked,
        and a default of False would be silently ignored.
        """
        if not point_in_time and not pit_note:
            raise ValueError(
                "a dataset declared NOT point-in-time must carry a pit_note "
                "explaining what is missing — otherwise the limitation is "
                "invisible at the point where someone is refused")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO datasets VALUES (?, ?, ?, ?, current_timestamp) "
                "ON CONFLICT DO NOTHING",
                [dataset_id, description, point_in_time, pit_note])

    def require_point_in_time(self, dataset_id: str) -> None:
        """FR-07. Refuse, do not warn.

        A warning is read once and then filtered out of the logs; a refusal
        changes what the researcher does. The requirement says "refuse ...
        rather than warning" and means it.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT point_in_time, pit_note FROM datasets WHERE dataset_id = ?",
                [dataset_id]).fetchone()
        if row is None:
            raise PointInTimeError(
                f"dataset {dataset_id!r} is not registered. An unregistered "
                "dataset has made no point-in-time guarantee, so a backtest "
                "against it cannot be trusted to avoid look-ahead.")
        if not row[0]:
            raise PointInTimeError(
                f"dataset {dataset_id!r} cannot supply point-in-time semantics "
                f"and must not be backtested against: {row[1]}")

    # ---- immutable versions ------------------------------------------------
    def append_facts(self, dataset_id: str, facts: Sequence[dict[str, Any]], *,
                     note: str | None = None) -> str:
        """Append facts as a new immutable version. Returns the version id.

        Every load is a version. There is no update path: a corrected value is a
        RESTATEMENT — a new fact with a later knowledge_date — which is what
        FR-02 requires and what makes as-first-reported queries possible at all.
        """
        self._assert_known(dataset_id)
        if not facts:
            raise ValueError("a version with no facts is not a version")

        rows = [self._normalise(dataset_id, f) for f in facts]
        payload = json.dumps(
            [[r["entity_id"], r["field"], r["value"],
              str(r["effective_date"]), str(r["knowledge_date"])] for r in rows],
            sort_keys=True)
        content_hash = hashlib.sha256(payload.encode()).hexdigest()

        with self._connect() as conn:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM dataset_versions WHERE dataset_id = ?",
                [dataset_id]).fetchone()
            version_number = int(n) + 1
            version_id = f"{dataset_id}@v{version_number}"
            max_knowledge = max(r["knowledge_date"] for r in rows)

            conn.execute(
                "INSERT INTO dataset_versions VALUES (?, ?, ?, ?, ?, ?, "
                "current_timestamp, ?)",
                [version_id, dataset_id, version_number, content_hash,
                 len(rows), max_knowledge, note])
            conn.executemany(
                "INSERT INTO facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [[f"{version_id}#{i}", dataset_id, version_id, r["entity_id"],
                  r["field"], r["value"], r["effective_date"],
                  r["knowledge_date"], r["is_restatement"], r["source"]]
                 for i, r in enumerate(rows)])
        return version_id

    def versions(self, dataset_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT version_id, version_number, content_hash, row_count, "
                "knowledge_date, note FROM dataset_versions WHERE dataset_id = ? "
                "ORDER BY version_number", [dataset_id]).fetchall()
        cols = ["version_id", "version_number", "content_hash", "row_count",
                "knowledge_date", "note"]
        return [dict(zip(cols, r)) for r in rows]

    def current_version(self, dataset_id: str) -> str | None:
        vs = self.versions(dataset_id)
        return vs[-1]["version_id"] if vs else None

    # ---- FR-01: what was known as of D ------------------------------------
    def as_of(self, dataset_id: str, knowledge_date: str | date, *,
              entity_id: str | None = None, field: str | None = None,
              effective_on_or_before: str | date | None = None
              ) -> list[dict[str, Any]]:
        """Every fact KNOWN as of `knowledge_date`, as first reported.

        Restatements published after `knowledge_date` are invisible, which is
        the entire point: a backtest run as of 2023-12-01 must see the number
        that was on the wire that day, not the one corrected in February.
        """
        self.require_point_in_time(dataset_id)
        sql = ("SELECT entity_id, field, value, effective_date, knowledge_date, "
               "is_restatement, source, version_id FROM facts "
               "WHERE dataset_id = ? AND knowledge_date <= ?")
        args: list[Any] = [dataset_id, str(knowledge_date)]
        if entity_id:
            sql += " AND entity_id = ?"
            args.append(entity_id)
        if field:
            sql += " AND field = ?"
            args.append(field)
        if effective_on_or_before:
            sql += " AND effective_date <= ?"
            args.append(str(effective_on_or_before))
        sql += " ORDER BY effective_date, knowledge_date"

        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        cols = ["entity_id", "field", "value", "effective_date", "knowledge_date",
                "is_restatement", "source", "version_id"]
        return [dict(zip(cols, r)) for r in rows]

    def as_reported(self, dataset_id: str, entity_id: str, field: str,
                    effective_date: str | date,
                    knowledge_date: str | date | None = None) -> dict[str, Any] | None:
        """FR-02's default: the FIRST reported value for a period.

        Not the latest, and not the best. The first — because that is what a
        researcher acting at the time would have had.
        """
        self.require_point_in_time(dataset_id)
        sql = ("SELECT entity_id, field, value, effective_date, knowledge_date, "
               "is_restatement, source, version_id FROM facts "
               "WHERE dataset_id = ? AND entity_id = ? AND field = ? "
               "AND effective_date = ?")
        args: list[Any] = [dataset_id, entity_id, field, str(effective_date)]
        if knowledge_date is not None:
            sql += " AND knowledge_date <= ?"
            args.append(str(knowledge_date))
        sql += " ORDER BY knowledge_date ASC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, args).fetchone()
        if row is None:
            return None
        cols = ["entity_id", "field", "value", "effective_date", "knowledge_date",
                "is_restatement", "source", "version_id"]
        return dict(zip(cols, row))

    def latest_including_restatements(self, dataset_id: str, entity_id: str,
                                      field: str, effective_date: str | date, *,
                                      acknowledge_contamination: bool = False
                                      ) -> dict[str, Any]:
        """FR-02: reading restated values is BLOCKED unless acknowledged.

        The flag is a required, explicitly-named argument rather than a default,
        because the contamination it admits to is invisible in the output
        otherwise — a restated fundamental looks exactly like an as-reported one,
        and produces a backtest that cannot legitimately be compared against a
        clean one.
        """
        self.require_point_in_time(dataset_id)
        if not acknowledge_contamination:
            raise LookAheadContamination(
                f"reading the latest value of {field!r} for {entity_id} "
                f"({effective_date}) may return a RESTATED figure that was not "
                "known at the time. Research defaults to as-reported — use "
                "as_reported(), or pass acknowledge_contamination=True and "
                "carry the flag through to the result record (FR-02).")

        with self._connect() as conn:
            row = conn.execute(
                "SELECT entity_id, field, value, effective_date, knowledge_date, "
                "is_restatement, source, version_id FROM facts "
                "WHERE dataset_id = ? AND entity_id = ? AND field = ? "
                "AND effective_date = ? ORDER BY knowledge_date DESC LIMIT 1",
                [dataset_id, entity_id, field, str(effective_date)]).fetchone()
        if row is None:
            raise PointInTimeError(f"no fact for {entity_id}/{field}/{effective_date}")
        cols = ["entity_id", "field", "value", "effective_date", "knowledge_date",
                "is_restatement", "source", "version_id"]
        result = dict(zip(cols, row))
        first = self.as_reported(dataset_id, entity_id, field, effective_date)
        result["look_ahead_contaminated"] = True
        result["as_first_reported"] = first["value"] if first else None
        result["differs_from_as_reported"] = (
            first is not None and first["value"] != result["value"])
        return result

    def restatements(self, dataset_id: str) -> list[dict[str, Any]]:
        """Every fact that revised an earlier one. Auditable by construction."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT entity_id, field, value, effective_date, knowledge_date, "
                "source, version_id FROM facts WHERE dataset_id = ? "
                "AND is_restatement ORDER BY knowledge_date", [dataset_id]).fetchall()
        cols = ["entity_id", "field", "value", "effective_date", "knowledge_date",
                "source", "version_id"]
        return [dict(zip(cols, r)) for r in rows]

    # ---- helpers -----------------------------------------------------------
    def _assert_known(self, dataset_id: str) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM datasets WHERE dataset_id = ?",
                               [dataset_id]).fetchone()
        if row is None:
            raise PointInTimeError(
                f"dataset {dataset_id!r} must be registered before facts are "
                "loaded, so its point-in-time guarantee is on record first")

    def _normalise(self, dataset_id: str, fact: dict[str, Any]) -> dict[str, Any]:
        missing = {"entity_id", "field", "effective_date", "knowledge_date"} - set(fact)
        if missing:
            raise ValueError(
                f"fact is missing {sorted(missing)}. Both dates are required: "
                "effective_date is the period described, knowledge_date is when "
                "it was learned, and collapsing them is how look-ahead enters.")
        effective = str(fact["effective_date"])
        knowledge = str(fact["knowledge_date"])
        if knowledge < effective:
            raise ValueError(
                f"knowledge_date {knowledge} precedes effective_date {effective} "
                f"for {fact['entity_id']}/{fact['field']}: a fact cannot be known "
                "before the period it describes has begun")
        return {
            "entity_id": str(fact["entity_id"]),
            "field": str(fact["field"]),
            "value": None if fact.get("value") is None else float(fact["value"]),
            "effective_date": effective,
            "knowledge_date": knowledge,
            "is_restatement": bool(fact.get("is_restatement", False)),
            "source": fact.get("source"),
        }
