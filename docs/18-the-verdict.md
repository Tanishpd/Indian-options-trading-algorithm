# 18 — The verdict: what works, what doesn't, and the choice that remains

This closes the strategy-research phase. It is the synthesis of docs/10–17: what was tested, what survived, and the single decision that remains. Read this first; the other docs are the evidence behind each line.

## Bottom line

- **The mandate as specified — 20–25% net at a 5–10% max drawdown, from automated options income — is not achievable in the verified evidence.** This is a *finding*, tested eight ways, not a gap waiting to be filled.
- **The one real, out-of-sample-surviving, externally-corroborated edge is NIFTY 200 momentum (docs/14): ~15% CAGR at ~30% max drawdown.** It is an equity strategy, not options.
- **For the options account specifically, the best decision is not to trade options.** Every *survivable* options structure has a structural return ceiling near ~5% (docs/12) — below the risk-free floor (~6–7%). Selling premium at a size that can't ruin you earns less than a liquid fund.
- **The remaining choice is a genuine fork, and it is the owner's:** take the real momentum edge and accept a ~30% drawdown, or preserve capital at ~6–7% and keep the drawdown cap intact. The options-income dream is not on the menu.

## The full ledger — everything tested, and its verdict

| Strategy family | Verdict | Evidence |
|---|---|---|
| Defined-risk condors/spreads (EOD, 71 trades) | net −₹16,740; no edge | [docs/10](10-first-backtest-findings.md) |
| Defined-risk condors (intraday, the rules the bot runs) | gross **negative** after 5-tick slippage | [docs/11](11-intraday-backtest-findings.md) |
| Far-OTM condor ±650/700 | statistically real but **1.4%/yr** — too small | [docs/12](12-where-the-edge-actually-is.md) |
| SENSEX (cap stops binding) | still loses ₹26,560 | [docs/12](12-where-the-edge-actually-is.md) |
| Stock options / outright futures / delta-hedged hybrid | all fail; hedging loses **even frictionless** | [docs/13](13-futures-and-hybrids.md) |
| Event-conditioned entry; volatility-regime filters | null (p = 0.965); higher vol **hurts** | [docs/12](12-where-the-edge-actually-is.md) |
| Indicator/overlay search, K=20 and exhaustive K=739 (Romano-Wolf) | **nothing beats base momentum**; trailing stops don't help | [docs/15](15-indicator-search.md), [docs/16](16-exhaustive-sweep.md) |
| Naked short strangle (₹6L, all constraints lifted) | 54% CAGR but a −13% gap = **−123% (ruin)** | [docs/17](17-the-6L-50pct-question.md) |
| Hedged strangle (protective wings) | 2% CAGR if truly capped; else not actually hedged | [docs/17](17-the-6L-50pct-question.md) |
| Intraday-only strangle (never hold overnight) | in-sample 30% is **H1 regime luck** (H2 negative); a pure slippage bet | [docs/17 addendum](17-the-6L-50pct-question.md) |
| Walk-forward regime filters to rescue intraday-only | **0/5** fix cold H2; best-in-H1 filter is **anti-predictive** in H2 (4th percentile) | this doc, below |
| Machine learning (14 configs, walk-forward + permutation + Deflated Sharpe) | **0/14** beat always-trade; winner beaten by 87% of noise (p=0.875), DSR 0.316; gradient boosting **worst** | [docs/19](19-ml-has-no-edge.md) |
| **NIFTY 200 momentum** | **the one edge** — ~15% CAGR, ~30% maxDD | [docs/14](14-momentum-the-one-real-edge.md) |

## Why options specifically cannot meet the mandate

One mechanism explains every negative result above:

1. **The variance risk premium is real and large, but entirely tail insurance** (docs/12). Everything within ±500 points of ATM is worth only +₹48/cycle; a defined-risk structure is short the near strikes and long the far ones — a net *buyer* of the only part of the surface that pays.
2. **The cap cannot reach the tail.** NIFTY's minimum risk unit is 50pt × lot 65 = **₹3,250, already above the ₹2,000 per-trade cap**, so every legal structure is confined to the body. The structural return ceiling is ~5%/yr; the mandate needs 19.23% *per cycle*.
3. **The return dial and the risk-of-ruin dial are the same dial** (docs/17). Remove the cap and you can reach 54% — with a −123% gap tail. Hedge the tail and the return collapses to 2%. Go intraday to dodge the gap and the edge turns out to be one regime's luck. Try to filter the bad regime and the filter is overfit noise. Every door out of the ceiling opens onto the same room.

