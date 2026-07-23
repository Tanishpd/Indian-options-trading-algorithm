"""Driver: pull long daily history from Angel One into per-symbol CSVs.

    python -m optionsbot.data.fetch_angel_history 2017-01-01 2026-07-16 \
        data/equity/angel --universe config/nifty200_pit.txt \
        --aws-secret tradingbot/angel

MUST run from the whitelisted box, when no live paper session holds the Angel
token (one session per client). Writes the same `date,close` shape the momentum
backtest reads. As with the free fetcher, supply a POINT-IN-TIME universe — a
current Nifty 200 list applied to history is survivorship bias (docs/14).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

from ..feed.angelone import SCRIP_MASTER_URL
from ..paper.credentials import load_credentials
from .angel_history import equity_tokens, fetch_daily

_RATE_GAP_S = 0.4          # Angel historical API ~3 req/s; stay under it


def _connect(creds: dict):
    """Authenticated SmartConnect. Login is IP-whitelisted to the box."""
    import pyotp
    from SmartApi import SmartConnect

    client = SmartConnect(api_key=creds["SMARTAPI_KEY"])
    sess = client.generateSession(
        creds["SMARTAPI_CLIENT_CODE"], creds["SMARTAPI_PIN"],
        pyotp.TOTP(creds["SMARTAPI_TOTP_SECRET"]).now())
    if not sess.get("status"):
        raise SystemExit(f"SmartAPI login failed: {sess.get('message', sess)} "
                         "(is this the whitelisted box, with no live session?)")
    return client


def _load_full_master() -> list[dict]:
    with urllib.request.urlopen(SCRIP_MASTER_URL, timeout=180) as resp:
        master = json.loads(resp.read())
    if not isinstance(master, list) or not master:
        raise SystemExit("scrip master download is not a non-empty JSON list")
    return master


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("start", type=date.fromisoformat)
    ap.add_argument("end", type=date.fromisoformat)
    ap.add_argument("out", type=Path)
    ap.add_argument("--universe", type=Path, required=True,
                    help="symbols, one per line (point-in-time Nifty 200)")
    ap.add_argument("--aws-secret", default="tradingbot/angel")
    ap.add_argument("--aws-region", default="ap-south-1")
    args = ap.parse_args(argv)

    symbols = {ln.strip().upper() for ln in args.universe.read_text().splitlines()
               if ln.strip() and not ln.startswith("#")}
    if not symbols:
        print(f"{args.universe} is empty", file=sys.stderr)
        return 1

    creds = load_credentials(None, aws_secret=args.aws_secret,
                             aws_region=args.aws_region)
    client = _connect(creds)
    tokens = equity_tokens(_load_full_master(), symbols)
    missing = symbols - set(tokens)
    print(f"resolved {len(tokens)}/{len(symbols)} symbols to Angel tokens"
          + (f"; unresolved: {sorted(missing)[:10]}..." if missing else ""))

    args.out.mkdir(parents=True, exist_ok=True)
    written, empty = 0, []
    for i, (sym, token) in enumerate(sorted(tokens.items()), 1):
        try:
            bars = fetch_daily(client, token, args.start, args.end,
                               pace=lambda: time.sleep(_RATE_GAP_S))
        except Exception as exc:                         # noqa: BLE001
            print(f"  {sym}: fetch error {exc!r}", file=sys.stderr)
            continue
        if not bars:
            empty.append(sym)
            continue
        with open(args.out / f"{sym}.csv", "w") as fh:
            fh.write("date,close\n")
            for d, c in bars:
                fh.write(f"{d.isoformat()},{c}\n")
        written += 1
        if i % 25 == 0:
            print(f"  {i}/{len(tokens)} done, {written} written")

    earliest = min((date.fromisoformat(open(args.out / f"{s}.csv").readlines()[1][:10])
                    for s in tokens if (args.out / f"{s}.csv").exists()), default=None)
    print(f"wrote {written} symbols to {args.out}; earliest bar {earliest}; "
          f"{len(empty)} returned no history")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
