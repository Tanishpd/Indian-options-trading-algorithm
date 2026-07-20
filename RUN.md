# Run Guide (Operational Runbook)

How to run and operate the system day to day. [SETUP.md](SETUP.md) gets you installed; this guide is for everything after. Sections 1–4 work today; 5–7 apply once the Phase 4/5 bot exists and are written now so the procedures are agreed before money moves.

## 1. Quick commands

```bash
# Full test suite (run before and after ANY code change)
.venv/bin/python -m pytest -q

# One module / one test
.venv/bin/python -m pytest tests/test_engine.py -q
.venv/bin/python -m pytest tests/test_engine.py::test_gate_2a_condor_round_trip_hand_computed -q

# A backtest script (see SETUP.md §5 for the template)
PYTHONPATH=src .venv/bin/python run_backtest.py
```

The suite is the safety interlock: **never trust a backtest run from a tree with failing tests**, and treat a gate-2a failure as "the cost engine is wrong, stop everything."

## 2. Running a backtest

1. Place data under `data/` (schema and loader rules: [SETUP.md](SETUP.md) §4).
2. Check `config/default.toml` — especially the lot-size schedule dates and risk caps.
3. Run your strategy script; keep one script per experiment so runs are reproducible.
4. Read the report **in this order**:

| Field | What it tells you | What good looks like |
|---|---|---|
| `halted` / `halt_reason` | Did a risk rule end the run? | `False` — a halted run is a failed parameter set, full stop |
| `max_drawdown_rupees` | The first-class metric | Within the cap (₹5–10k on ₹1L) with margin to spare |
| `net_return_pct` | Only meaningful if the two above pass | 20–25%/yr target, net of costs |
| `cost_drag_pct` | Costs as % of capital | Alert threshold ~8–10%/yr (docs/05) |
| `unfilled_orders` / `unquoted_orders` | Fill realism / data quality | Nonzero unfilled is normal (conservative fills); high unquoted means holes in your data |
| `open_positions_end` | Honesty flag | 0 — nonzero means the run ended with exposure the numbers don't fully reflect |
| `worst_trade` | Tail behavior per trade | Inside the ₹1–2k per-trade budget |

5. Log every run: data window, config hash/values, strategy parameters, and the report fields above. A result you can't reproduce is not evidence (docs/06 gate rules).

## 3. When a backtest halts — reading the kill-switch

| `halt_reason` contains | Meaning | Response |
|---|---|---|
| `max drawdown breached` | Equity fell ≥ cap from peak (start capital counts as first peak) | Parameter set fails. Reduce risk per trade or reject the config — do not widen the cap to make it pass |
| `daily loss limit breached` | One session lost ≥ the daily limit | Same as above; check which day and what the position was |
| `naked short exposure` | A short leg was live without its wing (usually the wing order gapped unfilled) | Fix the strategy's order placement: wing limits too tight, or enter wings first |
| `per-trade cap` | Book worst-case loss exceeded `per_trade_max_loss_rupees` | Tighten wings or cut size — this config trades bigger than the risk budget allows |

After any halt the engine attempts honest flatten fills on subsequent days; `open_positions_end > 0` means some exits never filled before data ran out — treat the reported loss as a floor, not the final number.

## 4. Errors by design (the engine refuses, loudly)

These raise instead of producing wrong numbers. The fix is always upstream, never "make the engine tolerate it":

| Error | Cause | Fix |
|---|---|---|
| `position … held past its expiry` | Strategy didn't square off by expiry day | Add an expiry-day exit rule (docs/05 rule 3) |
| `partial closes are not supported` / `stacking onto an existing same-side position` | Order shares mismatch an open position | Close full positions; one structure at a time |
| `pre-Nov-2024 data is banned` | Stale data in the window | Trim the dataset; old regimes are unrepresentative |
| `duplicate quote for …` | Merged/doubled data files | De-duplicate the CSV; find out why it happened |
| `unknown key(s) in [section]` | Config typo | Fix the key name — the default it would have silently used is exactly the bug this prevents |
| `no lot-size schedule configured` | Traded an index without a schedule | Add it to `[market.lot_sizes]` from exchange circulars |
| `outside the permitted universe` | Non-NIFTY/SENSEX instrument | Weekly universe is locked (docs/01) |

## 5. Paper trading operations

### Commands (works today, Angel One feed)

Credentials come from AWS Secrets Manager (`tradingbot/angel`, JSON with the
ANGELONE_* keys) via the AWS CLI — an EC2 instance role needs only
`secretsmanager:GetSecretValue`. A local `secrets/broker.env` remains as the
no-AWS fallback (template: `config/broker.env.example`). Set
`export OPTIONSBOT_AWS_SECRET=tradingbot/angel` to drop the flag below.

