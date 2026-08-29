#!/usr/bin/env python3
"""Create a persistent research workspace and load data into it — no searching.

    python3 scripts/install_workspace.py                 # the default home
    python3 scripts/install_workspace.py --home /srv/lab
    python3 scripts/install_workspace.py --status        # report, change nothing

WHY THIS IS SEPARATE FROM THE DEMOS

Seeding a fresh installation by running `real_data_pipeline.py` would work and
would be wrong: that script executes a 2,691-trial sweep, and those trials are
real searches against the dataset, so FR-08 requires counting them. Every
genuine result a researcher later produced against sp500 would then be deflated
against 2,691 trials nobody had any interest in — a permanent, invisible tax on
the count, paid for a demonstration.

So installation loads data, registers the dataset and defines the holdout, and
runs no search at all. The trial count of a fresh workspace should be zero
because nothing has been searched, not because nothing persists.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.research_integrity.ingest import (  # noqa: E402
    fetch_alfred,
    fetch_fred,
    load,
    price_facts,
    vintage_facts,
)
from src.research_integrity.workspace import Workspace  # noqa: E402

DATA = ROOT / "data"
VINTAGES = ("2024-02-15", "2024-06-15")
HOLDOUT = ("2025-01-01", "2026-12-31")


def _csv(name: str, fetcher, *, refetch: bool) -> str:
    path = DATA / name
    if refetch or not path.exists():
        DATA.mkdir(exist_ok=True)
        path.write_text(fetcher(), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=None)
    parser.add_argument("--fetch", action="store_true",
                        help="re-download from FRED and ALFRED")
    parser.add_argument("--status", action="store_true",
                        help="report on an existing workspace and exit")
    args = parser.parse_args(argv)

    lab = Workspace.open(args.home)
    if args.status:
        provenance = lab.provenance()
        print(f"  {lab.describe()}")
        for dataset, count in provenance["trials_by_dataset"].items():
            period = lab.holdout().holdout_period(dataset)
            print(f"    {dataset}: {count:,} trials, holdout {period}")
        return 0

    print(f"  workspace {lab.home}")
    store = lab.store()

    version = load(store, "sp500",
                   price_facts(_csv("SP500.csv", lambda: fetch_fred("SP500"),
                                    refetch=args.fetch), entity_id="SP500"),
                   description="FRED SP500 daily close", note="FRED series SP500")
    dates, closes = store.series("sp500", "SP500", "close")
    print(f"    sp500  {len(closes):,} closes {dates[0]}..{dates[-1]}  {version}")

    for vintage in VINTAGES:
        v = load(store, "gdp",
                 vintage_facts(_csv(f"GDPC1_{vintage}.csv",
                                    lambda x=vintage: fetch_alfred("GDPC1", x),
                                    refetch=args.fetch),
                               entity_id="GDPC1", vintage_date=vintage),
                 description="ALFRED real GDP, by vintage",
                 note=f"ALFRED vintage {vintage}")
        print(f"    gdp    vintage {vintage}  {v}")

    holdout = lab.holdout()
    existing = holdout.holdout_period("sp500")
    if existing is None:
        holdout.define("sp500", start=HOLDOUT[0], end=HOLDOUT[1])
        print(f"    holdout defined {HOLDOUT[0]}..{HOLDOUT[1]} — immutable now")
    else:
        print(f"    holdout already defined {existing[0]}..{existing[1]}, left alone")

    print()
    print(f"  {lab.describe()}")
    print("  No search was run, so the trial count is zero because nothing has")
    print("  been searched — not because nothing persists.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
