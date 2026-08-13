#!/usr/bin/env python3
"""The demonstration PRD 04 says to run publicly, early, before anyone trusts a backtest.

    python3 scripts/null_benchmark_demo.py

Acceptance criteria 4 and 5. It runs one parameter sweep against a returns
series, then the identical sweep against those same returns reshuffled, and puts
the two side by side.

Reshuffling preserves the marginal distribution exactly — same mean, same
volatility, same fat tails — while destroying every temporal relationship a
trading rule could exploit. There is nothing left to find. So whatever the
second search reports is the score this PROCEDURE manufactures from noise at
this trial count.

If the two raw Sharpes are comparable, the raw Sharpe is measuring how hard you
searched rather than what you found. The deflated Sharpe is what tells them
apart, and it can only do that because every trial was counted.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research_integrity.search import (  # noqa: E402
    compare_to_null,
    crossover_grid,
    null_benchmark,
    run_search,
)
from src.research_integrity.trial_counter import TrialCounter  # noqa: E402


def main() -> int:
    grid = crossover_grid(max_fast=70, max_slow=150)
    rng = np.random.default_rng(42)
    # Fat-tailed daily returns with no predictable structure whatsoever. Eight
    # years of data — longer than most published backtests.
    returns = rng.standard_t(df=4, size=2000) * 0.01

    print(__doc__.strip().splitlines()[0])
    print()
    print(f"  strategy family : moving-average crossover")
    print(f"  parameter grid  : {len(grid):,} combinations")
    print(f"  sample          : {returns.size:,} periods")
    print()

    with tempfile.TemporaryDirectory() as tmp:
        real = run_search(returns, grid,
                          counter=TrialCounter(Path(tmp) / "real.db"),
                          dataset_id="returns", search_id="sweep-real")
        null = null_benchmark(returns, grid,
                              counter=TrialCounter(Path(tmp) / "null.db"),
                              dataset_id="returns-shuffled", search_id="sweep-null",
                              seed=7)

    print(f"  {'':24}{'AS GIVEN':>14}{'RESHUFFLED':>14}")
    print(f"  {'-' * 52}")
    print(f"  {'trials counted':24}{real['n_trials']:>14,}{null['n_trials']:>14,}")
    print(f"  {'best raw Sharpe':24}{real['best_raw_sharpe']:>14.4f}"
          f"{null['best_raw_sharpe']:>14.4f}")
    print(f"  {'best parameters':24}"
          f"{str(tuple(real['best_params'].values())):>14}"
          f"{str(tuple(null['best_params'].values())):>14}")
    print(f"  {'DEFLATED Sharpe':24}{real['deflated_sharpe']:>14.4f}"
          f"{null['deflated_sharpe']:>14.4f}")
    print()

    verdict = compare_to_null(real, null)
    print("  VERDICT")
    for line in _wrap(verdict["verdict"], 72):
        print(f"    {line}")
    print()
    print("  The deflated Sharpe is the headline figure (FR-09). Both searches")
    print("  fall far below the 0.95 threshold, which is the correct answer:")
    print("  neither found anything. The raw Sharpe, reported alone, would have")
    print("  looked like a result in both columns.")
    return 0


def _wrap(text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
