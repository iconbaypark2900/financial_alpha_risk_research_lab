# Decisions

Durable architecture and product decisions are recorded here.

## Project phase: 2026-05-30T23:25:55

Phase=`unassessed` lifecycle=`registered`. registered via register-project

## Project phase: 2026-05-30T23:25:55

Phase=`unassessed` lifecycle=`assessed`. assessed; recommended alpha

## Project phase: 2026-05-30T23:25:55

Phase=`alpha` lifecycle=`classified`. classified

## Experiment log: SQLite, not MLflow — 2026-08-28

**Decision.** `run_record.py` stays as the system of record for FR-22 through
FR-25. MLflow is not adopted, and is removed from `requirements.txt` and the
backlog. Ratified rather than left as a silent divergence.

**Why, on the requirement rather than on preference.** FR-23 says any past run
MUST be re-executable from its record and MUST produce identical results. MLflow
*logs*: it records what it is told and never checks whether the run reproduces.
`run_record.py` restores the recorded seeds, re-executes, and compares a
canonical hash of the output against the one stored at the time — so a record
with every field populated still fails if an unrecorded seed was consumed, which
is the whole failure mode (the missing field is never the one you thought to
record). There is a test that consumes an unrecorded random source and requires
the replay to catch it.

Adopting MLflow would therefore satisfy the letter of "use MLflow" by weakening
the requirement MLflow was named to serve. Same reasoning as elsewhere in this
project: the spec names a tool to achieve an end, and where the two conflict the
end wins — stated out loud, not quietly.

**What MLflow would genuinely add**, and what would justify revisiting: a UI,
artifact storage, and model-registry integration for a team. None of those are
FR-22..FR-25. If they are wanted, the right shape is an EXPORT from the SQLite
record into MLflow for viewing — not moving the system of record into a store
that cannot enforce FR-23.

**Cost of this decision.** A reader who knows the PRD will expect MLflow and not
find it. That cost is paid by this record, the note in `run_record.py`, and the
README row that names the divergence.

**Reversible.** The record schema is ordinary SQLite; an exporter is additive.
