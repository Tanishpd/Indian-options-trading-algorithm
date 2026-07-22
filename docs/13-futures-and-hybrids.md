# 13 — Single Stocks, Futures, and the Hedged Hybrid (July 2026)

[docs/12](12-where-the-edge-actually-is.md) established that the variance risk
premium is real, large, and entirely tail insurance — and that a defined-risk
structure is a net *buyer* of the only part of the surface that pays.

This document records the three families tested after that, each proposed
because it attacked a different part of that mechanism. All three fail, and
together they close the space with an argument rather than an accumulation of
negative results.

**The single most important thing here is not a failure — it is the
[naked-strangle trap](#the-trap-a-result-that-passes-every-test-and-would-ruin-you)
in the last section. It clears the return target, passes every statistical test
this project applies, and would destroy the account.**

## 1. Single-stock options — killed by delivery margin

The motivation was sound and attacked the binding constraint directly: NIFTY's
risk quantum (50-point strikes × lot 65 = **₹3,250**) exceeds a ₹2,000 per-trade
cap, forcing near-ATM strikes where there is no premium. Stock options have
entirely different lot sizes and strike grids, so their quantum might be smaller.

**It is smaller — 4 of 210 underlyings are below ₹2,000 — and liquidity passes
cleanly** (INFY trades ~21,900 contracts/day at 2–3% OTM, 100% of strikes live).
That was the screen most expected to fail, and it didn't.

**What kills it is physical settlement.** Indian single-stock F&O is physically
settled, and delivery margin is levied as a percentage of **contract value**
(₹4.3–8.5 lakh), not of the spread's ₹2,000 risk — and **separately per leg, with
no spread netting**:

| | Requirement | Against a ₹1,00,000 account |
|---|---|---|
| E-1 (one session before expiry) | 25% of contract value | **₹1.09L–₹2.13L = 1.1–2.1×** |
| Expiry day | 50% of contract value | **2.2–4.3×** |
| E-2 | ~10% of contract value | ₹43k–85k = 43–85% |

So positions **must** be closed by E-2. That forces exit exactly when premium
decay is richest — the VRP is +1.96 vol points at 2 DTE versus +1.06 at 4 DTE —
so the structure is barred by margin rules from the most profitable part of its
own holding period. It also doubles the order count (2 → 4 for a vertical) and
drops the cycle count to ~13/yr versus 52.

**The deciding ratio for a monthly family**: 15%/yr at 2% risk needs
**57.7% per cycle**. Measured: **4.73%**. Short by 12×.

Honest backtest: n=18, +₹1,628, **+1.23%/yr**, t = +0.55, bootstrap CI spans
zero, train +₹2,642 → holdout −₹1,014. **Sign flip. Failure.**

### The data-quality finding — `volume > 0` is not enough

Ungated, the same configuration showed **+13.98%/yr**, right at target. Ninety
percent of it came from **one trade**: a TVSMOTOR put closing at 68.00 on **four
contracts**, while its own settlement was 31.05 and the neighbouring strike with
1,202 contracts was 59.05. That fabricated a ₹19.30 credit on a 20-point spread —
an implied 96% chance of finishing ITM on a put 3.7% out of the money.

With a three-part gate (minimum contracts, chain monotonicity against lattice
neighbours, close within 50% of settlement): **+13.98%/yr → −9.92%/yr.**

**Any stock-option spread result computed without such a gate should be
discarded.** The existing `0 < credit < width` bound check does not catch it.

## 2. Outright futures — you cannot size down

Futures are a genuinely different question: no premium structure at all, so the
tail-insurance mechanism does not apply. What applies instead is contract size.

One NIFTY futures lot is **65 × ~24,200 = ₹15.73 lakh of notional exposure**
against ₹1.78 lakh of margin (verified 22 July 2026). **P&L accrues on the
notional, not on the margin posted**, which is the point most often misunderstood:

```
NIFTY falls 10%. You lose Rs 1,57,300 --
  whether you posted Rs 1.78L, Rs 3L, or Rs 5L of margin.
```

Posting more margin does not reduce exposure. It only buys staying power before
forced liquidation:

| Capital | Exposure | Survives an adverse move of |
|---|---|---|
| ₹3.0L | 5.2× | **7.8%** |
| ₹5.0L | 3.1× | 20.5% |
| ₹10.0L | 1.6× | 52.3% |
| ₹15.7L | **1.0×** | 88.7% |

**To be genuinely unleveraged you need ₹15.73 lakh** — enough to own the notional
outright. Below that, the contract size sets your leverage regardless of how you
fund it. This is the risk quantum again: with options the minimum risk unit
(₹3,250) exceeded the cap; with futures the minimum exposure (₹15.73L) exceeds
the account.

One genuine advantage, worth recording: **index futures permit shorting**, which
cash equities do not for retail. That removes the constraint which made the
peer-reviewed momentum premium (a long-short construct) unreachable. The problem
is position size, not direction or edge.

## 3. The hedged hybrid — and why hedging destroys the premium

The best idea tested after docs/12: sell options to collect the real ATM premium,
and neutralise the direction with futures. It targets the +₹1,722–2,412/cycle
that genuinely exists, and it does *not* buy the tail to define risk — futures do
the hedging. It escapes the trap that killed the condors.

**Decomposition of a delta-hedged short straddle, 72 cycles, 15-minute rehedge:**

| | net/cycle | t | hedge trades |
|---|---:|---:|---:|
| fractional lots, zero cost | +₹2,034 | 2.32 | 72.1 |
| + whole-lot rounding | +₹1,419 | 1.15 | 4.3 |
| **+ real friction** | **+₹75** | **0.06** | 4.3 |

**Futures STT is levied on notional (₹15.73L), not on premium.** One hedge round
trip costs **₹500** — ₹972 after April 2026 — which is **13× an option round
trip**. Friction consumed ₹1,344 of ₹2,034 across only 4.3 trades. Capturing the
theoretical ceiling needs 72 hedge trades, costing ₹36,000–70,000 against ₹2,034
of edge.

**The quantum trap appears a third time.** A one-lot short straddle's fractional
hedge target never leaves (−1, +1) lots, so with lot 65 the only reachable hedge
states are **−1, 0, +1** — a three-state hedge for a continuous problem, peak
residual 108 shares. Delta bands of ≥1.0 lot never fired once in 72 cycles:
numerically identical to not hedging.

### The mechanism — hedging loses even frictionless

This is the finding worth keeping. Setting futures slippage to **zero** moved the
strangle's 15-minute net from +₹804 to +₹837 — essentially nothing. The rank
correlation between hedge activity and net P&L is **−0.846**; the optimising
rehedge frequency is *never*. Option gross falls from +₹2,241 unhedged to
₹1,473–1,607 hedged, and hedging **worsened 42 of 72 cycles**.

> **The delta hedge removes the tail exposure, and removes the premium with it.**

That is docs/12's mechanism seen from the other side. Condors failed as *buyers*
of the tail; the hedged straddle fails as a *seller who hands it back*. The
premium **is** payment for bearing tail risk — hedging away the risk necessarily
hedges away the payment.

**No capital level fixes this**: the cost/edge ratio is size-invariant (both scale
with lots), and the mechanism is negative before costs.

Covered structures (−₹932/cycle) and collars (−₹3,394/cycle, CI entirely below
zero) are closed on the same evidence.

A measurement caveat worth recording: hedge P&L cannot be computed to the needed
precision from spot. Day-over-day basis standard deviation of 39 points is
₹3,577/lot/cycle of noise — **3.8× the best variant's entire net**.

## The trap: a result that passes every test and would ruin you

The unhedged control — a **naked strangle** — clears the target:

```
+Rs 2,069/cycle | 21.5%/yr on Rs 5L | t = 2.49 | holdout HOLDS
```

It passes every statistical test this project applies, including the ones that
killed six earlier candidates. **It is the most dangerous result in this
repository.**

```
worst gap observed in the 17-month sample:   -3.86%
a  -5% gap loses  Rs   65,095
a -10% gap loses  Rs  152,951
a -20% gap loses  Rs  334,989   <- more than an entire Rs 3,00,000 account
NIFTY fell 13.0% in a single day on 2020-03-23
```

That 21.5% is **unearned insurance premium, not edge**. The window is 17 months
at mean India VIX 13.89 — the 21st percentile — during which no claim arrived.
Run it through four quiet years and it looks like genius; one March 2020 ends the
account, plus a margin call on the way down.

**The lesson generalises beyond this strategy: standard statistical tests cannot
distinguish a real edge from insurance that has not yet paid out.** t-statistics,
bootstrap intervals and holdout splits all measure the *observed* distribution,
and the whole risk of short-gamma positions lives in the part not yet observed.

This is precisely why the original mandate banned naked short options
([docs/01](01-strategy.md)), and that judgement was correct.

## What this closes

Every premium strategy must answer one question: **who bears the tail?**

| Approach | Result |
|---|---|
| **Buy the tail** to define risk (condors, spreads, butterflies) | Pays for the only part that pays. Dead — docs/12. |
| **Hedge the tail away** with futures | The hedge removes the exposure *and* the premium. Rank correlation −0.846. Dead. |
| **Bear the tail naked** | Captures the real premium — and one gap beyond 3.86% exceeds the account. Not dead; *undead*. |

There is no fourth option, because that trichotomy is what a premium *is*:
payment for bearing tail risk. At ₹3–5 lakh the tail cannot be borne, so the
payment cannot be collected.

That is a structural argument, not a search result — which is why further
parameter searching can only produce noise. Six times in this project a search
produced a positive result that dissolved on inspection; the naked strangle above
is the seventh and the most convincing of them.

## Limits

72–77 cycles of one index over 17 crisis-free months. This cannot rule out
event-conditioned or regime-specific behaviour beyond what
[docs/12](12-where-the-edge-actually-is.md) already tested, and it says nothing
about capital levels above ₹15.7 lakh, where futures become genuinely
unleveraged and the arithmetic changes.

It does establish that at ₹1–5 lakh, no premium-selling structure — defined-risk,
hedged, or naked — is both profitable and survivable.