### The walk-forward filter result (closing intraday-only)

The intraday-only strangle looked like the best thing options produced — 30.8% CAGR in-sample — until an out-of-sample split showed it was **+74% in H1 and negative in H2** (docs/17). The obvious rescue is a regime filter that stands down in H2-like conditions. Done honestly — fit each filter's threshold on **H1 only**, lock it, test **cold on H2**, and require it to beat a permutation null (removing the same number of H2 days at random) — five pre-registered filters (rich/cheap premium, low realized vol, low trend, small gap) all fail, at both realistic (₹0.50/leg) and optimistic (₹0.25/leg) fills:

- **0 of 5 turn cold H2 positive. 0 of 5 beat random day-dropping.**
- The filter that fit **best** on H1 (skip-high-realized-vol) landed at the **4th percentile** on H2 — *worse* than 96% of random day-drops. The signal-to-return relationship flipped between regimes: a filter fit to H1 tells you to do exactly the wrong thing in H2.

That is the definitive close: the intraday negatives are not a fixable defect, they are the strategy's true edge (≈0, regime-dependent) refusing to be filtered away.

## The one edge that survived: NIFTY 200 momentum

[docs/14](14-momentum-the-one-real-edge.md) is the only strategy in the entire investigation with an edge that (a) survives out-of-sample and (b) is corroborated by outside evidence (the momentum factor is one of the most-replicated anomalies in equities). The K=20 and K=739 searches (docs/15–16) then proved nothing beats *base* momentum — the survivor is the plain strategy, not a curve-fit overlay.

Honest profile:
- **~15% CAGR, ~30% maximum drawdown.** A monthly-rebalanced basket of the strongest momentum names in the NIFTY 200 — **equity, not options.**
- **It does not meet the 5–10% drawdown cap** (~30% is 3–6× the budget), and ~15% sits just under the 20–25% target.
- **It needs clean point-in-time data to validate and run live** (survivorship-bias-free). That is the one concrete task between "backtest exists" and "tradeable."

It is real, which nothing in options is. But it is a different risk profile than the original mandate, and that must be faced honestly rather than papered over.

## The choice that remains

- **Path A — pursue the edge.** Accept ~30% drawdown, secure clean point-in-time NIFTY 200 data, and validate/run the docs/14 momentum strategy at live grade. The only path to a tradeable edge.
- **Path B — preserve capital.** Accept that active options trading has no survivable edge here; pledge liquid ETFs / hold T-bill-like instruments for ~6–7% near-risk-free, drawdown cap intact.

Both are honest. The third option — keep chasing 20–25% at 5–10% drawdown from options — is the one the evidence rules out.

## What was NOT the problem (so it is not relitigated)

Not the cost model, not the capital size, not a missing parameter, and **not the risk architecture.** Shift the tested per-trade distribution to earn 20%/yr while keeping its exact variance and P(drawdown ≤ 10%) is 99.7% — the drawdown is a symptom of the negative mean, not a separate failure. The risk design is sound and should be kept.

## Why to trust this

Every too-good result in this project was an artifact caught by verification *before* it was acted on: the condor's 58% was survivorship bias (docs/17), the intraday 30% was one regime's luck, the rescue filters were overfit noise, and earlier the momentum "edge" was an index-fetch bug (docs/15). The infrastructure — backtester, cost engine, overfit controls, walk-forward discipline — is sound and reusable. The premise that failed was options income at a low drawdown, not the machinery that tested it.

**Research phase: closed.** Gate 2 remains NOT PASSED for options (PLAN.md). The forward path is the owner's choice between Path A and Path B above.

## Reproduce

```bash
# The options ledger (docs/10–17) — each doc has its own reproduce block.
# The walk-forward filter study that closes intraday-only:
python -m optionsbot.research.walk_forward data/intraday/NIFTY
python -m pytest tests/test_walk_forward.py -q
```
