"""Cross-sectional reads — the paths that had never seen more than one series.

The factor library, purged/embargoed CV and capacity analysis were all built for
a cross-section and had only ever been run on a single series. Pointing them at
six real FRED series found three things within minutes: an O(n) query in
ingestion that never finished, a real negative price, and a panel that has to
decide what to do about ragged dates. All three are pinned here.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("duckdb", reason="the panel is a store read")

from src.research_integrity.ingest import load, price_facts
from src.research_integrity.point_in_time import PointInTimeError, PointInTimeStore

# Real rows. NIKKEI225 is absent on 2019-01-02 (a Japanese holiday) and present
# on 2019-01-04, which is the ragged shape that makes alignment a decision.
US = """observation_date,SP500
2019-01-02,2510.03
2019-01-03,2447.89
2019-01-04,2531.94
"""
JP = """observation_date,NIKKEI225
2019-01-03,19561.96
2019-01-04,19561.96
"""
OIL = """observation_date,DCOILWTICO
2019-01-02,46.31
2019-01-03,47.09
2019-01-04,47.96
2020-04-20,-36.98
"""


@pytest.fixture()
def store(tmp_path: Path) -> PointInTimeStore:
    s = PointInTimeStore(tmp_path / "w.duckdb")
    for csv, entity in ((US, "SP500"), (JP, "NIKKEI225"), (OIL, "DCOILWTICO")):
        load(s, "world", price_facts(csv, entity_id=entity))
    return s


def test_the_panel_keeps_ragged_dates_and_marks_them_nan(store):
    """No forward-fill. A holiday is an absence, and filling it puts a stale
    price into a ranking against live ones."""
    dates, entities, matrix = store.panel("world", ["SP500", "NIKKEI225"], "close")
    assert dates == ["2019-01-02", "2019-01-03", "2019-01-04"]
    assert entities == ["SP500", "NIKKEI225"]
    assert np.isnan(matrix[0, 1]), "NIKKEI did not trade on 2019-01-02"
    assert matrix[0, 0] == pytest.approx(2510.03)


def test_complete_cases_drops_the_ragged_dates_instead(store):
    dates, _, matrix = store.panel("world", ["SP500", "NIKKEI225"], "close",
                                   complete_cases=True)
    assert dates == ["2019-01-03", "2019-01-04"]
    assert not np.isnan(matrix).any()


def test_the_panel_never_invents_a_price(store):
    """Between the two options — NaN or drop the date — neither fills."""
    _, _, loose = store.panel("world", ["SP500", "NIKKEI225"], "close")
    _, _, strict = store.panel("world", ["SP500", "NIKKEI225"], "close",
                               complete_cases=True)
    assert np.isnan(loose).sum() == 1
    assert len(strict) < len(loose)
    for observed in np.concatenate([loose[~np.isnan(loose)], strict.ravel()]):
        assert observed in {2510.03, 2447.89, 2531.94, 19561.96}


def test_an_empty_universe_is_refused(store):
    with pytest.raises(PointInTimeError, match="no entities"):
        store.panel("world", [], "close")


def test_a_universe_that_never_traded_together_is_refused(tmp_path):
    s = PointInTimeStore(tmp_path / "d.duckdb")
    load(s, "d", price_facts("observation_date,A\n2019-01-02,1.0\n", entity_id="A"))
    load(s, "d", price_facts("observation_date,B\n2020-01-02,1.0\n", entity_id="B"))
    with pytest.raises(PointInTimeError, match="never traded together"):
        s.panel("d", ["A", "B"], "close", complete_cases=True)


# --- the negative price, which is a real market event ----------------------

def test_non_positive_prices_are_reported_before_a_factor_crashes(store):
    """WTI crude settled at -36.98 on 2020-04-20 and FRED carries it.

    The factor library refuses a non-positive price — correctly, since a simple
    return through zero is undefined — and learning that from a FactorError two
    hundred lines into a strategy is a poor way to find out the universe
    contains an instrument this library cannot price.
    """
    flagged = store.non_positive("world")
    assert list(flagged) == ["DCOILWTICO"]
    assert flagged["DCOILWTICO"] == [("2020-04-20", -36.98)]


def test_a_clean_universe_reports_nothing(store):
    assert store.non_positive("world", field="nonexistent") == {}


def test_the_factor_library_names_the_offending_value():
    """The refusal stands; it just has to say what it found and why."""
    from src.research_integrity.factors import FactorError, momentum

    with pytest.raises(FactorError, match="2020-04-20|-36.98|non-positive"):
        momentum([46.31, 47.09, -36.98, 47.96], lookback=2, skip=0)


# --- ingestion at cross-sectional scale ------------------------------------

def test_restatement_detection_uses_one_query_not_one_per_fact(store):
    """It called as_reported() per incoming fact: 58,699 round trips for a
    six-series cross section, which simply never finished. Correct logic, never
    run at the scale it would meet."""
    index = store.as_reported_index("world")
    assert index[("SP500", "close", "2019-01-02")] == pytest.approx(2510.03)
    assert index[("DCOILWTICO", "close", "2020-04-20")] == pytest.approx(-36.98)
    assert len(index) == 3 + 2 + 4


def test_the_index_returns_the_first_report_not_the_latest(tmp_path):
    s = PointInTimeStore(tmp_path / "r.duckdb")
    load(s, "d", price_facts("observation_date,A\n2019-01-02,10.0\n", entity_id="A"))
    s.append_facts("d", [{"entity_id": "A", "field": "close", "value": 99.0,
                          "effective_date": "2019-01-02",
                          "knowledge_date": "2020-01-01", "is_restatement": True}])
    assert s.as_reported_index("d")[("A", "close", "2019-01-02")] == pytest.approx(10.0)
