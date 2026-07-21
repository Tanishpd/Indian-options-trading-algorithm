# 11 — Intraday Backtest Findings (July 2026)

The second real backtest, and the first one that tests **the strategy the live
bot actually runs** — entry inside a time window, exit on a profit target or a
stop, forced square-off on expiry day. [docs/10](10-first-backtest-findings.md)
could not evaluate those rules, because end-of-day data cannot say which trigger
was reached first.

**It is another negative result, and it is stronger than the first one.** It also
found a defect in the deployed bot that had nothing to do with profitability.

## Setup

- **Data**: minute-level NIFTY option chains, the final ten trading days before
  each expiry, **72 expiry cycles, 2024-11-07 → 2026-03-24**, 112,711 chain
  minutes. Authenticity verified against official NSE bhavcopy before use — see
  [Data provenance](#data-provenance) below.
- **Strategy**: iron condor, shorts ~0.8% OTM, 50-point wings, entered 2–6 DTE
  between 10:00 and 14:00, exited on profit target, stop, or expiry-day
  square-off.
- **Costs**: the project cost engine. Verified independently during review —
  ₹226.74/trade, of which ₹160 is brokerage on 8 orders; STT charged on sell
  legs only, reconciled to the paisa.
- **Risk**: ₹2,000 per-trade cap; lot size from the exchange schedule (25 → 75 →
  65 across the sample).

## The headline

Shipped configuration (target 50% of credit, stop 60% of max loss), 0.25 points
per leg of slippage, on ₹1,00,000:

| | Trades | Net P&L | Gross | Costs | Max DD |
|---|---:|---:|---:|---:|---:|
| **As the bot runs it** (per-trade cap on) | 57 | **−₹12,745** | +₹369 | ₹13,114 | **₹12,745** |
| **All 72 cycles** (cap not filtering entry) | 72 | **−₹21,066** | −₹4,828 | ₹16,237 | **₹21,066** |

Drawdown is 12.7% on the first line and 21.1% on the second.

> **CORRECTED framing ([docs/12](12-where-the-edge-actually-is.md)).** This
> originally read "two to four times the mandated cap, the same failure mode as
> docs/10", presenting the drawdown as a second, independent failure. It is not —
> it is a consequence of the negative mean. Bootstrapping this same per-trade
> distribution, shifted only so the strategy earns 20%/yr and keeping its exact
> variance, gives a median 1-year drawdown of **3.4%** and **P(drawdown ≤ 10%) =
> 99.7%**. There is one problem, the mean, not two. The risk framework is sound
> and should not be redesigned in response to these results.

**Gross is roughly zero in the first row and negative in the second.** That is
the whole finding: the apparent edge is smaller than the bid/ask spread it has to
cross eight times.

This is *not* because the options are efficiently priced. They are not — the
measured variance risk premium is **+2.08 volatility points (t = 2.95)**, worth
about ₹240 per condor against a ₹226 cost floor. The edge is real and the same
size as the cost. See [docs/12](12-where-the-edge-actually-is.md).

Read the second row as the honest one. The gap between the two is not the
strategy performing better under a risk control — it is the per-trade cap acting
as an undeclared entry filter, quantified below.

## Why the first number was wrong

### 1. Slippage was zero

Entry credit and exit value both used the same last-traded price, so the
round-trip spread on eight legs was unmodelled — against
[mandate rule 4](../CLAUDE.md). At a modest 5 ticks per leg the entire gross
edge disappears:

Shipped config, all 72 cycles:

| Slippage/leg | Gross | Net |
|---|---:|---:|
| 0.00 | +₹6,190 | −₹9,999 |
| 0.10 | +₹2,489 | −₹13,698 |
| **0.25** | **−₹4,828** | **−₹21,066** |
| 0.50 | −₹13,488 | −₹29,707 |

The study's `slippage_per_leg` now defaults to 0.25 rather than 0.0, so the
honest run is no longer the one you have to remember to ask for.

### 2. The per-trade risk cap was silently acting as a volatility filter

Entry waits until the condor is rich enough that `(wing − credit) × lot` fits the
₹2,000 cap. That is a **"only enter when premium is rich" signal**, not a risk
control. It rejects **25,357 of 49,829 candidate entry minutes (50.9%)** — every
other filter in the entry path combined rejects zero — and drops 15 cycles
outright.

**The dropped cycles are systematically the quiet weeks.** Traded cycles average
12.18% realised volatility; dropped cycles average 7.20%. Three independent
estimators agree on a ratio near 1.6, so it is not an artifact of one measure:

| Measure | Traded | Dropped | Ratio |
|---|---:|---:|---:|
| Daily close-to-close, annualised | 12.18% | 7.20% | 1.69 |
| Minute-return, annualised | 12.11% | 7.57% | 1.60 |
| Cycle spot range % (estimator-free) | 3.41% | 2.12% | 1.61 |

Mann-Whitney z = +4.19: traded cycles rank above dropped ones in 85% of pairs.
The shipped config therefore **reports a loss 63% smaller than the full sample
and hides 21% of the calendar during which the bot sits flat.**

Two further things make it indefensible as a result:

- **Its threshold is a contract-spec artifact, not a market fact.** Required
  credit is `50 − 2000/lot`: −30.00 at lot 25 (the cap can never bind), 19.23 at
  lot 65, 23.33 at lot 75. Re-running each dropped week's identical bars at each
  lot size: **15 of 15 trade at lot 25, 8 of 15 at lot 65, 0 of 15 at lot 75.**
  Same prices, different verdict, purely from the lot divisor. The sample
  contains three different entry rules wearing one name.
- **Adding a cost improved P&L.** At 0.10 slippage the net *rose*, because more
  cycles fell below the cap and dropped out. A backtest where costs help has a
  selection filter in it, definitionally.

`no_entry` is also a mislabel: it reads as "no opportunity" but means "no
*affordable* entry" — a credit filter reported under a risk label, which is
exactly how it escaped notice for two rounds of review.

The live bot has the same cap and will behave the same way, so this is not a bug
to fix. It is the reason the cap-on figure must never be quoted alone.

### 3. One correction pointed the other way

The stop fires on first touch and is whipsawed. Median overshoot past the
threshold is **+0.40 points** on a 50-point structure; **76.5% of stop exits
revert within one minute**, and 55% are back below the threshold within five.
Requiring the level to hold for two consecutive minutes recovers ₹1,835.

This is *not* stale or thin data — at stop-firing minutes the thinnest leg had
median volume 89,738, and no exit had any leg below 375. It is genuine
non-synchronicity between four last-traded prices inside the same minute.

₹1,835 recovered against ₹8,321 of selection and ₹11,067 of unmodelled slippage.
The net direction is unambiguous: **the truth is worse than first reported.**

## The defect this study found in the deployed bot

Independent of profitability, and the reason this work mattered even though the
answer was again "no edge":

**The live stop could not fire.** It was written as a multiple of the entry
credit — exit when the buyback cost reaches `2.0 × credit`. On a 29-point credit
(the sample median) that asks for a structure worth 58 when a 50-point wing caps
it at 50. Measured across the 72 cycles, **the stop was unreachable in 45 of them
(62%)**. The bot was running with no stop most of the time, and nothing in the
logs said so, because an unreachable threshold is silent.

The fix expresses both triggers in rupees against the book that actually exists:

```python
credit = sum(-p.entry_price * p.net for p in book)     # premium received
worst  = worst_case_loss(self._book_legs(book))        # the book's own max loss
pnl    = sum((q.ltp - p.entry_price) * p.net for p, q in zip(book, quotes))

if not (-worst <= pnl <= credit):
    return                                  # non-synchronous prints, not a price
if pnl >= profit_target_frac * credit:  ...     # target
elif -pnl >= stop_loss_frac * worst:    ...     # stop, always attainable
```

Deriving max loss from `params` instead of from the held book was itself rejected
in review: a params/book divergence — a config edit across a restart, or the
adopt-from-book path — put the threshold beyond anything the structure could
reach. Same failure, new route. `worst_case_loss` uses the real strikes and share
counts, so the threshold is a fraction of a quantity the position can actually
reach, by construction.

### Two more, found only by mutation-testing the fix itself

**A limit price of ₹0.00 was being sent for any leg sitting at the minimum tick.**
`to_tick` rounds SELL limits down, so a 0.05 leg with the exit pad applied
(0.049x) floored to zero. A zero SELL limit is not a low price — it is *"accept
anything"* — and the broker crossed it and booked ₹0.00 for a leg worth ₹3.25.
It fired on both exit paths, including `_flatten`, which is the expiry-day
square-off and kill-switch backstop, at every configured protection band
(0.0475 → 0.00 at the default 5%). That path runs precisely when deep-OTM wings
are sitting at 0.05. The money is small — roughly ₹470/yr — but the mechanism is
not: `to_tick` exists to keep limits on the exchange grid, and its own
`max(0.0, ...)` clamp was laundering a sub-minimum price into a valid-looking
one. `to_tick` had **no test coverage at all**, which is how it shipped.

**The live entry path had no no-arbitrage bound.** The study rejects an
over-wing credit; the live strategy did not, and the per-trade cap cannot catch
it — an over-wing credit makes `worst` *negative*, so the cap check passes
trivially and the bot enters a real position on a price that never existed.

Two further defects were fixed in the same pass:

- **The live bot had no no-arbitrage bound on its mark.** The study rejects a
  structure value outside `[0, wing]`; the live code had no counterpart, so a
  single stale print implying a ₹5,850 loss on a ₹1,690 max-loss book would have
  flattened a sound position and booked a real loss.
- **The study never bound-checked its entry credit.** Only exits were checked. An
  inflated credit from four non-synchronous prints pushes the stop threshold
  above the wing, so the position runs unstopped to a settled exit that books a
  guaranteed profit. It did not fire on this data — maximum observed entry credit
  was 38.6 against a 50-point wing — but it was a live trap in the evidence base.

### How these were found, and what it says about the tests

Every defect above except the first survived at least one round of review that
declared the code correct. What actually found them was **mutation testing** —
changing one constant or one operator and asking whether any test notices. The
first pass found 15 surviving mutants, meaning the suite could not distinguish
the shipped code from these:

| Mutant | Survived |
|---|---|
| Live stop 0.60 → 0.30 | ✓ |
| Live profit target 0.50 → anything in 0.34–0.68 | ✓ |
| Study stop 0.60 → anything in 0.10–0.73 | ✓ |
| Study profit target 0.50 → anything ≤ 0.50 | ✓ |
| `>=` → `>` on either trigger, live and study | ✓ |
| No-arbitrage bound inverted to `-credit <= pnl <= worst` | ✓ |
| Bound widened to 3.2× the wing width | ✓ |
| Entry bound check deleted, live and study | ✓ |
| Tick zero-clamp removed | ✓ |

A green suite meant almost nothing about the thresholds. Asserting one point on
the far side of a threshold pins the *direction* but not the *level*, and a stop
whose level is untested is exactly how this strategy shipped with an unreachable
one. The suite now carries near-side and exact-equality cases for every
threshold; **all 15 mutants are killed**, and 203 tests pass.

## Data provenance

The dataset is real, not synthetic, and was verified before use rather than
assumed:

- Per-contract daily volume reconciles to official NSE bhavcopy at a ratio of
  **74.95 against a lot size of exactly 75** (299 of 329 contracts within 1%).
- The official closing price falls inside the observed intraday range for
  **329 of 329** contracts tested.
- 375 bars per session, as expected.
- Spot agrees across all four chain legs in every one of 112,711 minutes.
- Weekday census — Thursday 40, Tuesday 28, Wednesday 2, Monday 2 — consistent
  with the NIFTY Thursday→Tuesday expiry change plus holiday shifts.

Known limitations, documented rather than smoothed over:

- **30.5% of minutes carry zero volume.** Those prices are forward-filled
  carries, not trades. `Bar.tradeable` is a first-class concept and `Bar.price`
  is `None` when volume is zero; entry requires all four legs tradeable in the
  *same* minute.
- **4.4% of prices sit off the 0.05 tick grid**, implying per-minute aggregation
  rather than a raw last trade.
- The derived columns in the source are junk (a 23050 PUT labelled ITM at spot
  25266; theta 43.9 on a ₹0.05 option) and are not read.
- One price per minute: no OHLC, no bid/ask. **This is why slippage has to be
  assumed rather than measured**, and why the 0.25 pts/leg row above is the one
  to believe.

## What this means for the plan

1. **Do not go live with this strategy.** Two independent studies on two
   independent datasets now agree: hold-to-expiry (docs/10) and
   intraday-triggered (here). Neither monetises the edge that exists
   ([docs/12](12-where-the-edge-actually-is.md)): the variance risk premium is
   real at +2.08 volatility points but worth ₹240 against a ₹226 cost floor, and
   20%/yr would require 5.4 points.
2. **The cost floor is the binding problem, not the parameters.** ₹227 per round
   trip on a structure whose median credit is 28 points (₹1,820 at lot 65) means
   costs eat 12% of maximum theoretical profit before any market risk. A 3×3
   parameter sweep did not find a corner where that reverses — all nine
   combinations lost money, and the best in-sample config (+₹843) went to −₹6,302
   out of sample.
3. **Stop-loss placement is not the lever.** It was worth testing precisely
   because the deployed stop was broken, but fixing it did not change the
   conclusion. Stops at 40%, 60% and 80% of max loss all lose.
4. **Mutation-test any future study before believing it.** A green suite did not
   distinguish this code from fifteen broken variants of itself, several of which
   would have manufactured a positive result.
5. **Any future variant must clear a higher bar than "positive in sample."** The
   selection-filter finding above is the reason: a result can be positive because
   of a filter nobody declared. Report cap-on and cap-off figures side by side,
   and model slippage explicitly, or the number is not evidence.

## Reproducing

```
python -m optionsbot.research.run_intraday data/intraday/NIFTY --targets 0.50 --stops 0.60
```

reproduces the headline table exactly. Every figure in this document comes from
that runner; the first version of these findings was produced by a throwaway
script, which is not evidence anyone can audit.

The study module is [`src/optionsbot/research/intraday_condor.py`](../src/optionsbot/research/intraday_condor.py);
its correctness rules are documented in the module docstring, and each one exists
because violating it fabricates money. The hand-computed test literals are in
[`tests/test_intraday_condor.py`](../tests/test_intraday_condor.py).
