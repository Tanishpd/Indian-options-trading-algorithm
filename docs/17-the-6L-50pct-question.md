# 17 — The ₹6L / 50%-return question: naked selling works, and would ruin you; hedging it is either return-free or not a hedge

**Read this before anyone proposes "just sell strangles" or "hedge the strangle with wings/futures."** The owner asked, explicitly lifting the mandate's three binding constraints — the ₹5–10k drawdown cap, the defined-risk-only rule, and the ₹1L capital — whether options can target **50%+ annual** on **₹6,00,000** with "no objection to anything." This is the honest answer, measured on the same real NIFTY minute data as docs/10–11 (72 weekly cycles, 2024-11-07 → 2026-03-24, 1.37 years), net of honest costs and slippage.

The short version: **yes, a naked short strangle clears 50% in this window — and it is an uninsurable path to ruin.** Every attempt to keep the return while capping the tail collapses back onto the same frontier. There is no options structure here that pays 50% at a survivable drawdown. This is not an opinion; it is four measurements below.

## The vehicle: naked short strangle

Sell a ~1% OTM call and a ~1% OTM put each weekly cycle, collect the premium, hold to expiry. It harvests theta and the variance risk premium (docs/12) — and it is short the exact tail those same studies showed is where both the money and the ruin live. There are no wings; the loss is unbounded. Built in [`short_strangle.py`](../src/optionsbot/research/short_strangle.py), measured in [`run_strangle.py`](../src/optionsbot/research/run_strangle.py). Nothing in the engine caps per-trade loss — the whole point is to show what removing the cap costs.

Margin for a naked NIFTY strangle is ~₹1.4L/lot (SPAN+exposure; **verify with broker**), so ₹6L funds **4 lots**. All figures below use 4-lot sizing.

## Finding 1 — it DOES clear 50%, and the tail is ruin

At 1% OTM, 4 lots, hold-to-expiry:

- **CAGR ≈ 54%.** Real, in this window. The 50% target is achievable — that was never the question.
- **In-sample maxDD ≈ 66%.** Even without a single true gap in the sample, the grind of losing weeks alone draws the account down two-thirds.
- **A single −13% overnight gap (COVID-day size) = −123% of capital.** That is not a drawdown; it is a **debit balance** — the account is gone and you owe the broker. One gap, once, ends it.

Return and risk-of-ruin are **the same dial**: both scale linearly with lots. Turning CAGR up to 100% requires ~8 lots, which ₹6L cannot margin, and would make the gap tail −250%. There is no lot count that delivers 50%+ CAGR at ≤30% maxDD. The "50/30" profile does not exist in the naked strangle.

Why the in-sample maxDD understates the danger: this 16-month window contains **no gap anywhere near the stress sizes** (worst single day −2.94%, peak-to-trough −14.6% spread over weeks). The −123% tail is not in the backtest — it is what the structure owes when the gap that *isn't* in this sample arrives. A benign sample is the naked seller's most dangerous friend.

## Finding 2 — exit management does not rescue it

A real trader runs a stop, so the study also measures the same strangle under stops, targets, and trailing locks. None of them helps, for one structural reason:

**A stop-loss caps a GRIND but not a GAP.** Intra-cycle marks come from the data. When the index jumps between the last bar of one day and the first of the next, the position is marked — and can only be exited — at the *gapped* price, not the stop level. You cannot trade during the gap. So the stop that looks like a floor in a slow bleed is worthless against the exact event (the overnight jump) that produces the −123% tail.

And the "softer" exits actively destroy the return: a profit target caps the winners while leaving the losers uncapped (the payoff asymmetry that makes short premium dangerous), and a trailing profit-lock whipsaws out of positions that would have expired worthless — the identical failure the trailing stop showed on momentum (docs/15/16) and on the condor (docs/11 addendum). Short premium is negative-gamma/positive-theta; a trailing stop is structurally wrong for it.

## Finding 3 — the condor "breakthrough" was a survivorship artifact

Mid-investigation a wide-wing iron condor appeared to break the frontier: **58% CAGR / 27% maxDD / −28% *capped* tail** — seemingly dominating the naked strangle and hitting the "50%/30%" profile I had said was impossible. I flagged it as suspicious and refused to report it until verified. It was an artifact, on two counts:

