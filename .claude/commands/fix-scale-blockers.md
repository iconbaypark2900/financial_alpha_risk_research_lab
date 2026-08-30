---
description: Eight O(n) read/write paths that are invisible on fixtures and fatal on the 20,281-company universe
---

# Fix the scale blockers

## Why these matter now

The repository already found this shape once and wrote it up: ingestion was O(n)
in queries — `load` called `as_reported()` once per incoming fact, 58,699 round
trips for six series, "invisible on a five-row fixture … it never finished on the
first real cross-section."

**The fix traded a query problem for several others of the same shape.** Every
item below was measured, not estimated. They are the practical blocker on the
universe work that `/resolve-data-question` is about: whatever data you license,
these paths are what it has to go through.

## Measured, in rough order of cost

1. **`append_facts` inserts row-by-row** — `point_in_time.py:204`,
   `conn.executemany("INSERT INTO facts VALUES (?,...)")`. Benchmarked at
   **2,428 rows/s** against **818,403 rows/s** for a bulk `INSERT..SELECT` — a
   **337x** gap, 410x under load. This is the only write path into the store.
   `ingest.load()` of 1,156,017 facts measured **484 s**, of which only 2.7 s is
   normalise plus `json.dumps`. A 51M-fact price cross-section extrapolates to
   **6–14 hours of pure INSERT** against 1–2 minutes.

2. **`as_reported_index()` materialises the whole dataset** —
   `point_in_time.py:444-449`, an unbounded `fetchall()` with no LIMIT and no
   aggregation. This is the function that *fixed* the round-trip bug, and
   `ingest.load()` calls it unconditionally at `ingest.py:196` — so appending a
   single new day of prices requires materialising the dataset's entire history
   as Python objects. Same failure mode as the bug it replaced: fine on fixtures,
   dead on real data.

3. **`panel()` runs one full sequential scan per entity** —
   `point_in_time.py:407-408`, a `for entity in entities:` loop calling
   `self.series()`. This is the store's **only** cross-sectional read API. Measured
   on a 51,108,120-row table: **53 ms/entity, flat** — so the full 20,281-company
   universe is a single grouped query's work done 20,281 times.

4. **`rank_churn` issues 3 scans and 6 connections per company** —
   `universe.py:165-174`. Per entity it calls `store.series()` then
   `store.latest_including_restatements()`, which itself calls
   `require_point_in_time()` and `as_reported()`, each opening its own connection.
   This is the function that produces the README's headline FR-02 result.

5. **`_connect()` opens and closes a fresh DuckDB connection per call** —
   `point_in_time.py:126-127`. Connect plus close alone is 6–14 ms, and `series()`
   pays it twice (once inside `require_point_in_time`, once for the query), so a
   read whose SQL takes 3.3 ms takes 21.4 ms. `panel(N)` opens `2N+1` connections.
   This is the constant multiplier under items 3 and 4.

6. **`LookAheadAudit` calls `max()` over the whole bar cache on every bar** —
   `backtest.py:298-299`. The audit is on by default and is what FR-21 rests on,
   so nobody will turn it off. It scans up to 10,000 cached bars per bar to find a
   maximum timestamp that is already `bar.ts_event` of the newest bar. Measured
   overhead quadruples as bars double — 500 bars: 0.01 s; 5,000 bars: 0.36 s.
   The comment at `backtest.py:315` describes exactly the fix that was applied to
   the momentum signal three lines below it.

7. **`Mirror.read` / `read_cik` / `entries` / `count` reopen the 1.4 GB archive
   per call** — `mirror.py:160`, a fresh `zipfile.ZipFile` from `read` (:174),
   `entries` (:166) and `count` (:170). Measured **28 ms per read**, ~4,700x
   slower than reusing one handle. `read_cik` is the README-documented way to read
   the mirror; walking a chosen CIK list costs about 10 minutes.

8. **`realised_volatility` recomputes `np.std` over a fresh slice per t** —
   `factors.py:186-187`, O(n × window) with numpy call overhead per step. 12.3 ms
   per 2,520-close series, **290x** the rolling-moment form. Across the universe
   that is 4.2 minutes of pure interpreter overhead.

## How to do this without breaking the thing that matters

- **Correctness first, always.** Item 3's `panel()` deliberately does not
  forward-fill, because "a stale price ranks against live ones, so a holiday would
  read as a day the asset did not move while everything else did." A grouped query
  must reproduce that exactly, including `complete_cases=True`. Same for item 2:
  the as-reported-versus-restated distinction (FR-02) is the whole point of the
  index, and an optimisation that quietly changes which value wins is a look-ahead
  bug, not a speedup.
- **Pin the behaviour before you touch it.** For each item, write a test that
  captures the current *output* on a fixture, then optimise, then require the
  output identical. Several of these feed published README figures.
- **Measure, do not assume.** Every number above came from a benchmark. Reproduce
  it, change the code, re-measure, and record both figures in the commit message.
- Keep the minimal install working — none of this may require DuckDB where it is
  currently optional.

## Done when

`pytest -q` is green, each fixed path has a before/after measurement recorded, and
no published figure in the README has moved without being regenerated through
`scripts/readme_tables.py`.
