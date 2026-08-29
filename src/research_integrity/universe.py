"""Building a multi-company universe from the bulk mirror — PRD 04 §5.1.

SELECTION IS WHERE SURVIVORSHIP GETS IN

The obvious way to pick a universe from 20,281 companies is to take the ones
with the longest filing history, or the most complete data, or the largest
balance sheets. Every one of those conditions on survival: a company that went
bankrupt in 2015 has a short history, incomplete data and a small final balance
sheet precisely BECAUSE it died. Selecting that way rebuilds the bias the mirror
was chosen to avoid, inside the function whose job is avoiding it.

So `build` selects by CIK order and by nothing else. CIK is assigned at
registration and has no relationship to outcome, which makes it arbitrary in the
one way that matters. Companies with no usable data are skipped AFTER selection
and counted, so the skip rate is visible rather than silently shaping the set.

WHAT A UNIVERSE HERE IS AND IS NOT

It is fundamentals with real filing dates for companies including ones that no
longer trade. It is not a return series: EDGAR publishes no prices, so nothing
here supports a backtest. What it supports is the question fundamentals alone
can answer — how much a cross-sectional ranking moves when you use figures
nobody had at the time.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Iterator, Sequence

DEFAULT_TAGS = {
    "book_equity": ("StockholdersEquity", "us-gaap", "USD"),
    "assets": ("Assets", "us-gaap", "USD"),
}


class UniverseError(RuntimeError):
    """A universe could not be built."""


@dataclass
class BuildReport:
    """What the build did, including what it left out.

    The skipped counts are not diagnostics. A universe that quietly dropped a
    third of its candidates is a different universe from the one requested, and
    the only way to know is for the function to say so.
    """
    dataset_id: str
    mirror_version: str
    considered: int = 0
    loaded: int = 0
    skipped_no_data: int = 0
    skipped_error: int = 0
    facts: int = 0
    entities: list[str] = dataclass_field(default_factory=list)
    versions: list[str] = dataclass_field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "mirror_version": self.mirror_version,
            "considered": self.considered,
            "loaded": self.loaded,
            "skipped_no_data": self.skipped_no_data,
            "skipped_error": self.skipped_error,
            "facts": self.facts,
            "entities": list(self.entities),
            "skip_rate": (self.skipped_no_data + self.skipped_error)
                         / self.considered if self.considered else 0.0,
        }


def candidates(mirror: Any, limit: int | None = None) -> Iterator[tuple[int, str]]:
    """Companies in CIK order — arbitrary with respect to outcome.

    Deliberately not sorted by size, history length or data completeness. Each
    of those correlates with having survived.
    """
    yield from mirror.iter_ciks(limit=limit)


def build(mirror: Any, store: Any, dataset_id: str, *,
          limit: int = 500,
          tags: dict[str, tuple[str, str, str]] | None = None,
          forms: Sequence[str] = ("10-K",)) -> BuildReport:
    """Load fundamentals for `limit` companies from `mirror` into `store`.

    Returns a report including how many candidates were skipped and why, because
    a build that silently dropped half of them produced a different universe
    from the one asked for.
    """
    from .ingest import IngestError, concept_facts, load

    tags = tags or DEFAULT_TAGS
    if limit < 1:
        raise UniverseError(f"limit must be at least 1, got {limit}")

    report = BuildReport(dataset_id=dataset_id,
                         mirror_version=mirror.version_id())
    collected: list[dict[str, Any]] = []

    for cik, payload in candidates(mirror, limit=limit):
        report.considered += 1
        entity = f"CIK{cik:010d}"
        facts: list[dict[str, Any]] = []
        for field_name, (tag, taxonomy, unit) in tags.items():
            try:
                facts.extend(concept_facts(
                    payload, entity_id=entity, field=field_name, tag=tag,
                    taxonomy=taxonomy, unit=unit, forms=forms))
            except IngestError:
                continue                      # this company did not file that tag
            except (ValueError, TypeError):
                report.skipped_error += 1
                break
        if not facts:
            report.skipped_no_data += 1
            continue

        collected.extend(facts)
        report.entities.append(entity)
        report.loaded += 1
        report.facts += len(facts)

    # ONE load for the whole universe, not one per company. `load` scans the
    # dataset to detect restatements, so calling it per company makes the build
    # quadratic — 600 companies meant 600 increasingly expensive scans, and it
    # did not finish. Exactly the defect fixed in ingest two commits ago,
    # reappearing one level up because the fix was applied to the function
    # rather than to the pattern.
    #
    # Correctness is unaffected: restatement detection already runs within a
    # batch as well as against the store, so a bigger batch detects strictly
    # more, not less.
    if collected:
        report.versions.append(load(store, dataset_id, collected))

    if not report.loaded:
        raise UniverseError(
            f"no company among the first {report.considered} candidates filed "
            f"any of {sorted(tags)} in forms {list(forms)}")
    return report


def rank_churn(store: Any, dataset_id: str, entities: Sequence[str], *,
               field: str = "book_equity", knowledge_date: str,
               buckets: int = 10) -> dict[str, Any]:
    """How much a cross-sectional ranking moves when you use figures nobody had.

    Ranks the universe on the latest period known at `knowledge_date`, twice:
    as-first-reported, and with every later restatement applied. Reports the
    rank correlation and how many names change bucket.

    This is the question fundamentals alone can answer without prices, and it is
    the one FR-02 is really about. "Use as-reported data" is advice; "17% of the
    universe changes decile if you do not" is a reason.
    """
    import numpy as np

    if buckets < 2:
        raise UniverseError(f"buckets must be at least 2, got {buckets}")

    honest: dict[str, float] = {}
    hindsight: dict[str, float] = {}
    for entity in entities:
        dates, values = store.series(dataset_id, entity, field,
                                     knowledge_date=knowledge_date)
        if not dates:
            continue
        period = dates[-1]
        honest[entity] = values[-1]
        latest = store.latest_including_restatements(
            dataset_id, entity, field, period, acknowledge_contamination=True)
        hindsight[entity] = float(latest["value"])

    shared = sorted(set(honest) & set(hindsight))
    if len(shared) < buckets:
        raise UniverseError(
            f"only {len(shared)} companies have data as of {knowledge_date}; "
            f"too few to form {buckets} buckets")

    a = np.array([honest[e] for e in shared])
    b = np.array([hindsight[e] for e in shared])
    rank_a = np.argsort(np.argsort(a))
    rank_b = np.argsort(np.argsort(b))

    n = len(shared)
    bucket_a = (rank_a * buckets) // n
    bucket_b = (rank_b * buckets) // n
    moved = int(np.sum(bucket_a != bucket_b))

    # Spearman without scipy: Pearson on the ranks.
    ra = rank_a - rank_a.mean()
    rb = rank_b - rank_b.mean()
    denominator = float(np.sqrt((ra ** 2).sum() * (rb ** 2).sum()))
    spearman = float((ra * rb).sum() / denominator) if denominator else 1.0

    differing = int(np.sum(a != b))
    return {
        "knowledge_date": knowledge_date,
        "companies": n,
        "restated": differing,
        "restated_share": differing / n,
        "spearman": spearman,
        "buckets": buckets,
        "changed_bucket": moved,
        "changed_bucket_share": moved / n,
    }
