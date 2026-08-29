"""Ingestion of real market data, tested without the network.

The CSV excerpts below are VERBATIM from FRED and ALFRED, captured 2026-08-28.
They are real rows, not invented ones, so the parsers are exercised against the
actual shape the sources emit — while the suite stays offline, because a test
that fails when a third party rate-limits you is a test people learn to ignore.

The GDP figures are the interesting part: the February vintage reports
2023-10-01 as 22672.859 and the June vintage restates it to 22679.255, while
2024-01-01 does not exist in February at all. That is FR-01 and FR-02 with a
real revision and a real publication lag, rather than a fixture shaped to pass.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="ingestion targets the point-in-time store")

from src.research_integrity.ingest import (
    IngestError,
    load,
    price_facts,
    vintage_facts,
)
from src.research_integrity.point_in_time import PointInTimeStore

SP500 = """observation_date,SP500
2016-08-29,2180.38
2016-08-30,2176.12
2016-08-31,2170.95
2016-09-01,2170.86
2016-09-02,2179.98
"""

GDP_FEB = """observation_date,GDPC1_20240215
2023-07-01,22490.692
2023-10-01,22672.859
"""

GDP_JUN = """observation_date,GDPC1_20240615
2023-07-01,22490.692
2023-10-01,22679.255
2024-01-01,22749.846
"""


# --- parsing real responses ------------------------------------------------

def test_prices_parse_with_knowledge_equal_to_effective():
    """A closing level is known at the close. Stated as a claim, not assumed."""
    facts = price_facts(SP500, entity_id="SP500")
    assert len(facts) == 5
    assert facts[0]["effective_date"] == "2016-08-29"
    assert facts[0]["knowledge_date"] == "2016-08-29"
    assert facts[0]["value"] == pytest.approx(2180.38)
    assert all(f["effective_date"] == f["knowledge_date"] for f in facts)


def test_a_missing_observation_is_dropped_not_carried_forward():
    """FRED writes a lone period where no observation exists. A holiday is an
    absence; filling it invents a price that was never quoted."""
    with_gap = SP500 + "2016-09-05,.\n2016-09-06,2186.48\n"
    facts = price_facts(with_gap, entity_id="SP500")
    assert len(facts) == 6
    assert "2016-09-05" not in {f["effective_date"] for f in facts}


def test_vintages_carry_the_publication_lag():
    """knowledge_date is the vintage, effective_date the period it describes."""
    facts = vintage_facts(GDP_FEB, entity_id="GDPC1", vintage_date="2024-02-15")
    assert all(f["knowledge_date"] == "2024-02-15" for f in facts)
    assert {f["effective_date"] for f in facts} == {"2023-07-01", "2023-10-01"}


def test_the_february_vintage_simply_lacks_the_unpublished_quarter():
    """The protection is the SOURCE's, not this parser's.

    A first version of this test asserted that parsing the June CSV under a
    February vintage date would drop 2024-01-01. It does not, and cannot: the
    parser's `observation_date > vintage_date` guard compares the period a
    figure DESCRIBES against the date it was taken, and Q1 2024 is dated
    2024-01-01 — before 2024-02-15 — while not being published until late
    April. Publication lag is not visible in the observation date.

    What actually holds is that ALFRED's February vintage does not contain the
    quarter, because in February it did not exist. That is the guarantee worth
    testing, and it belongs to the source.
    """
    february = {f["effective_date"] for f in vintage_facts(
        GDP_FEB, entity_id="GDPC1", vintage_date="2024-02-15")}
    june = {f["effective_date"] for f in vintage_facts(
        GDP_JUN, entity_id="GDPC1", vintage_date="2024-06-15")}
    assert "2024-01-01" not in february
    assert "2024-01-01" in june


@pytest.mark.parametrize("bad", ["", "not,a,fred,csv\n1,2,3,4\n",
                                 "observation_date,SP500\n"])
def test_malformed_csv_is_refused(bad):
    with pytest.raises(IngestError):
        price_facts(bad, entity_id="X")


def test_a_non_numeric_observation_is_refused():
    with pytest.raises(IngestError, match="not a number"):
        price_facts("observation_date,SP500\n2016-08-29,abc\n", entity_id="SP500")


# --- through the store -----------------------------------------------------

@pytest.fixture()
def store(tmp_path: Path) -> PointInTimeStore:
    return PointInTimeStore(tmp_path / "facts.duckdb")


def test_loading_registers_and_versions(store):
    version = load(store, "sp500", price_facts(SP500, entity_id="SP500"))
    assert version == "sp500@v1"
    store.require_point_in_time("sp500")        # must not raise
    assert store.current_version("sp500") == version


def test_new_facts_make_a_new_version(store):
    load(store, "sp500", price_facts(SP500, entity_id="SP500"))
    second = load(store, "sp500", price_facts(
        "observation_date,SP500\n2016-09-06,2186.48\n", entity_id="SP500"))
    assert second == "sp500@v2"
    assert len(store.versions("sp500")) == 2


def test_loading_identical_facts_twice_is_idempotent(store):
    """Harmless while every store lived in a TemporaryDirectory; wrong once one
    persists.

    A daily run would otherwise accumulate sp500@v1..vN of the same data, and
    two runs over identical facts would record DIFFERENT dataset versions —
    making FR-06's "a backtest MUST record the exact version it used" true in
    letter and misleading in fact.
    """
    first = load(store, "sp500", price_facts(SP500, entity_id="SP500"))
    again = load(store, "sp500", price_facts(SP500, entity_id="SP500"))
    assert again == first
    assert len(store.versions("sp500")) == 1


def test_idempotence_does_not_swallow_a_restatement(store):
    """The revision must still land: identical means identical, and a changed
    value is not."""
    load(store, "gdp", vintage_facts(GDP_FEB, entity_id="GDPC1",
                                     vintage_date="2024-02-15"))
    revised = load(store, "gdp", vintage_facts(GDP_JUN, entity_id="GDPC1",
                                               vintage_date="2024-06-15"))
    assert revised == "gdp@v2"
    assert len(store.restatements("gdp")) >= 1


def test_the_series_comes_back_in_order(store):
    load(store, "sp500", price_facts(SP500, entity_id="SP500"))
    dates, values = store.series("sp500", "SP500", "close")
    assert dates == sorted(dates)
    assert len(dates) == 5
    assert values[0] == pytest.approx(2180.38)


def test_the_series_respects_the_requested_range(store):
    load(store, "sp500", price_facts(SP500, entity_id="SP500"))
    dates, _ = store.series("sp500", "SP500", "close",
                            start="2016-08-31", end="2016-09-01")
    assert dates == ["2016-08-31", "2016-09-01"]


# --- FR-01 and FR-02, on a real revision -----------------------------------

@pytest.fixture()
def macro(tmp_path: Path) -> PointInTimeStore:
    s = PointInTimeStore(tmp_path / "macro.duckdb")
    load(s, "gdp", vintage_facts(GDP_FEB, entity_id="GDPC1",
                                 vintage_date="2024-02-15"))
    load(s, "gdp", vintage_facts(GDP_JUN, entity_id="GDPC1",
                                 vintage_date="2024-06-15"))
    return s


def test_a_query_cannot_see_a_period_not_yet_published(macro):
    """2024-01-01 was published between the two vintages. FR-01."""
    dates, _ = macro.series("gdp", "GDPC1", "value",
                            knowledge_date="2024-02-15")
    assert "2024-01-01" not in dates
    dates, _ = macro.series("gdp", "GDPC1", "value",
                            knowledge_date="2024-06-15")
    assert "2024-01-01" in dates


def test_the_series_returns_the_first_report_not_the_revision(macro):
    """FR-02, on a real revision: 22672.859 was on the wire in February and
    22679.255 replaced it in June. A query after the revision must still get
    what was knowable at the time it asks about."""
    _, february = macro.series("gdp", "GDPC1", "value",
                               start="2023-10-01", end="2023-10-01",
                               knowledge_date="2024-02-15")
    _, june = macro.series("gdp", "GDPC1", "value",
                           start="2023-10-01", end="2023-10-01",
                           knowledge_date="2024-06-15")
    assert february[0] == pytest.approx(22672.859)
    assert june[0] == pytest.approx(22672.859), "the revision reached back"


def test_the_revision_is_available_but_only_on_request(macro):
    """It is not hidden — it is behind an explicit acknowledgement (FR-02)."""
    from src.research_integrity.point_in_time import LookAheadContamination

    with pytest.raises(LookAheadContamination):
        macro.latest_including_restatements("gdp", "GDPC1", "value", "2023-10-01")

    restated = macro.latest_including_restatements(
        "gdp", "GDPC1", "value", "2023-10-01", acknowledge_contamination=True)
    assert restated["value"] == pytest.approx(22679.255)
    assert restated["as_first_reported"] == pytest.approx(22672.859)
    assert restated["differs_from_as_reported"] is True


def test_a_real_restatement_is_auditable(macro):
    assert len(macro.restatements("gdp")) >= 1
