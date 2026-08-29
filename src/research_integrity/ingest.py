"""Real market data into the point-in-time store — PRD 04 §5.1.

WHY FRED AND ALFRED

Every component in this package had only ever seen `standard_t` noise or
hand-built fixtures. The store had a schema and no facts, the factor library
computed over arrays nobody had filled, and the engine backtested synthetic
bars. Nothing had been exercised as a system.

The source has to satisfy one hard constraint the obvious ones do not: FR-01
needs data with a real KNOWLEDGE date, distinct from the date the fact refers
to. A price scraper gives you today's view of history and nothing else — you
cannot ask it what was on the wire in February, so as-first-reported is
unavailable and FR-02 can only ever be simulated.

  FRED    daily index closes. A close is known at the close, so effective and
          knowledge dates coincide, honestly rather than by assumption.

  ALFRED  the same series BY VINTAGE — what the number looked like on a given
          date. Macro series are revised heavily and published with real lags,
          so a vintage query returns genuinely as-first-reported values with
          the actual delay. This is the point-in-time semantics FR-01 and FR-02
          describe, from a source rather than from a fixture.

Neither needs a key, both are plain CSV over HTTPS, and both come from the
Federal Reserve Bank of St. Louis rather than a scraper that breaks quarterly.

WHAT THIS DOES NOT SOLVE

FR-03 (delisted securities) is untouched, and index levels do not help: an index
has its constituent changes baked in, so a backtest on SP500 is a backtest on a
survivorship-adjusted composite, not on a survivorship-free universe. FR-04
(index membership with effective dates) is likewise absent — this loads the
index's LEVEL, not its members. Anyone reaching for a cross-section still needs
vendor data nobody here has.

Said plainly because the temptation is to treat "we have real data now" as
having closed those requirements. It has not. `docs/REQUIREMENTS.md` still marks
them not implemented, and this module is why that stays true.
"""
from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any, Iterable, Sequence

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
EDGAR_CONCEPT = ("https://data.sec.gov/api/xbrl/companyconcept/"
                 "CIK{cik:010d}/us-gaap/{tag}.json")
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ALFRED_CSV = ("https://alfred.stlouisfed.org/graph/alfredgraph.csv"
              "?id={series_id}&vintage_date={vintage_date}")

# FRED writes a lone period where an observation does not exist.
MISSING = "."


class IngestError(RuntimeError):
    """Data could not be fetched or parsed into facts."""


def fetch(url: str, *, timeout: float = 60.0) -> str:
    """GET a CSV. Network access, and the only function here that needs it.

    Kept separate from parsing on purpose: the parsers below are pure and are
    tested against captured real responses, so the suite exercises the real data
    SHAPE without the network — which would otherwise make CI fail for reasons
    that have nothing to do with this repository.
    """
    # `Accept-Encoding: identity` matters: urllib does not transparently decode
    # a gzipped body, and a project-specific User-Agent had the request stall
    # rather than fail — which looks like an outage and is a header.
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; research-lab/0.1)",
        "Accept": "text/csv,*/*",
        "Accept-Encoding": "identity",
        "Connection": "close",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise IngestError(f"could not fetch {url}: {exc}") from exc


def _rows(csv_text: str) -> list[tuple[str, str]]:
    lines = [line.strip() for line in csv_text.splitlines() if line.strip()]
    if not lines:
        raise IngestError("empty CSV")
    header = lines[0].split(",")
    if len(header) < 2 or not header[0].lower().startswith("observation"):
        raise IngestError(
            f"unexpected CSV header {lines[0]!r}; expected an observation_date "
            "column followed by the series")
    out = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        out.append((parts[0].strip(), parts[1].strip()))
    if not out:
        raise IngestError("CSV contained a header and no observations")
    return out


def price_facts(csv_text: str, *, entity_id: str, field: str = "close",
                source: str = "FRED") -> list[dict[str, Any]]:
    """Daily closes as facts, with knowledge date equal to effective date.

    That equality is a claim, not a convenience: a closing level is known at the
    close. It would be wrong for a fundamental, which is why `vintage_facts`
    exists separately rather than this taking a lag argument nobody would set.

    Rows marked missing are DROPPED rather than carried forward. A holiday is an
    absence, and filling it invents a price that was never quoted.
    """
    facts = []
    for observation_date, raw in _rows(csv_text):
        if raw == MISSING or raw == "":
            continue
        try:
            value = float(raw)
        except ValueError as exc:
            raise IngestError(
                f"{entity_id} {observation_date}: {raw!r} is not a number") from exc
        facts.append({
            "entity_id": entity_id, "field": field, "value": value,
            "effective_date": observation_date,
            "knowledge_date": observation_date,
            "source": source,
        })
    if not facts:
        raise IngestError(f"{entity_id}: every observation was missing")
    return facts


