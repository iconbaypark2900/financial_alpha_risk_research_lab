# The four data-blocked requirements: license, engineer around, or rescope

**Decided 2026-08-30. The summary entry is in `.spark-flow/memory/decisions.md`.**

Four requirements are open and none of them blocks on engineering. `docs/REQUIREMENTS.md`
records why:

> The remaining gaps still block on **data**, not engineering: order-book depth
> (FR-19), a delisting date and survivorship-free PRICES (FR-03), index membership
> with effective dates (FR-04), and corporate actions (FR-05).

This page decides what to do about that. It changes no status. Statuses move when a
test moves, and a decision is not a test.

## What is actually blocked, and what is not

The blocked thing is narrow and it is worth stating before anything else, because
"the data is missing" reads as "the platform cannot run research" and that is false.
The platform runs research today:

- a 2,691-trial sweep over real S&P 500 closes, in which not one variant beat holding
  the index and the reshuffled control scored higher than the real series;
- a pre-registered Faber test against the protected holdout, registered before the run
  and now spent;
- a 672-company EDGAR cross-section that measured how far a restatement moves a
  ranking — 0.96% of names at decile granularity, 7.35% at percentile granularity;
- purged, embargoed CV over a real six-series panel, where naive k-fold leaks 160
  observations and `assert_no_leakage` passes on all five folds.

Every one of those is a real result on real data with the controls binding. What
cannot be done is narrower:

| | blocked |
|---|---|
| FR-03 | a survivorship-free **price** study — a return series that includes the dead — and a real delisting **date** rather than a proxy |
| FR-04 | any study that needs to know who was in an index on a past date |
| FR-05 | any factor whose input is changed by a split, a spin-off or a distribution |
| FR-19 | a **partial fill**, at any order size, because a daily bar carries no depth to consume |

Three of those four are about a *universe*. The fourth is about *microstructure*.
They are not one problem and the options below do not treat them as one.

## Method, and what counts as evidence here

Everything below is one of three things, and the document says which:

1. a clause **quoted from a licence agreement that the vendor or a subscriber has
   published**;
2. a price **published by the vendor on its own site**;
3. a **measurement taken against a live source on 2026-08-30**, reproducible by
   re-running the command in the footnote.

Where a vendor publishes no price, this page records "no published price" rather than
filling in a plausible number. The absence is itself one of the findings, and it is
the one that determines time-to-first-result.

Prior recalled knowledge was not used for prices or terms. One recalled belief was
checked and found wrong; it is in *What this found in the project's own record*, below.

---

## Option 1 — license it

### What each vendor actually closes

| | FR-03 delisting date | FR-03 survivorship-free prices | FR-04 index membership + dates | FR-05 corporate actions | FR-19 order-book depth |
|---|---|---|---|---|---|
| **CRSP US Stock** (now Morningstar) | yes — delisting date, delisting code, delisting return | yes — NYSE monthly from Dec 1925 and daily from Jul 1962, AMEX from Jul 1962, Nasdaq from Dec 1972 | yes — `dsp500list`/`msp500list`, PERMNO with start and end dates, from 1958 | yes — distributions file with declaration, ex, record and payment dates | **no** |
| **Compustat Point-in-Time** | no | no (fundamentals) | **no — and it used to; see below** | no | **no** |
| **WRDS** | delivery only | delivery only | delivery only | delivery only | via **NYSE Daily TAQ** — trades, quotes and NBBO, i.e. top of book; full depth needs the separate **NYSE Integrated Feed** |
| **LSEG (Refinitiv) Tick History** | no | no | no | no | yes — "time and sales, quotes and **market depth**" back to January 1996 |
| **LSEG Datastream / Quantitative Analytics** | partial — "dead" securities are retrievable | yes | partial | partial | no |
| **Norgate Data Platinum** | partial — delisted symbols carry a year-month suffix; no filed date | yes — delisted US equities back to 1990 | **yes** — historical constituents as a per-day membership flag | yes — capital events and dividends with ex-dates, and unadjusted prices | **no** |
| **Databento** | no | no | no | no | **yes** — MBO (L3) and MBP-10 (L2) from Nasdaq TotalView-ITCH and 15 US venues |

**No single vendor closes all four.** CRSP closes three and leaves FR-19 exactly where
it is. Databento closes FR-19 and leaves the other three exactly where they are. That
is not a quirk of these two: nobody sells a survivorship-free daily universe and a
reconstructed order book as one product, because they are different businesses.

