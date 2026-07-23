# 12 — Where the Edge Actually Is (July 2026)

> **Disclaimer:** Educational/research only — **not investment advice**, and the author is **not SEBI-registered**. All figures below are **backtested and hypothetical** (some partial or biased, as noted); **past performance does not guarantee future results**. Named funds/securities are **illustrative, not recommendations**. See [DISCLAIMER.md](../DISCLAIMER.md).

Two studies said the strategy loses ([docs/10](10-first-backtest-findings.md),
[docs/11](11-intraday-backtest-findings.md)). Both explained it with a mechanism
that is **wrong**. This document gives the right one and closes the question.

It exists because "we lost money" is not a finding. **"The premium is real, it is
large, it is stable, and it lives in a part of the surface the risk cap forbids us
from being short"** is a finding — it ends the parameter search instead of
inviting a tenth sweep.

## 1. Options are NOT priced efficiently

docs/10 concluded *"the options are priced efficiently — the premium collected
compensates precisely for the risk taken. There is no gross edge to harvest."*

Refuted. Implied volatility at entry against subsequently realised volatility to
expiry, 72 cycles:

| | 2 sessions to expiry | 4 sessions | 1 session |
|---|---|---|---|
| **Variance risk premium** | **+1.96 vol points** | +1.06 | +1.89 |
| t-statistic | **+3.76** | +2.02 | +3.01 |
| Bootstrap 95% CI | [+0.90, +2.91] | — | — |
| Cycles positive | **74%** | — | — |

Robust to the realised-vol estimator (1-min 12.42%, 5-min 12.60%, 30-min 12.55%),
so it is not an artifact of sampling frequency. **NIFTY options are systematically
overpriced, and the premium grows as expiry approaches.**

Independent corroboration: a preprint measuring 43M one-minute bars over
2022–2026 reports the VRP positive on 74.9% of days at +1.208 points, against our
independent 74% at +1.06. Convergent on the *measurement* — it says nothing about
tradeability and is not evidence of an exploitable edge (mandate rule 5).

### The edge is worth 7–10× the cost floor

Three independent methods agree on its size:

| Method | Per cycle |
|---|---|
| Zero-cost short ATM straddle, perfect fills | **+₹1,722** |
| Delta-hedged at 15-minute intervals | **+₹2,412** (t = +2.95) |
| Vega × measured (IV − RV) | **+₹2,182** |

Against a ₹230 cost floor. So the premium is not marginal. It is roughly ten times
what it costs to trade.

**Which makes the real question: why did every structure we built capture none of it?**

## 2. The answer: the entire premium is tail insurance

This is the central finding, and it needs no volatility model — just prices:

```
short ATM straddle              +Rs 1,722 / cycle
short ±500 strangle inside it   +Rs 1,750 / cycle
-------------------------------------------------
=> everything within ±500       +Rs    48 / cycle
```

**The tail is 102% of the straddle's edge.** Every rupee of premium in NIFTY
weeklies is compensation for tail risk. The body of the distribution — the region
a capped, defined-risk structure is confined to — pays essentially nothing.

Now apply that to what we were trading. **A defined-risk structure is short the
near strikes and long the far ones. It is a net *buyer* of the only part of the
surface that pays.** We were not failing to harvest the premium. We were paying it.

That is arithmetic, not a parameter failure, and it explains docs/10 and docs/11
mechanically. Corroborating evidence that this is structural rather than local:
Carr & Wu (2009, *Review of Financial Studies* 22(3)) find the SPX premium
"concentrated in the downside" and driven substantially by crash risk — the same
tail concentration, in a different market, twenty years earlier.

Direct confirmation, at zero cost and perfect fills:

- **ATM iron butterfly**: −₹27 (50-wide), −₹126 (100), −₹179 (200), −₹409 (300)
  per cycle — negative at every width, before a single rupee of cost.
- **36 condor configurations**: not one has a bootstrap 95% lower bound above the
  ₹230 cost floor.

## 3. Why the cap cannot reach the tail: the risk quantum

NIFTY strikes are 50 points apart (verified, zero exceptions across the sample)
and the lot is 65. So the **smallest possible width-based max loss is
50 × 65 = ₹3,250 — already above the ₹2,000 per-trade cap.**

Every NIFTY credit structure therefore needs credit ≥ ₹1,250, i.e. **38.5% of the
width, just to be legal.** Credit that rich exists only within ±200 points of ATM.

```
cap stops binding at   ~±200 from ATM
edge starts at         ~±400 from ATM
```

A dead zone between them, and a 50-point grid offers no intermediate structure.
Measured edge inside ±200: **−₹153 to +₹20 per cycle, every CI spanning zero.**

