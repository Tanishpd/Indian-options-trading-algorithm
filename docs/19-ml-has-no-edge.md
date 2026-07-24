# 19 — Machine learning finds nothing usable (and this dataset could not prove it if it did)

**Read this before anyone proposes "train an ML model on it."** The owner asked whether the best ML model could rescue the intraday strangle (docs/17). It cannot — but the honest reason is sharper, and less flattering to the method, than "the models lost money."

Two things are true at once, and both matter:

1. **No model beats simply trading every day — at any cost assumption tested.** Romano-Wolf adjusted p for the best-of-family is **0.32 / 0.21 / 0.21** at ₹0.25 / ₹0.50 / ₹0.75 per leg of slippage. This is the invariant result and the one to quote. The best model's entire advantage is a single skipped day.
2. **For a model that genuinely gates, this dataset could not certify a mandate-sized edge anyway.** The minimum detectable improvement for a mid-sized gate (trading 50–150 of the 194 days) is ~₹31k–37k. (For a gate skipping only a *handful* of days the MDE is much smaller and such an edge *would* be visible — the study looked there and found nothing.)

> **What is NOT a robust fact:** an earlier version of this doc led with *"every model loses money; 0 of 14 is profitable — a direct observation, and the load-bearing fact."* It is not a direct observation; it is a property of an undisclosed slippage assumption. See the sensitivity table below.

## What was run

- **A wide sweep under true walk-forward.** 14 configs spanning the capacity range (regularized logistic ×4, ridge ×3, gradient boosting ×2, random forest ×2, kNN, both SVM kernels). At every step the **scaler and the model are refit on the expanding training slice only**, then predict the next 5-day block. 13 features, all knowable before the trade: trailing realized vol (5/10/20d), 5d/10d trend, the overnight gap and its magnitude, the morning's credit (an IV proxy), a credit/vol ratio, DTE, day-of-week, and the previous two days' results. Each model is scored as a gate — trade when it predicts a profit — against a benchmark of **trading every day**.
- **A null resampled *within the test region*.** A model trading k of the N out-of-sample days is compared against drawing k of those same N days at random.
- **Romano-Wolf step-down (max-T)** across the whole family — the correction [docs/16](16-exhaustive-sweep.md) already established as this project's standard — using one permutation per draw applied to every config, so cross-model dependence is preserved.
- **A positive control** (large injected edge) for harness integrity, and **a power analysis** for the question the positive control cannot answer.

## The result

323 usable days; walk-forward OOS over **194 days**. Always-trade OOS net = **−₹6,636** (1 lot).

| model | gated net | trades | daily SR | vs base | marginal p |
|---|---|---|---|---|---|
| **logistic C=.03** | −1,940 | 193/194 | −0.005 | **+4,695** | 0.020 |
| logistic C=1 | −5,396 | 171/194 | −0.015 | +1,239 | 0.444 |
| ridge a=1 | −5,547 | 84/194 | −0.029 | +1,089 | 0.573 |
| rforest d5 | −6,117 | 185/194 | −0.015 | +519 | 0.411 |
| knn k=15 | −6,286 | 164/194 | −0.017 | +349 | 0.491 |
| svm linear | −6,636 | 194/194 | −0.016 | +0 | — |
| logistic C=.1 | −6,960 | 190/194 | −0.017 | −324 | 0.470 |
| logistic C=.3 | −7,035 | 179/194 | −0.018 | −399 | 0.490 |
| rforest d3 | −8,882 | 192/194 | −0.022 | −2,246 | 0.892 |
| svm rbf | −10,529 | 186/194 | −0.026 | −3,894 | 0.790 |
| ridge a=50 | −11,335 | 115/194 | −0.048 | −4,699 | 0.686 |
| gboost d3 | −12,583 | 161/194 | −0.037 | −5,948 | 0.725 |
| ridge a=10 | −13,741 | 94/194 | −0.066 | −7,105 | 0.755 |
| gboost d2 | −20,526 | 179/194 | −0.055 | −13,890 | 0.984 |

At this cost assumption every model loses money. **But that is a fact about the strategy's execution costs, not about ML** — and it is not robust:

### The cost assumption, disclosed (this is a free parameter)

`build_dataset` uses **₹0.50/leg** of slippage — *double* the ₹0.25 default the rest of the project uses (`intraday_only.py`). docs/19 previously never stated this. Re-running the entire sweep at three cost levels:

| slippage | always-trade base | profitable configs | best model | **Romano-Wolf p** |
|---|---|---|---|---|
| ₹0.25/leg (project default) | **+7,334** | **13 of 14** | gboost d2 (+16,508) | **0.320** |
| ₹0.50/leg (used here) | −6,636 | 0 of 14 | logistic C=.03 | **0.213** |
| ₹0.75/leg | −20,606 | 0 of 14 | gboost d3 | **0.207** |

Two conclusions, and only one of them is about ML:

