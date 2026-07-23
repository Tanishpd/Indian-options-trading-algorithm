# 14 — Momentum: The One Externally-Corroborated Edge (July 2026)

> **Disclaimer:** Educational/research only — **not investment advice**, and the author is **not SEBI-registered**. All figures below are **backtested and hypothetical** (some partial or biased, as noted); **past performance does not guarantee future results**. Named funds/securities are **illustrative, not recommendations**. See [DISCLAIMER.md](../DISCLAIMER.md).

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
(hold cash whenever the index is below its 200-DMA) reduces the drawdown, per the
framework, Raju & Chandrasekaran (2019), and — now — this project's own backtest
on real data (below). There is no version of this that returns ~20% and never
falls ~20%.

## The real backtest (July 2026) — measured on this project's own data

Run on ₹5,00,000 over **2017-01-02 → 2026-07-16 (9.5 years, 115 monthly
rebalances)**, using Angel One daily history for 254 of the 258 stocks that were
ever in the Nifty 200 over 2022–2026, with point-in-time membership applied from
2022-09-30 (the free NSE reconstruction) and the **real NIFTY 50** as the regime
benchmark:

| Configuration | CAGR | Max DD | Sharpe |
|---|---:|---:|---:|
| Fixed universe (survivorship-biased ceiling) | 34.1% | 28.1% | 1.64 |
| Fixed universe + regime | 24.8% | 29.4% | 1.41 |
| **Point-in-time, no regime** | **29.9%** | 28.1% | 1.51 |
| **Point-in-time + real regime filter** | **23.6%** | **21.3%** | **1.51** |

What this establishes, honestly:

1. **Survivorship bias is real and measurable.** Correcting it (fixed → PIT) took
   the raw 34.1% down to 29.9% — a ~4-point overstatement, concentrated in the
   2022+ window where the membership schedule applies. Raw backtests overstate.
2. **The edge survives the correction.** Even PIT-corrected, momentum returns
   ~24–30% CAGR gross — well above the 15% target and NIFTY's ~12%. This is the
   strongest evidence in the project that a reachable edge exists.
3. **The regime filter works, and Sharpe reveals why.** With the *real* index (a
   first attempt with a crude equal-weight proxy gave bad signals and did not
   help), the filter cut max drawdown **28.1% → 21.3%** for ~6 points of CAGR,
   holding **Sharpe flat at 1.51** — it trades return for drawdown one-for-one in
   risk-adjusted terms, which is exactly a regime filter's job. Note the framework's
   "halves the drawdown" is overstated: the real reduction here is ~24%, not 50%.

Caveats that keep this short of a final verdict, none of them small:

- **Only 2022+ is point-in-time-clean.** The earlier ~5 years still fall back to
  the survivorship-biased union universe, so the true long-run CAGR is likely
  somewhat below 23.6%, and the pre-2022 span also misses stocks that left the
  index before 2022 (a deeper survivorship layer).
- **Gross of STCG.** ~115 round trips at monthly turnover; short-term
  capital-gains tax pulls the ~23.6% down toward the high-teens net, possibly
  lower — the single largest unmodelled haircut.
- **21% is still a real drawdown.** Better than 28%, but "capital preservation
  matters" and a one-fifth temporary loss is not nothing.


### RSI overlay — tested, and it does not help

A natural question (does adding an RSI filter to momentum improve it?) was tested
directly, with the same discipline: a **pre-specified** variant set, judged on the
**out-of-sample** 2022-09+ window, not a threshold sweep with the best kept.

All on the best base config (PIT membership, real NIFTY 50 regime filter, ₹5L,
gross of STCG):

