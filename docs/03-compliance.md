# 03 — SEBI Algo Compliance Checklist (EC2 Bot)

**The setup is legal.** SEBI's retail algo framework (circular Feb 4, 2025) explicitly
permits tech-savvy retail investors to run self-hosted algos. All items below verified
3–0 unless noted.

**Timeline — corrected July 2026 against the primary sources.** Two earlier research
passes on this project each got this wrong in a different direction, so the actual
sequence, from the SEBI circulars themselves:

| Date | Event |
|---|---|
| Feb 4, 2025 | Circular issued. Stated effect date **August 1, 2025** |
| Jul 29, 2025 | Extended to **October 1, 2025** |
| Sep 30, 2025 | Brokers who are ready **go live from October 1, 2025**; a glide path is given for the rest |
| Oct 31 / Nov 30, 2025 | Glide-path milestones 1 and 2 (algo registration with the exchange) |
| Jan 3, 2026 | Milestone 3 — broker must have joined a mock session |
| Jan 5, 2026 | Brokers missing the milestones are **barred from onboarding new retail API algo clients** |

**The framework has therefore been live since October 1, 2025** — not April 2026 (which
this document previously stated, and which appears to have come from confusing it with
NSE circular NSE/INVG/73992 of April 30, 2026 on algo-provider empanelment), and not
August 1, 2025 (the original date, superseded before it took effect).
Source: SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/132, September 30, 2025.

## Pre-launch checklist

- [ ] **EC2 in ap-south-1 (Mumbai) with an Elastic IP** — a static IP is mandatory. AWS Elastic IP whitelisted with the broker is an explicitly endorsed compliant setup (Zerodha forums). No India-residency mandate on the IP was found.
- [ ] **Whitelist the static IP with the broker** before the first live order. Broker-specific limits apply — e.g., Angel One allows one primary + one secondary IP, updatable at most once per calendar week. Plan IP changes carefully; a broken Elastic IP association can lock the bot out for days.
- [ ] **API access**: unique client-specific API key; OAuth-only authentication; 2FA. Open APIs are prohibited. **Design the bot around the daily OAuth token refresh** — it is a hard operational dependency, and the one step that may resist full automation depending on broker.
- [ ] **Stay under 10 orders/second** (Threshold Orders Per Second, per exchange/segment,
  measured on a calendar-clock second). Below it, a self-developed algo needs **no
  per-algo exchange registration** — it is tagged with a generic exchange-provided algo
  ID. A few spread orders per day is far below this. Rate-limit the order loop anyway as
  a guard. **Note the attribution**: this threshold is specified by the **exchanges**
  (NSE), not by the SEBI circular — a July 2026 research pass wrongly reported it as
  unpublished because it searched SEBI sources only. Orders both below and above the
  threshold must still carry the exchange-provided unique identifier for audit trail.
- [ ] **Limit orders only** — market orders are banned for algo/API trading (NSE circular, April 2025). Angel One also bans IOC *(2–1 verification vote on the IOC scope — broker-specific)*. Zerodha converts API market orders into protection-band limit orders: near-certain fills within the band, **no guarantee on gaps**. See [04-risk-management.md](04-risk-management.md) for the exit-handling this forces.
- [ ] **Do not share or sell the algo.** A self-developed algo may be used by family only (spouse, dependent children/parents) — never other investors. Vendor-distributed strategies require exchange registration regardless of order frequency.

## Refuted claims — ignore if seen elsewhere

- ~~"Framework effective August 2025"~~ — that was the circular's original stated date,
  superseded by extension before it took effect. ~~"Full applicability April 1, 2026"~~ —
  also wrong; this document asserted it and it does not appear in any SEBI circular.
  **Correct: live since October 1, 2025**, per the table above.
- ~~"The 10 orders/second threshold is not published"~~ — wrong. It is published by the
  exchanges rather than by SEBI, which is why a SEBI-only search missed it.
- ~~Specific exercise-STT rates/payer~~ — refuted 1–2; mechanics unverified. Standard practice regardless: square off ITM long legs before expiry.

## Broker choice note

Framework implementations vary by broker (order-type restrictions, IP-update policies, API pricing). Angel One's rules do not automatically describe Zerodha/Fyers/Upstox. **API subscription costs produced no verified claims** — confirm current pricing (e.g., Kite Connect) before committing; at ₹1L capital a monthly API fee is a material fraction of the return target.
