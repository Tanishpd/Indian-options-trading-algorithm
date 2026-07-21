# 01 — Strategy Selection

**Recommendation: single-lot, defined-risk option selling on NIFTY/SENSEX weeklies — credit spreads or iron condors.**

## Why this and only this

At ₹1 lakh, this is the sole structurally feasible selling category (verified 3–0):

- One NIFTY lot (65) controls ~₹16 lakh+ notional. An unhedged short lot needs ~₹2.3 lakh+ margin — more than double the account.
- Hedged structures (buy wings against the short legs) cut margin roughly 60–70% under NSE's SPAN hedge-benefit framework, bringing a one-lot iron condor within reach of ₹1 lakh — with a *higher* return on blocked margin than the naked equivalent.
- Defined max loss is what makes the 5–10% drawdown cap enforceable at all. Naked selling has uncapped tail risk; one gap event ends the project.

## Permitted universe

| Venue | Instrument | Weekly expiry |
|---|---|---|
| NSE | NIFTY options (lot 65) | Tuesday |
| BSE | SENSEX options | Thursday |

That's the entire weekly universe. Since November 2024 each exchange may run one weekly index expiry only.

**SENSEX can be traded but not yet validated to the same standard as NIFTY.**
Free BSE bhavcopy supplies end-of-day SENSEX option data (verified working, same
UDiFF schema as NSE), so hold-to-expiry economics are testable. What does not
exist at any retail price is **intraday SENSEX option history**, so the
intraday-triggered rules the live bot actually runs cannot be backtested on
SENSEX at all. NIFTY has the same intraday gap, but a far deeper EOD sample.

Consequence for the docs/06 gate order: **Phase 3 validation is NIFTY-first in
practice.** Trading SENSEX live would rest on materially thinner evidence, and
that should be a deliberate decision rather than something discovered after the
fact.

## Explicitly ruled out

- **Naked strangles/straddles/short options** — margin impossible at ₹1L; tail risk violates the drawdown cap at any capital.
- **BANKNIFTY/FINNIFTY/MIDCPNIFTY weekly systems** — weeklies discontinued November 2024; monthly only. Any vendor showing a BANKNIFTY-weekly backtest is showing an unreproducible strategy.
- **Multi-lot positions** — not until capital grows (see [07-compounding-roadmap.md](07-compounding-roadmap.md)).
- **Option buying as the core strategy** — no verified evidence of positive expectancy; low win rates make the drawdown cap hard to defend. Debit spreads may serve as occasional directional tactics, not the engine.

## The evidence gap (read before believing anyone)

**No backtested or live return/drawdown claim for ANY strategy survived adversarial verification** — not from AlgoTest, Streak, YouTube, forums, or vendors. Only regulation, margin, and cost claims verified. Consequences:

1. Strategy parameters (deltas, wing widths, entry/exit timing) must be chosen via our own backtests on post-November-2024 data ([06-backtesting-and-validation.md](06-backtesting-and-validation.md)).
2. "Consistent 3–5% monthly" claims are marketing until reproduced on our own data.
3. The paper-trading record is the only performance evidence that will exist. Plan for it.

## Base-rate honesty

SEBI: 93% of 1+ crore retail F&O traders lost money FY22–FY24; only ~1% earned >₹1 lakh profit after costs. The target (₹20–25k/yr on ₹1L) is a top-1% outcome. The plan is structurally sound; its probability is unproven. Expect sub-target years.