- **Whether the underlying strategy makes money is a pure execution bet** — it flips sign between ₹0.25 and ₹0.50 per leg. That is docs/17's finding restated, not a new one, and it is why the live paper shadow (which measures *real* fills) is the only thing that can settle it.
- **The ML contribution is nil at every cost level.** Romano-Wolf stays 0.21–0.32 throughout: no model beats always-trade whether the strategy is winning or losing. **Slippage is a constant per-day shift, so it cancels out of every studentized statistic** — which is exactly why this is the invariant claim and the one the document leads with.

Note also that at ₹0.25/leg the *best* config is `gboost d2` (+16,508) — the very model an earlier version of this doc called "the worst, a textbook signature of overfitting." The ranking is noise, and it reshuffles with an assumption that has nothing to do with model capacity.

### The winner is one coin flip

`logistic C=.03` traded **193 of 194 days**. The single day it skipped lost **−₹4,695** — exactly its "+₹4,695 vs base". So its statistic has literally one degree of freedom, and the p-value reduces in closed form to the *rank of that one day*: it was the **4th worst of 194**, giving p = 4/194 = **0.021**. It traded straight through the −₹13,751, −₹12,367 and −₹10,344 days.

**Romano-Wolf adjusted across the 14 configs, p = 0.215** — roughly one noise run in five produces a best-of-14 this good. That is the headline statistic.

> **A correction to an earlier version of this doc.** It reported the winner as failing a Bonferroni bar of 0.05/14 = 0.00357. That comparison was meaningless: because the model skips exactly one day, the *smallest attainable* p is 1/194 = **0.00515**, already above the bar. **No one-skip model could ever have cleared it** — an oracle skipping the single worst day also fails. Rejecting against an unreachable threshold is not evidence. Romano-Wolf (0.215) is dependence-aware, not limited by that resolution floor, and is what this project uses elsewhere.

### The model *ranking* is noise — including the part that flattered my priors

An earlier version of this doc claimed "capacity actively hurts — gradient boosting worst — the textbook signature of overfitting." **An adversarial review refuted that using this study's own data, and it was right.** In the only controlled comparison available — *within* a model family — higher capacity is **better in 3 of the 4 families** that permit the comparison:

| family | lower capacity | higher capacity | winner |
|---|---|---|---|
| gradient boosting | d2: −20,526 | **d3: −12,583** | higher (+7,943) |
| random forest | d3: −8,882 | **d5: −6,117** | higher (+2,765) |
| ridge | a=50: −11,335 / a=10: −13,741 | **a=1: −5,547** | higher (least regularized) |
| logistic | — | non-monotone (C=1 second best) | neither |

And gboost d2's poor showing fails the *same* correction the winner fails (two-sided p × 14 ≈ 0.44–0.48 across independent Monte-Carlo runs — nowhere near significant either way). The original wording applied multiple-testing control to reject the result it disliked while keeping the one it liked — a double standard. **The honest statement is: 13 of 14 marginal p-values sit between 0.41 and 0.98, and the ranking among configs is indistinguishable from noise.**

Relatedly, an earlier claim that "the models are demonstrably not degenerate — they choose between 84 and 194 trading days" was wrong. **194/194 (svm linear) *is* the degenerate always-trade classifier, and 8 of 14 configs trade ≥90% of days.** With a 64.4% OOS win rate, "trade" is the majority class, and accuracy-trained classifiers collapsing onto it is exactly the expected no-signal behaviour. Only the three ridge regressors (84/94/115 days) gate meaningfully — and all three lose money.

### Robustness: the "edge" is a knife-edge

The adversarial audit swept the two arbitrary walk-forward knobs (`INIT_FRAC` 0.30–0.50, `STEP` 1–20, 20 combinations). The winner's advantage over base is **always exactly +₹4,695 or exactly +₹0 — never any other value** — and it vanishes entirely in 6 of 20 settings. Across nearby regularization strengths, C=0.01/0.02 collapse to always-trade (+0), C=0.03/0.04 give +4,695, C=0.05/0.07 give +2,157. It is a single decision-boundary crossing toggling on and off with arbitrary hyperparameters. That invariance is more persuasive than any p-value, and it is immune to disputes about the null.

**Disclosure of a free parameter:** `INIT_FRAC` was chosen, not derived, and the *benchmark* is sensitive to it — always-trade is **+₹7,721 at 0.30** (profitable), −₹6,636 at 0.40, −₹15,793 at 0.50. So "an already-losing stretch" is a property of where the cut was placed, not of the period. The model's own contribution is invariant to it; the benchmark is not. (K=14 also undercounts the true family: the 13 features, INIT_FRAC, STEP and the slippage assumption were all chosen too, which makes the correction anti-conservative and only strengthens the null.)

## The part that actually settles it: power

