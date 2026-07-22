"""Run live paper trading: python -m optionsbot.paper [--collect-only] [--once]

Credentials come from AWS Secrets Manager (--aws-secret NAME, or the
OPTIONSBOT_AWS_SECRET env var) or fall back to secrets/broker.env; see
config/broker.env.example for the required keys.

Kill-switch recovery: python -m optionsbot.paper --rearm "your name" [--reset-peak]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import load_config
from ..feed.angelone import AngelOneFeed
from ..paper.loop import CollectOnly, PaperSession
from ..risk.killswitch import KillSwitch
from ..strategies import registry
from ..strategies.reference_condor import CondorParams, ReferenceCondor
from .alerts import TelegramAlerter, discover_chat_id
from .credentials import load_credentials, load_optional_secret

IST = ZoneInfo("Asia/Kolkata")


def telegram_setup(secret_id: str, region: str | None) -> None:
    """One-time: find the owner's chat ID and store it beside the bot token."""
    import subprocess

    data = load_optional_secret(secret_id, region)
    if not data or not data.get("TELEGRAM_BOT_TOKEN"):
        raise SystemExit(
            f"create the secret first:\n  aws secretsmanager create-secret "
            f"--name {secret_id} --secret-string "
            "'{\"TELEGRAM_BOT_TOKEN\":\"<token from @BotFather>\"}'"
        )
    token = data["TELEGRAM_BOT_TOKEN"]
    chat_id = data.get("TELEGRAM_CHAT_ID") or discover_chat_id(token)
    if not chat_id:
        raise SystemExit(
            "no chat found — open Telegram, send your bot any message (e.g. 'hi'), "
            "then run --telegram-setup again"
        )
    data["TELEGRAM_CHAT_ID"] = chat_id
    args = ["aws", "secretsmanager", "put-secret-value", "--secret-id", secret_id,
            "--secret-string", json.dumps(data)]
    if region:
        args += ["--region", region]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"failed to store chat id: {proc.stderr.strip()}")
    ok = TelegramAlerter(token, chat_id, log=print).send(
        "alert channel is live — kill-switch trips, flatten failures, and feed "
        "death will page here"
    )
    print(f"chat id {chat_id} stored in {secret_id}; test message "
          f"{'delivered' if ok else 'FAILED — check the token'}")


def build_pager(secret_id: str, region: str | None) -> TelegramAlerter | None:
    data = load_optional_secret(secret_id, region)
    if data and data.get("TELEGRAM_BOT_TOKEN") and data.get("TELEGRAM_CHAT_ID"):
        return TelegramAlerter(data["TELEGRAM_BOT_TOKEN"], data["TELEGRAM_CHAT_ID"], log=print)
    return None