**CRSP does not fully close FR-03 either, and the literature says so.** Shumway (1997),
*The Delisting Bias in CRSP Data*, established that correct delisting returns are
unavailable for most stocks delisted for negative reasons since 1962, that the omitted
returns are large and negative on average, and that they are systematically associated
with poor firm performance. The standard corrections — Shumway's imputations, and
Beaver, McNichols & Price (2007) — are assumptions applied where the data is absent.
Buying CRSP buys the best available answer to FR-03. It does not buy the delisting
return of the average bankrupt.

### Cost

| | published price | commitment |
|---|---|---|
| CRSP | **none published.** The site routes to `subscriptions@crsp.ChicagoBooth.edu` / +1-312-263-6400 | the standard agreement §8.1 sets the **initial term at two data-years** for Academic and Commercial Subscribers, with a 50% early-termination fee under §7.3 |
| Compustat | **none published** | via WRDS annual contract |
| WRDS | **none published.** Routes to `wrds@wharton.upenn.edu` | annual |
| LSEG Tick History | **none published** | annual |
| **Norgate Data (US stocks)** | **published**: Silver USD 270/yr, Gold USD 360/yr, **Platinum USD 630/yr**, Diamond USD 787.50/yr | 6- or 12-month |
| **Databento** | **published**: usage-based with USD 125 free credit; **Standard USD 199/mo** (L2/L3 history 1 month); **Plus USD 1,750/mo** (L2/L3 history 16+ years, external distribution rights); **Unlimited USD 4,500/mo** | monthly / annual |

The gap in that table is the finding. The four vendors that dominate this space in
reputation publish nothing; the two that publish are the cheap ones. Anyone budgeting
for "the CRSP option" is budgeting for a number nobody outside a signed agreement has.
A commonly-repeated figure of roughly USD 60k for CRSP+Compustat appears only on an
anonymous forum and is **not** treated as evidence here.

**The counterparty changed seven months ago.** Morningstar completed its acquisition of
CRSP from the University of Chicago on 2026-02-02 for USD 365 million and rebranded the
CRSP Market Indexes to Morningstar Market Indexes in July 2026. The Research Data
Products moved with it. No current agreement or price list has been published under the
new owner, so even the clause numbers quoted below are from the pre-acquisition standard
agreement.

### Time to first result

For CRSP, Compustat, WRDS and LSEG the floor is **a sales cycle, not a download** —
quote, licence review, purchase order, provisioning — and this page will not guess at
how many weeks that is. What can be stated exactly is the shape: none of the four can be
started on a Friday afternoon by anyone in the team without a counterparty. Norgate and
Databento can: both take a card and deliver the same day.

### What the licences permit — and this is the part that decides it

**CRSP Standard Data Subscription Agreement** (as published by a subscribing university
library; CRSP publishes no current agreement, so clause numbers may have moved under
Morningstar):

- **§1.2** — licensed for "Internal Use", meaning use "within a specific department and
  geographic location on one computer system or approved server and group of networked
  workstations located at one street address", and "expressly excludes further
  dissemination of the information or data contained in the Data Files in electronic
  form".
- **§1.3** — Subscriber "will not transfer, sell, publish, redistribute or release or
  otherwise make available the Data Files or the data contained therein to any individual
  or third party who is not an employee or consultant, a faculty or staff member, or a
  student of Subscriber".
- **§1.8** — no copying "onto any device or medium ... without the express written
  consent of CRSP", except back-up copies for internal use.
- **§2.1** — "Subscriber will not communicate or disseminate any information or the raw
  data contained in the Data Files in computer readable form to any third party ... What
  is precluded is the distribution of the raw data in machine readable or any other form,
  so that the recipient could actually use the data, rather than taking out some form of
  additional subscription."
- **§2.2** — "Subscriber may use the Data Files for publications as set forth in the
  Statement of Use set forth in Appendix A."
- **§2.3** — any approved publication "shall contain attribution to CRSP®".
- **§9.1** — on cancellation, Subscriber "is obligated to erase and/or to destroy the
  original and all copies of the Data Files ... within thirty (30) days", and to certify
  it in writing, signed by a senior executive or, for an academic subscriber, by a Dean.

**WRDS Terms of Use**: "you may not reproduce, distribute, modify, adapt, create
derivative works of, display, transmit, broadcast, sell, license or in any way exploit
the Proprietary Material"; "You may not reveal, disclose, transfer or share your username
and password with anyone, including without limitation a co-author or other
collaborator"; and a mandatory citation in all publications.

