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
    marked = []
    for fact in facts:
        fact = dict(fact)
        if "is_restatement" not in fact:
            previous = store.as_reported(dataset_id, fact["entity_id"],
                                         fact["field"], fact["effective_date"])
            fact["is_restatement"] = bool(
                previous is not None and previous["value"] != fact["value"])
        marked.append(fact)
    return store.append_facts(dataset_id, marked, note=note)


def fetch_fred(series_id: str, **kwargs) -> str:
    return fetch(FRED_CSV.format(series_id=series_id), **kwargs)


def fetch_alfred(series_id: str, vintage_date: str, **kwargs) -> str:
    return fetch(ALFRED_CSV.format(series_id=series_id,
                                   vintage_date=vintage_date), **kwargs)
