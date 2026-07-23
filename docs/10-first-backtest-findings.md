# 10 — First Backtest Findings (July 2026)

> **Disclaimer:** Educational/research only — **not investment advice**, and the author is **not SEBI-registered**. All figures below are **backtested and hypothetical** (some partial or biased, as noted); **past performance does not guarantee future results**. Named funds/securities are **illustrative, not recommendations**. See [DISCLAIMER.md](../DISCLAIMER.md).

The first evidence in this project produced from real market data rather than
research, marketing, or a placeholder. **It is a negative result, and it is the
most valuable thing built so far.**

## Setup

- **Data**: free NSE bhavcopy, 421 trading days, 2024-11-01 → 2026-07-20, 414,327 option rows. Untraded contracts excluded (their close is a stale carried-forward figure).
- **Strategy**: iron condor entered 4 trading days before expiry at the close, exited on expiry day at the close. Deliberately **EOD-decidable** — every rule can be evaluated from one row per contract per day.
- **Costs**: the project cost engine (STT, brokerage, exchange charges, GST, stamp duty), the same one pinned by the gate-2a hand-computed test.
- **Risk**: ₹2,000 per-trade cap, lot 65.

## Result

Largest honest sample — 0.8% OTM shorts, 50-point wings, **71 trades over 20 months**:

| Metric | Value |
|---|---|
| Net P&L | **−₹16,740** (−16.7% on ₹1 lakh) |
| Gross P&L (before costs) | **+₹75** — about ₹1 per trade |
| Transaction costs | ₹16,815 |
| Win rate | 42% |
| Max drawdown | ₹22,591 (22.6%) — but see the note below |

## Why it loses — the mechanism, not the noise

Median credit was **29 points on a 50-point wing**, so:

- max win = 29 points ≈ ₹1,882
- max loss = 21 points ≈ ₹1,368
- risk:reward ≈ 1 : 1.38 — which *looks* favourable
- **breakeven win rate required: 42%. Actual win rate: 42%.**

The strategy lands exactly on its breakeven point. **Gross P&L before any
costs is +₹75 across 71 trades** — roughly one rupee per trade, on a ₹1 lakh
account, over twenty months.

> **CORRECTED (see [docs/12](12-where-the-edge-actually-is.md)).** This section
> originally concluded that *"the options are priced efficiently — there is no
> gross edge to harvest."* **That is wrong, twice over.**
>
> The variance risk premium is real and large: **+1.96 volatility points at 2 DTE
> (t = +3.76, positive in 74% of 72 cycles)**, worth **₹1,700–2,400 per cycle**
> against a ₹230 cost floor — roughly ten times what it costs to trade.
>
> The reason we captured none of it is that **the entire premium is tail
> insurance**. Estimator-free, from prices alone: a short ATM straddle earns
> +₹1,722/cycle and the ±500 strangle *inside* it earns +₹1,750, so everything
> within ±500 points of ATM is worth **+₹48**. A defined-risk structure is short
> the near strikes and long the far ones — **a net *buyer* of the only part of the
> surface that pays.** We were not failing to harvest the premium; we were paying
> it. That is arithmetic, not a parameter failure.

> **CORRECTED drawdown framing ([docs/12](12-where-the-edge-actually-is.md)).**
> The drawdown is *not* an independent failure alongside the negative return. It
> is a consequence of the negative mean. Bootstrapping this same per-trade
> distribution, shifted only so the strategy earns 20%/yr and keeping its exact
> variance, gives a median 1-year drawdown of **3.4%** and **P(drawdown ≤ 10%) =
> 99.7%**. The variance is entirely compatible with the cap. There is one problem
> — the mean — not two, and the risk architecture should not be redesigned in
> response to these results.

## Two data traps found while verifying this result

Both were discovered by checking whether the numbers were *arithmetically
possible*, not by reading documentation. Neither appears in any of the
thirteen research streams.

**1. Both exchanges write the settlement INDEX LEVEL into `SttlmPric` on
expiry day**, and BSE writes it into `ClsPric` as well. A real row: SENSEX
76100CE on 2026-06-18 reported a close and settlement of 77,409.98 — the index
— while `LastPric` held the true 1,313.70. Valuing expiring contracts from
those fields prices every option at the index level. The ingester now detects
this and falls back to `LastPric`, then to intrinsic value.

**2. Last-traded prices are non-synchronous, and differencing them breaks
arithmetic bounds.** A condor spread cannot be worth more than its wing width
at expiry, yet 24 of 71 cycles produced exit values that exceeded it — one at
59.7 points on a 50-point wing, because both calls last printed ~65 points
below intrinsic at different moments. The study now settles at intrinsic value
against the settlement index, which is both correct and bounded. Zero breaches
remain.

This is the concrete form of a limitation the research anticipated in the
abstract: end-of-day fields are not a coherent snapshot of a multi-leg
structure at a single instant.

## Two structural constraints this exposed

