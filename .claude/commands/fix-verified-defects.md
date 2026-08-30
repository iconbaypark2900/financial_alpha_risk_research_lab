---
description: Fix six reproduced correctness defects — four of them controls that fail in the exact case they exist for
---

# Fix the verified defects

Each item below was **reproduced**, not inferred, by an audit on 2026-08-30 against
commit `b426964`. Reproduce each one yourself before fixing it, then make the
reproduction a test. Take them in order; the first two are controls failing in the
regime they were built for.

## 1. `compare_to_null` inverts its verdict for negative Sharpes

`search.py:288-289`. `indistinguishable = null_s >= real_s * 0.8` silently assumes
a positive Sharpe. When `real_s < 0`, `real_s * 0.8` is *less* negative than
`real_s`, so the NOISE branch fires only when the null is meaningfully **better**
than the real search — and two indistinguishable negative Sharpes get the
flattering verdict. `ratio = real_s / null_s` on line 288 is positive and
meaningless for two negatives.

This is not hypothetical. `moving_average_crossover` defaults to `mode="excess"`
and its own docstring reports the best of 7,866 SPY variants scoring **-0.0194**,
which the README presents as the honest finding. Reproduced:

```
compare_to_null(real=-0.0194, null=-0.0190)
  -> indistinguishable_from_noise = False
  -> "The real search (-0.0194) meaningfully exceeds the null benchmark (-0.0190), 1.0x"
```

Noise strictly outperformed the real search and the tool said the opposite. The
suite never reaches it because every test uses positive Sharpes
(`tests/test_search_and_null_benchmark.py:174-185`). **This is the null-result
benchmark — FR-16, the acceptance criterion the PRD calls the most valuable test
in the document — failing on the exact result the README leads with.**

## 2. `portfolio_kelly` accepts a singular covariance and returns 1e14 leverage

`kelly.py:214-226`. The docstring promises refusal: a singular covariance "is NOT
silently replaced … answering anyway hides a data problem behind a plausible
portfolio." It answers anyway.

The PSD tolerance is `-1e-10 * max(1.0, max|eig|)`. The `max(1.0, ...)` floor pins
it to an **absolute** `-1e-10`, so it does not scale with the data: a daily
covariance with eigenvalues around `1e-4` that is genuinely non-PSD at min
eigenvalue `-5e-11` sails through. The only remaining defence is
`np.linalg.solve`, which the code's own comment two lines earlier says "raises
only on EXACT singularity."

```
x = rng.normal(0, 0.01, 500); y = x + rng.normal(0, 1e-9, 500)
portfolio_kelly([0.0005, 0.0004], np.cov([x, y]))
  -> ACCEPTED, weights [+1.054e14, -1.054e14], gross_leverage 2.108e14
simulate(...) on that -> ruin_probability 0.0
```

Two near-perfectly-correlated assets is the ordinary way a sample covariance goes
rank-deficient. An undefined optimum is being presented as a riskless arbitrage.
Make the tolerance relative to the eigenvalue scale, and add a conditioning check.

## 3. FR-24 records that code was unknown, then discards the evidence

`run_record.py:158-167`. Dirtiness is tracked-modifications **or** untracked source
files (line 160), but the diff is `git diff HEAD` (line 166), which by definition
never contains untracked files. `untracked_source` (line 158) only decorates the
rejection message — it is never passed to the INSERT and the `runs` table has no
column for it.

So the case the module went out of its way to detect — "an untracked `.py` can be
imported and is genuinely unknown code" — is exactly the case where
`allow_uncommitted=True` stores `code_dirty=1` with `code_diff=''`. FR-24 says
uncommitted code must be "either rejected or recorded as a full diff." This is
neither. Add the untracked file contents to the recorded diff, or refuse.

## 4. FR-23 raises a false `NotReproducible` on every search after the first

`search.py:224` vs `study.py:263-267`. `run_search` embeds the live counter's
global state in its result (`**inputs` — `n_trials`, `var_trials`, and the derived
`deflated_sharpe`, `min_backtest_length`, `sample_too_short`). Those grow
monotonically with the dataset's whole history, **by design** (FR-08). But
`replay_search` deliberately recomputes with a throwaway `TrialCounter` in a
`TemporaryDirectory`, so the replay sees only its own param sets.

```
search 1 -> n_trials 22, dsr 0.6931; replay -> reproduced=True
search 2 -> n_trials 44, dsr 0.6432; replay -> NotReproducible
```

The failure message blames "an unrecorded seed, an environment difference, or
uncommitted code" — none of which is the cause. The run is stamped
`replay_verified=0` permanently. This passes today only because every test and
demo replays the first and only search on a fresh workspace; the pipeline's own
`--home` flag, whose stated purpose is that the count "accumulates across runs",
is what breaks it. `run_record.py`'s own docstring names this hazard: false
reproducibility failures "teach everyone to ignore them."

Fix by excluding counter-derived global state from the replayed hash, or by
restoring the recorded counter state for the replay. Whichever you choose, say in
the docstring why the other was rejected.

## 5. `Mirror.iter_ciks` applies `limit` before filtering

`mirror.py:193-198` enumerates `archive.namelist()` and returns on `i >= limit`
**before** the `startswith("CIK")` filter. So `iter_ciks(limit=N)` and
`universe.build(..., limit=N)` silently deliver fewer than N companies whenever
non-CIK entries appear early — which the project's own fixtures model
(`README.txt`, `notacompany.txt`) and the real 1.4 GB archive contains.

```
archive [README.txt, CIK0000320193.json, CIK0000886158.json]
  limit=1 -> 0 companies   limit=2 -> 1   limit=3 -> 2
```

`build()`'s docstring says "Load fundamentals for `limit` companies." Note this
also silently shrinks the README's 672-company universe result — check whether
the published figures move once fixed, and say so if they do.

## 6. The numpy seed branch is never executed and seeds the wrong RNG

`run_record.py:341-342`. The `"numpy"` branch calls `np.random.seed(value)`, which
seeds the **legacy global** RNG and has no effect on `np.random.default_rng(...)`
— the generator every randomised module here actually uses (`factors.py:303`,
`search.py:264`, `simulator.py:213`, and both demo scripts). A run recording
`seeds={"numpy": N}` replays with its randomness unrestored, and no test notices,
because the suite only ever restores `"python"`.

## House rules

- Every fix gets a test that **fails before it and passes after**. Paste the
  reproduction in as the test where you can.
- Items 1, 3, 4 and 6 are controls. If a fix changes what a control reports,
  check whether any published figure in the README moves, and update it through
  `scripts/readme_tables.py` rather than by hand.
- Do not mark anything in `docs/REQUIREMENTS.md` as newly met. Two of these are
  requirements currently recorded as **met** that are not — if a fix is deferred,
  the status must come down, not stay up.
