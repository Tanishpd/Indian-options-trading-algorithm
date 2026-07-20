# 07 — Compounding Roadmap

**Rule: profits are reinvested into trading capital only. No fresh capital additions; no withdrawals until an owner-decided milestone.**

## Projection (illustrative arithmetic, pre-tax)

| Year end | At 20% | At 25% | What unlocks |
|---|---:|---:|---|
| 1 | ₹1,20,000 | ₹1,25,000 | More MTM headroom on the single lot |
| 2 | ₹1,44,000 | ₹1,56,250 | Wider wings or a second concurrent spread becomes thinkable |
| 3 | ₹1,72,800 | ₹1,95,313 | Two defined-risk lots with margin to spare |
| 4 | ₹2,07,360 | ₹2,44,141 | Naked one-lot margin (~₹2.3L+) comes into range — **still ruled out** under the drawdown cap |
| 5 | ₹2,48,832 | ₹3,05,176 | Capital doubles in ~3.8 yrs at 20%, ~3.1 yrs at 25% |

## Scaling rules

1. **Size steps up only at capital milestones, never on winning streaks.** The bot's position size is a function of account equity bands, recomputed monthly — not of recent P&L.
2. **The drawdown cap scales with capital** (stays 5–10% of current equity), and per-trade risk stays 1–2% of current equity.
3. **Second concurrent structure** only when equity supports two positions' combined margin with the same headroom standards as gate 1 in [06-backtesting-and-validation.md](06-backtesting-and-validation.md) (~₹2L+ equity in practice — verify on the margin calculator at that time).
4. **Naked selling stays banned at every capital level.** The unlock at year ~4 is a margin fact, not a recommendation — uncapped tail risk is incompatible with the drawdown mandate.
5. Keep the pledged-collateral ratio intact as capital grows: ~85–90% in pledged liquid ETF/fund, ~10–15% cash for MTM ([02-capital-setup.md](02-capital-setup.md)). Pledge new profits quarterly to keep them yielding.
6. Fixed costs (API fees, EC2) shrink as a share of returns as capital grows — recheck the cost-drag metric ([05-costs-and-taxes.md](05-costs-and-taxes.md)) at each milestone.

## Honest caveat

The table assumes the target is hit every year with no drawdown breach — a top-1% outcome per SEBI's population data. The verified evidence supports this plan's *structure*, not its *probability*. Sub-target years compound slower; a cap breach halts the project pending owner review. Taxes (business income — see CA note in [05-costs-and-taxes.md](05-costs-and-taxes.md)) will reduce the compounding rate below headline returns.