**1. The risk cap dictates wing width, and tight wings destroy risk:reward.**
With lot 65, a ₹2,000 per-trade budget is 30.8 points per share, so
`wing − credit ≤ 30.8`. Wings of 150–200 points are arithmetically impossible
(rejected in 34 of 34 and 41 of 41 cycles). Tight wings force a roughly 1:1
payoff, which demands a win rate the market does not concede.

**2. Configurations that appear profitable are selection artifacts.** Wider
wings showed 86–100% win rates — on 5–9 trades out of 50 cycles. The cap only
admits cycles whose credit is unusually high, i.e. unusually high implied
volatility: passing cycles had a median credit of 81 points against 66 for
blocked ones. That filter selects on a variable correlated with the outcome.
Walk-forward confirms it — mid-sample configurations flip sign between train
and holdout (+₹765 → −₹1,412; −₹1,508 → +₹6,311), which is noise, not edge.

## What this does and does not establish

**Does:** a hold-to-expiry condor at these parameters has no edge on NIFTY over
this period, and the ₹1 lakh / ₹2,000-cap combination structurally forces
payoff geometry that requires an edge the market is not offering.

**Does not:** invalidate the live paper strategy, which exits on intraday
profit targets and stops. EOD data cannot evaluate those — when a day's range
contains both triggers it cannot say which came first, and that ordering
decides the trade. Whether intraday management adds enough to overcome this
remains untested and requires 1-minute data (issue #13).

**Cannot be verified from this data:** whether the four entry legs' closing
prices were simultaneously achievable. NSE's closing price is a last-half-hour
weighted average, so all four legs reflect the same window and should be
broadly synchronous — but end-of-day files offer no independent source to
check that against (on non-expiry days `ClsPric` and `SttlmPric` are the same
number). If entry credits are systematically optimistic, the true result is
worse than reported, not better.

Also untested here: implied-volatility or regime filters, alternative entry
timing, and directional or calendar structures.

## Follow-up: the implied-volatility filter also fails (issue #25)

The one signal worth chasing was that high-premium cycles looked different. That
was retested as an explicit rule applied to **every** cycle — enter only when the
credit is at least X% of the wing width — rather than letting it emerge as a
side-effect of the risk cap.

Full-sample results improve and one threshold turns positive: at 55%, 45 trades
net **+₹1,269** with a 49% win rate. Gross per trade rises from ₹1 (unfiltered)
to ₹274.

**It does not survive validation.**

| Threshold | Full net | Train net | Holdout net | Holdout gross/trade |
|---|---:|---:|---:|---:|
| 50% | −₹7,015 | +₹1,650 | −₹8,664 | −₹82 |
| **55%** | **+₹1,269** | +₹6,021 | **−₹4,752** | +₹21 |
| 60% | +₹35 | +₹6,480 | −₹6,445 | −₹114 |

Every threshold flips sign between train and holdout, and **holdout net is
negative at every threshold tested**. Splitting into thirds shows why: the entire
result comes from **3 trades** in one window.

| Period | Trades | Gross | Net |
|---|---:|---:|---:|
| Nov 2024 – May 2025 | 22 | ₹5,074 | −₹140 |
| May – Dec 2025 | **3** | **₹6,810** | +₹6,161 |
| Dec 2025 – Jul 2026 | 20 | ₹429 | −₹4,752 |

Gross per trade out of sample is ₹21 against ₹475 in training. Three trades
during a single volatility episode that resolved favourably is luck wearing the
costume of an edge — the same shape as the selection artifact this experiment was
designed to rule out, reproduced under a rule that was supposed to eliminate it.

**Conclusion: no volatility-timing edge is detectable in this strategy family on
this data.**

> **Method note ([docs/12](12-where-the-edge-actually-is.md)).** The test above is
> weaker than it should be: an *absolute* credit-as-%-of-wing threshold conflates
> IV level with DTE and moneyness, and sweeping thresholds invites overfitting. A
> competent seller filters on **IV rank**, not an absolute level. That better test
> was subsequently run on minute data — Black-Scholes ATM IV, expanding-window IV
> rank with no look-ahead, walk-forward — and **fails harder**: correlation with
> gross P&L is −0.016, which kills every possible threshold at once without
> sweeping any. The conclusion stands; the reasoning behind it is now sound.

## Bearing on the mandate

The target is 20–25% annually with a 5–10% maximum drawdown. This
configuration returned **−18.6% with a 23.5% drawdown**, on real prices with
honest costs.

That does not close the question, but it does relocate it. The burden is no
longer "which parameters?" but "**where is the edge, and what evidence supports
it?**" — precisely the standard RESEARCH.md rule 5 sets, now applied to our own
work rather than to a vendor's claims.

**That question has since been answered: [docs/12](12-where-the-edge-actually-is.md).**
The edge is the variance risk premium, it is real and statistically significant at
+2.08 volatility points, and it is 2.6× too small to fund this mandate at ₹1 lakh —
where flat per-order brokerage alone consumes 8.2% a year.

## Reproduce

```bash
PYTHONPATH=src .venv/bin/python -m optionsbot.data --index NIFTY \
  --from 2024-11-01 --to 2026-07-20
# then drive optionsbot.research.hold_to_expiry.run() over the loaded rows
```