1. **The condor engine ([`intraday_condor.py`](../src/optionsbot/research/intraday_condor.py)) requires all four legs tradeable in the same minute to enter.** The 750-point wings are deep OTM with frequent zero volume, so the condor **could not enter 24 of the 72 cycles and silently dropped them.** Deleting cycles is precisely the survivorship the condor module's own comment warns of ("removed only maximum-loss outcomes — enough to flip the sign of the result"). Its 27% maxDD came from never trading the weeks that hurt.
2. **On the cycles it did trade, it entered at a *different* minute/spot than the strangle** (it had to wait for a minute where the illiquid wings were also quotable), producing impossible per-cycle comparisons — e.g. 2025-05-15, same expiry: naked −₹36,149 vs "condor" −₹1,184. Not the wing working; a different position entirely.

So the condor-vs-strangle comparison was never apples-to-apples. It compared a 48-cycle strategy to a 72-cycle one, entered differently. The 58/27/capped result is not a valid measurement of "strangle + wings" and is **off the table.**

## Finding 4 — the clean apples-to-apples hedge test: no free lunch, and you can't hedge the weeks that hurt

To measure the wing's *true* effect, the strangle engine was extended to bolt wings onto the **identical** position: same entry minute, same short strikes, same 72 cycles — the only variable is the wings. When the wing strikes have no volume at entry, the cycle stays **naked and flagged** (not dropped), which is what a real trader actually faces and which kills the survivorship. (`StrangleParams.wing_points`; tests pin the wing capping the loss and the naked fallback.)

Same shorts, same entry, same 72 cycles, 4 lots, 1% OTM:

| Structure | Weeks actually hedged | CAGR | in-samp maxDD | −13% gap tail |
|---|---|---|---|---|
| **Naked** (wings = 0) | 0 / 72 | **54%** | 66% | **−123%** (unbounded) |
| + 300pt wings | **72 / 72** | **2%** | 33% | **−9%** (truly capped) |
| + 500pt wings | 71 / 72 | 7% | 55% | −17% hedged / −123% naked |
| + 750pt wings | **22 / 72** | 45% | 68% | −29% hedged / −123% naked |
| + 1000pt wings | 0 / 72 | 54% | 66% | −123% (never tradeable) |

The two endpoints are the entire result:

- **Cap the tail for real (300pt wings, tradeable every week): CAGR collapses to 2%.** The wings ate the entire return. A fully-defined-risk condor at survivable sizing pays *below a fixed deposit* — the same conclusion docs/10–11 reached by a different road.
- **Keep the 45–54% CAGR (750–1000pt wings): you are naked on 50–72 of the 72 weeks**, so the −123% gap tail is fully intact. The wide wing that would be cheap enough to leave return on the table is exactly the strike with no volume — it is never actually in place. "45% CAGR hedged" is the naked strategy wearing a costume.

And the kill shot is the per-cycle table. Of the 8 worst naked weeks, **7 ran naked even in the "750pt hedged" run** — the wing was untradeable those exact weeks — so it helped by ₹0:

```
expiry        naked net   hedged net   hedged?
2025-04-17     -36,431     -36,431      NAKED
2025-05-15     -36,149     -36,149      NAKED
2025-04-09     -32,035     -32,035      NAKED
2025-03-20     -25,729     -25,729      NAKED
2025-06-26     -22,802     -22,802      NAKED
2025-10-20     -21,742     -21,742      NAKED
2026-03-24     -14,443     -14,443      NAKED
2026-03-02     -14,325     -15,723      yes    (wing made it -1,398 WORSE)
```

**You cannot hedge the weeks that hurt you.** The deep OTM wing has no liquidity precisely when the market is moving — it is available on calm weeks (where it is pure cost, as 2026-03-02 shows) and gone on the weeks you need it. This is not a data quirk to engineer around; it is the structural reason the tail cannot be cheaply insured.

Futures/delta-hedged hybrids fail the same way and worse (documented separately in docs/13): a future hedges direction, not the gamma that the gap detonates, and it converts the defined-cost problem into a margin-and-basis problem.

## Verdict

The frontier holds. Restated cleanly, and now proven on identical positions rather than inferred:

- **50%+ CAGR on ₹6L via options is achievable only by selling naked, which carries an unbounded gap tail that a single COVID-sized move turns into a debit balance.** The benign sample hides it; it does not remove it.
- **Insuring that tail costs the return in near-exact proportion.** Fully capped ⇒ 2% CAGR. Anything paying 45%+ is not actually capped.
- **There is no options structure in this data that delivers 50%+ CAGR at a survivable drawdown.** Return and risk-of-ruin are one dial; wings move you along the frontier, never off it.

This is the mandate's defined-risk-only rule and drawdown cap, re-derived from scratch with the constraints removed — which is the strongest possible confirmation of them. The answer to "can options make 50%+ if we drop every rule" is **yes, once, and then never again.**

