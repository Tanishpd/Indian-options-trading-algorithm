# 05 — Costs and Taxes

**Cost drag is material at ₹1 lakh: the average retail F&O trader paid ₹26,000/year in transaction costs in FY24 — 26% of this account.** Every backtest and live P&L must model costs per the table below. A backtest without costs is fiction.

## Verified cost model (3–0)

| Component | Rate / amount | Notes |
|---|---|---|
| STT — option **sale** | **0.15% of premium** (from Apr 1, 2026) | Charged to the seller on premium, not notional. Use 0.10% for backtest dates before Apr 1, 2026. |
| STT — futures sale | 0.05% (from Apr 1, 2026) | 0.02% before. |
| Brokerage (discount broker) | ₹20/order → **~₹160 per iron condor round trip** | 4 legs × entry + exit. |
| Weekly condor cadence | ~₹7,700/yr brokerage alone | ~7.7% of capital before STT, exchange charges, GST, stamp duty, slippage. |
| Worked STT example | Lot 65 × ₹50 premium → ₹3,250 × 0.15% = **₹4.88 per short leg** | Verified arithmetic. |

## Rules for the bot and backtester

1. Apply **date-appropriate STT** (0.10% / 0.15% boundary at April 1, 2026).
2. Charge every leg: short legs pay STT at entry (sale); long legs pay STT when sold to close.
3. **Square off ITM long legs before expiry** rather than letting them exercise — exercise-STT mechanics were *refuted/unverified* in research (1–2 vote); avoidance is the safe engineering choice.
4. Model slippage as **protection-band limit-order fills**, not market-order fills (market orders are banned for algos — see [03-compliance.md](03-compliance.md)).
5. Track realized cost drag as a first-class metric in live trading; alert if annualized costs exceed ~8–10% of capital.

## Unverified — resolve before go-live

These were in research scope but produced **no verified claims**. Do not treat any number found online as reliable:

- **Broker API subscription fees** (e.g., Kite Connect pricing) — confirm current pricing with the broker; at ₹1L, a monthly fee is a material fraction of the target.
- **EC2 + Elastic IP + data feed costs** — price the actual stack; a t3.micro-class instance may suffice for a low-frequency bot.
- **Taxation**: F&O profits are generally treated as business income, but specifics (advance tax, tax-audit thresholds, expense deduction of infra/API costs) — **consult a CA before go-live**. Compounding math in [07-compounding-roadmap.md](07-compounding-roadmap.md) is pre-tax.