def vintage_facts(csv_text: str, *, entity_id: str, vintage_date: str,
                  field: str = "value",
                  source: str = "ALFRED") -> list[dict[str, Any]]:
    """A vintage series as facts: what was KNOWN on `vintage_date`.

    effective_date is the period the number describes; knowledge_date is the
    vintage. The gap between them is the real publication lag, which is the
    whole reason this is worth loading — a 2024-02-15 vintage of a quarterly
    series genuinely does not contain the quarter that had not been published.

    Loading successive vintages of the same series produces exactly the
    restatement structure FR-02 requires, with real revisions rather than
    invented ones.
    """
    facts = []
    for observation_date, raw in _rows(csv_text):
        if raw == MISSING or raw == "":
            continue
        try:
            value = float(raw)
        except ValueError as exc:
            raise IngestError(
                f"{entity_id} {observation_date}: {raw!r} is not a number") from exc
        if observation_date > vintage_date:
            # A vintage cannot contain observations after the date it was taken.
            continue
        facts.append({
            "entity_id": entity_id, "field": field, "value": value,
            "effective_date": observation_date,
            "knowledge_date": vintage_date,
            "source": f"{source}@{vintage_date}",
        })
    if not facts:
        raise IngestError(f"{entity_id}: vintage {vintage_date} held nothing")
    return facts


def load(store: Any, dataset_id: str, facts: Sequence[dict[str, Any]], *,
         note: str | None = None, description: str | None = None) -> str:
    """Register the dataset if needed and append the facts as a new version.

    Registered `point_in_time=True` because the knowledge dates above are real:
    for prices they are the day the close printed, for vintages the day the
    figure was published. A loader that set this flag on data it had faked would
    be defeating FR-07 at the point of entry.
    """
    store.register_dataset(dataset_id, point_in_time=True,
                           description=description)

    # FR-02 wants restatements kept as SEPARATE records, and `restatements()`
    # finds them by the flag — so loading a later vintage that revises an
    # earlier one has to set it. Nothing else can: the parsers see one CSV at a
    # time and cannot know a period has been reported before. Detected by
    # comparing against the value already on record, which is exactly the
    # question `as_reported` answers.
    # ONE query, not one per fact. This called as_reported() per incoming fact,
    # which is 58,699 round trips for a six-series cross section and never
    # finished. Correct logic, never run at the scale it would actually meet —
    # which is the same way every other defect in this project has arrived.
    known = store.as_reported_index(dataset_id)

    # WITHIN the batch as well as against the store. Comparing only against what
    # is already stored catches a revision that arrives in a LATER load, which is
    # how the FRED/ALFRED vintages arrive — one CSV per vintage. EDGAR does the
    # opposite: a company-concept payload carries every vintage of every period
    # at once, so all of Apple's restatements are inside a single batch and none
    # of them was marked. FR-02 wants restatements kept as separate records, and
    # a record nothing flags as one is not kept as one.
    #
    # Sorted by knowledge date first, so "first reported" means first in time
    # rather than first in whatever order the source happened to emit.
    ordered = sorted(facts, key=lambda f: (str(f["effective_date"]),
                                           str(f["knowledge_date"])))
    marked = []
    for fact in ordered:
        fact = dict(fact)
        key = (fact["entity_id"], fact["field"], str(fact["effective_date"]))
        if "is_restatement" not in fact:
            previous = known.get(key)
            fact["is_restatement"] = bool(
                previous is not None and previous != fact["value"])
        if key not in known:
            known[key] = fact["value"]
        marked.append(fact)

    # Idempotent. Appending identical facts again produces a second version with
    # the same content hash, which was harmless while every store lived in a
    # TemporaryDirectory and is wrong once one persists: a daily run would
    # accumulate sp500@v1..vN of the same data, and two runs over identical
    # facts would record DIFFERENT dataset versions — making FR-06's "record the
    # exact version it used" true in letter and misleading in fact.
    existing = _identical_version(store, dataset_id, marked)
    if existing is not None:
        return existing
    return store.append_facts(dataset_id, marked, note=note)


