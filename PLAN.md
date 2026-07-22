# Build Plan — Automated Options Bot (₹1 Lakh, NIFTY/SENSEX Defined-Risk)

Working plan from zero code to live trading. Each phase ends with a gate; no phase starts before the previous gate passes. Rules and evidence live in [CLAUDE.md](CLAUDE.md), [RESEARCH.md](RESEARCH.md), and [docs/](docs/).

**Status legend**: `[ ]` todo · `[x]` done · `[~]` in progress

---

## Phase 0 — Decisions & reality checks (owner tasks, no code)

The cheapest place to kill or reshape the project. Everything here blocks Phase 1.

- [ ] **Margin reality check**: price a one-lot NIFTY (lot 65) iron condor and a defined-width credit spread on a broker margin calculator. Confirm it fits ~₹76–80k collateral with MTM headroom. *If it doesn't fit, the strategy universe must be redesigned — stop and reassess.*
- [ ] **Pick the broker** (Zerodha / Fyers / Upstox / Angel One). Decision inputs: current API subscription price (unverified in research — get it in writing), static-IP policy, order-type restrictions, liquid-ETF pledge support, margin-benefit order sequencing rules. → record decision + rationale in `docs/decisions/`.
- [ ] **Price the infra stack**: EC2 instance class + Elastic IP + any data-feed cost. Target: fixed costs under ~2–3% of capital/year.
- [ ] **CA consult**: business-income treatment of F&O, advance tax, audit thresholds, deductibility of API/infra costs ([docs/05](docs/05-costs-and-taxes.md)).
- [ ] **Historical data source**: find post-November-2024 NIFTY/SENSEX options data (1-min or better for expiry-day work; OI + bid/ask if possible). Candidates to evaluate for coverage/cost; verify it spans the Sept 2025 expiry-weekday change.

**Gate 0**: margin fits, broker chosen, all-in fixed costs known, data source secured.

## Phase 1 — Foundations

- [~] Repo scaffolding: Python project, config system (all trading parameters in config, never hardcoded), structured logging, secrets handling (API keys never in git). *(project + TOML config + .gitignore done; logging/secrets pending)*
- [ ] EC2 (ap-south-1) + Elastic IP provisioned; IP whitelisted with broker ([docs/03](docs/03-compliance.md) checklist items 1–2).
- [ ] Broker API connectivity: OAuth login flow + daily token refresh, instrument master download, quote fetch, margin query. Paper/sandbox mode if the broker offers one.
- [ ] Alerting channel working end-to-end (e.g., Telegram/email): the bot must be able to page the owner before it can trade.

**Gate 1**: from EC2, the bot can authenticate, refresh tokens across a session boundary, pull quotes, and raise an alert.

## Phase 2 — Backtester (can start in parallel with Phase 1)

Build per [docs/06](docs/06-backtesting-and-validation.md) rules:

- [~] Data layer over the Phase-0 source; post-Nov-2024 only; expiry-calendar aware (NIFTY Tuesday / SENSEX Thursday, weekday change Sept 2025). *(schema + CSV loader + calendar done; real data source pending Phase 0)*
- [x] Cost engine per [docs/05](docs/05-costs-and-taxes.md): date-appropriate STT (0.10%/0.15% boundary Apr 1 2026), ₹20/order brokerage, exchange charges, GST, stamp duty.
- [x] Fill simulator: protection-band limit-order fills only; conservative gap handling; expiry-day slippage stress mode.
- [x] Metrics: max drawdown (peak-to-trough, the first-class metric), net return, per-trade cost drag, worst single trade.
- [ ] Train/holdout split machinery baked in — no full-data tuning possible by construction.

**Gate 2a**: backtester reproduces a hand-computed spread P&L (including all costs) exactly. ✅ **PASSED** — `tests/test_engine.py::test_gate_2a_condor_round_trip_hand_computed`

## Phase 3 — Strategy research

**Status: gate 2 tested twice, failed twice. Do not propose parameters without
reading both findings documents first.**