**S&P Global Academic Research Essentials** (the route that would make Compustat
affordable): eligibility is standing faculty, research staff and enrolled students, and
"S&P RE is for academic and non-commercial research purposes only" — users may not employ
the data "for any non-academic or commercial endeavor". CRSP's own §1.2 says the same
from the other side: "Internal Use does not include use for consulting or other for-profit
uses by an Academic Subscriber."

**Norgate Data EULA**: clause 2(i) permits installation "on two computers that are
normally accessed by the Licensee for personal use"; clause 8, "The Licensee may use the
Content for a personal purpose such as investment or trading"; clause 8(i), the Licensee
"will not redistribute the Content in any way or form except where express permission has
been sought and obtained to publish limited extracts"; clause 14, the Content "may not
otherwise be stored, copied, reproduced, altered or transmitted in any form"; clause 21,
"Following any expiration of a Subcription the Licensee must delete all Content and
Information related to that subscription ... The Licensee is permitted to retain Derived
Data", where Derived Data expressly includes "trading result, simulated trading
(backtests), and statistics related to those results".

**Databento**: "Databento doesn't apply any redistribution restrictions" of its own;
rights follow the venue's terms, with most permitting redistribution after 24 hours, and
historical T+1 access requires no licence unless you redistribute.

**A licence can also be withdrawn from under you.** S&P Dow Jones Indices constituent
names were removed from Compustat on the WRDS platform in July 2020, under direct
licensing, leaving CRSP as the route to S&P 500 membership for subscribers who had been
getting it from Compustat. Index membership is separately licensed from the fundamentals
it sits beside, and it has been pulled from a platform mid-relationship before. That is
worth weighing against FR-04 specifically: buying access to membership data is not the
same as owning a membership history.

**The README's front page describes this repository as an internal tool run by the team
that trades the strategies.** That single fact removes the academic tier from every
option above. It is not a price problem. It is an eligibility problem, and it is written
into the agreements in both directions.

---

## Option 2 — keep engineering around the gap

The precedent for this option is real and recent. Delisted names were "the one
requirement written off as procurement", and SEC EDGAR turned out to supply them for
nothing — a US Government work, public domain under 17 U.S.C. §105, mirrored once as a
1,407,496,523-byte file with a sha256 that a run record can name. So the question
"is there another back door" deserves to be asked seriously rather than dismissed.

It was asked for all four. One of the four answers is a genuine yes.

### FR-03, the delisting date: **yes, and it was verified**

`docs/REQUIREMENTS.md` currently says:

> EDGAR publishes no delisting DATE, so `last_filing` is a proxy

That sentence is true of the **bulk company-facts archive** the project mirrors. It is
**not true of EDGAR**. Delisting is a filing, on a form, with a date.

Under 17 CFR 240.12d2-2, a national securities exchange **must** file Form 25 to strike
a class of securities, and "An application on Form 25 to strike a class of securities from
listing on a national securities exchange will be effective 10 days after Form 25 is filed
with the Commission" (§(d)(1)). Paragraph (a) covers redemption, maturity and
substitution-by-operation-of-law; paragraph (b) covers everything else, subject to the
exchange's own notice and appeal procedures; paragraph (c) is the issuer's own voluntary
application.

Counted directly from the EDGAR quarterly form indexes:

```
2009 QTR1    54 × Form 25   +  330 × Form 25-NSE   =  384
2016 QTR1    17 × Form 25   +  376 × Form 25-NSE   =  393
2023 QTR1    36 × Form 25   +  582 × Form 25-NSE   =  618
```

Only the **25-NSE** filings are structured XML. A plain Form 25 carries no
`primary_doc.xml` — it is a free-form HTM document — which is 36 of the 618 in
2023 QTR1, 5.8%. So the machine-readable route covers the large majority and
not all of it, and a parser must fall back or skip for the rest.

The project's own worked example, Bed Bath & Beyond
(CIK 886158), reads:

```xml
<exchange><cik>0001354457</cik><entityName>Nasdaq Stock Market LLC</entityName></exchange>
<issuer><cik>0000886158</cik><entityName>BED BATH &amp; BEYOND INC</entityName></issuer>
<descriptionClassSecurity>Common stock</descriptionClassSecurity>
<ruleProvision>17 CFR 240.12d2-2(b)</ruleProvision>
<signatureDate>2023-07-10</signatureDate>
```

