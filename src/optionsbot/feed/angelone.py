"""Angel One SmartAPI quote feed (market data only — no orders).

Compliance notes (docs/03): SmartAPI access requires your public IP to be
whitelisted in the SmartAPI portal (Angel One allows 1 primary + 1 secondary,
updatable at most once per calendar week), OAuth-style session login, and
TOTP 2FA. Reading market data places no orders, so order-type rules and the
10-orders/second threshold are not in play for this feed.

Credentials come from the environment (see config/broker.env.example):
    SMARTAPI_KEY, SMARTAPI_CLIENT_CODE, SMARTAPI_PIN, SMARTAPI_TOTP_SECRET
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from ..backtest.data import LegKey
from ..calendar import SUPPORTED_INDICES, check_index
from ..instruments import Right
from .base import Quote

SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)
_QUOTE_BATCH = 50          # SmartAPI FULL-mode market data cap per request
_MIN_CALL_GAP_S = 1.05     # pace ALL market-data calls under the ~1 req/s limit
_MASTER_MAX_AGE = timedelta(hours=20)  # refresh the instrument master daily

_SPOT_SYMBOLS = {"NIFTY": ("NSE", "nifty 50"), "SENSEX": ("BSE", "sensex")}

# Scrip-master expiry format: 14JUL2026
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _expiry_str(d: date) -> str:
    return f"{d.day:02d}{_MONTHS[d.month - 1]}{d.year}"


def _parse_expiry(s: str) -> date | None:
    try:
        day, mon, year = int(s[:2]), _MONTHS.index(s[2:5]) + 1, int(s[5:])
        return date(year, mon, day)
    except (ValueError, IndexError):
        return None


def _relevant(row: dict) -> bool:
    """Keep only the rows the feed can ever use — the full master is ~100k+
    rows / hundreds of MB parsed; this drops >95% of it."""
    if (
        row.get("instrumenttype") == "OPTIDX"
        and row.get("name") in SUPPORTED_INDICES
        and row.get("exch_seg") in ("NFO", "BFO")
    ):
        return True
    symbol = (row.get("symbol") or "").lower()
    return any(
        row.get("exch_seg") == exch and symbol == want
        for exch, want in _SPOT_SYMBOLS.values()
    )


class AngelOneFeed:
    def __init__(
        self,
        api_key: str,
        client_code: str,
        pin: str,
        totp_secret: str,
        client: Any | None = None,               # injectable for tests
        cache_dir: str | Path = "data/cache",
        strikes_around: int = 24,                # 49 strikes x 2 rights fits 2 batches
        strike_step: float = 50.0,
        log: Callable[[str], None] = lambda msg: None,
    ) -> None:
        self._api_key = api_key
        self._client_code = client_code
        self._pin = pin
        self._totp_secret = totp_secret
        self._client = client
        self._cache_dir = Path(cache_dir)
        self._strikes_around = strikes_around
        self._strike_step = strike_step
        self._log = log
        self._master: list[dict] | None = None
        self._spot_tokens: dict[str, str] = {}
        self._token_cache: dict[tuple[str, date], dict[LegKey, str]] = {}
        self._last_call = 0.0

    # -- session ---------------------------------------------------------

    def _login(self) -> None:
        import pyotp

        session = self._client.generateSession(
            self._client_code, self._pin, pyotp.TOTP(self._totp_secret).now()
        )
        if not session.get("status"):
            raise RuntimeError(
                f"SmartAPI login failed: {session.get('message', session)} — "
                "check credentials, TOTP secret, and that this machine's public "
                "IP is whitelisted in the SmartAPI portal (docs/03)"
            )

    def connect(self) -> None:
        if self._client is None:
            from SmartApi import SmartConnect  # lazy: core library stays SDK-free

            self._client = SmartConnect(api_key=self._api_key)
            self._login()
        self._load_master()

    def reconnect(self) -> None:
        """Re-authenticate the existing client (token death mid-session)."""
        if self._client is not None and hasattr(self._client, "generateSession"):
            self._log("feed: re-authenticating SmartAPI session")
            self._login()

    # -- instrument master -------------------------------------------------

    def _load_master(self) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_dir / "scrip_master.json"
        fresh = (
            path.exists()
            and datetime.now() - datetime.fromtimestamp(path.stat().st_mtime) < _MASTER_MAX_AGE
        )
        raw: bytes | None = None
        if not fresh:
            with urllib.request.urlopen(SCRIP_MASTER_URL, timeout=120) as resp:
                raw = resp.read()
            # Validate BEFORE caching: a bad body must not poison the cache.
            parsed = json.loads(raw)
            if not isinstance(parsed, list) or not parsed:
                raise RuntimeError("scrip master download is not a non-empty JSON list")
            path.write_bytes(raw)
        else:
            parsed = json.loads(path.read_text())
        self._master = [row for row in parsed if _relevant(row)]
        self._token_cache.clear()
        self._spot_tokens.clear()
        if not self._master:
            raise RuntimeError("scrip master contained no NIFTY/SENSEX option rows")

    def _rows(self) -> list[dict]:
        if self._master is None:
            raise RuntimeError("connect() before requesting quotes")
        return self._master

    def list_expiries(self, index: str) -> list[date]:
        check_index(index)
        out = {
            e
            for row in self._rows()
            if row.get("name") == index and row.get("instrumenttype") == "OPTIDX"
            and (e := _parse_expiry(row.get("expiry", ""))) is not None
        }
        return sorted(out)

    def option_tokens(self, index: str, expiry: date) -> dict[LegKey, str]:
        """LegKey -> exchange token for the chain (strike in the master is
        paise — divide by 100). Cached per (index, expiry)."""
        check_index(index)
        cached = self._token_cache.get((index, expiry))
        if cached is not None:
            return cached
        exch = "NFO" if index == "NIFTY" else "BFO"
        want_expiry = _expiry_str(expiry)
        out: dict[LegKey, str] = {}
        for row in self._rows():
            if (
                row.get("exch_seg") == exch
                and row.get("name") == index
                and row.get("expiry") == want_expiry
            ):
                symbol = row.get("symbol", "")
                if symbol.endswith("CE"):
                    right = Right.CALL
                elif symbol.endswith("PE"):
                    right = Right.PUT
                else:
                    continue
                strike = float(row["strike"]) / 100.0
                out[(index, expiry, strike, right)] = row["token"]
        if not out:
            listed = ", ".join(str(d) for d in self.list_expiries(index)[:5])
            raise RuntimeError(
                f"no {index} options for expiry {want_expiry} in the scrip master — "
                f"nearest listed expiries: {listed}"
            )
        self._token_cache[(index, expiry)] = out
        return out

    def lot_size(self, index: str, expiry: date) -> int | None:
        exch = "NFO" if index == "NIFTY" else "BFO"
        want_expiry = _expiry_str(expiry)
        for row in self._rows():
            if (
                row.get("exch_seg") == exch
                and row.get("name") == index
                and row.get("expiry") == want_expiry
            ):
                try:
                    return int(row["lotsize"])
                except (KeyError, ValueError):
                    return None
        return None

    def _spot_token(self, index: str) -> tuple[str, str]:
        """(exchange, token) for the index spot."""
        if index not in self._spot_tokens:
            exch, want = _SPOT_SYMBOLS[index]
            for row in self._rows():
                if row.get("exch_seg") == exch and (row.get("symbol") or "").lower() == want:
                    self._spot_tokens[index] = row["token"]
                    break
            else:
                raise RuntimeError(f"spot token for {index} not found in scrip master")
            return exch, self._spot_tokens[index]
        return _SPOT_SYMBOLS[index][0], self._spot_tokens[index]

    # -- quotes ------------------------------------------------------------

    def _paced(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < _MIN_CALL_GAP_S:
            time.sleep(_MIN_CALL_GAP_S - gap)
        self._last_call = time.monotonic()

    def _market_data(self, exchange: str, tokens: list[str]) -> dict[str, dict]:
        """FULL-mode quotes for up to _QUOTE_BATCH tokens per call, keyed by token."""
        fetched: dict[str, dict] = {}
        for i in range(0, len(tokens), _QUOTE_BATCH):
            batch = tokens[i : i + _QUOTE_BATCH]
            self._paced()
            resp = self._client.getMarketData("FULL", {exchange: batch})
            if not resp.get("status"):
                raise RuntimeError(f"SmartAPI market data failed: {resp.get('message', resp)}")
            data = resp.get("data") or {}
            for item in data.get("fetched") or []:
                fetched[str(item["symbolToken"])] = item
            unfetched = data.get("unfetched") or []
            if unfetched:
                self._log(f"feed: {len(unfetched)} token(s) unfetched in {exchange} batch")
        return fetched

    def spot(self, index: str) -> float:
        exchange, token = self._spot_token(index)
        data = self._market_data(exchange, [token])
        item = data.get(str(token))
        if item is None or not item.get("ltp"):
            raise RuntimeError(
                f"no spot quote for {index} (token {token} unfetched or ltp empty) — "
                "market may be closed or the API is throttling"
            )
        return float(item["ltp"])

    def option_chain(
        self, index: str, expiry: date, spot: float | None = None
    ) -> Mapping[LegKey, Quote]:
        tokens = self.option_tokens(index, expiry)
        if spot is None:
            spot = self.spot(index)
        lo = spot - self._strikes_around * self._strike_step
        hi = spot + self._strikes_around * self._strike_step
        near = {k: t for k, t in tokens.items() if lo <= k[2] <= hi}

        exch = "NFO" if index == "NIFTY" else "BFO"
        data = self._market_data(exch, list(near.values()))

        chain: dict[LegKey, Quote] = {}
        skipped = 0
        for key, token in near.items():
            item = data.get(str(token))
            if item is None:
                continue
            ltp = item.get("ltp")
            if ltp is None or float(ltp) <= 0.0:
                skipped += 1  # untraded/invalid — never present 0 as a real price
                continue
            bid = ask = None
            depth = item.get("depth") or {}
            buys, sells = depth.get("buy") or [], depth.get("sell") or []
            if buys and buys[0].get("price"):
                bid = float(buys[0]["price"])
            if sells and sells[0].get("price"):
                ask = float(sells[0]["price"])
            chain[key] = Quote(ltp=float(ltp), bid=bid, ask=ask)
        if skipped:
            self._log(f"feed: skipped {skipped} zero/None-ltp quote(s) on {expiry}")
        return chain
