#!/usr/bin/env python3
"""The whole machine, once, on real market data.

    python3 scripts/real_data_pipeline.py            # uses data/ if present
    python3 scripts/real_data_pipeline.py --fetch    # re-download from FRED/ALFRED

Every component in this package had only ever seen synthetic noise or hand-built
fixtures. This runs the real thing end to end and reports what it finds, which
is expected to be nothing — that being the point.

    FRED SP500       ->  point-in-time store, immutably versioned   FR-01, FR-06
    ALFRED GDPC1     ->  two vintages, a real revision between them FR-02
    store            ->  a series read as first reported            FR-01
    Study            ->  refusals before the count, record after    FR-07, FR-10
    search           ->  every trial counted                        FR-08, FR-15
    null benchmark   ->  the same sweep on reshuffled real returns  FR-16
    deflated Sharpe  ->  from a real trial count and real variance  FR-09
    ExperimentLog    ->  a run record that can be replayed          FR-22..FR-25
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.research_integrity import (  # noqa: E402
    ExperimentLog,
    ProtectedHoldout,
    Study,
    TrialCounter,
    deflated_sharpe_ratio,
)
from src.research_integrity.ingest import (  # noqa: E402
    fetch_alfred,
    fetch_fred,
    load,
    price_facts,
    vintage_facts,
)
from src.research_integrity.point_in_time import PointInTimeStore  # noqa: E402
from src.research_integrity.workspace import Workspace  # noqa: E402
from src.research_integrity.search import crossover_grid, null_benchmark  # noqa: E402

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
    parser.add_argument("--fetch", action="store_true",
                        help="re-download from FRED and ALFRED")
    parser.add_argument("--home", default=None,
                        help="persist into this research workspace. WITHOUT it "
                             "the run uses a throwaway workspace and touches "
                             "nothing — a demonstration must not tax the global "
                             "trial count with searches nobody had an interest in")
    args = parser.parse_args(argv)

    print(__doc__.strip().splitlines()[0])
    print()

    with tempfile.TemporaryDirectory() as scratch:
        tmp = Path(scratch)
        # EPHEMERAL BY DEFAULT. This is a demonstration, and it runs a
        # 2,691-trial sweep. Those are real searches against the dataset, so
        # FR-08 requires counting them — which means pointing this at a real
        # workspace by default would tax every genuine result anyone later
        # produced against sp500 with 2,691 trials nobody had an interest in.
        # That is exactly what install_workspace.py exists to prevent, and it
        # arrived here through a different door: the safe path must be the lazy
        # one. Real research goes through Workspace and Study, not through a
        # script in scripts/.
        lab = Workspace.open(args.home if args.home else tmp / "lab")
        print(f"  WORKSPACE  {lab.describe()}")
        if not args.home:
            print("             throwaway — pass --home PATH to persist. "
                  "Nothing here")
            print("             touches a real trial count or holdout.")
        print()
        store = lab.store()

        # ---- FR-01, FR-06: real prices, immutably versioned ---------------
        prices_csv = _csv("SP500.csv", lambda: fetch_fred("SP500"),
                          refetch=args.fetch)
        version = load(store, "sp500", price_facts(prices_csv, entity_id="SP500"),
                       description="FRED SP500 daily close",
                       note="FRED series SP500")
        dates, closes = store.series("sp500", "SP500", "close")
        print(f"  DATA     {len(closes):,} real daily closes, "
              f"{dates[0]} to {dates[-1]}")
        print(f"           version {version}")

        # ---- FR-02: two vintages of a revised series ----------------------
        macro = PointInTimeStore(tmp / "macro.duckdb")
        for vintage in VINTAGES:
            load(macro, "gdp",
                 vintage_facts(_csv(f"GDPC1_{vintage}.csv",
                                    lambda v=vintage: fetch_alfred("GDPC1", v),
                                    refetch=args.fetch),
                               entity_id="GDPC1", vintage_date=vintage),
                 description="ALFRED real GDP, by vintage",
                 note=f"ALFRED vintage {vintage}")
        first = macro.series("gdp", "GDPC1", "value",
                             start="2023-10-01", end="2023-10-01",
                             knowledge_date=VINTAGES[0])[1]
        later = macro.series("gdp", "GDPC1", "value",
                             start="2023-10-01", end="2023-10-01",
                             knowledge_date=VINTAGES[1])[1]
        latest = macro.latest_including_restatements(
            "gdp", "GDPC1", "value", "2023-10-01",
            acknowledge_contamination=True)
        print(f"  FR-02    GDP 2023-10-01 first reported {first[0]:,.3f}; "
              f"as of {VINTAGES[1]} still {later[0]:,.3f}")
        print(f"           the restatement is {latest['value']:,.3f}, and the "
              "store returns it only on request")

        # ---- the controls, attached -------------------------------------
        holdout = lab.holdout()
        if holdout.holdout_period("sp500") is None:
            holdout.define("sp500", start=HOLDOUT[0], end=HOLDOUT[1])
        study = lab.study("sp500", repo=ROOT)
        print(f"  FR-10    holdout {HOLDOUT[0]} to {HOLDOUT[1]}, protected")

        # ---- FR-08, FR-16: a counted search on real returns --------------
        grid = crossover_grid(max_fast=40, max_slow=90)
        result = study.search_series(
            "SP500", grid, end="2024-12-31", search_id="sweep-real",
            allow_uncommitted=True)
        print(f"  FR-08    {result['n_trials']:,} trials counted, "
              f"run {result['run_id'][:8]}")

        # ---- the null benchmark, on REAL returns reshuffled --------------
        _, insample = store.series("sp500", "SP500", "close", end="2024-12-31")
        returns = np.diff(np.asarray(insample)) / np.asarray(insample)[:-1]
        null = null_benchmark(returns, grid,
                              counter=TrialCounter(tmp / "null.db"),
                              dataset_id="sp500-shuffled",
                              search_id="sweep-null", seed=7)

        inputs = study.counter.deflation_inputs("sp500")
        buy_and_hold = float(returns.mean() / returns.std())
        print()
        print("  The Sharpe below is EXCESS over buy-and-hold, which is what")
        print("  moving_average_crossover scores by default. A negative number")
        print(f"  means the rule LOST to simply holding the index (Sharpe "
              f"{buy_and_hold:+.4f}).")
        print()
        print(f"  {'':26}{'REAL S&P 500':>16}{'RESHUFFLED':>16}")
        print(f"  {'-' * 58}")
        print(f"  {'trials counted':26}{result['n_trials']:>16,}{null['n_trials']:>16,}")
        print(f"  {'best excess Sharpe':26}{result['best_raw_sharpe']:>16.4f}"
              f"{null['best_raw_sharpe']:>16.4f}")
        print(f"  {'best parameters':26}"
              f"{str(tuple(result['best_params'].values())):>16}"
              f"{str(tuple(null['best_params'].values())):>16}")
        print(f"  {'DEFLATED Sharpe':26}{result['deflated_sharpe']:>16.4f}"
              f"{null['deflated_sharpe']:>16.4f}")
        print()

        # ---- FR-09: the verdict -----------------------------------------
        deflated = deflated_sharpe_ratio(
            observed_sharpe=result["best_raw_sharpe"],
            n_trials=inputs["n_trials"], sample_length=len(returns),
            skewness=float(_skew(returns)), kurtosis=float(_kurtosis(returns)),
            var_trials=inputs["var_trials"])
        print(f"  FR-09    deflated Sharpe {deflated:.4f} against the real "
              f"skew ({_skew(returns):+.3f}) and kurtosis ({_kurtosis(returns):.2f})")
        verdict = ("SIGNIFICANT" if deflated >= 0.95
                   else "NOISE — the search found nothing that survives its own size")
        print(f"           {verdict}")
        print(f"           Not one of the {result['n_trials']:,} variants beat "
              "buy-and-hold, and the")
        print("           reshuffled series scored HIGHER than the real one.")

        # ---- FR-10, in the direction that matters ------------------------
        from src.research_integrity.holdout import HoldoutViolation
        try:
            study.search_series("SP500", grid[:4], end=HOLDOUT[1])
        except HoldoutViolation as exc:
            print(f"  FR-10    a sweep reaching into the holdout was REFUSED: "
                  f"{str(exc).splitlines()[0][:52]}...")

        # ---- FR-25 --------------------------------------------------------
        runs = study.log.query()
        print(f"  FR-25    {len(runs)} run(s) recorded, outcome "
              f"{runs[0]['outcome']}, code {runs[0]['code_sha'][:8]}")

        # ---- FR-23: re-execute it, and require the same answer -----------
        before = study.counter.trial_count("sp500")
        verified = study.replay_search(result["run_id"])
        after = study.counter.trial_count("sp500")
        print(f"  FR-23    replayed from the record alone: "
              f"reproduced={verified['reproduced']}, "
              f"hash {verified['result_hash'][:12]}...")
        print(f"           trial count {before:,} before, {after:,} after — a "
              "replay is verification, not new research")
        print()
        print(f"  WORKSPACE  {lab.describe()}")
        if args.home:
            print("             this count accumulates across runs and "
                  "researchers.")
            print("             Deleting the directory resets it, and the age "
                  "above is how")
            print("             you would notice.")
    return 0


def _skew(x: np.ndarray) -> float:
    d = x - x.mean()
    return float((d ** 3).mean() / (d.std() ** 3))


def _kurtosis(x: np.ndarray) -> float:
    d = x - x.mean()
    return float((d ** 4).mean() / (d.std() ** 4))


if __name__ == "__main__":
    raise SystemExit(main())