That is the CIK the project already keys on, the class removed, the **reason as a rule
citation** — (b) is the exchange striking the security under its own rules, the
involuntary case — and a filing date of 2023-07-10, so removal was effective 2023-07-20.

**How wrong is the proxy it replaces?** `listing_status()` returns
`last_filing = max(filingDate)`. For BBBY today that is **2023-12-04**: a SEC STAFF
ACTION notice, four and a half months after the shares stopped being listed. The proxy
is **137 days late** on the project's own headline example, and the error has no sign
and no bound — a company that delists and then stops filing entirely produces a proxy
that is early instead.

**What this back door does NOT close**, said as specifically as the EDGAR write-up already
says everything else:

- **It is the legal removal date, not the last trade.** Nasdaq suspended trading in BBBY
  on 2023-05-03; the Form 25-NSE was filed 2023-07-10. Under §(b) the exchange must run
  its notice-and-appeal procedure before filing, so for exactly the deficiency delistings
  that matter most, the Form 25 date trails the last trade — here by 68 days. It is an
  upper bound, and it is a far better bound than a proxy that is wrong in an unknown
  direction, but it is not the last trade.
- **It is not a delisting return.** The number a survivorship-free backtest consumes is
  what a holder got on the way out. Form 25 does not carry it, and neither, per Shumway,
  does CRSP for most negative delists.
- **It needs a second mirror.** The company-facts archive does not contain Form 25s. This
  is the quarterly form indexes plus one small XML per filing — measured at 54,362,089
  bytes per quarterly index, against 1,407,496,523 bytes and 226 seconds for the archive
  already mirrored. Same shape, same licence, smaller.
- **FR-03 would stay `partial`.** It closes the first of the two named gaps and not the
  second. Prices are still absent.

### FR-04, index membership with effective dates: **no**

The nearest thing to a back door is reconstructing membership from an index fund's own
filings. Position-level holdings for the entire US registered fund industry are on EDGAR
in Form N-PORT from October 2019, and in the quarterly holdings forms that preceded it.
It fails, for reasons that are structural rather than fixable:

- **The granularity is a quarter, not an event.** Only the third month of each fiscal
  quarter is public, released 60 days after quarter end. FR-04 asks for membership *with
  effective dates*; a quarterly snapshot gives a bracket containing the change, which is
  the same class of substitution as `last_filing` — and the project already marks that
  `partial` rather than `met` for exactly this reason.
- **The rule is moving the wrong way.** The 2024 amendments would have made monthly
  reports public 60 days after month end. An SEC proposal published 2026-02-23 rolls the
  public frequency back to quarterly.
- **A fund's portfolio is not the index.** Cash, futures overlays, securities on loan and
  sampling all put names in the file that are not in the index and leave out names that
  are.

The other candidate — scraping index-change press releases or a wiki page — supplies no
provenance, no completeness guarantee and no as-of semantics, which is the entire content
of FR-01. It is not a source this project can accept.

### FR-05, corporate actions: **partly, and the useful half is missing**

XBRL does carry some of this, and it carries it point-in-time, which is more than most
free sources manage. Verified against `data.sec.gov` on 2026-08-30:

- `us-gaap:StockholdersEquityNoteStockSplitConversionRatio1` — Apple's 7-for-1 split is
  present with `end` 2014-06-06 (the split date) and `filed` 2014-07-23 (a real knowledge
  date). Across all filers in CY2014Q2, **65 entities** reported this tag, against
  **6,582** reporting `StockholdersEquity` in the same frame.
- `us-gaap:CommonStockDividendsPerShareDeclared` — present, but it is the aggregate
  declared **over a period**. There is no ex-date, no record date and no payment date in
  it.

So: splits are reachable and dividends are not, in the form a backtest needs them. And the
coverage question cannot be settled from the inside — 65 splitters in a quarter is entirely
consistent with real split frequency, but a company that split and did not tag it is
invisible to that count, and there is no denominator of companies that actually split. The
honest status of the split back door is "present, point-in-time, completeness unmeasurable
without an external list", which is not the same as "available".

### FR-19, order-book depth: **free depth exists, and it would not move any result**

There is genuinely free depth. Nasdaq publishes sample TotalView-ITCH files on its public
server at `emi.nasdaq.com/ITCH`, and LOBSTER publishes free reconstructed order-book
samples for AAPL, AMZN, GOOG, INTC and MSFT at up to 200 price levels. A partial fill
could be demonstrated from those.