```bash
# Smoke test — one tick, zero trades, then exit (run during market hours):
PYTHONPATH=src .venv/bin/python -m optionsbot.paper --once --collect-only --aws-secret tradingbot/angel

# Full session with the reference condor (pipeline validation only).
# Detached so it survives terminals; PYTHONUNBUFFERED so the log streams live:
nohup env PYTHONPATH=src PYTHONUNBUFFERED=1 .venv/bin/python -m optionsbot.paper \
  --aws-secret tradingbot/angel >> data/live/session_$(date +%Y%m%d).log 2>&1 &

# Dataset building only, no paper trades:
PYTHONPATH=src .venv/bin/python -m optionsbot.paper --collect-only --aws-secret tradingbot/angel
```

What a session does: polls the live NIFTY chain (default 60s), snapshots every
chain to `data/live/chain_NIFTY_<date>.csv` (this builds the Phase-0 dataset),
simulates limit fills through the PaperBroker with the full cost model and
tick-grid limit prices, feeds equity to the kill-switch intraday, and persists
state atomically to `data/live/paper_state.json` — restarts recover positions,
entry basis, and marks, and a halted switch **stays halted across restarts**.

Session-level guarantees (independent of any strategy): expiry comes from the
exchange's own listed expiries (holiday-shifted weeks handled); the front three
listed expiries are archived each tick while only the front one is tradeable
(a contract's early life cannot be bought back once it expires); legs expiring
today are force-flattened after 15:00; naked-book and per-trade-cap checks run
every tick; kill-switch flattens escalate their band and page the owner after
3 unfilled attempts; feed failures trigger a re-auth attempt and pages; the
loop waits through weekends/holidays instead of exiting; a corrupt state file
refuses to start rather than silently resetting capital or forgetting a halt.

**Telegram alerts** (free; required before unattended/EC2 sessions): create a
bot via @BotFather, store the token as AWS secret `tradingbot/telegram`, send
the bot one message, then `python -m optionsbot.paper --telegram-setup` —
it discovers your chat id, stores it, and sends a test message. Sessions then
page kill-switch trips, flatten failures, feed death, and funds rejections to
your phone automatically; without it, pages go to the session log only.

**Re-arming after a halt** (the docs/04 audited manual step):

```bash
PYTHONPATH=src .venv/bin/python -m optionsbot.paper --rearm "your name" [--reset-peak]
```

This records the operator and prior halt reason in `rearm_history` inside the
state file. Root-cause first; `--reset-peak` rebases the drawdown budget to
current equity and is a deliberate decision, not a default.

The bundled `ReferenceCondor` is **pipeline validation, not evidence**: its
record does not count toward gate 3. Only a strategy that passed the backtest
gate can produce the gate-3 paper record.

Daily:
- Confirm the morning login/TOTP session succeeded **before** market open; a bot with a dead token and open positions is an incident (see §7).
- Verify the alert channel with a heartbeat message.
- EOD: reconcile the bot's fills, costs, and equity against the broker/paper record line-by-line.

Weekly review ritual (docs/06):
- Paper vs backtest divergence: fills, slippage, cost drag. Divergence is information — attribute it before continuing.
- Drawdown tracking against the cap.
- **No mid-run parameter changes.** A change resets the 3–6 month paper clock.

## 6. Live operations (Phase 6)

Pre-market checklist (automate, but keep manually runnable):
1. Token refreshed; API reachable from the whitelisted Elastic IP.
2. Alert channel heartbeat delivered.
3. Cash bucket ≥ MTM buffer floor (~₹10k) — pledged-collateral shortfalls accrue ~0.035%/day interest silently (docs/02).
4. Kill-switch state is ARMED and its caps match the current equity band (docs/07 scaling rules).

Monthly:
- Pledge accumulated profits into the liquid ETF; recompute size bands from equity (never from streaks).
- Review realized cost drag vs the ~8–10% alert line.
- Re-verify time-sensitive facts before relying on them: lot sizes, expiry weekdays, STT, broker algo rules.

## 7. Incident playbook

**Kill-switch tripped (any environment):**
1. Do nothing to the switch. It cannot and must not re-arm itself.
2. Write down: reason, positions at trip, equity path into the trip.
3. Root-cause before re-arm. Live: re-arm only after the docs/04 stop-and-review; the audit call is `killswitch.rearm(operator="<your name>", reset_peak=...)` — `reset_peak=True` only if the drawdown budget is being deliberately reset against current equity.

**Bot down / token dead with positions open:** this is the top tail risk of full automation (docs/04). Immediate manual step: open the broker terminal, verify positions, place protective exits by hand if needed. Then fix the bot. Never leave positions unattended waiting for a restart.

**Exit order won't fill (gap through band):** the live ladder is re-quote → widen band → page owner (docs/04). If paged: take over manually; a forced exit at a bad price that respects the drawdown cap beats holding and hoping.

**MTM cash shortfall:** top up cash or unpledge (T+1) immediately; the interest drag is silent and compounds.

**Broker API outage mid-session:** positions are defined-risk by construction — max loss is bounded. Confirm exposure via the broker terminal/app, set price alerts there, and do not re-enter until the API is stable for a full session.
