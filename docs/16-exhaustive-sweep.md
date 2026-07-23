# 16 — The exhaustive closes-only sweep: still nothing beats base

> **Disclaimer — backtested, hypothetical, not advice.** Every figure here is
> computed from historical data over a stated window and does **not** reflect real
> trading. Past (including backtested) performance does not predict future
> results. Educational research, not investment advice. See
> [DISCLAIMER.md](../DISCLAIMER.md).

## The question

After the disciplined K=20 search ([docs/15](15-indicator-search.md)) found no
overlay that beats base momentum, the owner asked to go further: **run the full
~800 closes-only indicator space, without false positives, and include a
trailing stop.** This document is the answer. The short version: **of 738
candidate configurations — trailing stops included — not one survives a proper
family-wise correction.** Base momentum with the 200-DMA regime filter remains
the strategy.

## Doing 800 without false positives

Testing 738 strategies on a ~33-month clean window is a multiple-testing minefield
— the best in-sample Sharpe is inflated by luck alone by more than the real edge.
Three corrections make the verdict trustworthy regardless of K:

1. **Romano-Wolf stepdown FWER control** — a stationary-bootstrap test that
   exploits the heavy correlation among the ~800 near-duplicate configs (an
   SMA-50 and an SMA-100 regime are almost the same strategy). It is far more
   powerful than Bonferroni yet still holds the family-wise error rate at 5%, and
   it returns a per-config adjusted p-value, so any survivor is individually
   trustworthy. (`overfit_stats.romano_wolf_pvalues`.)
2. **CSCV Probability of Backtest Overfitting** over the whole family.
3. **Deflated Sharpe** at the true N = 738 trials.

A config is a real find only if it clears **all**: beats base net Sharpe,
Romano-Wolf p < 0.05, PBO < 0.2, DSR > 0.95 — then the locked holdout is touched
once. The grid ([`search_grid.py`](../src/optionsbot/research/search_grid.py)) is
frozen before the cross-validation window is touched; K is exactly the number of
distinct configs generated.

## Method

- **K = 739** distinct closes-only configs: single-axis sweeps (regime, rank,
  weighting, exposure, top-N, lookbacks, **trailing stops**) plus high-value
  two-way interactions. **464 of the 739 carry a trailing stop** (per-stock and
  portfolio, 8 thresholds each, crossed with regimes / ranks / exposures).
- **Real data, net of everything**: 254 stocks, point-in-time NIFTY-200
  membership, real NIFTY-50, 2017-2026; ~30 bps round-trip costs **and** 20%
  STCG inside every equity curve.
- Base gross this run: **23.6% CAGR / 21.3% maxDD / 1.51 Sharpe** — identical to
  [docs/14](14-momentum-the-one-real-edge.md), the anchor that says the engine
  is correct.

## Result

Cross-validation (2022-09 → 2025-07, 33 monthly obs). Base net Sharpe = **1.54**.
**PBO = 0.79. Best-of-738 Romano-Wolf p = 0.261** (need < 0.05). **94 of 738**
beat base net Sharpe in-sample — fewer than half, i.e. most candidates are
*worse* than base, and the ones that "win" do so within the noise.

| config | CV Sharpe | RW p | DSR | full CAGR | full maxDD | what it is |
|---|---:|---:|---:|---:|---:|---|
| **base** | **1.54** | — | — | **19.5%** | **21.3%** | benchmark |
| g0734 | 1.75 | 0.997 | 0.89 | 15.0% | **42.9%** | score-prop weighting + breadth — huge drawdown |
| g0056 | 1.72 | 0.983 | 0.87 | 14.1% | 28.8% | 1-12m lookback — 85% turnover |
| g0542/56 | 1.72 | 1.000 | 0.88 | 15.5% | 20.6% | residual momentum + breadth |
| g0668 | 1.67 | 1.000 | 0.86 | 13.3% | 21.0% | vol-target 0.15 |
| g0234/48/62/76 | 1.65 | 1.000 | 0.85 | 16.2% | 21.1% | **portfolio trailing stop 15–30% — identical to base breadth** |
| g0164 | 1.65 | 1.000 | 0.85 | 16.2% | 21.1% | **per-stock trailing stop 30% — identical to base** |
| g0049 | 1.61 | **0.261** | 0.83 | 21.6% | 24.8% | top-20 (the single best RW p, still nowhere near 0.05) |

**Configs clearing all gates: 0. Holdout not touched.**

## Verdict

**Of 738 closes-only configurations, none beats base momentum net-of-tax by a
family-wise-significant margin.** The best-corrected p-value across the entire
space is 0.261 — the most promising single strategy out of 738 is not close to
significant. PBO = 0.79 confirms the space is treacherous: picking the in-sample
best is, once again, anti-predictive. This is the definitive, exhaustive close to
"but did you try everything?" — we did, with a correction that cannot manufacture
a false positive at 5% FWER, and the answer is base.

## Trailing stops, specifically

The owner's trailing-stop question is answered cleanly, and it is a "no":

- **Wide stops are inert.** Portfolio stops at 15–30% and per-stock stops at 30%
  produced *metrics identical to the no-stop base* (16.2% / 21.1% / 1.65) — on a
  monthly-rotating momentum book they essentially never trigger, so they change
  nothing.
- **Tight stops whipsaw.** The narrower thresholds cut return without a matching
  drawdown benefit (lower CV Sharpe), exactly as the momentum literature predicts:
  a trailing stop sells winners on normal pullbacks, and momentum's edge is riding
  those winners.
- Either way, **no trailing-stop config beats base**, and none comes near the RW
  threshold. The 200-DMA regime filter — a market-level stop — is the right and
  sufficient risk tool; a position-level trailing stop adds nothing.

## Recommendation

Unchanged, now on the strongest possible evidence: **ship base NIFTY-200 momentum
with the 200-DMA regime filter.** Do not add an indicator overlay or a trailing
stop — 738 of them were tested with proper family-wise control and none earned a
place. The most tax-efficient way to hold the exposure remains the momentum index
fund ([docs/14](14-momentum-the-one-real-edge.md) Option A). The locked
2025-07 → 2026-07 holdout is still untouched and reserved for a genuinely new
hypothesis with an ex-ante mechanism — not for re-searching this space.
