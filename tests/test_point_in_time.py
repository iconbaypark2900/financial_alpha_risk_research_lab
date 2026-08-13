"""Point-in-time store — PRD 04 FR-01, FR-02, FR-06, FR-07.

The scenario these tests keep returning to is the one that ruins backtests
quietly: a company reports EPS of 1.20, a researcher's backtest at the time
trades on 1.20, and four months later the figure is restated to 0.85. A store
that answers "what is EPS for Q3?" with 0.85 will make that backtest look
prescient, and nothing in the result will say why.

So the central test is `test_a_backtest_in_november_cannot_see_the_february_restatement`.
Everything else defends the conditions that make it hold.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("duckdb")

from src.research_integrity.point_in_time import (  # noqa: E402
    LookAheadContamination,
    PointInTimeError,
    PointInTimeStore,
)


@pytest.fixture()
def store(tmp_path) -> PointInTimeStore:
    s = PointInTimeStore(tmp_path / "d.duckdb")
    s.register_dataset("fundamentals", point_in_time=True,
                       description="as-reported fundamentals")
    return s


@pytest.fixture()
def restated(store) -> PointInTimeStore:
    """Q3 2023 EPS reported as 1.20 in November, restated to 0.85 in February."""
    store.append_facts("fundamentals", [
        {"entity_id": "ACME", "field": "eps", "value": 1.20,
         "effective_date": "2023-09-30", "knowledge_date": "2023-11-02",
         "source": "10-Q"}])
    store.append_facts("fundamentals", [
        {"entity_id": "ACME", "field": "eps", "value": 0.85,
         "effective_date": "2023-09-30", "knowledge_date": "2024-02-20",
         "is_restatement": True, "source": "10-K restatement"}])
    return store


# --- FR-01: what was known as of D -----------------------------------------

def test_a_backtest_in_november_cannot_see_the_february_restatement(restated):
    """The whole requirement in one assertion."""
    known = restated.as_of("fundamentals", "2023-12-01", entity_id="ACME")
    assert [f["value"] for f in known] == [1.20]


def test_the_restatement_becomes_visible_once_it_is_published(restated):
    known = restated.as_of("fundamentals", "2024-03-01", entity_id="ACME")
    assert sorted(f["value"] for f in known) == [0.85, 1.20]


def test_nothing_is_visible_before_it_was_reported(restated):
    """The company had not filed yet; the store must say so rather than
    reaching forward for a number that existed in the database."""
    assert restated.as_of("fundamentals", "2023-10-01") == []


def test_effective_and_knowledge_dates_are_independent_axes(restated):
    """A query can ask about an old period using only recent knowledge, which is
    exactly what table-snapshot time travel cannot express."""
    rows = restated.as_of("fundamentals", "2024-03-01",
                          effective_on_or_before="2023-09-30")
    assert len(rows) == 2
    assert {r["effective_date"].isoformat() for r in rows} == {"2023-09-30"}


# --- FR-02: as-reported by default, restatements flagged -------------------

def test_as_reported_returns_the_first_figure_not_the_best(restated):
    first = restated.as_reported("fundamentals", "ACME", "eps", "2023-09-30")
    assert first["value"] == 1.20
    assert first["is_restatement"] is False


def test_reading_restated_values_is_blocked_by_default(restated):
    """'Any run that reads restated values MUST be either blocked or explicitly
    flagged.' Blocking is the default here; the flag is opt-in."""
    with pytest.raises(LookAheadContamination, match="as-reported"):
        restated.latest_including_restatements(
            "fundamentals", "ACME", "eps", "2023-09-30")


def test_acknowledged_restatement_reads_carry_the_contamination_flag(restated):
    result = restated.latest_including_restatements(
        "fundamentals", "ACME", "eps", "2023-09-30",
        acknowledge_contamination=True)
    assert result["value"] == 0.85
    assert result["look_ahead_contaminated"] is True
    assert result["as_first_reported"] == 1.20
    assert result["differs_from_as_reported"] is True


def test_restatements_are_separate_records_not_overwrites(restated):
    """FR-02 requires restatements as separate versioned records. The original
    must still be readable — an UPDATE would destroy the only evidence of what
    was actually known."""
    revisions = restated.restatements("fundamentals")
    assert len(revisions) == 1
    assert revisions[0]["value"] == 0.85
    assert restated.as_reported("fundamentals", "ACME", "eps", "2023-09-30")["value"] == 1.20


