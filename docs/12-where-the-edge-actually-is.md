# 12 — Where the Edge Actually Is (July 2026)

Two studies said the strategy loses ([docs/10](10-first-backtest-findings.md),
[docs/11](11-intraday-backtest-findings.md)). Both explained it with a mechanism
that is **wrong**. This document corrects it, and states the one measurement that
decides whether this project's mandate is reachable at all.

It exists because "we lost money" is not a finding. "The market pays 2.08 volatility
points and this account needs 5.4" is a finding — it ends the parameter search
instead of inviting a tenth sweep.

## The correction: options are NOT priced efficiently

docs/10 concluded *"the options are priced efficiently — the premium collected
compensates precisely for the risk taken. There is no gross edge to harvest."*

That is refuted. Measured on our own data — implied volatility at entry against
subsequently realised volatility to expiry, 71 cycles, no holding-period
selection:

| | |
|---|---|
| **Variance risk premium** | **+2.08 volatility points** |
| t-statistic | **+2.95** |
| 95% confidence interval | [+0.70, +3.46] |
| Cycles where IV exceeded RV | **53 of 71** |
| Sign test | z = +4.15 |

**NIFTY index options are systematically overpriced, and the effect is
statistically solid.** Sellers are paid a real premium for bearing variance risk.
The failure in docs/10 and docs/11 is not the absence of an inefficiency. It is
the inability to monetise a real one at this account size.

That distinction matters, because "no edge exists" and "the edge is too small for
₹1 lakh" imply completely different next steps.

## Why a real edge still loses money

Size it against the structure actually traded:

```
condor net short vega            Rs 115.4 per volatility point
premium available                2.08 points
=> theoretical gross per trade   Rs 240
cost floor per round trip        Rs 226
=> edge net of costs             Rs +14 per trade
```

Two entirely independent methods agree. The realised backtest gives roughly zero
gross per trade; theory (vega × measured VRP) gives ₹240 against a ₹226 cost. **The
edge and the cost floor are the same size.** Everything this project has measured
follows from that one fact.

The requirement, stated as the market variable rather than as P&L:

> **20% a year on ₹1,00,000 requires a variance risk premium of 5.4 volatility
> points. The market offers 2.08, with a 95% upper bound of 3.46.**

The premium would have to more than double, and stay doubled.

## The second correction: the drawdown cap was never the problem

docs/10 and docs/11 both present the 21–23% drawdown as an *independent* failure —
"breaches the cap by 2–4×, the same failure mode". **It is not independent.** It is
a consequence of the negative mean, and it disappears when the mean does.

Bootstrapping the observed per-trade net distribution, shifted only so the strategy
earns 20% a year and otherwise keeping its exact variance:

| | |
|---|---|
| Median 1-year max drawdown | **3.4%** |
| P(drawdown ≤ 10%) | **99.7%** |

The variance of this strategy is entirely compatible with a 5–10% cap. There is
**one** problem — the mean — not two. **The risk architecture works. Do not
redesign the kill-switch, the per-trade cap, or the position rules in response to
the backtest results.** They are not what failed.

## Why more capital is the constraint, and why it is still not enough

₹188.80 of the ₹226 round trip is flat per-order brokerage plus the GST riding on
it — **independent of lot count**. Only ₹36.70 scales with size. So return on
capital rises sharply as the fixed cost is spread over more lots:

| Capital | Lots | Cost/trade | At measured VRP | At 95%-upper VRP |
|---|---:|---:|---:|---:|
| ₹1,00,000 | 1 | ₹226 | **+0.7%** | +8.8% |
| ₹5,00,000 | 5 | ₹372 | +8.4% | +16.5% |
| ₹10,00,000 | 10 | ₹556 | +9.4% | +17.4% |
| unlimited | — | — | **+10.3% ceiling** | +18.4% ceiling |

At ₹1 lakh, **fixed brokerage alone consumes 8.2% a year** — a third of the target,
gone before any market risk is taken.

But read the last row before treating capital as the answer. **Even with unlimited
capital and the optimistic end of the confidence interval, this structure tops out
below 20%.** More capital converts a losing strategy into a mediocre one; it does
not reach the mandate. And every figure in that table is optimistic: the
theoretical ₹240 sits *above* the realised gross 95% upper bound of ₹175.

## Objections tested and closed

### "72 cycles is too small to conclude anything"

It isn't, for the effect size that matters.

- Observed sd ₹1,046/trade, standard error ₹123
- Minimum detectable effect at 80% power: **₹345/trade**
- The mandate requires **₹619/trade** (20%) or **₹717** (25%)
- Power against those effects: **99.9%** and **100%**
- 95% CI on gross: [−₹309, **+₹175**]/trade — the *upper* bound annualises to
  **−2.6%** net, or **+5.5%** at zero brokerage

The sample is genuinely underpowered only for edges of ₹100–200/trade (power
13–37%). An edge that small cannot fund the mandate, so the ambiguity is real but
confined to a region that does not help.

### "The test ran in an unusually quiet volatility regime"

**Half right, and the strongest objection raised.** It was quiet:

- Window mean India VIX **13.89** — the **21st percentile** of 2010–2023; long-run
  mean 18.33, a factor of **1.32**
