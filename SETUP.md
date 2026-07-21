# Setup Guide

How to get this project running — from a fresh machine to a working backtest, and the operational setup path toward live trading. Follow the stages in order; each ends with a verification step.

## 1. Local development setup

**Prerequisites**: Python 3.11+ (3.14 tested), macOS or Linux.

```bash
cd ~/Desktop/options
python3 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

**Verify**: all tests pass (76 as of this writing, `0.1s`). The suite includes the gate-2a test that reproduces a hand-computed iron-condor P&L to the paisa — if that fails, the cost engine is broken and nothing else can be trusted.

No other dependencies exist by design: the core is stdlib-only until performance demands otherwise ([docs/08](docs/08-code-architecture.md)).

## 2. Know the layout

| Path | What it is |
|---|---|
| `src/optionsbot/` | The library — instruments, costs, fills, calendar, config |
| `src/optionsbot/backtest/` | Data loading and the day-loop engine |
| `src/optionsbot/risk/killswitch.py` | The drawdown-cap state machine |
| `src/optionsbot/broker/` | Broker adapter interface + paper broker |
| `config/default.toml` | Every tunable parameter |
| `tests/` | One test module per source module; `conftest.py` has shared builders |
| `PLAN.md` | Phased roadmap — check what's next here |

## 3. Configuration

Edit [config/default.toml](config/default.toml). Rules to know:

- **Unknown keys raise.** A typo'd key fails loudly instead of silently reverting to a default.
- **Cost rates beyond STT/brokerage are unverified** — confirm `txn_charge_rate`, `sebi_fee_rate`, `stamp_duty_rate` against your broker's actual contract note before trusting backtest totals. STT rates are dated constants in code (verified: 0.10% → 0.15% on option sales at April 1, 2026) and deliberately not configurable.
- **Lot sizes are date-dependent schedules**, not scalars — NIFTY changed 25 → 75 → 65 within the supported window. The shipped effective dates approximate the contract-revision calendar; verify against NSE circulars (NSE/FAOP/64625, NSE/FAOP/70616) before backtesting across a changeover.
- **Risk caps**: `max_drawdown_rupees` (kill-switch), `daily_loss_limit_rupees`, `per_trade_max_loss_rupees` (enforced against the whole book's worst-case loss after every trading day).
- Holidays: TOML-native dates (`[2026-10-02]`) or quoted strings both work. Populate from the exchange calendar before backtesting expiry-sensitive strategies.

## 4. Get market data (PLAN Phase 0 — currently the blocker)

The engine consumes CSV in this schema, one row per option per day:

```csv
day,index,expiry,strike,right,open,high,low,close
2026-07-07,NIFTY,2026-07-14,25900,CE,62.0,66.5,58.0,60.0
```

Hard rules enforced by the loader:
- **Post-November-2024 dates only** — earlier rows raise (lot sizes and the weekly-expiry universe make older data unrepresentative, [docs/06](docs/06-backtesting-and-validation.md)).
- **NIFTY and SENSEX only** — other indices raise.
- **No duplicate rows** for the same (day, index, expiry, strike, right) — merged files raise.
- Rights are `CE`/`PE`. Keep `data/` out of git (already in `.gitignore`).

When evaluating vendors, confirm coverage spans the September 2025 expiry-weekday change (NIFTY → Tuesday, SENSEX → Thursday) and, ideally, includes bid/ask for slippage realism.

## 4a. Free EOD data (works today, no account)

NSE and BSE publish end-of-day F&O bhavcopy for free in the identical UDiFF
schema, covering NIFTY and SENSEX from January 2024. Backfill it with:

```bash
PYTHONPATH=src .venv/bin/python -m optionsbot.data --index NIFTY \
  --from 2026-07-01 --to 2026-07-17
```

Writes one CSV per index per day under `data/eod/`. Weekends, holidays and
unpublished dates are skipped rather than failed, and re-running only fetches
what is missing.

**What this data can and cannot do.** It validates hold-to-expiry spread
economics, strike selection, the cost model, and lot-size history. It **cannot**
validate intraday-triggered rules: one row per contract per day gives no path
through the session, so when a day's range contains both the profit target and
the stop, the data cannot say which was touched first — and that ordering
decides the trade. Stop-loss logic needs 1-minute data (see issue #13).

Untraded contracts are dropped by default. Their closing price is a stale
carried-forward figure, not an achievable one: on 2026-07-17, 742 of 1,618
NIFTY option rows had zero volume and **every one of them carried a non-zero
close** — one showed 111.05 against a 54.10 settlement. Pass `--keep-untraded`
to retain them for open-interest or term-structure work.

## 5. Run a backtest

```python
# run_backtest.py (example)
from optionsbot.backtest.data import load_csv, by_day
from optionsbot.backtest.engine import BacktestEngine, Order
from optionsbot.config import load_config
from optionsbot.instruments import OptionLeg, Right, Side


class DoNothing:
    """Replace with a real strategy: return limit Orders from decide()."""

    def decide(self, ctx):
        # ctx.day, ctx.chain (read-only quotes), ctx.positions (frozen
        # snapshots), ctx.cash, ctx.equity
        return []


cfg = load_config("config/default.toml")
days = by_day(load_csv("data/nifty.csv"))
report = BacktestEngine(cfg, DoNothing()).run(days)

