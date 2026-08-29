"""Building a universe from the mirror — where survivorship gets in.

The obvious ways to pick companies from 20,281 candidates all condition on
survival: longest filing history, most complete data, largest balance sheet. A
company that went bankrupt in 2015 scores badly on every one of them BECAUSE it
died. Selecting that way rebuilds the bias the mirror was chosen to avoid,
inside the function whose job is avoiding it.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="a universe lands in the point-in-time store")

from src.research_integrity.mirror import Mirror
from src.research_integrity.point_in_time import PointInTimeStore
from src.research_integrity.universe import (
    BuildReport,
    UniverseError,
    build,
    candidates,
    rank_churn,
)


def _company(cik: int, rows: list[tuple[str, str, float]]) -> str:
    """rows are (end, filed, value) for StockholdersEquity."""
    return json.dumps({"cik": cik, "entityName": f"CO{cik}", "facts": {"us-gaap": {
        "StockholdersEquity": {"units": {"USD": [
            {"end": e, "filed": f, "val": v, "form": "10-K", "accn": f"{cik}{f}"}
            for e, f, v in rows]}}}}})


@pytest.fixture()
def mirror(tmp_path: Path) -> Mirror:
    path = tmp_path / "cf.zip"
    with zipfile.ZipFile(path, "w") as z:
        # A survivor, a company that restated, and one that stopped filing.
        z.writestr("CIK0000000100.json",
                   _company(100, [("2014-12-31", "2015-03-01", 1_000.0)]))
        z.writestr("CIK0000000200.json",
                   _company(200, [("2014-12-31", "2015-03-01", 2_000.0),
                                  ("2014-12-31", "2016-03-01", 2_400.0)]))
        z.writestr("CIK0000000300.json",
                   _company(300, [("2014-12-31", "2015-03-01", 3_000.0)]))
        z.writestr("CIK0000000400.json", json.dumps({"cik": 400, "facts": {}}))
        z.writestr("notacompany.txt", "x")
    import hashlib
    path.with_suffix(".zip.manifest.json").write_text(json.dumps({
        "url": "x", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size, "downloaded_at": "2026-08-28T00:00:00+00:00"}))
    return Mirror(path=path)


@pytest.fixture()
def store(tmp_path: Path) -> PointInTimeStore:
    return PointInTimeStore(tmp_path / "u.duckdb")


# --- selection -------------------------------------------------------------

def test_candidates_come_in_cik_order_and_nothing_else(mirror):
    """CIK is assigned at registration and has no relationship to outcome, which
    is what makes it arbitrary in the way that matters."""
    ciks = [c for c, _ in candidates(mirror)]
    assert ciks == sorted(ciks)
    assert ciks == [100, 200, 300, 400]


def test_selection_does_not_read_the_data_first(mirror, store):
    """A company with no usable data is skipped AFTER selection and counted, so
    the skip rate is visible rather than silently shaping the universe."""
    report = build(mirror, store, "u", limit=10)
    assert report.considered == 4
    assert report.loaded == 3
    assert report.skipped_no_data == 1
    assert report.as_dict()["skip_rate"] == pytest.approx(0.25)


def test_the_report_names_what_was_left_out(mirror, store):
    """A build that quietly dropped a third of its candidates produced a
    different universe from the one requested."""
    report = build(mirror, store, "u", limit=10)
    d = report.as_dict()
    assert set(d) >= {"considered", "loaded", "skipped_no_data", "skip_rate",
                      "mirror_version", "facts"}
    assert d["mirror_version"].startswith("cf.zip@")


def test_the_universe_is_identified_by_the_mirror_that_built_it(mirror, store):
    """FR-06: a run must name the exact data version. The universe inherits the
    archive's digest."""
    report = build(mirror, store, "u", limit=10)
    assert report.mirror_version == mirror.version_id()


def test_a_limit_below_one_is_refused(mirror, store):
    with pytest.raises(UniverseError, match="limit must be at least 1"):
        build(mirror, store, "u", limit=0)


