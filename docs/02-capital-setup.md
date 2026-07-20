# 02 — Capital Setup: Pledged Liquid-ETF Collateral

**Recommendation: create the margin collateral from the ₹1 lakh itself — no pre-existing holdings needed.**

## The allocation

| Bucket | Amount | Purpose |
|---|---:|---|
| Liquid ETF / liquid fund, pledged | ~₹85–90k | Margin collateral (~₹76–80k after ~10% haircut) + earns ~5–6% yield |
| Actual cash | ~₹10–15k | Mark-to-market settlement buffer |

## Why (verified 3–0)

- Exchanges require ≥50% of overnight F&O margin in cash or cash-equivalents. **Liquid ETFs (e.g., LiquidBees) and liquid mutual funds are classified as cash-equivalent**, so pledged units can back the *entire* margin requirement — the 50% rule doesn't bind them (unlike pledged stocks/equity funds).
- The ~5–6% yield (~₹4,500–5,500/yr on ₹90k) funds roughly a fifth of the 20–25% target essentially risk-free — the only guaranteed return component in the whole plan.

## Setup steps

1. Fund the account with ₹1,00,000.
2. Buy ~₹85–90k of a liquid ETF on the exchange (bought like a stock) or a liquid fund.
3. Pledge via the broker's platform (~₹30+GST per pledge; on Zerodha: Console → Portfolio → Pledge). Collateral margin appears the next trading day.
4. Keep ~₹10–15k as unencumbered cash for MTM.
5. **Before any trade**: price a one-lot NIFTY (lot 65) iron condor on the broker's margin calculator to confirm it fits inside the collateral with headroom. Current rupee margin was an open question the research could not verify — check it live, and account for the short-leg-first order sequencing brokers require for the hedge margin benefit.

## Trade-offs and traps

- **Haircut**: ~10% of margin power lost vs holding pure cash (₹1L cash → ₹1L margin; pledged route → ~₹90k total).
- **Unpledge latency**: about one trading day to convert back to sellable units — this capital is not instantly withdrawable.
- **MTM shortfall drag**: losses settle in real cash. If the cash bucket runs dry, some brokers charge ~0.035%/day interest on the shortfall instead of blocking orders. **The bot must monitor the cash balance and alert before this happens.**
- Haircuts and approved-securities lists change periodically — reconfirm with the broker at setup time.
