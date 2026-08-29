"""SEC EDGAR — the only free source with a real knowledge date and the dead.

Every other source this project can reach gives today's view of history. EDGAR
gives both dates on every record — `end` for the period a figure describes and
`filed` for the day it was on the wire — so as-first-reported is a property of
the data rather than a reconstruction. And it retains companies after they stop
trading, which is what FR-03 asks for.

The excerpts below are VERBATIM from data.sec.gov, captured 2026-08-28. Apple's
FY2009 stockholders' equity really was first reported as 27,832,000,000 and
restated to 31,640,000,000 — a 13.68% revision, from the retrospective change in
revenue recognition. Bed Bath & Beyond really does come back with no tickers and
no exchanges, under the name of its post-bankruptcy shell.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="EDGAR facts land in the point-in-time store")

from src.research_integrity.ingest import (
    IngestError,
    concept_facts,
    listing_status,
    load,
)
from src.research_integrity.point_in_time import PointInTimeStore

CONCEPT = json.dumps({
    "cik": 320193, "taxonomy": "us-gaap", "tag": "StockholdersEquity",
    "units": {"USD": [
        {"end": "2009-09-26", "val": 27832000000, "fy": 2009, "fp": "FY",
         "form": "10-K", "filed": "2009-10-27", "accn": "0001193125-09-214859"},
        {"end": "2009-09-26", "val": 31640000000, "fy": 2010, "fp": "FY",
         "form": "10-K", "filed": "2010-10-27", "accn": "0001193125-10-238044"},
        # EDGAR repeats a figure across the comparatives of later filings.
        {"end": "2009-09-26", "val": 31640000000, "fy": 2011, "fp": "FY",
         "form": "10-K", "filed": "2011-10-26", "accn": "0001193125-11-282113"},
        {"end": "2010-09-25", "val": 47791000000, "fy": 2010, "fp": "FY",
         "form": "10-K", "filed": "2010-10-27", "accn": "0001193125-10-238044"},
        {"end": "2010-09-25", "val": 47791000000, "fy": 2010, "fp": "FY",
         "form": "8-K", "filed": "2010-10-18", "accn": "0001193125-10-231947"},
    ]}})

DELISTED = json.dumps({
    "cik": "0000886158", "name": "20230930-DK-Butterfly-1, Inc.",
    "tickers": [], "exchanges": [], "sicDescription": "Retail-Home Furniture",
    "filings": {"recent": {"filingDate": ["2023-12-04", "2023-09-30"]}}})

LISTED = json.dumps({
    "cik": "0000320193", "name": "Apple Inc.",
    "tickers": ["AAPL"], "exchanges": ["Nasdaq"],
    "sicDescription": "Electronic Computers",
    "filings": {"recent": {"filingDate": ["2026-08-27", "2026-05-01"]}}})


# --- both dates, from the source -------------------------------------------

def test_the_period_and_the_filing_date_are_kept_apart():
    facts = concept_facts(CONCEPT, entity_id="AAPL", field="book_equity")
    first = next(f for f in facts if f["knowledge_date"] == "2009-10-27")
    assert first["effective_date"] == "2009-09-26"
    assert first["value"] == pytest.approx(27832000000)
    assert all(f["effective_date"] != f["knowledge_date"] for f in facts), (
        "a filing is never same-day with the period it describes")


def test_only_the_requested_forms_are_taken():
    """An 8-K earnings release and the 10-K it precedes are different
    assertions; mixing them silently changes what 'as reported' means."""
    facts = concept_facts(CONCEPT, entity_id="AAPL", field="book_equity",
                          forms=("10-K",))
    assert all("8-K" not in f["source"] for f in facts)
    with_8k = concept_facts(CONCEPT, entity_id="AAPL", field="book_equity",
                            forms=("10-K", "8-K"))
    assert len(with_8k) > len(facts)


def test_repeated_comparatives_are_collapsed():
    """EDGAR restates the same figure in the comparative columns of later
    filings. Each repetition is the same assertion on the same day, not new
    information, so identical (end, filed, value) rows collapse."""
    facts = concept_facts(CONCEPT, entity_id="AAPL", field="book_equity",
                          forms=("10-K", "8-K"))
    keys = [(f["effective_date"], f["knowledge_date"], f["value"]) for f in facts]
    assert len(keys) == len(set(keys))


def test_a_missing_unit_is_refused():
    with pytest.raises(IngestError, match="no EUR records"):
        concept_facts(CONCEPT, entity_id="AAPL", field="book_equity", unit="EUR")


def test_malformed_payloads_are_refused():
    with pytest.raises(IngestError, match="not valid JSON"):
        concept_facts("{not json", entity_id="X", field="y")


# --- FR-02, on a real 13.68% restatement -----------------------------------

@pytest.fixture()
def store(tmp_path: Path) -> PointInTimeStore:
    s = PointInTimeStore(tmp_path / "edgar.duckdb")
    load(s, "edgar", concept_facts(CONCEPT, entity_id="AAPL",
                                   field="book_equity", forms=("10-K",)))
    return s


def test_a_restatement_inside_one_batch_is_marked(store):
    """The defect this found. `load` compared only against what was already
    STORED, which catches a revision arriving in a later load — how FRED/ALFRED
    vintages arrive, one CSV each. EDGAR does the opposite: one payload carries
    every vintage of every period, so all of Apple's restatements were inside a
    single batch and none was marked. A record nothing flags as a restatement is
    not kept as one, which is what FR-02 asks for.
    """
    restatements = store.restatements("edgar")
    assert restatements, "the 13.68% revision was not recorded as a restatement"
    # DuckDB returns DATE columns as datetime.date, not str — comparing against
    # a string here silently matched nothing and the test passed on the wrong
    # assertion until it was checked.
    periods = {str(r["effective_date"]) for r in restatements}
    assert "2009-09-26" in periods, periods
    assert all(float(r["value"]) == pytest.approx(31640000000)
               for r in restatements
               if str(r["effective_date"]) == "2009-09-26")


def test_the_first_report_survives_the_revision(store):
    """27,832,000,000 was on the wire in October 2009. A query about that period
    must return it however many times it was later revised."""
    _, before = store.series("edgar", "AAPL", "book_equity",
                             start="2009-09-26", end="2009-09-26",
                             knowledge_date="2010-01-15")
    _, after = store.series("edgar", "AAPL", "book_equity",
                            start="2009-09-26", end="2009-09-26",
                            knowledge_date="2012-01-15")
    assert before[0] == pytest.approx(27832000000)
    assert after[0] == pytest.approx(27832000000), "the revision reached back"


def test_the_revision_is_reachable_only_by_acknowledging_it(store):
    latest = store.latest_including_restatements(
        "edgar", "AAPL", "book_equity", "2009-09-26",
        acknowledge_contamination=True)
    assert latest["value"] == pytest.approx(31640000000)
    assert latest["as_first_reported"] == pytest.approx(27832000000)
    assert latest["value"] / latest["as_first_reported"] - 1 == pytest.approx(
        0.1368, abs=1e-4), "the revision is 13.68%, not a rounding error"


def test_a_period_not_yet_filed_is_invisible(store):
    """FY2009 closed on 2009-09-26 and was filed on 2009-10-27. A query in
    between must see nothing — the publication lag, from the source."""
    dates, _ = store.series("edgar", "AAPL", "book_equity",
                            knowledge_date="2009-10-01")
    assert dates == []


# --- FR-03: the dead are retained ------------------------------------------

def test_a_delisted_company_reads_as_delisted():
    status = listing_status(DELISTED)
    assert status["still_listed"] is False
    assert status["tickers"] == [] and status["exchanges"] == []
    assert status["last_filing"] == "2023-12-04"
    assert "Butterfly" in status["name"], "renamed to its post-bankruptcy shell"


def test_a_live_company_reads_as_listed():
    status = listing_status(LISTED)
    assert status["still_listed"] is True
    assert status["tickers"] == ["AAPL"]


def test_listing_status_is_a_signal_not_a_registry():
    """EDGAR publishes no delisting DATE, so `last_filing` is a proxy. Treating
    it as authoritative would be the overclaim this project keeps catching, and
    the docstring says so — this pins that it keeps saying so."""
    from src.research_integrity import ingest

    assert "signal, not a registry" in ingest.listing_status.__doc__
    assert listing_status(DELISTED)["last_filing"] is not None


def test_a_contact_address_is_required():
    """The SEC asks for one in the User-Agent as a condition of use."""
    from src.research_integrity.ingest import fetch_edgar

    with pytest.raises(IngestError, match="condition of use"):
        fetch_edgar("https://data.sec.gov/x", contact="")
    with pytest.raises(IngestError, match="condition of use"):
        fetch_edgar("https://data.sec.gov/x", contact="not-an-email")
