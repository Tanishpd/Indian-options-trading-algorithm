# 06 — Backtesting and Validation

**Since zero public performance claims survived verification, the evidence must be generated here. The paper-trading record is the only track record that will ever exist for this system.**

## Backtest rules

1. **Post-November-2024 data only.** Older data is unrepresentative: lot sizes changed (NIFTY 25 → 75 → 65), weekly expiries were discontinued on all indices except NIFTY/SENSEX, and expiry weekdays moved in September 2025 (NIFTY → Tuesday, SENSEX → Thursday). A pre-2024 backtest — especially BANKNIFTY weeklies — is unreproducible and inadmissible.
2. **Full cost model** from [05-costs-and-taxes.md](05-costs-and-taxes.md), with date-appropriate STT.
3. **Limit-order fill simulation**: assume protection-band limit fills, never market-order fills. Penalize or fail fills on gap moves — the band gives no guarantee on gaps. Expiry-day volatility spikes are where backtest slippage and real drawdown diverge most (unresolved open question from research — be conservative).
4. **Judge by the drawdown cap first, returns second.** A parameter set returning 30% with a 12% max drawdown fails; 18% with 6% passes. Optimize inside the constraint, not for CAGR.
5. **Hold out data.** Tune on one period, validate untouched on another. A strategy tuned on all available data has no evidence value.
6. Log every simulated trade with full cost breakdown so paper/live results are comparable line-by-line.

## Validation ladder (gates, in order)

| Gate | Criterion to pass |
|---|---|
| 1. Margin reality | One-lot NIFTY iron condor margin confirmed on broker calculator, fits collateral with headroom |
| 2. Backtest | Meets return target net of costs **and** stays inside drawdown cap on held-out data |
| 3. Paper trading | **Minimum 3–6 months** under the live regime (real quotes, limit-order fills, OAuth flow, kill-switch armed) |
| 4. Go-live | Paper record clears target net of costs without breaching the drawdown cap; compliance checklist ([03-compliance.md](03-compliance.md)) complete |

No skipping gates. If paper trading breaches the drawdown cap, return to gate 2 with the failure analyzed — do not tweak parameters mid-paper-run and keep the clock running.

## Standing skepticism rule

Any strategy, parameter set, or "edge" sourced from vendors, marketplaces (AlgoTest/Streak), YouTube, or forums is treated as **unverified marketing** until it independently passes gates 2–3 here. This applies to future agent sessions too: do not import claimed performance numbers into designs or reports as facts.