def _identical_version(store: Any, dataset_id: str,
                       facts: Sequence[dict[str, Any]]) -> str | None:
    """The version id already holding exactly these facts, if there is one.

    Uses the store's own content hash rather than a second implementation of it,
    so the two cannot disagree about what "identical" means.
    """
    import hashlib
    import json

    normalised = [store._normalise(dataset_id, dict(f)) for f in facts]
    payload = json.dumps(
        [[r["entity_id"], r["field"], r["value"],
          str(r["effective_date"]), str(r["knowledge_date"])] for r in normalised],
        sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    for version in store.versions(dataset_id):
        if version["content_hash"] == digest:
            return version["version_id"]
    return None


def fetch_fred(series_id: str, **kwargs) -> str:
    return fetch(FRED_CSV.format(series_id=series_id), **kwargs)


def fetch_alfred(series_id: str, vintage_date: str, **kwargs) -> str:
    return fetch(ALFRED_CSV.format(series_id=series_id,
                                   vintage_date=vintage_date), **kwargs)


# --- SEC EDGAR: the only free source with a real knowledge date and the dead --

def fetch_edgar(url: str, *, contact: str, timeout: float = 60.0) -> str:
    """GET from SEC EDGAR. `contact` is required and goes in the User-Agent.

    The SEC asks for a contact address in the User-Agent and rate-limits to
    10 requests a second. Both are conditions of use rather than suggestions,
    so `contact` has no default: a caller who has not supplied one has not
    agreed to them.
    """
    if not contact or "@" not in contact:
        raise IngestError(
            "SEC EDGAR requires a contact email in the User-Agent — it is a "
            "condition of use, not a formality. Pass contact='you@example.com'.")
    request = urllib.request.Request(url, headers={
        "User-Agent": f"financial-alpha-risk-research-lab {contact}",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise IngestError(f"could not fetch {url}: {exc}") from exc


def fetch_edgar_concept(cik: int, tag: str, **kwargs) -> str:
    return fetch_edgar(EDGAR_CONCEPT.format(cik=int(cik), tag=tag), **kwargs)


def fetch_edgar_submissions(cik: int, **kwargs) -> str:
    return fetch_edgar(EDGAR_SUBMISSIONS.format(cik=int(cik)), **kwargs)


def concept_facts(payload: str, *, entity_id: str, field: str,
                  unit: str = "USD",
                  forms: Sequence[str] = ("10-K", "10-Q")) -> list[dict[str, Any]]:
    """XBRL company-concept records as facts, as first reported.

    This is the source FR-01 and FR-02 were written for, and the reason it beats
    every price feed: each record carries BOTH dates.

        end    the period the figure describes  -> effective_date
        filed  the day the filing was accepted  -> knowledge_date

    A period reported in more than one filing is a restatement, with the real
    revision and the real lag. Apple's FY2009 stockholders' equity was first
    reported as 27,832,000,000 on 2009-10-27 and restated to 31,640,000,000 on
    2010-10-27 — a 13.7% revision. A book-to-market computed today for early
    2010 uses a number nobody had, and it is not a rounding error.

    Duplicate (end, filed, value) rows are collapsed: EDGAR repeats a figure
    across the comparative columns of later filings, and each repetition is the
    same assertion made on the same day, not new information.
    """
    import json

    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise IngestError(f"{entity_id}: not valid JSON from EDGAR") from exc

    units = data.get("units", {})
    if unit not in units:
        raise IngestError(
            f"{entity_id}: no {unit} records; available units "
            f"{sorted(units) or 'none'}")

    seen: set[tuple] = set()
    facts = []
    for record in units[unit]:
        if forms and record.get("form") not in forms:
            continue
        end, filed, value = record.get("end"), record.get("filed"), record.get("val")
        if end is None or filed is None or value is None:
            continue
        key = (end, filed, value)
        if key in seen:
            continue
        seen.add(key)
        facts.append({
            "entity_id": entity_id, "field": field, "value": float(value),
            "effective_date": end, "knowledge_date": filed,
            "source": f"EDGAR/{record.get('form')}/{record.get('accn')}",
        })
    if not facts:
        raise IngestError(f"{entity_id}: no {unit} records in forms {list(forms)}")
    return facts


def listing_status(payload: str) -> dict[str, Any]:
    """Whether a company still trades, from its EDGAR submissions record.

    FR-03 asks for delisted securities to be retained. EDGAR retains them: a
    company that has left the exchanges keeps its CIK and its filing history and
    comes back with EMPTY `tickers` and `exchanges`. Bed Bath & Beyond
    (CIK 886158) reads that way, renamed to its post-bankruptcy shell.

    This is a signal, not a registry. A company can be absent from `exchanges`
    for reasons other than delisting, and EDGAR publishes no delisting DATE — so
    `last_filing` is the best available proxy for when it stopped being a going
    concern. Said plainly because treating this as an authoritative survivorship
    record would be exactly the overclaim this project keeps catching.
    """
    import json

    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise IngestError("not valid JSON from EDGAR") from exc

    recent = data.get("filings", {}).get("recent", {})
    dates = recent.get("filingDate", [])
    return {
        "cik": data.get("cik"),
        "name": data.get("name"),
        "tickers": list(data.get("tickers") or []),
        "exchanges": list(data.get("exchanges") or []),
        "still_listed": bool(data.get("tickers") and data.get("exchanges")),
        "last_filing": max(dates) if dates else None,
        "sic_description": data.get("sicDescription"),
    }
