---
description: Produce a ratified decision record on the data-procurement question blocking FR-03, FR-04, FR-05 and FR-19
argument-hint: "[optional: license | engineer | rescope — to argue one option in depth]"
---

# Resolve the data question

This is a **decision**, not a code change. Produce a written, ratified record —
do not start implementing an option.

## The problem

Four requirements are open and none of them block on engineering:

| FR | Needs | Current substitute |
|---|---|---|
| FR-03 | Delisting dates and survivorship-free **prices** | EDGAR gives survivorship-free *fundamentals* with real filing dates; `last_filing` is a proxy for a delisting date |
| FR-04 | Index membership with effective dates | Nothing. EDGAR publishes none |
| FR-05 | Corporate actions | Nothing |
| FR-19 | Order-book depth for partial fills | Daily bars carry no depth to consume |

Be precise about what this blocks, because it is easy to overstate. The platform
**does** run real research today: a 2,691-trial S&P 500 sweep scored with deflated
Sharpe, a pre-registered Faber test with the holdout spent once, a 672-company
EDGAR cross-section measuring restatement impact on rank, and purged CV over a
real six-series panel. What it cannot do is run a **survivorship-free,
price-based universe study**, and it cannot close FR-19.

Read `docs/REQUIREMENTS.md` (§5.1 notes and the Summary) and the README's
"Survivorship, worked around: SEC EDGAR" section before forming a view — the
honest accounting there is the input to this, and note that REQUIREMENTS.md says
only that the gaps "still block on data, not engineering", not that research is
impossible.

## The three options to evaluate

1. **License it.** CRSP, Compustat Point-in-Time, WRDS, Refinitiv, or an
   equivalent. Establish what each actually closes, what it costs, what the
   licence permits (can results be published? can the data sit in a repo-adjacent
   mirror the way EDGAR does?), and whether academic or trial access applies.
2. **Keep engineering around the gap.** The EDGAR mirror was written off as
   procurement and turned out to be free. Ask honestly whether any of the
   remaining four have a comparable back door — and be specific about what a
   back door would *not* close, the way the EDGAR write-up already is.
3. **Rescope.** Declare the project fundamentals-only, move FR-04 and FR-05 out
   of scope with the reasoning recorded, and say so on the front page rather
   than leaving them as permanent "not implemented" rows that read as debt.

## What the record must contain

- What each option closes, **per FR**, and what it leaves open. No option closes
  all four; say which ones it does not.
- Cost, in money and in time-to-first-result.
- The licensing constraint on publishing results — this bears directly on the
  credibility-asset positioning, where the negative results are the product.
- A recommendation with the reasoning stated on the **requirement**, not on
  preference. Follow the precedent in `.spark-flow/memory/decisions.md`, where
  MLflow was rejected because FR-23 needs re-execution and MLflow only logs.

## Where it goes

- A dated entry in `.spark-flow/memory/decisions.md`, matching the existing
  format ("**Decision.** … **Why, on the requirement rather than on preference.**").
- A short section in `docs/REQUIREMENTS.md` replacing the current Summary
  paragraph, so the status board says what is being *done* about the four gaps
  rather than only that they exist.
- If the decision is to rescope, the README's scope section changes too.

## House rules

- **Do not mark anything met.** No status in `docs/REQUIREMENTS.md` moves as a
  result of a decision; statuses move when a test does.
- "Partial" with the gap named beats "met" — FR-03 is partial precisely because
  EDGAR has no delisting date, and that distinction is the model here.
- Research current pricing and terms rather than recalling them; cite sources.
