# 14 — Momentum: The One Externally-Corroborated Edge (July 2026)

Every option-based approach in this project failed for the same structural
reason (docs/10–13): the variance risk premium is real but lives in the tail,
and a ₹1–5 lakh account cannot reach it. This document records the one direction
that does **not** hit that wall — and is corroborated by a source outside this
project.

## Why this one is different

Two independent research efforts reached the identical conclusion:

1. **This project's own deep-research pass** (July 2026) found that the single
   strongest, primary-source-backed edge in Indian equities is **momentum**, not
   option premium.
2. **An external framework** (Investors Way, "Complete Swing Trading Framework",
   17 April 2026), supplied by the owner, reached the same finding from different
   sources and — unusually for retail content — is honest about its own limits:
   it warns against 80%+ win-rate claims, flags survivorship bias and
   overfitting, insists on forward-testing, and admits it could not find a
   verifiable trade-level backtest for its own breakout variants.

Convergence from two independent directions is the strongest signal this project
has produced. It is worth acting on precisely because neither side is selling it.

## The number, and its source

**NIFTY 200 Momentum 30 Index: ~19.3% CAGR vs ~14% for the Nifty 200 over
2005–2025** (NSE Indices methodology; cited via HDFC AMC's Oct-2025 leaflet and
corroborated by the project's own research). The index's live-attempt Sharpe is
roughly 1.3.

Two caveats attached to that number, both load-bearing:

- **A large part of the pre-2015 track record is backtested** — the index
  launched later. NSE's own whitepaper says so.
- **The 15.98% "since 2009" figures that circulate are period-dependent
  artifacts** measured from the post-GFC trough. Use the full-history 14–19% band.

## The honest tension — read this before doing anything

The owner's revised mandate is **≥15% net, and capital preservation matters.**
Momentum meets the first and strains the second:

| | Momentum 30 | The owner's constraint |
|---|---|---|
| Return | ~19% CAGR gross, ~12–16% net of costs/tax | ≥15% ✓ |
| **Max drawdown** | **~30–35%** (2008, 2020, 2022) | "cannot lose a large fraction" ✗ |

A 30% drawdown **is** losing a large fraction, temporarily. This is not a defect
to engineer away — it is the price of the return. The **200-day regime filter**
(hold cash whenever the index is below its 200-DMA) roughly **halves** the
drawdown, per both the framework and Raju & Chandrasekaran (2019). On this
project's synthetic validation it cut a modelled drawdown from 30.8% to 23.8%.
Even filtered, expect 15–20% drawdowns. There is no version of this that returns
19% and never falls 15%.

## What was built

A cost-honest, tested momentum backtest, in the same style as the rest of the
project (correct infrastructure first; real numbers when the data is in hand):

- [`src/optionsbot/data/equity.py`](../src/optionsbot/data/equity.py) — daily
  price `Series` with the lookback-return and volatility helpers the score is
  built from.
- [`src/optionsbot/research/momentum.py`](../src/optionsbot/research/momentum.py)
  — the NSE methodology: two volatility-adjusted returns (6M, 12M), z-scored
  across the universe and averaged; top-N equal-weight; monthly rebalance;
  optional 200-DMA regime filter; delivery-equity cost model (STT both sides,
  stamp buy-only, GST on the right base, plus slippage) landing at ~30 bps round
  trip. Metrics: CAGR, **max drawdown %** (the first-class number), Sharpe,
  turnover.
- [`src/optionsbot/research/run_momentum.py`](../src/optionsbot/research/run_momentum.py)
  — driver over a directory of `<SYMBOL>.csv` daily files.
- [`tests/test_momentum.py`](../tests/test_momentum.py) — 10 tests, every
  building block pinned to a hand-computed value; the strategy tests pin ranking,
  value conservation, and that the regime filter forces cash.

## What has NOT been done, and must be, before believing any number

**The backtest has not been run on real Nifty 200 data — none exists in this
repo.** The verdict is only as honest as the universe fed to it:

1. **Data — the fetcher now exists.** `optionsbot.data.bhavcopy.fetch_equity_day`
   pulls NSE's cash-segment UDiFF file (verified live: 2,386 EQ stocks on
   2026-07-16), and `python -m optionsbot.data.fetch_equity <start> <end> <dir>
   --universe <list>` writes the per-symbol `date,close` files the backtest
   reads. What is still missing is a **benchmark index series** for the regime
   filter (the CM file has stocks, not indices — source NIFTY 50 separately) and
   the universe list below.