- July 2025 – February 2026 averaged **11.55** — the **4.8th percentile**. The ten
  lowest VIX closes in the index's history all fall inside this window.
- Our own measurement agrees: in-window realised vol 12.9% against ~17.0% long-run

But it does not bridge the gap, because **the condor's short vega falls as
volatility rises** — fixed 50-point wings sit relatively closer in delta terms, so
vega drops from ₹115.4 to ₹71.7 per point at 1.32× IV. The structure harvests less
of each additional point it is offered. Stacking *both* optimistic assumptions —
long-run volatility **and** the 95% upper VRP bound — yields **₹328/trade against
₹619 needed: 0.53×**. At zero brokerage, 0.71×.

The regime argument is worth perhaps +5%/yr, not +20%.

It also cuts both ways. The window ends with the March 2026 spike (VIX 13.7 → 28.9,
the highest since 2022): 4 cycles, **0% win rate, −₹4,410**. Excluding it, the
strategy still loses ₹16,655. The tail did not cause the loss — and a higher-vol
regime brings more such tails.

### "A proper IV filter would fix it"

docs/10's attempt was inadequate, and this is a fair criticism of it: it tested an
**absolute** credit-as-%-of-wing threshold, which conflates IV level with DTE and
moneyness, and it swept thresholds, which invites overfitting. A competent seller
filters on **IV rank** — relative, not absolute.

So the better test was run: Black-Scholes ATM implied volatility at every entry
minute, expanding-window IV rank with no look-ahead, walk-forward split. **It fails
harder.**

- Threshold-free correlation with gross P&L: ATM IV **r = −0.020**, IV rank
  **r = −0.016**, credit/wing **r = +0.072**. All null — a near-zero correlation
  kills every possible threshold at once, without sweeping any.
- Walk-forward: **every** IV-rank threshold (30/50/60/70/80/90) loses in holdout,
  and gross per trade gets *worse* at higher thresholds (−₹410 at rank 70, −₹815 at
  rank 80).
- High-IV vs low-IV tercile difference: +₹184/trade, **t = +0.60**. Not significant.

The tercile data does show the classic seller's trap: as IV rises the win rate
*falls* (58% → 42%) while the average win grows. That is why Spearman (+0.22)
exceeds Pearson (≈0) — and why it never becomes money.

### "Hold longer to earn more of the premium"

The VRP finding points here, and it fails hard. Entering earlier (DTE 4–8, 6–10)
drives gross from −₹67 to **−₹347/trade, t = −3.39**. A 0.8% offset is far too close
to the money to survive a longer window.

The best configuration found anywhere in this project is hold-to-expiry, DTE 2–6,
triggers disabled: gross **+₹122/trade** — but t = +0.62, not significant — netting
−₹7,255 with a 16.1% drawdown. At zero brokerage, +3.0%/yr.

## The pre-committed experiment

One measurement decides whether this strategy family can ever work, and the
threshold is set **before** running it so the result cannot be rationalised
afterwards.

**Measure the variance risk premium across ~4 years of NIFTY history**, spanning
2020 and 2022's higher-volatility regimes — roughly 200 observations, tightening
the confidence interval to about ±0.8 points.

- **Data**: free EOD bhavcopy plus the index series. No minute data, no execution
  modelling, no backtest engine, no broker. One script reusing
  [`src/optionsbot/data/bhavcopy.py`](../src/optionsbot/data/bhavcopy.py).
- **Method**: ATM implied volatility at entry against subsequently realised
  volatility to expiry, per cycle.

> **PRE-COMMITMENT: if the 95% upper bound on the variance risk premium comes in
> below 5.4 volatility points, the mandate is dead structurally — not
> regime-specifically — and no further parameter search on premium selling is
> justified.**

The point estimate would have to more than double to clear that bar, so the honest
expectation is that this confirms the stop. Its value is that it converts *"we
tested a quiet window and lost"* into *"the premium the market pays is structurally
too small for a ₹1 lakh account"* — a finding that ends the search rather than
inviting another sweep.

## What this changes

1. **docs/10's stated mechanism is wrong** and is corrected there. Options are not
   efficiently priced; the premium is real, measured, and too small.
2. **The drawdown framing in docs/10 and docs/11 is wrong** and is corrected in
   both. One failure, not two. The risk framework is sound.
3. **The question is no longer "which parameters".** It is "at what capital does a
   ~10% target become reachable" — and the table above answers ₹5 lakh or more, for
   roughly half the original goal.
4. **The mandate as written — 20–25% net on ₹1,00,000 at 5–10% drawdown from
   defined-risk index spreads — is refuted**, not by a noisy backtest but by
   arithmetic on a measured, statistically significant edge that is 2.6× too small,
   inside a cost structure that consumes 8.2%/yr of the account before risk.

## Limits of this analysis

One index, 71–72 cycles, 17 months, one volatility regime (a quiet one). The VRP
estimate is significant but its confidence interval is wide — [+0.70, +3.46] — and
the whole argument rests on it. That is precisely why the pre-committed experiment
above measures it on a longer history before anything else is built.

Nothing here rules out edges of a different kind: directional, cross-sectional, or
structures whose vega-per-rupee-of-cost is materially better than a symmetric
condor's. It rules out **harvesting the variance risk premium with defined-risk
NIFTY index spreads at ₹1 lakh**, which is what this project set out to do.