| Overlay | Full CAGR | Full maxDD | Sharpe | Holdout CAGR |
|---|---:|---:|---:|---:|
| **none (base momentum)** | **23.6%** | 21.3% | **1.51** | 25.1% |
| RSI-14 avoid > 90 | 23.8% | 21.3% | 1.52 | 25.1% |
| RSI-14 avoid > 80 | 22.8% | 21.5% | 1.46 | 23.6% |
| RSI-14 avoid > 70 | 20.8% | 19.5% | 1.38 | 23.9% |
| RSI-14 band 55–80 | 16.2% | 29.3% | 1.12 | 22.3% |
| RSI-2 avoid > 95 | 21.8% | 18.5% | 1.43 | 24.8% |

**No overlay beats base momentum on a risk-adjusted basis** — base has the highest
Sharpe (1.51), and every RSI variant is below it, both full-period and
out-of-sample. There is a clean reason, not just a data quirk: **momentum works
because winners keep winning**, and the strongest stocks are by construction
"overbought" on RSI. RSI's job is to flag exactly those and tell you to avoid them,
so the two signals fight — RSI sells the stocks momentum wants to hold. The
literature treats them as opposing, and this data confirms it.

Two traps the discipline caught:
- **RSI-14 avoid > 90 "wins" (23.8% vs 23.6%) — that is noise.** RSI above 90 barely
  excludes anything, so it is ~identical to base; the 0.2 point gap is meaningless.
  It is precisely the false find a "keep the best backtest" search would have kept.
- **Tighter filters (> 70, RSI-2 > 95) do cut drawdown** (21.3% → ~19/18.5%) — but
  they cut return more, so Sharpe falls. Not a free lunch, and the regime filter is
  already the better drawdown tool.

The RSI overlay is in the code (`MomentumParams.rsi_min/rsi_max`, opt-in, off by
default) so the result is reproducible, but the finding is: **base momentum with
the regime filter is the best configuration; RSI does not improve it.**

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

## The decision: fund vs bot

The strategy question is now answered. Momentum on Indian equities is a real,
reachable edge that beats the target, and the regime filter provides real (if
overstated-by-the-framework) drawdown protection. What remains is *how to hold
it* — and the two options deliver nearly the same economics:

**Option A — buy the fund.** The HDFC NIFTY 200 Momentum 30 Index Fund *is* this
strategy, professionally run. Zero code, zero execution risk, **no STCG drag**
(a fund rebalances internally without triggering your capital-gains tax on every
rotation — this alone is worth several points a year versus running it yourself),
zero tax-lot bookkeeping. ~12–16% net at ~25–30% drawdown. "Automated" in the
truest sense: you never touch it.

**Option B — run the bot.** The rules above on this repo's infrastructure. The
code is built, tested, and shipped; the data path is proven; the point-in-time
universe is reconstructed. But: **you pay STCG on every monthly rotation** (the
biggest reason B nets less than A), you carry execution and outage risk, and you
own the tax-lot accounting. Its one genuine advantage over the fund is *control*
— you can tune the regime filter, the universe, the rebalance cadence — which
matters only if you have a specific improvement in mind and the discipline to
forward-test it before trusting it.

**The honest recommendation:** unless you specifically want to tune the strategy,
**Option A wins on the numbers** — the fund's internal-rebalancing tax advantage
alone roughly cancels the bot's control advantage, and it removes every
operational risk. Build the bot if the *building* is the point (learning, control,
a thesis to test); buy the fund if the *returns* are the point.

**Option C, and the only test this project's history fully trusts — forward-test
first.** Whichever you lean toward, the shadow harness (docs/13) can run the
momentum bot live for months against data it was never fitted to, before a rupee
is committed. Every positive backtest in this project dissolved on inspection;
this one is the strongest yet, but it has not earned an exception to that rule.

The mandate as originally written (₹1 lakh, 20–25%, 5–10% drawdown, options) was
refuted. Momentum is the honest answer to the *revised* question (₹3–5 lakh,
≥15%, automated) — **provided the owner accepts a ~21% drawdown and the tax drag.**
That trade-off, not the code, is the decision, and it is now the owner's alone to
make.

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