## What this cost to learn correctly

The 58/27/capped mirage passed a naive comparison and looked like the one genuinely promising thing options offered. It died only because the result was flagged as too-good and verified before being reported — the same discipline that caught the momentum index-fetch gap (docs/15) and the naked-strangle margin trap (docs/13). A backtest that beats the frontier is a bug until proven otherwise.

## Addendum — "what if we don't take overnight positions at all?"

The ruin tail in Finding 1 is an *overnight* gap: it opens between the close and the next open, when you cannot trade. So the natural question is whether going **intraday-only** — flat every night — removes it. It does. But it removes two things, not one, and the second is the edge.

Going intraday-only (sell a 1% OTM strangle near the open on the nearest weekly, be flat by 15:25, or an intraday stop fires) **removes the overnight-gap ruin** — you are flat every night, and a stop *can* now act because there is a mark every minute — **but it also forgoes the overnight/weekend theta that is the actual edge, and pays entry+exit costs ~5× per week** instead of once per cycle. Built in [`intraday_only.py`](../src/optionsbot/research/intraday_only.py), each trading day is its own cycle, most-favourable window (earliest sane entry, latest exit), 4 lots, honest costs.

In-sample on the full window it is the *best* thing options produced in this whole investigation — which is exactly why it has to be verified before it is believed:

| Intraday-only, 1% OTM, 4 lots, 345 days | CAGR | maxDD | win | worst day |
|---|---|---|---|---|
| No stop (flat 15:25) | 30.8% | 19% | 70% | −₹73,511 |
| Stop 2× credit | 33.5% | 17% | 65% | −₹65,165 |
| Stop 1.5× credit | 21.6% | 21% | 60% | −₹37,916 |

The ruin tail is genuinely gone (worst day −₹18k/lot, bounded — not −123%), and the stop *earns its keep* here, unlike against a gap. But two tests kill the return:

**1. It is a pure execution bet.** The per-day edge is thin (~₹3/share net) and paid ~345×/year, so it lives or dies on the fill assumption:

| slippage / leg | CAGR | maxDD |
|---|---|---|
| ₹0.25 (5 ticks) | 30.8% | 19% |
| ₹0.50 (10 ticks) | 20.5% | 20% |
| ₹0.75 (15 ticks) | 9.8% | 24% |
| ₹1.00 (20 ticks) | −1.3% | 35% |
| ₹1.50 (30 ticks) | −25.2% | 61% |

Breakeven is ~₹1.00/leg; it clears the 20–25% target only inside ₹0.25–0.50/leg. There is no market-structure moat — you are paid for good execution, nothing more.

**2. It is entirely one regime.** Split the window in half and the edge is not there in the second:

| Half (no stop) | slip ₹0.25 | slip ₹0.50 |
|---|---|---|
| H1 (2024-11 → 2025-07) | +74.3% | +61.8% |
| H2 (2025-07 → 2026-03) | **−3.1%** | **−14.7%** |

The full-window 30.8% is the average of a spectacular H1 and a **losing H2** — the most recent eight months lost money. Out-of-sample there is no edge. The per-day shape is textbook short-premium: median +₹460/lot, a fatter left tail (min −₹18,378 vs max +₹11,058), 11 of 343 days worse than −₹5k/lot — and in H2 those hits cluster enough to erase the gains.

**Verdict:** intraday-only converts *ruin risk* into *no durable edge + an execution bet* — not into free return. It is the same frontier reached from a new direction. And even at its in-sample best the ~18% drawdown already exceeds the mandate's 5–10% cap. This is the result that would have snared us if the full-window 30.8% had been reported without the out-of-sample split — the identical discipline that killed the condor above and the momentum overlays (docs/15–16). A single-window backtest that clears the target is a hypothesis, not a finding.

## Reproduce

```bash
# Naked strangle: return, exit-management comparison, crash stress
python -m optionsbot.research.run_strangle data/intraday/NIFTY

# The clean apples-to-apples hedge test (same position, wings the only variable)
# lives in the research scripts; StrangleParams.wing_points drives it.
python -m pytest tests/test_short_strangle.py -q

# Intraday-only (never hold overnight): base table + slippage sweep + OOS split
python -m optionsbot.research.intraday_only data/intraday/NIFTY
python -m pytest tests/test_intraday_only.py -q
```

Data is the same local intraday NIFTY chains as docs/10–11 (not git-tracked). No result here is a recommendation to sell naked options; it is a measurement of the strategy the mandate forbids, so the cost of removing the cap is explicit and permanent.
