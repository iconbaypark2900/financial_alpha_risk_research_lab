"""A local, content-addressed mirror of a bulk data archive — FR-22, FR-23.

WHY A MIRROR RATHER THAN AN API

FR-23 requires any past run to be re-executable and produce identical results.
A run whose data came from a live HTTP endpoint is not re-executable, and the
run record cannot say otherwise: the endpoint can restate a figure, change a
schema, rate-limit, or disappear, and nothing in the record would show it. The
seeds were restored, the code SHA matched, and the answer changed anyway.

`real_data_pipeline.py` already cached its CSVs into data/ as a side effect of
not wanting to re-download. That worked by luck. It recorded no hash, so two
runs could read different bytes from the same path and both claim the same
dataset version.

A mirror makes the data a VERSIONED ARTEFACT. The archive is downloaded once,
hashed, and read offline thereafter. The digest is what a run record names, so
"the exact version it used" (FR-06) means a specific 1.4 GB file whose contents
can be checked rather than a URL that used to return something.

IT IS ALSO THE LICENCE-CLEAN OPTION

SEC EDGAR is a US Government work and therefore public domain under 17 U.S.C.
§105 — the most permissively licensed data of its kind. Mirroring it removes the
remaining third-party dependency entirely: after the download there is no API,
no rate limit, and no User-Agent condition, because there is no request.

WHAT THIS DOES NOT DO

It does not make the DATA correct, and it does not detect that the SEC has
revised an archive. Two mirrors taken a month apart legitimately differ, and the
digest tells you they differ without telling you which is right. That is the
correct division of labour: the mirror makes the input identifiable, and the
point-in-time store is what makes a revision visible as a restatement.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

CHUNK = 1 << 20
MANIFEST_SUFFIX = ".manifest.json"

COMPANY_FACTS = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SUBMISSIONS = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"


class MirrorError(RuntimeError):
    """A mirror could not be fetched, read, or verified."""


@dataclass(frozen=True)
class Mirror:
    """A downloaded archive plus the manifest that identifies it."""
    path: Path

    # ---- acquiring ---------------------------------------------------------
    @classmethod
    def fetch(cls, url: str, dest: str | Path, *, contact: str,
              timeout: float = 600.0, force: bool = False) -> "Mirror":
        """Download `url` to `dest` and write a manifest beside it.

        Streamed rather than read into memory: companyfacts.zip is 1.4 GB, and
        `response.read()` on that is a way to discover how much RAM the box has.

        Idempotent. An existing archive whose digest matches its manifest is
        left alone, because re-downloading 1.4 GB to get the same bytes is not
        verification, it is bandwidth.
        """
        if not contact or "@" not in contact:
            raise MirrorError(
                "SEC EDGAR requires a contact email in the User-Agent — a "
                "condition of use, not a formality. Pass contact='you@host'.")

        dest = Path(dest)
        mirror = cls(path=dest)
        if dest.exists() and not force:
            try:
                if mirror.verify():
                    return mirror
            except MirrorError:
                pass                       # no manifest, or it disagrees: refetch

        dest.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={
            "User-Agent": f"financial-alpha-risk-research-lab {contact}",
            "Accept-Encoding": "identity",
        })
        digest = hashlib.sha256()
        written = 0
        temporary = dest.with_suffix(dest.suffix + ".partial")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response, \
                    temporary.open("wb") as handle:
                while True:
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
                    digest.update(block)
                    written += len(block)
        # Broad because it cleans up and re-raises rather than continuing: no
        # partial file may outlive a failed download, whatever killed it. It
        # cannot be narrowed to OSError either — `http.client.IncompleteRead`,
        # the truncated stream this cleanup exists for, is an HTTPException —
        # and a narrower clause would let a Mirror method raise something the
        # caller was never told to catch. `from exc` keeps the cause.
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise MirrorError(f"could not fetch {url}: {exc}") from exc

        if written == 0:
            temporary.unlink(missing_ok=True)
            raise MirrorError(f"{url} returned no bytes")
        temporary.replace(dest)

        dest.with_suffix(dest.suffix + MANIFEST_SUFFIX).write_text(json.dumps({
            "url": url,
            "sha256": digest.hexdigest(),
            "bytes": written,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2), encoding="utf-8")
        return mirror

    # ---- identity ----------------------------------------------------------
    @property
    def manifest_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + MANIFEST_SUFFIX)

    def manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            raise MirrorError(
                f"{self.path} has no manifest, so it cannot be identified. An "
                "archive without a recorded digest is a file, not a version.")
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def digest(self) -> str:
        """The sha256 of the archive as it is on disk, computed now."""
        if not self.path.exists():
            raise MirrorError(f"{self.path} does not exist")
        h = hashlib.sha256()
        with self.path.open("rb") as handle:
            for block in iter(lambda: handle.read(CHUNK), b""):
                h.update(block)
        return h.hexdigest()

    def verify(self) -> bool:
        """Whether the bytes on disk still match the recorded manifest."""
        return self.digest() == self.manifest()["sha256"]

    def version_id(self) -> str:
        """What a run record should name (FR-06): the first 16 hex of the digest.

        Short enough to read, long enough that two archives colliding is not the
        thing to worry about.
        """
        return f"{self.path.name}@{self.manifest()['sha256'][:16]}"

    # ---- reading, offline --------------------------------------------------
    def _zip(self) -> zipfile.ZipFile:
        try:
            return zipfile.ZipFile(self.path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise MirrorError(f"{self.path} is not a readable archive: {exc}") from exc

    def entries(self, prefix: str = "") -> list[str]:
        with self._zip() as archive:
            return [n for n in archive.namelist() if n.startswith(prefix)]

    def count(self) -> int:
        with self._zip() as archive:
            return len(archive.namelist())

    def read(self, name: str) -> str:
        """One entry, as text. No network."""
        with self._zip() as archive:
            try:
                return archive.read(name).decode("utf-8")
            except KeyError as exc:
                raise MirrorError(f"{name!r} is not in {self.path.name}") from exc

    def read_cik(self, cik: int) -> str:
        """The company-facts entry for a CIK, named as EDGAR names it."""
        return self.read(f"CIK{int(cik):010d}.json")

    def iter_ciks(self, limit: int | None = None) -> Iterator[tuple[int, str]]:
        """The first `limit` companies in the archive, streamed not materialised.

        1.4 GB expands to hundreds of thousands of entries; building a list of
        them is how a mirror becomes an out-of-memory error. So the limit stops
        the walk rather than trimming a finished list, and nothing past the last
        company yielded is decompressed.

        `limit` counts COMPANIES YIELDED. It used to count entries EXAMINED: the
        return fired before the CIK filter, so a non-company entry inside the
        window was charged against the caller's quota and `iter_ciks(limit=1)`
        on an archive that opens with a README delivered nothing. An archive is
        not obliged to hold only CIK*.json — the fixtures here model one that
        does not — and the caller had no way to see the shortfall, because
        asking for 500 and receiving 480 looks exactly like an archive with 480
        companies in it.

        A limited walk now continues past the first `limit` entries until it has
        `limit` companies, so it reaches archive territory the old return never
        did. An entry named like a company whose CIK is not a number is refused
        there rather than skipped: this reader identifies companies by name, so
        a name it cannot read means the archive is not the shape it was told it
        was, and guessing is how a universe silently changes size. It used to
        escape as a bare ValueError from inside a generator.
        """
        if limit is not None and limit < 1:
            raise MirrorError(
                f"limit must be at least 1, got {limit}. A limit below one asks "
                "for no companies, which is never what a caller means; it is "
                "what arithmetic like `wanted - already_have` produces. Pass "
                "limit=None for every company in the archive.")
        yielded = 0
        with self._zip() as archive:
            for name in archive.namelist():
                if not name.startswith("CIK") or not name.endswith(".json"):
                    continue
                digits = name[3:-5]
                if not digits.isdecimal():
                    raise MirrorError(
                        f"{name!r} in {self.path.name} is named like a company "
                        "entry but its CIK is not a number. This archive is not "
                        "the shape this reader expects, and guessing which "
                        "entries are companies is how a universe silently "
                        "changes size.")
                yield int(digits), archive.read(name).decode("utf-8")
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
