# 19 — Machine learning finds nothing either (and the best model is the *simplest* one)

**Read this before anyone proposes "train an ML model on it."** The owner asked whether the best ML model could rescue the intraday strangle (docs/17). It cannot, and this records the run that settles it — on the real 345-day intraday dataset, with the out-of-sample discipline that every previous positive result in this project failed.

The headline is not "ML is bad." It is that **model choice was never the binding constraint**: the ceiling here is set by the data (≈300 noisy, non-stationary samples) and by an adversarial market, not by the algorithm. A better model cannot extract signal that is not there — and a *bigger* one overfits faster.

## What was run

Three things, because a null needs more defending than a positive:

1. **A wide sweep under true walk-forward.** 14 configs spanning the capacity range — regularized logistic at four strengths, ridge at three, gradient boosting at two depths, random forest at two, kNN, and both SVM kernels. At every step the **scaler and the model are refit on the expanding training slice only**, then used to predict the next 5-day block. No model ever sees its own test rows; nothing is standardized using future data. 13 features, all knowable before the trade: trailing realized vol (5/10/20d), 5d and 10d trend, the overnight gap and its magnitude, the morning's credit (an implied-vol proxy), a credit/vol "VRP" ratio, DTE, day-of-week, and the previous two days' results.
2. **A permutation null, resampled *within the test region*** — a model that trades k of the N out-of-sample days is compared against drawing k of those same N days at random (20,000 draws). (The first attempt shuffled labels globally and was biased; see the correction below.)
3. **A positive control** — the same machinery against a synthetic target with a deliberately injected edge. *A null from a blind harness means nothing*, so this has to pass before the null counts.

Each model is scored as a gate: trade the strangle on days it predicts a profit, sit out otherwise. The benchmark is simply **trading every day**.

## The result

323 usable days; walk-forward OOS over **194 days**. Always-trade OOS net = **−₹6,636** (1 lot).

| model | gated net | trades | daily SR | vs base |
|---|---|---|---|---|
| **logistic C=.03** | **−1,940** | 193/194 | −0.005 | **+4,695** |
| logistic C=1 | −5,396 | 171/194 | −0.015 | +1,239 |
| ridge a=1 | −5,547 | 84/194 | −0.029 | +1,089 |
| rforest d5 | −6,117 | 185/194 | −0.015 | +519 |
| knn k=15 | −6,286 | 164/194 | −0.017 | +349 |
| svm linear | −6,636 | 194/194 | −0.016 | +0 |
| logistic C=.1 | −6,960 | 190/194 | −0.017 | −324 |
| logistic C=.3 | −7,035 | 179/194 | −0.018 | −399 |
| rforest d3 | −8,882 | 192/194 | −0.022 | −2,246 |
| svm rbf | −10,529 | 186/194 | −0.026 | −3,894 |
| ridge a=50 | −11,335 | 115/194 | −0.048 | −4,699 |
| gboost d3 | −12,583 | 161/194 | −0.037 | −5,948 |
| ridge a=10 | −13,741 | 94/194 | −0.066 | −7,105 |
| **gboost d2** | **−20,526** | 179/194 | −0.055 | **−13,890** |

Three things kill it:

- **Every single model still loses money — 0 of 14 are profitable.** The "best" ones only lose *less* than always-trading, by sitting out days in an already-losing stretch. None turns the period positive.
- **The winner's entire edge is one skipped day.** `logistic C=.03` — the *most heavily regularized* model — traded **193 of 194 days**. The single day it sat out lost **−₹4,695**, which is exactly its "+₹4,695 vs base". Against the correct null (drawing the same 193 days at random from the test region) that lands at **p ≈ 0.02**, but with **K=14 configs the Bonferroni bar is p < 0.0036**, so it does not clear it. One lucky skip out of 194 is a coin flip that came up heads, not a strategy. Its Deflated Sharpe is **0.316** (needs > 0.95) on an observed daily Sharpe of **−0.005**.
- **Capacity actively hurts.** Gradient boosting is the **worst model tested** (−₹20,526; **p = 0.98**, i.e. worse than 98% of random day-selection), and the tree/kernel models cluster at the bottom. That is the textbook signature of overfitting ~300 noisy samples: the more the model *can* memorize, the worse it does out of sample.

