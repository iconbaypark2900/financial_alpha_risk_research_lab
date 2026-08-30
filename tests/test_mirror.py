"""The bulk mirror: making the input a versioned artefact rather than a URL.

FR-23 requires a past run to be re-executable and produce identical results. A
run whose data came from a live endpoint is not, and the record cannot say
otherwise — the endpoint can restate, rate-limit or vanish, and the seeds would
still restore and the code SHA still match while the answer changed.

These tests use a small archive built in the fixture. The mechanism has to be
correct independently of the 1.4 GB file it is meant for, and a suite that
depends on downloading one is a suite nobody runs.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from src.research_integrity.mirror import Mirror, MirrorError

AAPL = json.dumps({"cik": 320193, "units": {"USD": [
    {"end": "2009-09-26", "val": 27832000000, "form": "10-K",
     "filed": "2009-10-27", "accn": "a"}]}})
BBBY = json.dumps({"cik": 886158, "units": {"USD": [
    {"end": "2023-02-25", "val": -1000000, "form": "10-K",
     "filed": "2023-04-26", "accn": "b"}]}})


@pytest.fixture()
def archive(tmp_path: Path) -> Path:
    path = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(path, "w") as z:
        # The non-company entry goes FIRST. Where it sits is not ours to choose
        # in a real archive, and a fixture that buries it at the end cannot tell
        # a limit that counts companies apart from one that counts entries.
        z.writestr("README.txt", "not a company")
        z.writestr("CIK0000320193.json", AAPL)
        z.writestr("CIK0000886158.json", BBBY)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".zip.manifest.json").write_text(json.dumps({
        "url": "https://example.invalid/companyfacts.zip",
        "sha256": digest, "bytes": path.stat().st_size,
        "downloaded_at": "2026-08-28T00:00:00+00:00"}), encoding="utf-8")
    return path


@pytest.fixture()
def mirror(archive: Path) -> Mirror:
    return Mirror(path=archive)


# --- identity: the point of the whole thing --------------------------------

def test_the_digest_identifies_the_archive(mirror, archive):
    assert mirror.digest() == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert mirror.verify() is True


def test_a_changed_archive_stops_verifying(mirror, archive):
    """The property a URL cannot offer. If the bytes move, the run that named
    this version was reading something else."""
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr("CIK0000000001.json", "{}")
    assert mirror.verify() is False


def test_the_version_id_is_what_a_run_record_should_name(mirror):
    """FR-06 asks a backtest to record the exact version it used. A URL is not
    a version; a digest is."""
    version = mirror.version_id()
    assert version.startswith("companyfacts.zip@")
    assert len(version.split("@")[1]) == 16
    assert mirror.manifest()["sha256"].startswith(version.split("@")[1])


def test_an_archive_without_a_manifest_cannot_be_identified(tmp_path):
    """A file is not a version."""
    lonely = tmp_path / "x.zip"
    with zipfile.ZipFile(lonely, "w") as z:
        z.writestr("a.json", "{}")
    with pytest.raises(MirrorError, match="not a version"):
        Mirror(path=lonely).manifest()


# --- reading, offline ------------------------------------------------------

def test_entries_are_listed_and_read_without_a_network(mirror):
    assert sorted(mirror.entries("CIK")) == [
        "CIK0000320193.json", "CIK0000886158.json"]
    assert json.loads(mirror.read("CIK0000320193.json"))["cik"] == 320193


def test_a_cik_is_addressed_the_way_edgar_names_it(mirror):
    assert json.loads(mirror.read_cik(320193))["cik"] == 320193
    assert json.loads(mirror.read_cik(886158))["cik"] == 886158


def test_a_missing_entry_says_which_one(mirror):
    with pytest.raises(MirrorError, match="CIK0000000042.json"):
        mirror.read_cik(42)


def test_iteration_skips_non_company_entries(mirror):
    ciks = dict(mirror.iter_ciks())
    assert set(ciks) == {320193, 886158}, "README.txt must not be treated as a company"


def test_a_limit_counts_companies_not_archive_entries(mirror):
    """`limit=1` has to deliver one COMPANY.

    The limit was applied before the CIK filter, so every non-company entry
    inside the window was charged against the caller's quota. This archive opens
    with README.txt, so `iter_ciks(limit=1)` delivered nothing at all.

    What stood here was `len(list(mirror.iter_ciks(limit=1))) <= 1`, which is
    satisfied by yielding nothing: it could not distinguish a limit that was
    honoured from a limit that ate the only company asked for.
    """
    assert [cik for cik, _ in mirror.iter_ciks(limit=1)] == [320193]
    assert [cik for cik, _ in mirror.iter_ciks(limit=2)] == [320193, 886158]
    assert [cik for cik, _ in mirror.iter_ciks(limit=99)] == [320193, 886158]


def test_a_limit_stops_reading_the_archive(mirror, monkeypatch):
    """1.4 GB expands to hundreds of thousands of entries; materialising them is
    how a mirror becomes an out-of-memory error. So the limit has to bound the
    decompression too: filtering the whole namelist and then slicing the result
    would satisfy the counts above while still reading every company on disk."""
    read: list[str] = []
    original = zipfile.ZipFile.read

    def recording(self, name, *args, **kwargs):
        read.append(name if isinstance(name, str) else name.filename)
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "read", recording)
    assert len(list(mirror.iter_ciks(limit=1))) == 1
    assert read == ["CIK0000320193.json"], "entries past the limit were read anyway"


def test_a_limit_below_one_is_refused(mirror):
    """Prefer refusing to delivering nothing quietly. `limit=0` — what an
    arithmetic slip like `wanted - already_have` produces — returned an empty
    iterator indistinguishable from an archive containing no companies."""
    with pytest.raises(MirrorError, match="limit must be at least 1"):
        list(mirror.iter_ciks(limit=0))


def test_an_entry_named_like_a_company_but_not_numbered_is_refused(tmp_path):
    """`CIKindex.json` escaped as a bare `ValueError: invalid literal for int()`
    from inside a generator, taking a whole universe build with it. The limit fix
    makes it more reachable, because a limited walk now continues past the first
    `limit` entries until it has that many companies.

    Skipping it quietly would be worse than refusing. This reader identifies
    companies by their names, so a name it cannot read means the archive is not
    the shape it was told it was."""
    path = tmp_path / "odd.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("CIKindex.json", "{}")
        z.writestr("CIK0000000100.json", "{}")
    with pytest.raises(MirrorError, match="CIK is not a number"):
        list(Mirror(path=path).iter_ciks())


def test_a_corrupt_archive_is_refused(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"this is not a zip file")
    with pytest.raises(MirrorError, match="not a readable archive"):
        Mirror(path=bad).entries()


# --- the parser already written works on mirrored bytes --------------------

def test_the_existing_parser_reads_mirrored_entries_unchanged(mirror):
    """The reason this archive is the right one: its entries are byte-identical
    in FORM to what the API returns, so nothing downstream changes."""
    from src.research_integrity.ingest import concept_facts

    facts = concept_facts(mirror.read_cik(320193), entity_id="AAPL",
                          field="book_equity")
    assert facts[0]["effective_date"] == "2009-09-26"
    assert facts[0]["knowledge_date"] == "2009-10-27"


# --- fetching --------------------------------------------------------------

def test_a_contact_address_is_required(tmp_path):
    with pytest.raises(MirrorError, match="condition of use"):
        Mirror.fetch("https://example.invalid/x.zip", tmp_path / "x.zip",
                     contact="")


def test_fetch_leaves_a_verified_archive_alone(mirror, archive, monkeypatch):
    """Re-downloading 1.4 GB to obtain the same bytes is not verification."""
    def explode(*args, **kwargs):
        raise AssertionError("fetch tried to download an already-valid mirror")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    again = Mirror.fetch("https://example.invalid/companyfacts.zip", archive,
                         contact="t@t")
    assert again.path == archive