### Where the edge is real, and why it still fails

Far-OTM 50-wide condors at ±650/±700/±750:

| | ±650 | ±700 | ±750 |
|---|---|---|---|
| t-statistic, **gross** | +6.54 | +6.87 | +6.57 |
| t-statistic, **net** | **+2.89** | **+2.43** | **+1.38** (CI spans zero) |
| Net per cycle | +₹75 | +₹52 | +₹25 |
| Worst single cycle | **−₹463** | +₹132 | +₹132 |
| Paid out in | 1 of 72 | 0 of 72 | 0 of 72 |

> **Figures corrected 2026-07-22.** This table previously reported t-statistics
> of +4.04/+6.52/+6.33 without saying they were **gross-basis**; on net the ±750
> structure is not significant. It also reported a train→holdout of
> +₹1,296 → +₹1,107 against a ₹230 cost floor and a ₹48 net — which does not
> reconcile (1,107 − 230 = 877). The correct derivation is gross ₹148 − cost ₹97
> = **net ₹52**, independently re-derived over 369 grid cells. And "paid out in
> 0 of 72, worst cycle +₹132" was true at ±700/±750 but not at ±650, which paid
> out once at −₹463. The sign, the stability and the conclusion are unchanged;
> the numbers now reconcile.

**This is the only durable edge this project has found.** It is not luck, not an
outlier artifact, and it survives out of sample — unlike the ATM straddle edge,
which halves (train +₹2,964 → holdout +₹480).

Note what that means: **the stable part of the premium is precisely the part the
mandate cannot trade.**

Fully costed, the best surviving candidate (±650/700 condor, held to settlement,
4 orders) nets **+₹48/cycle ≈ 1.4%/yr at zero slippage**, with a median max loss
of ₹3,600 — **1.8× the cap**. Real, stable, and too small. And cap-legality is not
merely rare, it is **arithmetically unavailable**: the 8 of 71 cycles that appeared
"legal" were lot-25 artifacts from November–December 2024, before the lot rose.

### The ratio that settles it, independent of capital

With one structure at a time and max loss pinned at 2% of capital, annual return
is `(net / max loss) × 0.02 × 52`. So:

```
mandate needs      net / max-loss = 19.23% per cycle
best of 369 cells                    4.22%
structural ceiling                   5.14%
```

This is why nothing worked. More capital, more volatility, cheaper brokerage,
different expiries and every parameter sweep all leave that ratio roughly where it
is. The asymptote at ₹10 crore is **5.02%/yr — below the do-nothing floor** of
5.25–6.7%, so the strategy never clears 10%/yr at any capital and the compounding
question is vacuous.

## 4. Everything tested and closed

| Family | Result |
|---|---|
| NIFTY condor, hold to expiry | −₹16,740 / 71 trades (docs/10) |
| NIFTY condor, intraday triggers | −₹21,066 / 72 cycles (docs/11) |
| IV filters (absolute, and proper IV-rank walk-forward) | r = −0.016; every threshold loses in holdout |
| Cheaper execution | loses **even at ₹0 brokerage** (−₹7,472) |
| Wider wings | infeasible: required credit share rises with width |
| Trading less often | cost and capped opportunity both per-trade |
| 2-leg verticals | cost halves, max loss rises; 6/72 cycles fit |
| Raising the DD cap to 15% | **₹8,321 worse** — unblocks the worst cycles |
| 0-DTE ATM butterfly | −₹6,605 gross **before** costs, 77 cycles |
| Calendars | +₹612/trade gross, but 98% from 5 of 49 trades, sign-flips train→holdout, 49/49 breach the cap |
| **SENSEX credit structures** | **−₹26,560 condor, −₹6,168 vertical** |
| Non-option alternatives | futures need 1.8–2.3× the account as margin; SMA trend filters lose at all six lengths |

**SENSEX deserves a note**, because it was the strongest structural lead. Lot 20 ×
100-point strikes = a risk quantum of **exactly ₹2,000** — verified from live BSE
bhavcopy — so the cap stops binding and a genuinely OTM short becomes legal. That
is the one place the quantum trap disappears.

The quantum relief is real, and better than expected: friction is **4.9–5.3% of
the ₹2,000 risk against NIFTY's 18.0%**. But friction/risk is the wrong ratio.
**Friction/credit is binding, and at 3% out it is 283%**: the SENSEX 100-point
condor at the distance where the NIFTY edge lives collects a median credit of
**₹35 against ₹99 of friction — −₹64/cycle before the market moves at all**,
across 77 cycles. That is a feasibility floor, not a backtest. No edge rescues a
structure whose credit is below its fee.