A positive control confirms the harness is not *broken*: injecting a large synthetic edge, it is found immediately — base ₹293 → gated **₹30,067 (+₹29,774), p < 1/20,001**. But that injected effect is a per-day Sharpe of ~0.8, roughly an order of magnitude larger than a mandate-sized edge. **It proves integrity, not sensitivity.**

The real question is what size of edge this sample could certify. Under the correct k-conditional null:

| gate size k | null sd | MDE @ α=.05 | MDE @ Bonferroni |
|---|---|---|---|
| 50/194 | 12,968 | **+32,246** | +45,801 |
| 100/194 | 14,818 | **+36,844** | +52,333 |
| 150/194 | 12,416 | **+30,873** | +43,851 |
| 193/194 | 2,123 | +5,279 | +7,499 |

A model that genuinely gates (trading 50–150 of the 194 days) needs **+₹31,000–37,000** to register at α=.05 — note this is the required excess over the k-conditional *null mean*, not over always-trade, and it is a normal approximation to a skewed pool (skew −2.80), so treat it as indicative, or **+₹44,000–52,000** to clear a family-wise bar — that is **31–52% of a ₹1L account over roughly nine months**. A strategy delivering exactly the project's 20–25%/yr mandate (~₹19,000 over this window) reaches only z ≈ 1.3, p ≈ 0.1: **it would not have been detected here.**

> **Required caveat.** This study demonstrates the absence of a *detectable* edge, not the absence of an edge. Because ~300 samples and 194 OOS days cannot certify a mandate-sized edge even when one exists, **no mid-sized-gate ML result on this dataset is verifiable in either direction.** (A gate skipping only a few days is the one alternative this sample *can* resolve — and the study looked there: the winner's single skip is the 4th-worst day, exact p = 4/194.) That is a stronger and more durable reason not to deploy ML here than any of the losing backtests above.

Note also that the Deflated Sharpe (0.316) is **not** independent corroboration: once the best model has a negative Sharpe (−0.005), DSR < 0.5 follows arithmetically. It restates "nothing was profitable" rather than adding evidence.

## Why this outcome was likely anyway

1. **The data is tiny** — ~300 usable samples, 129–318 training rows. Gradient boosting is the right tool for tabular finance with *tens of thousands* of rows.
2. **The relationship is non-stationary, and we have measured the flip.** The walk-forward filter study ([docs/18](18-the-verdict.md)) showed the best-in-H1 signal became *anti-predictive* in H2. Here the same regime split shows up as a train region running +₹430/day (71% win) against a test region at −₹34/day (64% win).
3. **The search was already done more rigorously** — [docs/15](15-indicator-search.md) (K=20) and [docs/16](16-exhaustive-sweep.md) (K=739 with Romano-Wolf) are feature searches with family-wise error control, and nothing beat base momentum there either.
4. **The market is adversarial.** NIFTY index options are among the most arbitraged instruments in the world.

## What this means

- **Do not propose ML for this problem again**, and do not reach for a bigger model — not because "big models overfit" (this study does not show that), but because **the dataset cannot validate a mid-sized-gate edge of usable size**, so no result it produces can be trusted in either direction.
- **Scope of what was actually ruled out:** accuracy-trained classifiers and unweighted ridge, on 13 daily features, with 129→319 training rows over 39 refits. A P&L-weighted objective (`class_weight`/`sample_weight` ∝ |net|) was **not** tested — worth recording as untested, though the power ceiling above applies to it equally.
- If ML is ever revisited it must clear this bar: walk-forward OOS, a within-region null, a dependence-aware correction (Romano-Wolf), a positive control, **and a stated minimum detectable effect**. Anything less produces a curve-fit.
- The conclusion of [docs/18](18-the-verdict.md) is unchanged: the one real edge is NIFTY 200 momentum, and it is not an options strategy.

## Two methodology traps recorded

1. **A permutation null must resample from the pool the model actually chose from.** The first version shuffled labels across the *whole* series, importing the profitable early regime into the test-window null and inflating every p-value (the winner's read 0.875 instead of ~0.02). A null that flatters the conclusion is exactly as dangerous as a positive result that flatters the strategy.
2. **Never reject against a threshold the test cannot reach.** For a model making one decision, the p-value floor is 1/N. Check the attainable range of a statistic before quoting a bar.

*Known limitation:* features are built on a strike-quantized spot proxy (the midpoint of the short strikes, ±~0.1% on a ~24,000 index) rather than true spot. This degrades signal rather than manufacturing it, so it is conservative with respect to the null — but a future attempt should use the actual entry spot.

## Reproduce

```bash
pip install -e '.[research]'     # numpy/scikit-learn/scipy — offline only, never a runtime dep
python -m optionsbot.research.ml_study data/intraday/NIFTY
python -m pytest tests/test_ml_study.py -q
```

The bot and the EC2 box remain **stdlib-only** (`dependencies = []`); nothing in this study is imported by the paper loop or any live strategy.