# --- FR-06: immutable versioning -------------------------------------------

def test_every_load_creates_a_new_immutable_version(restated):
    versions = restated.versions("fundamentals")
    assert [v["version_number"] for v in versions] == [1, 2]
    assert versions[0]["version_id"] == "fundamentals@v1"


def test_versions_are_content_hashed(restated):
    versions = restated.versions("fundamentals")
    assert all(len(v["content_hash"]) == 64 for v in versions)
    assert versions[0]["content_hash"] != versions[1]["content_hash"]


def test_identical_content_hashes_identically(store, tmp_path):
    """So a backtest can record the exact version it used, and a reader can
    tell whether two runs saw the same bytes."""
    fact = [{"entity_id": "A", "field": "x", "value": 1.0,
             "effective_date": "2023-01-01", "knowledge_date": "2023-02-01"}]
    store.append_facts("fundamentals", fact)
    other = PointInTimeStore(tmp_path / "other.duckdb")
    other.register_dataset("fundamentals", point_in_time=True)
    other.append_facts("fundamentals", fact)
    assert (store.versions("fundamentals")[0]["content_hash"]
            == other.versions("fundamentals")[0]["content_hash"])


def test_every_fact_carries_the_version_that_produced_it(restated):
    rows = restated.as_of("fundamentals", "2024-03-01")
    assert {r["version_id"] for r in rows} == {"fundamentals@v1", "fundamentals@v2"}


# --- FR-07: refuse, do not warn --------------------------------------------

def test_a_non_point_in_time_dataset_is_refused(tmp_path):
    """'MUST refuse ... rather than warning.' A warning is filtered out of the
    logs; a refusal changes what the researcher does."""
    s = PointInTimeStore(tmp_path / "d.duckdb")
    s.register_dataset("vendor_snapshot", point_in_time=False,
                       pit_note="vendor overwrites history in place; no as-of")
    with pytest.raises(PointInTimeError, match="cannot supply point-in-time"):
        s.require_point_in_time("vendor_snapshot")


def test_the_refusal_says_what_is_missing(tmp_path):
    s = PointInTimeStore(tmp_path / "d.duckdb")
    s.register_dataset("vendor_snapshot", point_in_time=False,
                       pit_note="vendor overwrites history in place")
    with pytest.raises(PointInTimeError, match="overwrites history"):
        s.require_point_in_time("vendor_snapshot")


def test_declaring_a_dataset_non_pit_requires_saying_why(tmp_path):
    """Otherwise the limitation is invisible at the moment someone is refused."""
    s = PointInTimeStore(tmp_path / "d.duckdb")
    with pytest.raises(ValueError, match="pit_note"):
        s.register_dataset("mystery", point_in_time=False)


def test_an_unregistered_dataset_is_refused(store):
    with pytest.raises(PointInTimeError, match="not registered"):
        store.require_point_in_time("never_heard_of_it")


def test_queries_go_through_the_same_refusal(tmp_path):
    """The guard cannot be bypassed by querying instead of asking."""
    s = PointInTimeStore(tmp_path / "d.duckdb")
    s.register_dataset("bad", point_in_time=False, pit_note="no history")
    with pytest.raises(PointInTimeError):
        s.as_of("bad", "2024-01-01")


# --- refusals that keep the two axes honest --------------------------------

def test_a_fact_missing_either_date_is_refused(store):
    with pytest.raises(ValueError, match="knowledge_date"):
        store.append_facts("fundamentals", [
            {"entity_id": "A", "field": "x", "value": 1.0,
             "effective_date": "2023-01-01"}])


def test_knowledge_before_the_period_began_is_refused(store):
    """A fact cannot be known before the period it describes has started —
    that is not point-in-time data, it is a data error or a clairvoyant."""
    with pytest.raises(ValueError, match="precedes effective_date"):
        store.append_facts("fundamentals", [
            {"entity_id": "A", "field": "eps", "value": 1.0,
             "effective_date": "2023-09-30", "knowledge_date": "2023-01-01"}])


def test_facts_cannot_be_loaded_into_an_unregistered_dataset(store):
    with pytest.raises(PointInTimeError, match="must be registered"):
        store.append_facts("nope", [
            {"entity_id": "A", "field": "x", "value": 1.0,
             "effective_date": "2023-01-01", "knowledge_date": "2023-02-01"}])


def test_an_empty_version_is_refused(store):
    with pytest.raises(ValueError, match="not a version"):
        store.append_facts("fundamentals", [])