**And it would change no result this project has produced.** The engine backtests daily
bars. Consuming a book means running at message resolution, which is a different backtest
over a different horizon, not the same backtest at higher precision. A partial fill on one
sample day for one large-cap name would not make the 2,691-trial daily-bar sweep's fills
one basis point more realistic, and
`test_market_orders_against_daily_bars_do_not_partially_fill` would still pass, still
correctly. It would move FR-19's *evidence* without moving any *finding*.

That distinction is the reason to say no rather than yes. Booking a status change that
improves no result is precisely the move this project exists to catch. The README already
names it: "It would have been easy to book FR-19 as met."

---

## Option 3 — rescope

The proposal is to declare the project fundamentals-only, move FR-04 and FR-05 out of
scope with the reasoning recorded, and say so on the front page so the status board stops
carrying two permanent "not implemented" rows that read as unpaid debt.

The motivation is sound. A "not implemented" row that will never be implemented is a lie
of a different kind: it implies a plan.

**FR-04 rescopes cleanly.** Nothing in `src/` consumes index membership. The store's
schema carries effective-dated facts and would hold membership if it arrived; no factor,
no control and no result depends on it. Declaring it out of scope removes a row and
removes nothing else.

**FR-05 does not, and this is the finding that decides Option 3.**

FR-02 is met: fundamentals are read as-first-reported, restatements are kept as separate
versioned records, and a restated read requires `acknowledge_contamination=True`.
Restatement detection compares a period's value across filings, ordered by filing date.
Now look at what that machinery sees on any per-share figure. Apple's FY2013 basic EPS,
from `data.sec.gov` on 2026-08-30:

```
2012-09-30 .. 2013-09-28   val = 40.03   10-K   filed 2013-10-30
2012-09-30 .. 2013-09-28   val =  5.72   10-K   filed 2014-10-27
2012-09-30 .. 2013-09-28   val =  5.72   8-K    filed 2015-01-28
2012-09-30 .. 2013-09-28   val =  5.72   10-K   filed 2015-10-28
```

40.03 / 7 = 5.7186. That is not a restatement. That is the 7-for-1 split of 2014-06-06
applied retroactively, and the detector will report it as an **−85.71% restatement** of
Apple's FY2013 earnings. Two facts about the same period disagreeing by 85% is exactly
what FR-02 was built to catch, and here it is a corporate action wearing a restatement's
clothes. **Without FR-05 there is no field that tells them apart.**

This is latent, not live: `universe.py` reads `("StockholdersEquity", "us-gaap", "USD")`,
a total, and a split does not touch a total. It goes live the moment anyone adds a
per-share factor — EPS, book value per share, dividend yield — which is a one-line change
to the `tags` dict on line 31.

So FR-05 cannot be declared out of scope without also declaring that a met, running,
already-published control has a known false-positive class and nobody is going to fix it.
The restatement study is one of this project's headline results. Rescoping FR-05 would put
a footnote on it in exchange for tidying a status board.

**And rescoping moves a status without a test**, which is the house rule. The MLflow entry
did not rescope FR-23; it explained why a tool that satisfied the letter would weaken the
requirement, and left the requirement alone.

---

## The licensing constraint on publishing results

This bears directly on the project's strongest current use, where the negative results are
the product, so it is worth being exact about what is and is not prohibited.

**Publishing the results is permitted everywhere.** CRSP §2.2 permits publication as set
out in the Statement of Use and §2.3 requires attribution; WRDS requires a citation;
Norgate clause 21 expressly permits retaining "Derived Data", defined to include "trading
result, simulated trading (backtests), and statistics related to those results". A record
saying "we could not publish our negative results under a licence" would be false, and
this page does not say it.

**Publishing the artefact that makes them checkable is prohibited everywhere.** CRSP §1.3
and §2.1 forbid making the data available to anyone outside the subscriber and forbid
dissemination "so that the recipient could actually use the data"; §1.8 forbids copying it
to any medium; WRDS forbids reproduction and distribution outright; Norgate clause 8(i)
forbids redistribution except by written permission for limited extracts, and clause 14
forbids storing or transmitting the Content at all. **A repo-adjacent content-addressed
mirror of licensed data is prohibited under every licence examined.** Databento is the
exception and only for the venues whose own terms allow it, most after 24 hours.

