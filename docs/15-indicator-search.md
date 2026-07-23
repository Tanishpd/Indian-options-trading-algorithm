# 15 — The indicator search: nothing beats base momentum

> **Disclaimer — backtested, hypothetical, not advice.** Every figure here is
> computed from historical data over a stated window and does **not** reflect real
> trading. Past (including backtested) performance does not predict future
> results. This is educational research, not investment advice. See
> [DISCLAIMER.md](../DISCLAIMER.md).

## The question

The owner asked: *"try all the indicators and combinations and see the best
strategy."* This document is the answer. The short version: **no indicator or
combination we tested beats plain [NIFTY-200 momentum with the 200-DMA regime
filter](14-momentum-the-one-real-edge.md), net of tax, by any statistically
defensible margin.** The base is the strategy.

## Why we did not "try everything"

Enumerating the full indicator space (trend, oscillators, mean-reversion,
volatility, volume, composites) gives **~10⁸–10⁹** combinations once you allow
pairs and triples. Testing them all is not just slow — it is **statistically
self-defeating.** On the point-in-time-clean window (only ~33 monthly
observations), the best-of-K in-sample Sharpe is inflated by luck alone by
roughly `SE·√(2·ln K)`. At K = 10⁴ that is about **+2.2 Sharpe** — larger than
the entire real edge of the base strategy. A sweep would "discover" a phantom
strategy indistinguishable from the truth.

So instead of sweeping 800 runnable variants, we **pre-registered 20** (see
[`search_configs.py`](../src/optionsbot/research/search_configs.py)), each
carrying an ex-ante economic mechanism, and judged them with a multiple-testing
correction. The count is frozen before the cross-validation window is touched.
Compute was never the constraint; the number of things tested is.

## Method

Implemented in [`run_indicator_search.py`](../src/optionsbot/research/run_indicator_search.py)
and [`strategy_search.py`](../src/optionsbot/research/strategy_search.py):

- **Real data**: 254 stocks, point-in-time NIFTY-200 membership (from
  2022-09-30), the real NIFTY-50 index, 2017–2026.
- **Net of everything**: ~30 bps round-trip costs **and** 20% STCG accrued
  annually, inside the equity curve. The bar to beat is base *net*, not gross.
- **Three-tier temporal holdout**: exploration (pre-2022-09, survivorship-biased,
  hypothesis generation only) → **cross-validation** (2022-09 → 2025-07, PIT-clean)
  → **locked holdout** (2025-07 → 2026-07, touched once, only for a CV winner).
- **A candidate is a real find only if it clears every gate**: beats base net
  Sharpe, **Deflated Sharpe > 0.95** (corrected for N = 19 trials),
  **Probability of Backtest Overfitting < 0.2**, and **White's Reality Check
  p < 0.05**.

The engine's default config reproduces the pinned base backtest bar-for-bar
(tested), so every overlay is measured against the *real* base. Base gross this
run: **23.6% CAGR / 21.3% maxDD / 1.51 Sharpe** — identical to
[docs/14](14-momentum-the-one-real-edge.md), which is the confidence anchor for
the whole exercise.

## Result

Cross-validation window: 33 monthly observations. Base net Sharpe (annualised) =
**1.54**. **PBO = 0.88. SPA p = 0.578.** (net of costs and 20% STCG)

| config | CV Sharpe | DSR | > base? | full CAGR | full maxDD | mechanism |
|---|---:|---:|:--:|---:|---:|---|
| **base** | **1.54** | — | — | **19.5%** | **21.3%** | momentum + 200-DMA regime — the benchmark |
| vt_pure | 1.30 | 0.92 | no | 20.0% | 28.1% | H1 vol-target on index vol, no 200-DMA |
| vt_floor | 1.30 | 0.92 | no | 20.0% | 28.1% | H1 vol-target, 0.3 exposure floor |
| vt_regime | 1.52 | 0.97 | no | 17.6% | 20.9% | H1 vol-target **+** 200-DMA |
| resid | 1.54 | 0.97 | ~tie | 18.8% | 22.7% | H2 residual (idiosyncratic) momentum |
| resid_vt | 1.28 | 0.92 | no | 18.5% | 32.3% | H2×H1 |
| slope21 | 1.27 | 0.92 | no | 14.0% | 28.1% | H3 200-DMA slope regime (replaces price>MA) |
| slope63 | 1.15 | 0.90 | no | 14.5% | 28.1% | H3 slower slope |
| breadth | 1.65 | 0.98 | yes | 16.2% | 21.1% | H4 % universe above its 50-DMA |
| breadth_and | 1.48 | 0.96 | no | 14.3% | 17.8% | H4 breadth **and** price>200-DMA |
| skip21 | 1.50 | 0.96 | no | 19.2% | 21.2% | H5 12-1 skip-month momentum |
| skip42 | 1.46 | 0.96 | no | 19.6% | 20.3% | H5 12-2 skip-month |
| invvol | 1.50 | 0.96 | no | 17.9% | 21.5% | H6 inverse-vol weighting |
| trendq | 1.53 | 0.97 | no | 18.2% | 20.4% | H7 trend-quality (frog-in-the-pan) tilt |
| dispersion | 1.41 | 0.97 | no | 20.2% | 28.9% | H8 cross-sectional dispersion regime |
| macd_regime | 1.03 | 0.87 | no | 11.7% | 20.8% | index MACD regime (replaces price>MA) |
| downside | 1.58 | 0.97 | yes | 20.5% | 21.8% | Sortino-denominator ranking |
| score_prop | 1.58 | 0.98 | yes | 20.9% | 40.4% | score-proportional weighting |
| ctrl_no_regime | 1.30 | 0.92 | no | 25.5% | 28.1% | **control**: no regime filter |
| ctrl_top50 | 1.64 | 0.97 | yes | 15.7% | 20.8% | **control**: top-50 (over-diversified) |