print(f"net return: {report.net_return_pct:.2f}%")
print(f"max drawdown: Rs {report.max_drawdown_rupees:,.2f}")
print(f"cost drag: {report.cost_drag_pct:.2f}%")
print(f"halted: {report.halted} ({report.halt_reason})")
print(f"unfilled/unquoted orders: {report.unfilled_orders}/{report.unquoted_orders}")
print(f"positions still open at end: {report.open_positions_end}")
```

Run with `PYTHONPATH=src .venv/bin/python run_backtest.py` (or install the package with `.venv/bin/pip install -e .`).

Engine behaviors your strategy must respect (all raise or halt, by design):
- Square off every position **before** its expiry — held past expiry raises.
- A naked short book (e.g., your wing order didn't fill) trips the kill-switch.
- Book worst-case loss above `per_trade_max_loss_rupees` trips the kill-switch.
- No partial closes, no stacking onto the same contract.
- Judge results by `max_drawdown_rupees` first, returns second ([docs/06](docs/06-backtesting-and-validation.md) gate rules).

## 6a. Angel One SmartAPI credentials (for live paper trading — works now)

The paper-trading loop (`RUN.md` §5) uses Angel One SmartAPI for **market data
only** — it never places real orders. Setup:

1. Log in at [smartapi.angelbroking.com](https://smartapi.angelbroking.com) with your Angel One account → **Create an App** (Market Data type is enough) → copy the **API key**.
2. Enable **TOTP**: portal → Enable TOTP → scan the QR with any authenticator app, and copy the **base32 secret string shown under the QR** (the bot generates the 6-digit codes itself from this secret).
3. **Whitelist this machine's public IP** in the SmartAPI portal (`curl ifconfig.me` to find it). Angel One allows 1 primary + 1 secondary IP, updatable at most once per calendar week — if your home IP is dynamic, note the weekly cap before it bites. The EC2 Elastic IP goes in the second slot when you deploy.
4. Credentials live in **AWS Secrets Manager** as `tradingbot/angel` (JSON keys
   `ANGELONE_API_KEY`, `ANGELONE_CLIENT_ID`, `ANGELONE_PASSWORD`,
   `ANGELONE_TOTP_SECRET` — the loader maps them; canonical `SMARTAPI_*` names
   also work). Fetched via the AWS CLI, so the Mac needs a configured AWS
   profile and EC2 needs an instance role with `secretsmanager:GetSecretValue`
   on that secret. No-AWS fallback: a local `secrets/broker.env` per
   `config/broker.env.example`.

5. Smoke test during market hours (9:15–15:30 IST, Mon–Fri):

```bash
PYTHONPATH=src .venv/bin/python -m optionsbot.paper --once --collect-only --aws-secret tradingbot/angel
```

Expect: a log line with spot/equity, and a chain snapshot in `data/live/`. First run downloads the exchange instrument master (~1 min). The session also cross-checks the exchange's lot size against your config and refuses to run on a mismatch.

## 6. Broker + API setup (before Phase 4/5)

Decision checklist in [PLAN.md](PLAN.md) Phase 0; compliance detail in [docs/03](docs/03-compliance.md). Sequence:

1. Open the trading + demat account; enable F&O segment.
2. Get current **API pricing in writing** (unverified by research — a monthly fee is material at ₹1L).
3. Create the API app; note the client-specific API key. OAuth-only + 2FA is mandatory — plan the daily token refresh into your ops.
4. Confirm the broker's static-IP policy (e.g., Angel One: 1 primary + 1 secondary, weekly update cap) and their order-type restrictions for algos (market orders banned everywhere; IOC varies by broker).
5. Record the decision and rationale in `docs/decisions/broker.md`.

## 7. EC2 setup (Phase 1)

Full step-by-step with exact commands, systemd template, and the cost math: [docs/09-ec2-deployment.md](docs/09-ec2-deployment.md). The short version:

1. Launch a small instance in **ap-south-1 (Mumbai)** — a t3.micro-class box is plenty for a low-frequency bot.
2. Allocate an **Elastic IP** and associate it with the instance (this is your static IP; it survives restarts).
3. **Whitelist that IP with your broker** before the first live order.
4. Python 3.11+, clone the project, same venv setup as §1; keep API secrets in environment variables or a git-ignored `secrets/` file — never in the repo.
5. Set up the alerting channel (Telegram bot or email) and test it end-to-end — the bot must be able to page you before it may trade.

**Verify (gate 1)**: from the EC2 box, the bot can authenticate, refresh a token across a session boundary, pull quotes, and raise an alert.

## 8. Capital setup (Phase 6 — only after paper-trading gates pass)

Per [docs/02](docs/02-capital-setup.md): fund ₹1,00,000 → buy ~₹85–90k liquid ETF → pledge it (~₹30+GST; collateral margin appears next trading day) → keep ~₹10–15k cash for MTM. First verify a one-lot NIFTY iron condor's margin on the broker's calculator actually fits the collateral with headroom.

## 9. Where you are now

```
[x] §1  Local dev + tests green
[x] §2-3  Layout + config understood
[ ] §4  Market data source          <- current blocker (PLAN Phase 0)
[ ] §5  First real backtest
[ ] §6  Broker decision + API
[ ] §7  EC2 + static IP + alerts
[ ] §8  Capital + pledge (gated on 3-6 months of paper trading)
```

Do not skip gates. The validation ladder in [docs/06](docs/06-backtesting-and-validation.md) is the contract: margin reality → honest backtest → 3–6 months paper → live at minimum size.
