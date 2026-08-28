# finGuard — retired 2026-08-28. Do not import from this directory.

This is the source finGuard project, kept for lineage. **Everything in it that
this repository wanted has been replaced**, and the replacements are in
`src/portfolio/`. Nothing here is on the import path, nothing here is tested by
this project's suite, and its `todo.md` is AI-generated self-assessment with no
standing.

| here | status | replacement |
|---|---|---|
| `src/finguard/kelly.py` | superseded — 6 defects | `src/portfolio/kelly.py` |
| `src/finguard/drawdown.py` | superseded — 5 defects | `src/portfolio/drawdown.py` |
| `src/finguard/simulator.py` | rewritten — 4 defects, never tested here | `src/portfolio/simulator.py` |
| `src/finguard/visualizer.py` | **out of scope** — a Plotly UI, never imported, does not even import | none |
| `src/app.py` | **out of scope** — Streamlit UI | none |

## Why it is retired rather than kept as an inbox

It shipped with **23 passing tests** and a `todo.md` calling its architecture
"Perfect" and rating its own gaps as LOW. Those tests covered 302 of its 968
lines. Checking all three substantive modules against their published sources
found **thirteen defects**, every one of which flatters the strategy. Two are
severe enough to name here:

**A sign inversion.** `calculate_portfolio_kelly` divided the weights by their
sum. For `mu = [-0.10, 0.02]` and `S = diag(0.04, 0.01)`, Kelly says short the
first (−2.5) and hold the second (+2.0); the sum is −0.5, dividing by it flipped
both signs, and after clipping and renormalising it returned `[1.0, 0.0]` —
fully long the asset it was told to short and nothing in the one it was told to
buy. Wrong on both legs, from one unguarded division.

**A recovery-time formula that needs no finance to falsify.** It used
`log(1+x)` where recovering a fall of *x* requires `−log(1−x)`. A 50% drawdown
needs a 100% gain, so at 10% a year the answer is `log(2)/log(1.1)` = 7.27
years. It reported 4.25 — 41.5% optimistic.

And in the simulator, which was never tested at all: one `DrawdownManager`
shared across every simulated path with its peak never reset, so path 2 began
50% underwater; returns measured against the terminal value of path 0, turning a
40% probability of loss into 60%; and no random seed anywhere.

The full list is in this repository's README under *V1 — portfolio
construction*, with a regression test named after each one.

## The point of keeping it

A directory of working-looking code with thirteen known defects, sitting on the
path, is a standing invitation to import the wrong version — which is exactly
what `requirements.txt` and the task backlog did with the superseded
specification next door. It is kept for lineage and moved out of reach, the same
call and for the same reason.

Its own 23 tests still pass, from here, and that is the whole problem:

```bash
PYTHONPATH=docs/superseded/finGuard/src pytest docs/superseded/finGuard/tests/ -q
# 23 passed — and the code under them inverts positions.
```
