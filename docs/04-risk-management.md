# 04 — Risk Management: The Drawdown Cap Governs Everything

**The 5–10% max drawdown (₹5–10k total, peak-to-trough) is the binding constraint of this project — harder to satisfy than the 20–25% return target.** A single un-managed max-loss on a one-lot iron condor (typically ₹5–15k depending on wing width) can consume the entire annual budget in one event.

## Position rules

1. **Per-trade risk: 1–2% of capital (₹1,000–2,000).** Wing width must be chosen so max loss ≤ this bound — tight wings, not wide ones.
2. **Exit losers early**: close at 1.5–2× credit received. Never ride a defined-risk position to max loss; "defined" is the backstop, not the plan.
3. **One defined-risk structure at a time** at this capital size. No overlapping positions, no averaging down, no doubling after losses.
4. **Position sizing never scales with confidence.** The bot trades fixed, pre-computed size; capital growth is the only thing that changes size (see [07-compounding-roadmap.md](07-compounding-roadmap.md)).

## Kill-switch (mandatory, build first)

A hard portfolio-level circuit breaker, robust to the limit-order-only regime:

- **Trigger**: cumulative drawdown reaching the configured cap (start at ₹5k) → flatten all positions, halt trading, require manual re-arm.
- **Unfilled-exit handling** (market orders are banned — exits are limit orders that can fail to fill):
  1. Place exit at protection-band limit.
  2. If unfilled in N seconds, re-quote toward the touch.
  3. Widen the band stepwise.
  4. If still unfilled, alert the owner immediately (SMS/email) — do not silently retry forever.
- **Daily loss limit** in addition to the global cap (e.g., ₹2k/day → stop for the day).
- **Cash-bucket monitor**: alert before the MTM cash buffer runs dry (brokers may charge ~0.035%/day on shortfalls rather than blocking orders — a silent drag).
- **Heartbeat/watchdog**: if the bot loses connectivity or the OAuth token expires mid-session with positions open, alert immediately. An unattended open position is the biggest tail risk of full automation.

## Expectation setting

- The pledged-collateral yield (~5–6%) is the only guaranteed component. The options overlay must earn ~15–19%/yr on ₹1–2k risk per trade — a genuinely positive-expectancy system, which no public source could prove exists.
- After realistic cost drag ([05-costs-and-taxes.md](05-costs-and-taxes.md)), expect net returns below the 20–25% target in most years. Sub-target years are not failure; breaching the drawdown cap is.
- If the cap is breached: stop, analyze, and only restart with the owner's explicit decision. That rule is the difference between this project and the 93%.