**Verdict: no model is profitable, and none beats always-trade while clearing the multiple-testing bar. Not one of 14.**

### A correction, and the trap that caused it

The first version of this study reported the winner's permutation p as **0.875** ("beaten by 87% of noise"). **That number was wrong**, and an adversarial review of the methodology caught it.

The bug: the null shuffled labels across the **entire series** and re-ran the walk-forward. Because the early part of the sample is the profitable regime and the test window is the losing one, a global shuffle **imports early-regime P&L into the test-window null**, inflating what "noise" appears to earn and therefore inflating every p-value. Corrected — resampling only from the test-region days the model actually chose among — the winner's p moves from 0.875 to **≈0.02**, a 40-fold difference.

The conclusion is unchanged (0/14 profitable, 0/14 clear the K=14 bar, DSR 0.316), but the *reason* it holds changed: not "the model is worse than noise", but "the model's one good decision does not survive having tried 14 models". The general lesson is worth keeping: **a permutation null must resample from the pool the model actually chose from.** Shuffling across a regime boundary silently tests a different, easier question — and in this project's history, a null that flatters the conclusion is exactly as dangerous as a positive result that flatters the strategy.

## Why the null is believable: the positive control

A null is only as good as the harness's ability to detect an edge. So the same walk-forward + permutation machinery was re-run against a synthetic target with an edge injected ("trade when the 5-day trend is negative"):

- always-trade net **−₹335** (the synthetic mixes ±400 to ~zero by construction),
- the model **found it**: gated net **+₹29,655** (**+₹29,990** vs base), permutation **p = 0.000**.

**The harness detects a real edge at p = 0.000 and finds nothing in the real data.** So the null reflects absence of signal, not a blind test. (Two other audit concerns resolve the same way: leakage would *fabricate* signal, so finding none makes the result conservative; and the models are demonstrably not degenerate — they choose between 84 and 194 trading days, so they genuinely discriminate.)

## Why ML was never going to work here

Nothing above is surprising given what the project already knew:

1. **The data is tiny.** ~300 usable daily samples. Gradient boosting is the right tool for tabular finance with *tens of thousands* of rows; at 300 it memorizes noise — exactly as observed.
2. **The relationship is non-stationary, and we have measured the flip.** The walk-forward filter study (docs/18) showed the best-in-H1 signal became **anti-predictive in H2** (4th percentile). ML assumes the future resembles training; this market reverses patterns *because* they get traded away.
3. **The search was already done, more rigorously.** docs/15 (K=20) and docs/16 (exhaustive K=739 with Romano-Wolf) are feature searches — the core of what ML does — with proper family-wise error control. Nothing beat base momentum there either.
4. **The market is adversarial.** NIFTY index options are among the most arbitraged instruments in the world. A retail daily-bar model is not going to find what better-capitalised desks with better data and latency missed.

## What this means

- **Do not propose ML for this problem again**, and do not reach for a bigger model. The ordering observed here — simplest model best, biggest model worst — is the data telling you it has no signal to give.
- If ML is ever revisited it must clear this same bar: walk-forward OOS, a permutation null, a Deflated Sharpe over the number of configs tried, **and a positive control**. Anything less produces a beautiful curve-fit, which is the single most common way retail traders lose money.
- The conclusion of [docs/18](18-the-verdict.md) is unchanged: the one real edge is NIFTY 200 momentum, and it is not an options strategy.

## Reproduce

```bash
pip install -e '.[research]'     # numpy/scikit-learn/scipy — offline only, never a runtime dep
python -m optionsbot.research.ml_study data/intraday/NIFTY
python -m pytest tests/test_ml_study.py -q
```

The bot and the EC2 box remain **stdlib-only** (`dependencies = []`); nothing in this study is imported by the paper loop or any live strategy.
