# 03 — SEBI Algo Compliance Checklist (EC2 Bot)

**The setup is legal.** SEBI's retail algo framework (circular Feb 4, 2025; fully in force since **April 1, 2026**) explicitly permits tech-savvy retail investors to run self-hosted algos. All items below verified 3–0 unless noted.

## Pre-launch checklist

- [ ] **EC2 in ap-south-1 (Mumbai) with an Elastic IP** — a static IP is mandatory. AWS Elastic IP whitelisted with the broker is an explicitly endorsed compliant setup (Zerodha forums). No India-residency mandate on the IP was found.
- [ ] **Whitelist the static IP with the broker** before the first live order. Broker-specific limits apply — e.g., Angel One allows one primary + one secondary IP, updatable at most once per calendar week. Plan IP changes carefully; a broken Elastic IP association can lock the bot out for days.
- [ ] **API access**: unique client-specific API key; OAuth-only authentication; 2FA. Open APIs are prohibited. **Design the bot around the daily OAuth token refresh** — it is a hard operational dependency, and the one step that may resist full automation depending on broker.
- [ ] **Stay under 10 orders/second** (Threshold Orders Per Second, per exchange/segment). Below it, a self-developed algo needs **no per-algo exchange registration** — it is tagged with a generic exchange-provided algo ID. A few spread orders per day is far below this. Rate-limit the order loop anyway as a guard.
- [ ] **Limit orders only** — market orders are banned for algo/API trading (NSE circular, April 2025). Angel One also bans IOC *(2–1 verification vote on the IOC scope — broker-specific)*. Zerodha converts API market orders into protection-band limit orders: near-certain fills within the band, **no guarantee on gaps**. See [04-risk-management.md](04-risk-management.md) for the exit-handling this forces.
- [ ] **Do not share or sell the algo.** A self-developed algo may be used by family only (spouse, dependent children/parents) — never other investors. Vendor-distributed strategies require exchange registration regardless of order frequency.

## Refuted claims — ignore if seen elsewhere

- ~~"Framework effective August 2025"~~ — refuted 0–3. Full applicability: April 1, 2026.
- ~~Specific exercise-STT rates/payer~~ — refuted 1–2; mechanics unverified. Standard practice regardless: square off ITM long legs before expiry.

## Broker choice note

Framework implementations vary by broker (order-type restrictions, IP-update policies, API pricing). Angel One's rules do not automatically describe Zerodha/Fyers/Upstox. **API subscription costs produced no verified claims** — confirm current pricing (e.g., Kite Connect) before committing; at ₹1L capital a monthly API fee is a material fraction of the return target.