| Study | Data | Result |
|---|---|---|
| [docs/10](docs/10-first-backtest-findings.md) | EOD bhavcopy, 71 trades, 20 months | net −₹16,740, gross +₹75, max DD 22.6% |
| [docs/11](docs/11-intraday-backtest-findings.md) | Minute bars, 72 cycles, 17 months | net −₹21,066, gross −₹4,828, max DD 21.1% |

**Why**, established in [docs/12](docs/12-where-the-edge-actually-is.md): the
variance risk premium is **real and large** — +1.96 volatility points at 2 DTE
(t = +3.76), worth ₹1,700–2,400 per cycle against a ₹230 cost floor. Options are
not efficiently priced. But **the entire premium is tail insurance**: everything
within ±500 points of ATM is worth +₹48/cycle, and a defined-risk structure is
short the near strikes and long the far ones — a net *buyer* of the only part of
the surface that pays.

The cap cannot reach the tail. NIFTY's minimum risk unit is 50pt × lot 65 =
**₹3,250, already above the ₹2,000 cap**, so every legal structure needs credit
≥ 38.5% of width, which exists only within ±200 of ATM. The cap stops binding at
~±200; the edge starts at ~±400.

Eleven strategy families were tested and closed, including SENSEX (whose risk
quantum is exactly ₹2,000, so the cap stops binding — it still loses ₹26,560).
The only durable edge found is a far-OTM condor at ±650/700: statistically
bulletproof (t = +4.04 to +6.52, holdout holds) and worth **1.4%/yr** at 1.8× the
cap. Real, stable, too small.

**The ratio that settles it, independent of capital**: with one structure at a
time and max loss at 2% of capital, annual return = `(net / max loss) × 1.04`. The
mandate needs **19.23% per cycle**; the best of 369 grid cells is **4.22%** and the
structural ceiling is **5.14%**. The asymptote at ₹10 crore is 5.02%/yr — below the
do-nothing floor of 5.25–6.7%. That is why capital, volatility, brokerage and every
parameter sweep all failed: none of them move that ratio far enough.

**Scale of the ask**: 22.5% net at a 10% drawdown cap implies Sharpe ≈ 1.9; at 5%,
≈ 3.4. Medallion ran 1.89.

**Closed 2026-07-22** — the last three open doors, now tested rather than assumed:
far-OTM SENSEX (credit ₹35 against ₹99 of friction = −₹64/cycle *before* the market
moves), event-conditioned entry (a real null: IV +2.38 vol points, RV +2.33, net
+0.05, p = 0.965), and regime dependence (339 cycles over 6.5 years spanning VIX
9–84: premium scales with vol at r = +0.939, realised P&L at r = +0.020, and
−₹370/cycle above VIX 25 — **a more volatile regime hurts**).

The second study tests the rules the bot actually runs (time-window entry,
target/stop exits, expiry square-off), which EOD data structurally cannot
evaluate. In it the gross edge is *negative* once slippage is modelled at 5
ticks/leg.

**The drawdown is not a second failure.** It follows from the negative mean:
shift the same per-trade distribution to earn 20%/yr, keeping its exact variance,
and P(drawdown ≤ 10%) is **99.7%**. The risk architecture works and should not be
redesigned in response to these results.

- [x] Implement candidate structures: iron condor with configurable
      offsets/wings/entry-exit rules; per-trade max loss constrained to ₹1–2k
      ([docs/04](docs/04-risk-management.md)).
- [x] Parameter search **inside the drawdown constraint**. A 3×3 sweep over
      profit target × stop level found no survivor: all nine configurations lose
      money and every one breaches the cap.
- [x] Robustness checks: slippage stress (0 → 0.50/leg), chronological
      train/holdout split, bootstrap significance. The best in-sample config
      (+₹843) returns −₹6,302 out of sample; no t-statistic reaches 1.
- [ ] Write up the chosen system as `docs/decisions/strategy-spec.md` —
      **blocked, and correctly so: there is no chosen system to write up.**

