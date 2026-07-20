# 08 — Code Architecture (Build Spec)

Blueprint for the codebase — what to build, in what order, and the interfaces between parts. Implements Phases 1–4 of [PLAN.md](../PLAN.md). No code exists yet; this doc is the starting point when implementation begins.

## Tech stack

- **Python 3.11+** (3.14 available on the dev machine), stdlib-first: `dataclasses`, `tomllib` for config, `csv` for data. No pandas/numpy until performance demands it — correctness-first.
- **pytest** for tests (only dev dependency to start).
- Broker SDK (Kite Connect / SmartAPI / Fyers) added only in Phase 4, behind the adapter interface — the broker decision (PLAN Phase 0) must not block the backtester.

## Project layout

```
options/
├── pyproject.toml
├── config/
│   └── default.toml          # every trading parameter lives here, never hardcoded
├── src/optionsbot/
│   ├── config.py              # typed config dataclasses + TOML loader
│   ├── calendar.py            # expiry calendar
│   ├── instruments.py         # legs, spreads, condors + defined-risk validation
│   ├── costs.py               # cost engine (the heart of honest backtesting)
│   ├── fills.py               # protection-band limit-order fill simulator
│   ├── metrics.py             # drawdown, returns, cost drag
│   ├── backtest/
│   │   ├── data.py            # quote schema, CSV loader, synthetic generator
│   │   └── engine.py          # day-loop backtester
│   ├── risk/
│   │   └── killswitch.py      # state machine: ARMED → HALTED
│   └── broker/
│       ├── base.py            # abstract adapter (auth, quotes, orders, margin)
│       └── paper.py           # paper broker for dry runs / Phase 5
└── tests/                     # one test module per source module
```

## Module responsibilities and key rules

### `config.py`
Frozen dataclasses (`CostConfig`, `RiskConfig`, `FillConfig`, …) loaded from TOML. Rule: any number that could ever be tuned — band widths, deltas, risk caps, cost rates — is config, not code. Unknown keys in any section raise (a typo silently reverting to a default mis-sizes everything downstream). **Lot sizes are date-dependent schedules**, not scalars — NIFTY changed twice inside the supported data window (25 → 75 → 65).

### `calendar.py`
- Universe locked to `NIFTY` and `SENSEX`; any other index raises (enforces [docs/01](01-strategy.md) in code).
- Expiry weekdays with the September 1, 2025 changeover: NIFTY Thursday→Tuesday, SENSEX Tuesday→Thursday. Holiday list injected via config; expiry on a holiday rolls back to the previous trading day.

### `instruments.py`
- `OptionLeg` (index, right, strike, expiry, side, lots) and `Structure` with constructors `iron_condor(...)`, `credit_spread(...)`.
- **Constructor-level defined-risk validation**: every short leg must be paired with an equal-count further-out long wing (same right, same expiry). A naked short raises `ValueError` — the ban from [docs/01](01-strategy.md) is unrepresentable in code, not just documented.
- `max_loss()` per structure; construction fails if max loss exceeds the per-trade cap from `RiskConfig` (₹1–2k rule, [docs/04](04-risk-management.md)).

### `costs.py`
Implements [docs/05](05-costs-and-taxes.md) exactly:
- STT on **sells only**, on premium: 0.10% before April 1, 2026, 0.15% from that date — rate selected by fill date.
- **Refuses any date before November 1, 2024** (raises) — the post-Nov-2024-data-only rule is enforced by the cost engine itself, so stale data can't silently enter a backtest.
- Brokerage ₹20/order (config), exchange transaction charges, SEBI fees, GST (18% on brokerage + txn + SEBI), stamp duty (buy side). Rates beyond STT/brokerage were not verified by research — defaults carry a `# verify against broker contract note` marker and live in config.
- Returns a `CostBreakdown` per fill so reports can show cost drag line-by-line.

### `fills.py`
Bar-based limit-order simulator, conservative by design. The live paper path
adds a second realism layer in `broker/paper.py`: an order crosses only when
the *executable* side reaches the limit (buys must reach the ask, sells the
bid), with LTP standing in only when the feed provides no depth — so spread
cost is paid rather than assumed away. Measured on collected NIFTY chains,
spreads at traded strikes run Rs 0.10-0.20 (about Rs 3-7 per lot per crossing,
so roughly Rs 25-55 per four-leg round trip).
- BUY limit fills only if `bar.low <= limit`, at the limit price (never assume price improvement). SELL fills only if `bar.high >= limit`.
- Gap through the band → **no fill** (mirrors the real risk that protection-band orders give no guarantee on gaps).
- `protection_band_price(reference, side, band_pct)` mimics broker band construction; band width is config.

