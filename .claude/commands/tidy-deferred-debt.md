---
description: Clear the small debts — upstream warnings, broad excepts, stale figures — without weakening any pin
---

# Tidy the deferred debt

Small items only. Nothing here changes a requirement status; if something you
find would, stop and raise it rather than folding it in.

## 1. The 50 pandas warnings are upstream, not ours

The suite emits 50 `Pandas4Warning: Timestamp.utcnow is deprecated` warnings,
all pointing at `engine.run()` in `backtest.py:427` and `tests/test_backtest.py`.
**The deprecated call is inside `nautilus_trader`, not in this repository** —
the repo's own `_utcnow()` helpers in `holdout.py`, `trial_counter.py` and
`run_record.py` are separate and fine. Verify that before doing anything.

The right response is therefore a scoped `filterwarnings` in
`[tool.pytest.ini_options]` naming the upstream cause, or a documented pin note
— **not** a code change here and **not** a blanket `-W ignore`, which would also
hide warnings from this project's own code.

## 2. Seven broad `except Exception` clauses

`study.py:148,175` · `search.py:196` · `mirror.py:108` ·
`run_record.py:142,178,292`

They are **not** all the same pattern, and giving them one shared FR-25
justification would be wrong — it would attach "records the failure before
re-raising" to sites that silently discard errors, which is the distinction the
annotation exists to make. They break down as:

- **Record a failed outcome, then re-raise (FR-25):** `study.py:148`,
  `study.py:175`, `run_record.py:292`.
- **Clean up, then re-raise as a typed error:** `mirror.py:108` removes a partial
  download and raises `MirrorError`.
- **Deliberately swallow:** `search.py:196` (a failed trial still consumes a
  look), `run_record.py:142` and `run_record.py:178` (git and
  `importlib.metadata` failures degrade to `None`/`[]` rather than breaking a run
  record).

Give each its own one-line reason, in the style this codebase already uses for
its `# type: ignore` comments. Do not narrow one until you have checked what it
is protecting.

## 3. Stale figures

Grep for hard-coded counts and check each against reality:

- `docs/LIAISON_PROJECT_BRIEF.md` says "Expected: 248 tests passing". The actual
  figure is **508**. The brief already carries a dated warning that some
  sections describe an architecture that no longer exists — extend that
  treatment to the happy path, or fix the number.
- The README's `508` appears in prose at `README.md:48` and in the quickstart
  block at `README.md:67`. Both **are** guarded — by
  `tests/test_packaging.py::test_the_documented_test_count_is_the_real_one`, which
  also pins the matching strings in `pyproject.toml` and `requirements.txt`.
  `test_readme_is_true.py` guards the numeric tables only and says nothing about
  the headline count, so do not look for it there.
- **`338 of the 508` is wrong and unguarded.** The real minimal-install figure is
  **351 passed, 18 skipped** (369 collected) on a fresh numpy+pytest venv. The
  count test explicitly `pytest.skip`s on a minimal install, so nothing catches
  it. Fix the number at `README.md:76`, `pyproject.toml:35` and
  `requirements.txt:5` — and consider making the guard run in that configuration
  instead of skipping, since this is the one claim it was most needed for.

## 4. What not to touch

- **`test_market_orders_against_daily_bars_do_not_partially_fill`** pins the
  FR-19 limitation and is *supposed* to fail if partial fills ever start
  occurring. That is the signal telling whoever adds order-book data that the
  docs can be strengthened. Leave it exactly as it is.
- Any `# type: ignore[...]` carrying a written reason.
- The duplicate dependency declaration across `pyproject.toml` and
  `requirements.txt` — that is deliberate and `test_packaging.py` polices it.

## Done when

`pytest -q` is green, the warning count is reduced by suppression that names its
upstream cause rather than by silence, and every figure in `docs/` matches what
the suite actually reports.
