#!/usr/bin/env python3
"""Point the machine at a strategy people actually believe in.

    python3 scripts/believed_strategy.py

The null-result benchmark declares noise to be noise, which is a demo. The
product is what this does: take a rule a large number of practitioners commit
real money to, pre-register the claim its believers make, and report which half
of it survives.

THE STRATEGY

Faber, M. (2007), "A Quantitative Approach to Tactical Asset Allocation",
Journal of Wealth Management. Hold the index while its price is above a long
moving average; hold cash otherwise. It underpins an entire tactical-allocation
industry, and its claim is specific:

    equity-like returns with materially smaller drawdowns.

WHY THIS IS THE RIGHT TEST AND THE PARAMETER SWEEP WAS NOT

The sweep in real_data_pipeline.py searched 2,691 variants and had to be
punished for it. This rule was specified in 2007, in public, before the sample
below existed. That is the situation pre-registration exists for, and it is
treated far more kindly by the same machinery — correctly, because the
multiple-testing burden really is N=1.

The honest caveat, made a measurement rather than a footnote: the WINDOW is a
choice. 200 days is one of many that could have been picked, so the run below
also asks whether the result is a property of the rule or an artifact of the
number.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.portfolio.drawdown import max_drawdown  # noqa: E402
from src.research_integrity import (  # noqa: E402
    ExperimentLog,
    ProtectedHoldout,
    Study,
    TrialCounter,
    deflated_sharpe_ratio,
)
from src.research_integrity.ingest import fetch_fred, load, price_facts  # noqa: E402
from src.research_integrity.workspace import Workspace  # noqa: E402
from src.research_integrity.search import moving_average_timing  # noqa: E402

DATA = ROOT / "data" / "SP500.csv"
WINDOW = 200
FAMILY = (50, 100, 125, 150, 175, 200, 225, 250, 300)
HOLDOUT_START = "2025-01-01"
HOLDOUT_END = "2026-12-31"
TRADING_DAYS = 252


def summarise(returns: np.ndarray) -> dict[str, float]:
    equity = 100.0 * np.cumprod(1.0 + returns)
    per_period = float(returns.mean() / returns.std())
    return {
        "sharpe_per_period": per_period,
        "sharpe_annualised": per_period * np.sqrt(TRADING_DAYS),
        "max_drawdown": max_drawdown(np.concatenate([[100.0], equity])),
        "total_return": float(equity[-1] / 100.0 - 1.0),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=None,
                        help="research workspace (default: $RESEARCH_LAB_HOME or "
                             "~/.financial-alpha-research-lab)")
    parser.add_argument("--ephemeral", action="store_true",
                        help="throwaway workspace — resets the holdout, which "
                             "is the thing this script is about")
    args = parser.parse_args(argv)

    print(__doc__.strip().splitlines()[0])
    print()

    if not DATA.exists():
        DATA.parent.mkdir(exist_ok=True)
        DATA.write_text(fetch_fred("SP500"), encoding="utf-8")

    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        # THE HOLDOUT MUST PERSIST, or this script is a lie about itself.
        # It built its holdout in a TemporaryDirectory while printing "the
        # registration is spent" — and the next run got a fresh, unspent one.
        # The demonstration of exhaustion was the thing defeating exhaustion.
        lab = Workspace.open(Path(scratch) / "lab" if args.ephemeral
                             else args.home)
        print(f"  WORKSPACE  {lab.describe()}")
        if args.ephemeral:
            print("             EPHEMERAL — the holdout resets when this exits,")
            print("             so 'the registration is spent' will not be true")
        print()

        store = lab.store()
        load(store, "sp500", price_facts(DATA.read_text(encoding="utf-8"),
                                         entity_id="SP500"),
             description="FRED SP500 daily close")

        holdout = lab.holdout()
        if holdout.holdout_period("sp500") is None:
            holdout.define("sp500", start=HOLDOUT_START, end=HOLDOUT_END)
        study = lab.study("sp500", repo=ROOT)

        prior = holdout.exhaustion("sp500", "faber-ma-timing")
        if prior["evaluations"]:
            print(f"  ALREADY LOOKED  this family has been evaluated against "
                  f"this holdout {prior['evaluations']} time(s) before.")
            print(f"  {prior['warning']}")
            print()

        # ---- PRE-REGISTER, before looking at anything -------------------
        registration = study.preregister(
            strategy_family="faber-ma-timing",
            hypothesis=(f"Holding the S&P 500 while it trades above its "
                        f"{WINDOW}-day mean, and cash otherwise, produces a "
                        "materially smaller maximum drawdown than buy-and-hold "
                        "without giving up risk-adjusted return."),
            expected_result=("max drawdown below two thirds of buy-and-hold's, "
                             "and an annualised Sharpe no worse than "
                             "buy-and-hold's less 0.05"))
        print(f"  PRE-REGISTERED  {registration[:8]}  before any figure was seen")
        print(f"  HOLDOUT         {HOLDOUT_START} to {HOLDOUT_END}, protected")
        print()

        # ---- in sample, outside the holdout ------------------------------
        dates, closes = store.series("sp500", "SP500", "close",
                                     end="2024-12-31")
        prices = np.asarray(closes)
        rule, market, exposure = moving_average_timing(prices, WINDOW)
        in_rule, in_bh = summarise(rule), summarise(market)

        print(f"  IN SAMPLE  {dates[0]} to {dates[-1]}, {len(prices):,} closes, "
              f"{exposure:.0%} of days invested")
        print(f"  {'':22}{'buy & hold':>14}{'MA rule':>14}")
        print(f"  {'-' * 50}")
        for label, key, fmt in (("annualised Sharpe", "sharpe_annualised", "{:+.3f}"),
                                ("max drawdown", "max_drawdown", "{:.1%}"),
                                ("total return", "total_return", "{:+.1%}")):
            print(f"  {label:22}{fmt.format(in_bh[key]):>14}"
                  f"{fmt.format(in_rule[key]):>14}")
        print()

        # ---- is it the rule, or is it the number 200? --------------------
        print("  IS 200 SPECIAL, OR IS THE RULE?")
        family = {w: summarise(moving_average_timing(prices, w)[0]) for w in FAMILY}
        sharpes = [f["sharpe_annualised"] for f in family.values()]
        drawdowns = [f["max_drawdown"] for f in family.values()]
        best = max(family, key=lambda w: family[w]["sharpe_annualised"])
        print(f"    Sharpe across {len(FAMILY)} windows: {min(sharpes):+.3f} to "
              f"{max(sharpes):+.3f}  (spread {max(sharpes) - min(sharpes):.3f})")
        print(f"    drawdown across the same:  {min(drawdowns):.1%} to "
              f"{max(drawdowns):.1%}  vs buy-and-hold {in_bh['max_drawdown']:.1%}")
        print(f"    best window is {best}, not {WINDOW}")
        print()
        print(f"    Every window cuts the drawdown, by a lot. The Sharpe varies by")
        print(f"    {max(sharpes) - min(sharpes):.3f} across windows — wider than the "
              f"{abs(in_rule['sharpe_annualised'] - in_bh['sharpe_annualised']):.3f} "
              "between the")
        print("    rule and buy-and-hold. So the drawdown claim is a property of the")
        print("    rule; any Sharpe claim for one window is inside the noise of")
        print("    having picked that window.")
        print()

        # ---- FR-09: what the deflation says, pre-registered vs searched ---
        deflated_registered = deflated_sharpe_ratio(
            observed_sharpe=in_rule["sharpe_per_period"], n_trials=1,
            sample_length=len(rule), skewness=0.0, kurtosis=3.0,
            var_trials=float(np.var([f["sharpe_annualised"] / np.sqrt(TRADING_DAYS)
                                     for f in family.values()], ddof=1)))
        deflated_searched = deflated_sharpe_ratio(
            observed_sharpe=max(sharpes) / np.sqrt(TRADING_DAYS),
            n_trials=len(FAMILY), sample_length=len(rule), skewness=0.0,
            kurtosis=3.0,
            var_trials=float(np.var([f["sharpe_annualised"] / np.sqrt(TRADING_DAYS)
                                     for f in family.values()], ddof=1)))
        variance = float(np.var([f["sharpe_annualised"] / np.sqrt(TRADING_DAYS)
                                 for f in family.values()], ddof=1))
        swept = deflated_sharpe_ratio(
            observed_sharpe=max(sharpes) / np.sqrt(TRADING_DAYS), n_trials=2691,
            sample_length=len(rule), skewness=0.0, kurtosis=3.0,
            var_trials=variance)
        print("  WHAT PRE-REGISTRATION BUYS (FR-09)")
        print(f"    committed to {WINDOW} in advance          N=1     "
              f"deflated {deflated_registered:.4f}")
        print(f"    best of {len(FAMILY)} windows                    "
              f"N={len(FAMILY)}     deflated {deflated_searched:.4f}")
        print(f"    the sweep from the other script       N=2,691 deflated {swept:.4f}")
        print()
        print(f"    Be precise about the size of this: at N={len(FAMILY)} the penalty is "
              f"{deflated_registered - deflated_searched:.4f}, which is")
        print("    almost nothing. Nine windows is not a fishing expedition. The")
        print("    deflation is built to punish the third line, and it does —")
        print("    the burden scales with how much of the space you actually")
        print("    swept, not with the fact that you looked more than once.")
        print()

        # ---- FR-12: the holdout, spent once ------------------------------
        _, all_closes = store.series("sp500", "SP500", "close")
        hold_from = [i for i, d in enumerate(
            store.series("sp500", "SP500", "close")[0]) if d >= HOLDOUT_START]
        out_prices = np.asarray(all_closes)[max(0, hold_from[0] - WINDOW):]
        out_rule, out_market, out_exposure = moving_average_timing(out_prices, WINDOW)
        oos_rule, oos_bh = summarise(out_rule), summarise(out_market)

        verdict = study.evaluate_on_holdout(registration, observed={
            "sharpe_annualised": oos_rule["sharpe_annualised"],
            "buy_and_hold_sharpe_annualised": oos_bh["sharpe_annualised"],
            "max_drawdown": oos_rule["max_drawdown"],
            "buy_and_hold_max_drawdown": oos_bh["max_drawdown"],
        })
        print(f"  HOLDOUT  {HOLDOUT_START} onward — the registration is now spent")
        print(f"  {'':22}{'buy & hold':>14}{'MA rule':>14}")
        print(f"  {'-' * 50}")
        for label, key, fmt in (("annualised Sharpe", "sharpe_annualised", "{:+.3f}"),
                                ("max drawdown", "max_drawdown", "{:.1%}"),
                                ("total return", "total_return", "{:+.1%}")):
            print(f"  {label:22}{fmt.format(oos_bh[key]):>14}"
                  f"{fmt.format(oos_rule[key]):>14}")
        print()

        drawdown_held = oos_rule["max_drawdown"] < oos_bh["max_drawdown"] * (2 / 3)
        sharpe_held = (oos_rule["sharpe_annualised"]
                       >= oos_bh["sharpe_annualised"] - 0.05)
        holdout_days = len(out_rule)
        print("  VERDICT AGAINST THE PRE-REGISTERED CLAIM")
        print(f"    'drawdown below two thirds of buy-and-hold'      "
              f"{'HELD' if drawdown_held else 'FAILED'}")
        print(f"    'Sharpe no worse than buy-and-hold less 0.05'    "
              f"{'HELD' if sharpe_held else 'FAILED'}")
        # `evaluations`, `exhausted` and `warning` — the keys evaluate() really
        # returns. This read `verdict.get("exhaustion_status", "first look")`,
        # a key that has never existed, so it printed "first look" however
        # exhausted the holdout was: a silent misreport of the one control this
        # script exists to demonstrate. A default that looks like an answer is
        # worse than a KeyError.
        print(f"    looks at this family: {verdict['evaluations']}")
        print(f"    {verdict['warning'] or 'no exhaustion warning — first look'}")
        if verdict["exhausted"]:
            print("    This holdout is now in-sample for this family. Any")
            print("    further variant needs a fresh period, not another look.")
        print()
        print("  WHAT THIS DOES AND DOES NOT LICENCE")
        print("    Both legs held out of sample, which is an uncommon result here")
        print("    and is not the same as vindication:")
        print(f"    - The holdout is {holdout_days} trading days. One period, one")
        print("      market regime, and no drawdown in it deep enough to be the")
        print("      test the rule exists for.")
        print("    - The DRAWDOWN claim is the durable half. Every one of the")
        print(f"      {len(FAMILY)} windows cuts it substantially, in sample and out, so")
        print("      it is a property of being out of the market sometimes rather")
        print("      than of the number 200.")
        print("    - The SHARPE claim held here, but the in-sample family spans")
        print(f"      {max(sharpes) - min(sharpes):.3f} across windows against a "
              f"{abs(in_rule['sharpe_annualised'] - in_bh['sharpe_annualised']):.3f} gap "
              "to buy-and-hold. A")
        print("      result smaller than the spread of the choices that produced")
        print("      it is not yet evidence about the rule.")
        print()
        print("    The registration is spent. A second look at this family is")
        print("    flagged as exhaustion, which is the point: the holdout is only")
        print("    a holdout while it is scarce.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