### `metrics.py`
`max_drawdown` (peak-to-trough, rupees — the first-class metric), net return, per-trade cost drag, worst trade. `BacktestReport` dataclass aggregates everything.

### `backtest/engine.py`
Simple day-loop, no event-bus over-engineering:
1. For each trading day: expiry guard → hand the strategy the day's option chain (immutable snapshots); strategy returns limit orders.
2. Simulate fills (`fills.py`), apply costs (`costs.py`), update positions (keyed by leg for O(1) settling).
3. **End-of-day book validation**: naked short exposure or a book worst-case loss above the per-trade cap trips the kill-switch — the docs/01 ban and docs/04 cap are enforced on the execution path, not just in the `Structure` library layer.
4. Mark-to-market at close (missing quotes carry the last known mark, never reset to entry) → equity curve point → feed the kill-switch.
5. Kill-switch HALTED → flatten on subsequent days via simulated limit fills banded around the prior day's mark: gaps through the band and missing quotes leave positions open for the next attempt, and `report.open_positions_end` says so if data runs out — the engine never fabricates an exit.
6. Positions must be squared off by expiry (docs/05 rule 3): the engine raises rather than fabricate post-expiry marks (no underlying spot data exists to settle at intrinsic).

Strategy is a small protocol (`decide(day_context) -> list[Order]`) so candidate systems from PLAN Phase 3 are plug-ins.

### `risk/killswitch.py`
State machine, built and tested **before** any live order code (PLAN Phase 4 rule):
- **Seeded with starting capital** so first-day losses count against both caps (an unseeded switch baselines from the first observation and is blind to day one).
- Trips on: global drawdown ≥ cap, daily loss ≥ limit (resets each session), cash-buffer breach (live only). `trip(reason)` is public so the engine routes book-invariant breaches (naked exposure, cap) through the same halt/alert machinery.
- Tripping emits exactly one alert through a callback interface; re-arming requires an explicit manual operator action — the bot can never un-halt itself. A deliberate plain class, not a dataclass: safety state must not be clonable via `dataclasses.replace`.
- Same class runs in backtest and live, so the halt behavior is itself backtested.

### `broker/base.py` + `paper.py`
Abstract adapter: `authenticate()`, `quotes()`, `place_limit_order()`, `positions()`, `margin_available()`. `paper.py` implements it in-memory for dry runs and Phase 5. The real broker adapter (plus OAuth token refresh, static-IP assumptions, the unfilled-exit ladder from [docs/04](04-risk-management.md)) is written only after the Phase 0 broker decision.

## Test plan (gate 2a lives here)

One test module per source module. The critical ones:

- **`test_costs.py` — gate 2a**: a scripted iron-condor round trip (8 fills, lot 65) whose expected net P&L is a **hand-computed literal** in the test, not derived from the code under test. Example fixture: entry sells at ₹60/₹55, wing buys at ₹25/₹22; exit buys at ₹10/₹8, wing sells at ₹2/₹1.5 → gross ₹3,477.50; brokerage ₹160; STT ₹11.55 (0.15%, sells only) → net ₹3,305.95. Plus boundary tests: March 31 vs April 1, 2026 STT rates; pre-Nov-2024 date raises.
- **`test_instruments.py`**: naked short raises; max-loss math; per-trade-cap rejection.
- **`test_fills.py`**: touch fills, gap no-fills, band construction.
- **`test_killswitch.py`**: trips at cap, single alert, manual re-arm required, daily reset.
- **`test_calendar.py`**: weekday changeover around Sept 1, 2025; holiday rollback.
- **`test_engine.py`**: end-to-end scripted backtest reproducing a hand-computed equity curve; halts mid-run when the scripted losses breach the cap.

## Build order

1. `config.py` + `calendar.py` + `instruments.py` (pure logic, no I/O)
2. `costs.py` + gate-2a test — **nothing else proceeds until this test passes**
3. `fills.py`, `metrics.py`
4. `backtest/data.py` (synthetic generator first, real loader when Phase 0 data source lands) + `engine.py`
5. `risk/killswitch.py`
6. `broker/base.py` + `paper.py`
7. Real broker adapter + ops (systemd, alerting) — Phase 4, after broker decision

Steps 1–6 are fully unblocked today: no broker account, market data, or capital required.