def rearm(state_path: Path, cfg, operator: str, reset_peak: bool) -> None:
    """Audited kill-switch re-arm against the persisted session state (docs/04)."""
    if not state_path.exists():
        raise SystemExit(f"{state_path} not found — nothing to re-arm")
    state = json.loads(state_path.read_text())
    switch = KillSwitch(cfg.risk)
    switch.restore(state["switch"])
    if not switch.halted:
        raise SystemExit("kill-switch is not halted — nothing to do")
    reason = switch.halt_reason
    switch.rearm(operator, reset_peak=reset_peak)
    state["switch"] = switch.snapshot()
    state.setdefault("rearm_history", []).append(
        {"at": datetime.now(IST).isoformat(), "operator": operator,
         "reset_peak": reset_peak, "was_halted_for": reason}
    )
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, state_path)
    print(f"re-armed by {operator!r} (was halted for: {reason})")
    print("review docs/04 stop-and-review before restarting the session.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Live paper trading (no real orders)")
    ap.add_argument("--config", default="config/default.toml")
    ap.add_argument("--secrets", default="secrets/broker.env",
                    help="dotenv fallback when no AWS secret is configured")
    ap.add_argument("--aws-secret", default=os.environ.get("OPTIONSBOT_AWS_SECRET"),
                    help="AWS Secrets Manager secret name (e.g. tradingbot/angel)")
    ap.add_argument("--aws-region", default=None,
                    help="override the AWS CLI's configured region")
    ap.add_argument("--state", default="data/live/paper_state.json")
    ap.add_argument("--collect-only", action="store_true",
                    help="snapshot chains only; place no paper trades")
    ap.add_argument("--once", action="store_true", help="single tick (smoke test)")
    ap.add_argument("--poll", type=int, default=60, help="seconds between polls (min 5)")
    ap.add_argument("--rearm", metavar="OPERATOR",
                    help="re-arm a halted kill-switch in the persisted state, then exit")
    ap.add_argument("--reset-peak", action="store_true",
                    help="with --rearm: rebase the drawdown peak to the next observation")
    ap.add_argument("--telegram-secret",
                    default=os.environ.get("OPTIONSBOT_TELEGRAM_SECRET", "tradingbot/telegram"),
                    help="AWS secret holding TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID")
    ap.add_argument("--strategy", default=None, metavar="NAME",
                    help="run one registered strategy live (see --list-strategies)")
    ap.add_argument("--evaluate", metavar="NAME", action="append", default=None,
                    help="run a strategy in SHADOW alongside the others; repeatable. "
                         "Shadows place no real orders and each keeps its own book, "
                         "so one session yields an independent forward record per "
                         "strategy. Read them with optionsbot.research.forward_report.")
    ap.add_argument("--forward-root", default="data/forward",
                    help="where forward records are written (default data/forward)")
    ap.add_argument("--list-strategies", action="store_true",
                    help="print registered strategy names and exit")
    ap.add_argument("--telegram-setup", action="store_true",
                    help="discover + store your chat id, send a test message, exit")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.list_strategies:
        for name, desc in registry.available().items():
            print(f"  {name:<20} {desc}")
        return
    if args.telegram_setup:
        telegram_setup(args.telegram_secret, args.aws_region)
        return
    if args.rearm:
        rearm(Path(args.state), cfg, args.rearm, args.reset_peak)
        return

    creds = load_credentials(
        Path(args.secrets), aws_secret=args.aws_secret, aws_region=args.aws_region
    )
    if args.aws_secret:
        print(f"credentials loaded from AWS Secrets Manager: {args.aws_secret}")

    feed = AngelOneFeed(
        api_key=creds["SMARTAPI_KEY"],
        client_code=creds["SMARTAPI_CLIENT_CODE"],
        pin=creds["SMARTAPI_PIN"],
        totp_secret=creds["SMARTAPI_TOTP_SECRET"],
        strike_step=cfg.market.strike_step("NIFTY"),
        log=print,
    )

    if args.collect_only:
        strategy = CollectOnly()
    elif args.strategy:
        strategy = registry.build(args.strategy, cfg.risk)
        print(f"live strategy: {args.strategy} — {registry.available()[args.strategy]}")
    else:
        # 1.0% OTM: at the default 1.5%, live weekly credits (~Rs 16/share) can't
        # satisfy the Rs 2k per-trade cap; ~1.0% earns ~Rs 23+ and passes. The
        # cap check still guards every entry regardless of this number.
        strategy = ReferenceCondor(params=CondorParams(offset_pct=0.010), risk=cfg.risk)
        print(
            "NOTE: running the PIPELINE-VALIDATION reference condor. Its record "
            "does not count toward the docs/06 gate-3 paper evidence."
        )

    pager = build_pager(args.telegram_secret, args.aws_region)
    print(
        "telegram alerts ON" if pager else
        "telegram alerts NOT configured (pages go to the log only) — "
        "run --telegram-setup before unattended sessions"
    )

    session = PaperSession(
        cfg=cfg, feed=feed, strategy=strategy,
        poll_seconds=max(args.poll, 5), state_path=Path(args.state),
        page=pager.send if pager else None,
    )

    if args.evaluate:
        from datetime import date as _date

        from .evaluator import Evaluator

        specs = [(n, registry.build(n, cfg.risk)) for n in args.evaluate]
        session.evaluator = Evaluator.build(
            specs, cash=cfg.starting_capital, costs=cfg.costs,
            per_trade_max_loss=cfg.risk.per_trade_max_loss_rupees,
            root=Path(args.forward_root), day=_date.today(),
        )
        print(f"shadow evaluation: {', '.join(args.evaluate)} "
              f"-> {args.forward_root} (no real orders)")

    if args.once:
        session.feed.connect()
        session.tick()
        print("single tick complete — see data/live/ for the chain snapshot")
        return
    session.run()


if __name__ == "__main__":
    sys.exit(main())