That is a real loss, and it is a loss of a specific property rather than a vague one. The
EDGAR mirror lets a run record name `companyfacts.zip@314ebb3149c96c98` and lets a reader
fetch the same 1.4 GB file and check the digest. That is FR-06's "the exact version it
used" meaning a file whose contents can be verified — by the reader, not only by the
author. Under a licence, the digest names a file the reader may not have, and the strongest
available claim degrades from *check it* to *trust us*. For a platform whose stated design
goal is making its results believable, that is the expensive part of the bill, and it is
not on the invoice.

**And one clause is a requirement-level defect, not a design regret.** FR-23 says any past
run MUST be re-executable and MUST produce identical results. CRSP §9.1 obliges the
subscriber to erase and destroy every copy within thirty days of cancellation and to
certify it. Norgate clause 21 obliges deletion of all Content on expiry. So the moment a
subscription lapses, every run record naming that dataset names a file the subscriber is
contractually required not to possess, and `replay()` cannot run. **Under both licences
FR-23 holds only while the invoice is paid.** Norgate's carve-out for Derived Data is
precisely the wrong shape: it lets you keep the *result*, which is what a log keeps. FR-23
exists because a log is not enough.

---

## What no option closes

| | license | back door | rescope |
|---|---|---|---|
| FR-03 delisting **date** | closed (CRSP) | **closed** — Form 25/25-NSE, verified | n/a |
| FR-03 last-trade date and delisting **return** | partly — Shumway shows the negative-delist returns are largely absent even in CRSP | **not closed** | n/a |
| FR-03 survivorship-free **prices** | closed (CRSP, Norgate, Datastream) | **not closed** | n/a |
| FR-04 membership **with effective dates** | closed (CRSP daily list; Norgate daily flag) | **not closed** — quarterly bracket only | removed, not closed |
| FR-05 splits | closed | partly — XBRL tag, coverage unmeasurable | removed, not closed — and see the EPS finding |
| FR-05 dividends with ex-dates | closed | **not closed** — XBRL gives a period aggregate | removed, not closed |
| FR-19 partial fills | closed by Databento, LSEG Tick History or the NYSE Integrated Feed via WRDS; **not by CRSP, Compustat or Norgate** | free samples exist and change no result | out of scope was not proposed |
| FR-23 across a lapse | **broken** by CRSP §9.1 and Norgate cl.21 | unaffected — public domain | unaffected |
| a reader can verify the dataset | **lost** under every licence but Databento | unaffected | unaffected |

---

## Recommendation

**1. Build the Form 25 / 25-NSE mirror. Adopt this.**

On the requirement: FR-03 is `partial` with two named gaps, and one of them is "EDGAR
publishes no delisting DATE, so `last_filing` is a proxy". That sentence is wrong about
EDGAR — 618 dated, structured, machine-readable removal notices were filed in 2023 Q1
alone, each carrying the issuer CIK this project already keys on and the rule provision
that says why. The proxy it would replace is 137 days late on the project's own worked
example, with no known sign or bound. This is the same source, the same public-domain
licence, and the same mirror-and-hash shape as the archive already in the repository.

**FR-03 would remain `partial`**, because prices are still absent and Form 25 gives the
legal removal date rather than the last trade — 68 days apart for BBBY. And it moves only
when a test moves.

**2. Do not license CRSP, Compustat, WRDS or LSEG. Reject.**

Not on cost — the cost is unknown, and that is itself a finding rather than an excuse. On
the requirements:

- **FR-19 is untouched by CRSP and Compustat**, and FR-19 is the one requirement V0 has
  open on the engine side. The two vendors whose names dominate this decision do not
  address it at all.
- **FR-23 becomes rentable.** CRSP §9.1 requires destruction of every copy within thirty
  days of cancellation, certified by a Dean or an officer. A requirement that the project
  enforces by re-execution would become a requirement that holds while the contract does.
  The MLflow decision refused a tool that logs without checking; a dataset that must be
  destroyed makes every historical record a log by contract instead of by design.
- **The affordable tier is closed by eligibility, not price.** S&P Global Academic
  Research Essentials is "for academic and non-commercial research purposes only", and
  CRSP §1.2 says "Internal Use does not include use for consulting or other for-profit uses
  by an Academic Subscriber." The README describes this as an internal tool run by the team
  that trades the strategies.