Liquidity is not the excuse: 100% of contracts trade out to 5% OTM, median 97,363
lots at 3%. And this is the *optimistic* case — it assumes hold-to-settlement.
Active closing doubles friction to ~₹190 and every band except ~1% goes negative.

## 5. The drawdown cap was never the problem

docs/10 and docs/11 both presented the 21–23% drawdown as an *independent* failure.
It is not — it follows from the negative mean. Bootstrapping the same per-trade
distribution shifted only so the strategy earns 20%/yr, keeping its exact variance:

| | |
|---|---|
| Median 1-year max drawdown | **3.4%** |
| P(drawdown ≤ 10%) | **99.7%** |

There is **one** problem, the mean, not two. **The risk architecture works. Do not
redesign the kill-switch, the per-trade cap, or the position rules in response to
these results.**

## 6. What the mandate actually asks for

Stated as a risk-adjusted target rather than a return:

> 22.5% net at a 10% maximum drawdown implies a Sharpe ratio near **1.9**.
> At a 5% cap, near **3.4**.
>
> Renaissance Technologies' Medallion fund ran **1.89**.

The mandate as written asks for Medallion — from ₹1 lakh, retail, automated, on
weekly index spreads. That is the honest scale of the ask, and it was not visible
at the start of this project.

Capital does not fix it. ~₹5 lakh makes the tail condor cap-legal, and it still
yields ~1.4%/yr. A sub-₹15-lakh-notional index contract would change the
arithmetic, but SEBI's minimum contract value forbids one and mini contracts were
discontinued in 2012.

**The do-nothing floor is 5.25–6.7% at near-zero drawdown.**

## 7. Limits of this analysis

72–77 cycles of one index over 17 months, in a **crisis-free, unusually quiet
window** — mean India VIX 13.89, the 21st percentile of 2010–2023, with July 2025
to February 2026 at the 4.8th percentile.

This cannot rule out:

- a volatility regime unlike 2024–26 (though the condor's short vega *falls* as
  vol rises — ₹115.4 → ₹71.7 per point at 1.32× IV — so stacking long-run vol
  *and* the optimistic VRP bound still gives only 0.53× of what the mandate needs)
- intraday SENSEX behaviour — only EOD was tested, and no retail intraday SENSEX
  history exists (docs/01), so SENSEX entry timing, spread and fill realism are
  permanently unmeasurable. BSE also publishes settlement = close for the entire
  front chain, removing a cross-check NIFTY has.
- an edge too small to detect at n = 72 — but anything that small cannot fund a
  20% target either
- extreme volatility: only 25 of 1,619 sessions ever had VIX above 43, and the
  one window where cap and edge were jointly satisfiable is 6 cycles inside 49
  days of 2020, two of which lost

**Closed since this document was first written** (2026-07-22):

- **Event-conditioned entry is a genuine null**, not an underpowered one. Implied
  vol is bid up **+2.38 vol points** before FOMC/RBI/Budget — and realised vol
  rises **+2.33** alongside it. Net premium difference **+0.05 points,
  permutation p = 0.965**, with buckets adequately powered (MDE₈₀ ₹289–301 against
  the ₹619 the mandate needs). Event conditioning also cuts frequency 6×, so it
  *lowers* annual return.
- **A higher-volatility regime hurts, it does not help.** Over **6.5 years and 339
  cycles spanning VIX 9–84**, premium scales with volatility almost perfectly
  (r = +0.939) but realised P&L does not (r = +0.020). At constant delta the
  condor nets −₹58/−₹58/−₹56 across low/mid/high vol terciles, and **−₹370/cycle
  above VIX 25.** Waiting for a better regime is not a strategy.
- **The crisis risk is a run, not a single cycle.** Worst 4-cycle window:
  **−₹6,995 = 7% of the account.**

What it does establish: **harvesting the variance risk premium with defined-risk
index spreads at ₹1 lakh is refuted** — not by a noisy backtest, but by a
decomposition showing the premium sits entirely outside the region the risk cap
permits, on a strike grid whose minimum risk unit already exceeds that cap.

## Reproducing

All headline figures were computed from
[`data/intraday/NIFTY`](../data/intraday/) — 72 expiry cycles, authenticity
reconciled to NSE bhavcopy (docs/11) — and from
[`src/optionsbot/data/bhavcopy.py`](../src/optionsbot/data/bhavcopy.py) for the
SENSEX contract specification. The condor study itself:

```
python -m optionsbot.research.run_intraday data/intraday/NIFTY --targets 0.50 --stops 0.60
```