## Verdict

**Nothing beats base net-of-tax by a significant margin. The locked holdout was
not touched.** PBO = 0.88 means that across cross-validation splits the
in-sample-best config lands **below** the out-of-sample median almost every time
— ranking candidates by in-sample Sharpe is essentially *anti-predictive*. SPA
p = 0.578 says no candidate beats base once you correct for having tried 19 of
them.

**The harness proved it works by catching the trap in real time.** The negative
control `ctrl_top50` — an over-diversified config we *expected* to lose — posted
the **highest** CV Sharpe (1.64) and cleared its individual Deflated Sharpe. A
naive "keep the best backtest" would have crowned it. The family-wise gates
(PBO, SPA) correctly refused it, along with `downside`, `score_prop`, `breadth`,
and `resid`, whose high CV Sharpes are noise around base.

## What each hypothesis actually did

- **H1 vol-target sizing** — the a-priori favourite — *worsened* drawdown
  (28.1% vs 21.3%). Index realised vol is not a good predictor of momentum
  crashes here; it levered up at the wrong times. Only stacked *on top of* the
  200-DMA (`vt_regime`) did it shave drawdown to 20.9%, and then at a return cost
  (17.6% CAGR) and still no Sharpe edge.
- **H2 residual momentum** — correctly implemented (see the bug note below) —
  **ties** base (CV Sharpe 1.54) with slightly lower CAGR and slightly higher
  drawdown. A fair test; no improvement.
- **H3 200-DMA slope** and **MACD** regime replacements were **worse** than the
  simple `price > 200-DMA` test (14% and 12% CAGR). The plain 200-DMA gate is
  confirmed as the better drawdown tool.
- **H4 breadth** and **breadth_and** cut drawdown (to 21.1% and a best-in-class
  17.8%) but cut return more (16.2%, 14.3%) — the same 1:1 trade the 200-DMA
  already makes, no free lunch.
- **H5 skip-month**, **H6 inverse-vol**, **H7 trend-quality** all landed inside
  the noise band — marginally lower return, marginally lower drawdown, no Sharpe
  edge.
- `score_prop` posted a high CV Sharpe but a **40.4% drawdown** — concentration
  risk the CV window happened to reward.
- `ctrl_no_regime` had the highest full-period CAGR (25.5%) and the worst
  drawdown (28.1%) — exactly what removing the crash protection should do.

## Methodology integrity — the bug chain

Three defects were found and fixed *before* any result was published. Recording
them because the discipline is the point:

1. **Residual momentum scored zero names.** The first run showed `resid` at
   ~2.8% CAGR. Cause: the residual subtracted the fitted intercept as well as
   beta·market, and OLS forces residuals to sum to zero — so the ranking was
   noise. Fixed to keep the idiosyncratic drift (`residual = y − β·x`).
2. **The NIFTY-50 fetch skipped 2021–2026.** Diagnosing (1) surfaced a worse
   bug: `load_index` advanced its 5-year fetch cursor from the window *end*
   instead of *end + 1 day*, leaving the index cache with **zero bars in the
   entire cross-validation window**. `index_on_or_before` then returned a stale
   2021 value, **freezing the regime filter** for all of 2022–2025. Every
   index-using config in the first run was corrupted — that table was discarded.
3. **Guardrails added** so neither can recur silently: `fetch_windows` is a
   unit-tested pure function whose invariant is that windows abut; `main()`
   now **aborts** if the index has too few bars in the CV window. The engine
   suite is mutation-tested (5/5 deliberate bugs caught).

Only after all three fixes did base gross reproduce **23.6% / 21.3% / 1.51**,
which is why that reproduction is the trust anchor for this document.

## Recommendation

**Ship base momentum with the 200-DMA regime filter, unchanged.** It is the best
configuration we can defend. Do not add an overlay chosen by in-sample Sharpe —
PBO = 0.88 says that is the wrong move. As [docs/14](14-momentum-the-one-real-edge.md)
concludes, the most capital-efficient way to *hold* this exposure net of the 20%
STCG drag is the momentum **index fund** (Option A), whose internal rebalancing
defers the tax a monthly-rotating bot cannot. The locked 2025-07 → 2026-07
holdout remains **untouched and reserved** for a future hypothesis with a genuine
ex-ante mechanism — not for re-searching this set.
