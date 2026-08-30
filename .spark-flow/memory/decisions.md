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

## The data gap: EDGAR again, not CRSP — 2026-08-30

**Decision.** FR-03, FR-04, FR-05 and FR-19 stay open, and no vendor data is licensed.
The one back door that was verified gets built: EDGAR Form 25 and 25-NSE carry a filed,
dated, structured removal-from-listing notice, so the delisting DATE that FR-03 is
missing is free and public-domain like the archive already mirrored. CRSP, Compustat,
WRDS and LSEG are rejected. The rescope of FR-04 and FR-05 out of scope is refused. The
full analysis, with prices, licence clauses and the measurements behind every claim, is
in `docs/DATA_DECISION.md`. No status in `docs/REQUIREMENTS.md` moves; statuses move
when a test moves.

**Why, on the requirement rather than on preference.** FR-23 says any past run MUST be
re-executable and MUST produce identical results. Both licences whose terms were read in full oblige
destruction of the data when the subscription ends — CRSP §9.1, "erase and/or destroy the
original and all copies of the Data Files" within thirty days, certified by a Dean or an
officer; Norgate clause 21, "must delete all Content", with permission to keep only
"Derived Data". Derived Data is the *result*, which is what a log keeps. So under a
licence FR-23 holds while the invoice is paid and not after, and every run record naming
that dataset would name a file the subscriber is contractually required not to possess.
That is the MLflow reasoning one layer down: MLflow was refused because it logs and never
re-executes; a dataset that must be deleted makes the record a log by contract rather than
by design.

Three further requirement facts, none of them about preference. **FR-19 is untouched by
CRSP and Compustat** — the two names that dominate this decision do not carry order-book
depth at all, and FR-19 is V0's one open engine requirement. **The affordable tier is
closed by eligibility, not price**: S&P Global Academic Research Essentials is "for
academic and non-commercial research purposes only" and CRSP §1.2 excludes "for-profit
uses by an Academic Subscriber", while this repository's front page describes an internal
tool run by the team that trades the strategies. And **FR-05 is not severable from FR-02**,
which is met and running: Apple's FY2013 basic EPS was first reported 40.03 on 2013-10-30
and reads 5.72 in the 10-K filed 2014-10-27 — a −85.71% "restatement" that is entirely the
7-for-1 split, and without corporate actions no field tells the two apart. Rescoping FR-05
would declare that false-positive class permanent in a control the project already
publishes results from.

**What a licence would genuinely add**, and what would justify revisiting: survivorship-free
PRICES, which no free source supplies and which is the half of FR-03 the Form 25 mirror does
not touch; index membership with real effective dates; and dividend ex-dates. Norgate Data
Platinum sells all three for a published **USD 630 a year** — two orders of magnitude under
the assumption this decision started from, and the reason the price was looked up rather
than recalled. It is still not bought, because clause 21 breaks FR-23 on expiry and clauses
2(i) and 8 licence it to one person for personal use on two computers. Revisit it the moment
either (a) a vendor offers a perpetual licence to a dated snapshot rather than access for the
term, or (b) FR-06 and FR-23 are restated to say "re-executable while the licence is current"
AND `replay()` REFUSES — not warns — a run whose licence-bound dataset cannot be verified,
with a test that fails if it ever silently proceeds.

**Cost of this decision.** Three requirements stay open that money could close, and the
status board keeps two "not implemented" rows that a reader may mistake for a plan. That
cost is paid by this record and by `docs/DATA_DECISION.md`, which states per requirement
what each option closes and what it leaves. The second cost is subtler and is the one worth
naming: licensed data would not stop the project publishing its negative results — CRSP §2.2
and Norgate clause 21 both permit that — but every licence examined forbids the
content-addressed mirror, so a reader could no longer fetch the bytes and check the digest.
For a platform whose design goal is believability, that property is the expensive item and it
never appears on the invoice.

**Reversible.** Nothing here forecloses anything. The Form 25 mirror is additive and reuses
`mirror.py`'s shape. A licence can be bought later once the two prerequisites above exist,
and the store's schema already carries membership and corporate actions as ordinary
effective-dated facts, waiting for data nobody has loaded.