- **Ownership changed seven months ago.** CRSP was acquired by Morningstar on 2026-02-02,
  and no agreement or price has been published since.

**3. If FR-03's prices, FR-04 and FR-05 must close, price Norgate Data Platinum at USD 630
per year — and do not buy it until two things exist.**

This is the part of the analysis that most surprised the assumption it started from. The
requirement that was written off as a five-figure procurement is sold, with a published
price, for **USD 630 a year**: survivorship-free US equities back to 1990 including
delisted names, historical index constituents as a per-day membership flag, capital events
and dividends with ex-dates, and unadjusted prices. That is FR-03's price gap, FR-04 and
FR-05 for roughly the cost of a monitor.

It is not recommended for adoption today, and the reason is on the requirement rather than
on the price:

- **Clause 21 breaks FR-23 on expiry** — all Content must be deleted; only Derived Data may
  be kept, which is exactly the distinction FR-23 was written to refuse.
- **Clause 2(i) and clause 8 licence it to one person for personal use on two computers.**
  A platform described as a team's internal tool does not fit that licence, and this page
  will not recommend acquiring data under terms the project would be outside on day one.

If the team wants it anyway, the two prerequisites are concrete:

1. FR-06 and FR-23 restated to say **re-executable while the licence is current**, with the
   limitation named the way FR-19's is;
2. `replay()` **refusing** — not warning — a run whose dataset version is licence-bound and
   whose bytes cannot be verified, with a test that fails if it ever silently proceeds. "A
   warning is read once and then filtered out of the logs."

Until those exist, buying it would silently convert a met requirement into a rented one,
which is the failure mode this project already ratified a decision against.

**4. Reject the rescope for FR-05; FR-04 could be rescoped, and should not be yet.**

FR-05 is not severable from FR-02. The Apple FY2013 EPS figures above are a −85.71%
"restatement" that is entirely a corporate action, in a control that is met, running and
already reported on. Declaring corporate actions out of scope declares that false-positive
class permanent. FR-04 *would* rescope cleanly, but rescoping one of a pair while the other
is refused converts a coherent "these four need data" into an incoherent status board, and
option 3's whole appeal was coherence. Both stay.

**5. FR-19 stays `partial`, and the pinning test stays.**

Databento is the only priced route (USD 199–4,500/month, published); among the
incumbents, LSEG Tick History carries depth directly and WRDS can deliver it through the
separate NYSE Integrated Feed. The free ITCH and LOBSTER samples would demonstrate a
partial fill and change no result the platform has produced, because the backtests run on
daily bars. FR-19 is honestly described today, pinned by a test, and the right thing to
do with it is nothing.

---

## What this found in the project's own record

Two things, both from checking rather than recalling:

**`docs/REQUIREMENTS.md` and the README both state that EDGAR publishes no delisting
date.** It is true of the bulk company-facts archive and false of EDGAR, where delisting is
Form 25 and Form 25-NSE with a filed date, a rule provision and a ten-day statutory
effective date. The sentence needs its scope made explicit rather than deleted — the caveat
about `last_filing` being a proxy is correct and should stay until the mirror exists. The
same sentence appears in the `listing_status()` docstring in
`src/research_integrity/ingest.py`. No status changes; the prose does.

**The assumption that this class of data costs five figures went unchecked.** It is right
for CRSP and it is wrong by two orders of magnitude for the smallest vendor that closes the
same three requirements. The thing that actually disqualifies the cheap option is its
licence, not its price — which is only visible because the price was looked up instead of
assumed.

---

## What would change this decision

- **PRD 04 arriving in the repository**, if §5.1 turns out to say something about FR-04 or
  FR-05 that the reconstruction in `docs/REQUIREMENTS.md` cannot see.
- **A vendor offering terms that survive termination** — a perpetual licence to a dated
  snapshot rather than access for the term. That single change would remove the FR-23
  objection from Option 1 and from Norgate, and it is the one term worth asking for in any
  sales conversation this decision would otherwise avoid.
- **The engine growing a message-resolution path.** If a backtest ever runs on ticks rather
  than daily bars, free ITCH samples stop being a status change that moves no result and
  become a real one, and FR-19's answer changes with it.
- **Measuring Form 25 coverage against a known list of delistings.** This page verified that
  the filings exist in volume across three eras; it did not establish completeness, and
  nothing here should be read as if it had.

---

## Sources

Licence and regulatory text:

