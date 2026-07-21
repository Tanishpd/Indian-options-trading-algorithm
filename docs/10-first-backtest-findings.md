# 10 — First Backtest Findings (July 2026)

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
| Net P&L | **−₹18,591** (−18.6% on ₹1 lakh) |
| Gross P&L (before costs) | −₹1,776 |
| Transaction costs | ₹16,816 |
| Win rate | 42% |
| Max drawdown | **₹23,453 (23.5%)** — 2–4× the mandated cap |
| Avg win / avg loss | ₹1,522 / −₹1,567 |

## Why it loses — the mechanism, not the noise

Median credit was **29 points on a 50-point wing**, so:

- max win = 29 points ≈ ₹1,882
- max loss = 21 points ≈ ₹1,368
- risk:reward ≈ 1 : 1.38 — which *looks* favourable
- **breakeven win rate required: 42%. Actual win rate: 42%.**

The strategy lands exactly on its breakeven point. **Gross P&L before any
costs is −₹1,776 over 71 trades** — statistically indistinguishable from zero.
(Zeroing the configurable cost rates leaves −₹3,705, because STT is statutory
and deliberately hard-coded rather than configurable.)

**The options are priced efficiently.** The premium collected compensates
precisely for the risk taken. There is no gross edge to harvest, and
transaction costs are then pure subtraction from a coin flip.

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

Also untested here: implied-volatility or regime filters, alternative entry
timing, and directional or calendar structures.

## Bearing on the mandate

The target is 20–25% annually with a 5–10% maximum drawdown. This
configuration returned **−18.6% with a 23.5% drawdown** — failing both, on real
prices, with honest costs.

That does not close the question, but it does relocate it. The burden is no
longer "which parameters?" but "**where is the edge, and what evidence supports
it?**" — precisely the standard RESEARCH.md rule 5 sets, now applied to our own
work rather than to a vendor's claims.

## Reproduce

```bash
PYTHONPATH=src .venv/bin/python -m optionsbot.data --index NIFTY \
  --from 2024-11-01 --to 2026-07-20
# then drive optionsbot.research.hold_to_expiry.run() over the loaded rows
```