def test_a_universe_with_no_usable_company_is_refused(tmp_path, store):
    import hashlib

    empty = tmp_path / "e.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("CIK0000000400.json", json.dumps({"cik": 400, "facts": {}}))
    empty.with_suffix(".zip.manifest.json").write_text(json.dumps({
        "url": "x", "sha256": hashlib.sha256(empty.read_bytes()).hexdigest(),
        "bytes": empty.stat().st_size, "downloaded_at": "2026-08-28T00:00:00+00:00"}))
    with pytest.raises(UniverseError, match="no company"):
        build(Mirror(path=empty), store, "u", limit=5)


# --- the load is batched ---------------------------------------------------

def test_the_whole_universe_loads_as_one_version(mirror, store):
    """`load` scans the dataset to detect restatements, so calling it per
    company makes the build quadratic — 600 companies did not finish. The fix
    belongs to the pattern, not to one function."""
    report = build(mirror, store, "u", limit=10)
    assert len(report.versions) == 1
    assert len(store.versions("u")) == 1


def test_batching_still_detects_a_restatement(mirror, store):
    """A bigger batch must detect strictly more, not less: within-batch
    detection was already in place."""
    build(mirror, store, "u", limit=10)
    assert store.restatements("u"), "CIK 200 restated 2000 -> 2400"


# --- the measurement -------------------------------------------------------

def test_rank_churn_compares_as_reported_against_hindsight(mirror, store):
    report = build(mirror, store, "u", limit=10)
    churn = rank_churn(store, "u", report.entities,
                       knowledge_date="2017-01-01", buckets=3)
    assert churn["companies"] == 3
    assert churn["restated"] == 1, "only CIK 200 was revised"
    assert churn["restated_share"] == pytest.approx(1 / 3)
    assert -1.0 <= churn["spearman"] <= 1.0


def test_a_revision_too_small_to_reorder_leaves_the_ranking_alone(mirror, store):
    """The finding this measurement exists to produce. 2000 -> 2400 does not
    overtake 3000, so the ranking is unchanged even though a third of the
    universe was restated."""
    report = build(mirror, store, "u", limit=10)
    churn = rank_churn(store, "u", report.entities,
                       knowledge_date="2017-01-01", buckets=3)
    assert churn["spearman"] == pytest.approx(1.0)
    assert churn["changed_bucket"] == 0


def test_a_revision_large_enough_to_reorder_shows_up(tmp_path, store):
    """And the control: a revision that DOES overtake a neighbour moves ranks."""
    import hashlib

    path = tmp_path / "big.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("CIK0000000100.json",
                   _company(100, [("2014-12-31", "2015-03-01", 1_000.0)]))
        z.writestr("CIK0000000200.json",
                   _company(200, [("2014-12-31", "2015-03-01", 2_000.0),
                                  ("2014-12-31", "2016-03-01", 9_000.0)]))
        z.writestr("CIK0000000300.json",
                   _company(300, [("2014-12-31", "2015-03-01", 3_000.0)]))
    path.with_suffix(".zip.manifest.json").write_text(json.dumps({
        "url": "x", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size, "downloaded_at": "2026-08-28T00:00:00+00:00"}))

    report = build(Mirror(path=path), store, "u", limit=10)
    churn = rank_churn(store, "u", report.entities,
                       knowledge_date="2017-01-01", buckets=3)
    assert churn["changed_bucket"] > 0
    assert churn["spearman"] < 1.0


def test_too_few_companies_for_the_buckets_is_refused(mirror, store):
    report = build(mirror, store, "u", limit=10)
    with pytest.raises(UniverseError, match="too few to form"):
        rank_churn(store, "u", report.entities, knowledge_date="2017-01-01",
                   buckets=50)


def test_fewer_than_two_buckets_is_refused(mirror, store):
    report = build(mirror, store, "u", limit=10)
    with pytest.raises(UniverseError, match="buckets must be at least 2"):
        rank_churn(store, "u", report.entities, knowledge_date="2017-01-01",
                   buckets=1)