- CRSP Standard Data Subscription Agreement — <https://library.ucsd.edu/_files/license-agreements/CRSP9-14.pdf>
- WRDS Terms of Use — <https://wrds-www.wharton.upenn.edu/users/tou/>
- S&P Global Academic Research Essentials — <https://spre.wharton.upenn.edu/>
- Norgate Data Licence Agreement — <https://norgatedata.com/subscribe/eula.php>
- 17 CFR § 240.12d2-2, Removal from listing and registration — <https://www.law.cornell.edu/cfr/text/17/240.12d2-2>
- SEC Form 25 — <https://www.sec.gov/files/form25.pdf>

Prices, coverage and corporate facts:

- Norgate Data stock market packages — <https://norgatedata.com/stockmarketpackages.php>
- Norgate Data content tables — <https://norgatedata.com/data-content-tables.php>
- Databento pricing — <https://databento.com/pricing>
- Databento US equities — <https://databento.com/blog/introducing-databento-us-equities>
- CRSP subscription information (no published price) — <https://www.crsp.org/subscription-information/>
- Morningstar completes acquisition of CRSP, 2026-02-02 — <https://newsroom.morningstar.com/news/news-details/2026/Morningstar-Completes-Acquisition-of-CRSP-and-Extends-Relationship-with-Vanguard/default.aspx>
- Morningstar rebrands CRSP Market Indexes, July 2026 — <https://newsroom.morningstar.com/news/news-details/2026/Morningstar-Completes-Rebrand-of-CRSP-Market-Indexes-to-Morningstar-Market-Indexes/default.aspx>
- CRSP S&P 500 constituents via WRDS (`dsp500list`/`msp500list`) — <https://wrds-www.wharton.upenn.edu/pages/grid-items/downloading-the-sp-500-constituents/>
- SPDJI constituent names withdrawn from Compustat, July 2020 — <https://library.smu.edu.sg/topics-insights/notes-and-thoughts-retrieving-historical-members-sp-500-wrds>
- CRSP US Stock Databases, coverage by exchange — <https://www.crsp.uchicago.edu/products/research-products/crsp-us-stock-databases>
- LSEG Tick History factsheet (market depth back to January 1996) — <https://www.lseg.com/content/dam/data-analytics/en_us/documents/fact-sheets/final_re2664707_ent_tick_history_factsheet_a4_v4_web.pdf>
- NYSE Daily TAQ (trades, quotes, NBBO) — <https://www.nyse.com/market-data/historical/daily-taq>
- Form N-PORT public-release timing and the 2026 proposal — <https://www.federalregister.gov/documents/2026/02/23/2026-03460/form-n-port-reporting> and <https://www.sec.gov/newsroom/press-releases/2026-19-sec-proposes-amendments-reduce-burdens-reporting-fund-portfolio-holdings>
- LOBSTER free order-book samples — <https://homepage.univie.ac.at/nikolaus.hautsch/lobster.html>
- Nasdaq Historical TotalView-ITCH — <https://www.nasdaqtrader.com/trader.aspx?id=itch>
- Shumway, T. (1997), *The Delisting Bias in CRSP Data*, Journal of Finance 52(1) — <https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1997.tb03818.x>
- SEC EDGAR access policy (declared User-Agent required) — <https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data>

Measurements taken 2026-08-30, each reproducible:

```
# 384 / 393 / 618 delisting notifications per quarter
curl -A "<contact>" https://www.sec.gov/Archives/edgar/full-index/2023/QTR1/form.idx \
  | awk '{print $1}' | grep -cE '^(25|25-NSE)$'

# BBBY: Form 25-NSE filed 2023-07-10, last_filing proxy 2023-12-04
curl -A "<contact>" https://data.sec.gov/submissions/CIK0000886158.json
curl -A "<contact>" https://www.sec.gov/Archives/edgar/data/886158/000135445723000478/primary_doc.xml

# Apple FY2013 EPS: 40.03 filed 2013-10-30, 5.72 filed 2014-10-27
curl -A "<contact>" https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/EarningsPerShareBasic.json

# 65 split-ratio reporters vs 6,582 equity reporters, CY2014Q2
curl -A "<contact>" https://data.sec.gov/api/xbrl/frames/us-gaap/StockholdersEquityNoteStockSplitConversionRatio1/pure/CY2014Q2I.json
curl -A "<contact>" https://data.sec.gov/api/xbrl/frames/us-gaap/StockholdersEquity/USD/CY2014Q2I.json
```