2. **Survivorship bias — the code half is now done; only the data remains.** The
   backtest accepts a **point-in-time membership schedule** (`backtest(...,
   membership=...)`, loaded from dated `YYYY-MM-DD.txt` index snapshots via
   `equity.load_membership`; `run_momentum --membership <dir>`). With it, each
   rebalance picks from the index as it actually stood then, so stocks that fell
   out — the failures — are included over the span they were members and dropped
   after. Without it, the whole supplied universe is eligible on every date,
   which silently keeps only survivors and overstates the result. The remaining
   input is the schedule itself: NSE reconstitutes the Nifty 200 semi-annually,
   so ~2 snapshots/year reconstructed from its reconstitution circulars is
   enough. Until that schedule is supplied, every run is an optimistic ceiling
   and is labelled so in the driver output.
3. **STCG tax is not modelled.** The backtest is gross of tax; short-term equity
   gains are taxed at the prevailing rate (15% historically). Apply that haircut
   to the CAGR for a net figure.
4. **Forward-test before funding.** This is exactly the case the forward-
   evaluation harness (docs/13, RUN §5b) exists for: run it on data it was never
   fitted to before a rupee is at risk. Every positive backtest in this project's
   history dissolved on inspection; this one has not yet earned an exception.

## The three ways to act on this

1. **Simplest, and what the evidence best supports: buy the index fund.** The
   HDFC NIFTY 200 Momentum 30 Index Fund *is* the strategy, professionally run —
   zero code, zero execution risk, ~12–16% net at ~30% drawdown. "Automated" in
   the truest sense.
2. **The bot the owner asked for:** the rules above, automated on this repo's
   infrastructure. Real, buildable, and the harness generalises to it — but it is
   an equity strategy, so it needs the equity data path and a point-in-time
   universe before its numbers mean anything.
3. **Forward-test first, decide later.** Run it live in shadow for months, then
   choose. Costs nothing but time, and it is the only test this project's history
   says can be trusted.

The mandate as originally written (₹1 lakh, 20–25%, 5–10% drawdown, options) was
refuted. Momentum is the honest answer to the *revised* question (₹3–5 lakh,
≥15%, automated) — provided the owner accepts the drawdown that comes with it.
That trade-off, not the code, is the decision.

## Exploratory run on real data — and the data-source ceiling it exposed

The pipeline was run end to end on **real NSE cash-segment data** (July 2026).
The result is not a verdict, and the reason it cannot be is itself the finding.

**Free NSE UDiFF equity EOD only reaches back to about January 2024.** A fetch
requested from 2021 returned data only from 2024-01-01 — 625 sessions, ~2.5
years. After the 12-month momentum lookback, that leaves roughly **1.5 years of
backtest (2025-01 to 2026-07, 31 rebalances)** — far too short to say anything
about a strategy whose entire claim rests on 20-year behaviour across multiple
drawdowns.

On that short, survivorship-biased slice (universe = the 200 most-liquid stocks
present throughout; benchmark = a crude equal-weight proxy, since the cash file
carries no index), on ₹5,00,000:

| | CAGR | max DD | Sharpe |
|---|---:|---:|---:|
| No regime filter | **+4.58%** | 14.9% | 0.39 |
| 200-DMA regime filter | **−1.83%** | 17.5% | −0.12 |

**This says essentially nothing about the strategy** — one regime, 1.5 years,
survivorship bias, a crude proxy index (which sent the filter to cash 8 of 31
times, hurting it), and gross of STCG. It is a *mechanics check*, and the
mechanics are sound. It is **not** the ~19% CAGR the framework cites, and it
cannot be, because the window is 1/13th the length that number is built on.

**The load-bearing conclusion:** the ~19% / ~30%-drawdown momentum figure rests
on NSE's OWN published 20-year index (the Nifty200 Momentum 30) — a primary
source, and the most credible claim this project has encountered, precisely
because the exchange runs the index and a real fund tracks it. But **we cannot
independently reproduce it on free data**, because free NSE equity history does
not go back far enough. Independent verification would need paid long-history
data; the pre-2024 legacy NSE bhavcopy format was retired.

So the honest options narrow to three, unchanged by this run:
- **Trust NSE's published index** (reasonable — it is the exchange's own
  methodology, not a vendor's backtest) and **buy the fund**. Simplest, and what
  the evidence best supports.
- **Buy paid long-history equity data** and run the real backtest here — the
  toolchain is built and proven; only the data is missing. (Angel One's
  SmartAPI `getCandleData` is a partial free route: `fetch_angel_history` pulls
  daily candles back further than the UDiFF, from the whitelisted box, when no
  live session holds the token. It still needs a point-in-time universe to be a
  verdict rather than a ceiling.)
- **Forward-test live** from today and accumulate your own record, which is the
  one form of evidence this project has shown can always be trusted.