**Gate 2** (= gate 2 in docs/06): chosen config meets target net of costs AND stays inside the drawdown cap on held-out data. *If nothing passes honestly, the finding is "target infeasible as specified" — report it, don't torture parameters.*

**Gate 2 verdict: NOT PASSED.** Invoking that clause as written. The binding
problem is not the cost floor and not a parameter: it is that the premium is
concentrated in the tail while the ₹2,000 cap — against a ₹3,250 minimum risk
unit — confines every legal structure to the body. Advancing to Phase 4/5 with a
defined-risk premium-selling strategy would be torturing parameters by another
name.

Two methodological traps this phase surfaced, both of which will silently
manufacture a passing result if repeated — see docs/11 for the evidence:

1. **A risk cap doubles as a selection filter.** Entry that waits for the
   structure to become affordable is an undeclared "enter only when premium is
   rich" signal. It was worth ₹4,474 of an earlier reported figure, and its
   threshold moves with lot size, so it cannot generalise. Report cap-on and
   cap-off results side by side.
2. **Unmodelled slippage.** Minute data carries no bid/ask, so this cost must be
   assumed rather than measured. Assuming zero was worth ~₹12,000.

## Phase 4 — Trading bot

- [~] **Kill-switch first** ([docs/04](docs/04-risk-management.md)): global drawdown halt, daily loss limit, unfilled-exit ladder (re-quote → widen → page owner), cash-bucket monitor, connectivity/token watchdog. Unit-tested against simulated failures before any order logic exists. *(core state machine + tests done; live-only parts — exit ladder, cash monitor, watchdog — pending Phase 4)*
- [ ] Execution engine: limit orders only, short-leg-first sequencing for margin benefit, order-rate limiter, idempotent order state machine (safe across restarts).
- [ ] Strategy runner: consumes `strategy-spec.md` config; positions reconciled against broker state on every start.
- [ ] Ops: systemd/pm2 supervision on EC2, log shipping, daily P&L + cost-drag report to owner.

**Gate 3-ready**: full dry-run day on live quotes with order placement stubbed, zero unhandled errors.

## Phase 5 — Paper trading (minimum 3–6 months)

- [~] **Paper-trading loop built early** (live Angel One quotes → PaperBroker simulated fills with full costs → intraday kill-switch → state persistence → chain snapshots to CSV). Runs now via `python -m optionsbot.paper` (see RUN.md §5). Currently trades the pipeline-validation ReferenceCondor — **the gate-3 clock does NOT start until a backtest-gated strategy (Phase 3) runs it**. Side benefit: every session appends live chain data to `data/live/`, building the Phase-0 dataset.
- [ ] Run the complete system under the live regime: real quotes, real OAuth cycle, kill-switch armed, simulated fills at protection-band logic.
- [ ] Weekly review ritual: paper vs backtest divergence (fills, slippage, costs), drawdown tracking.
- [ ] No mid-run parameter changes; a change resets the paper clock ([docs/06](docs/06-backtesting-and-validation.md)).

**Gate 3**: paper record clears the target net of costs without breaching the drawdown cap.

## Phase 6 — Go-live & capital ops

- [ ] Fund account ₹1,00,000; buy ~₹85–90k liquid ETF; pledge; confirm collateral margin lands ([docs/02](docs/02-capital-setup.md)).
- [ ] Full [docs/03](docs/03-compliance.md) checklist re-verified (rules may have changed since July 2026).
- [ ] Start at minimum size with the kill-switch cap at the tight end (₹5k).
- [ ] Monthly: pledge new profits, recompute size bands, review cost drag ([docs/07](docs/07-compounding-roadmap.md)).

---

## Standing rules for whoever executes this plan

1. The drawdown cap outranks the return target at every decision point.
2. Gates are sequential — no skipping, no "provisional" go-live.
3. Every material decision (broker, data source, strategy spec) gets a short write-up in `docs/decisions/`.
4. Time-sensitive facts (lot sizes, STT, expiry days, broker rules) are re-verified at the phase where they're used — figures in these docs were current July 2026.
