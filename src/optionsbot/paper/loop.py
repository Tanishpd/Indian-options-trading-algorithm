"""Live paper-trading session loop.

Each tick: fetch chains for every relevant expiry (current weekly PLUS any
expiry still held) -> snapshot to CSV (dataset building) -> feed quotes to the
PaperBroker -> risk checks -> strategy -> simulated fills -> mark equity ->
kill-switch -> persist. No real orders are ever placed.

Hardening (post-review):
- Expiry is taken from the exchange's LISTED expiries (holiday-shifted weeks
  included), and held expiries keep being quoted until closed.
- Legs expiring today are force-flattened by the session after the square-off
  deadline (infrastructure backstop, independent of strategy policy); a
  position somehow past expiry trips the kill-switch and pages the owner.
- Marks carry: live quote -> persisted last mark -> entry basis. Never 0.0.
- Book-level naked and worst-case-loss checks run every tick (shared with the
  backtest engine via risk/book.py).
- Kill-switch flatten escalates: band widens per retry, owner paged after N
  unfilled attempts. Insufficient-funds rejections page immediately and stop
  the tick's remaining orders.
- State persists atomically (temp file + rename); a corrupt state file refuses
  to start rather than silently resetting capital or forgetting a halt.
- Feed failures escalate: re-authentication attempt after N consecutive
  failures, owner paged; the loop never exits on a weekend/holiday wait.
"""
from __future__ import annotations

import csv
import json
import os
import time as time_mod
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from ..backtest.data import LegKey
from ..backtest.engine import Order
from ..broker.paper import BookPosition, PaperBroker
from ..calendar import next_weekly_expiry
from ..config import AppConfig
from ..feed.base import Quote, QuoteFeed
from ..fills import protection_band_limit, to_tick
from ..instruments import OptionLeg, Right, Side
from ..risk.book import BookLeg, naked_exposure, worst_case_loss
from ..risk.killswitch import KillSwitch

_MAX_FLATTEN_BAND = 0.30


def _key_str(key: LegKey) -> str:
    index, expiry, strike, right = key
    return f"{index}|{expiry.isoformat()}|{strike}|{right.value}"


def _key_from_str(s: str) -> LegKey:
    index, expiry, strike, right = s.split("|")
    return (index, date.fromisoformat(expiry), float(strike), Right(right))


@dataclass(frozen=True)
class PaperContext:
    now: datetime
    index: str
    expiry: date
    spot: float
    chain: Mapping[LegKey, Quote]
    positions: tuple[BookPosition, ...]
    cash: float
    equity: float
    lot_size: int
    strike_step: float


class PaperStrategy(Protocol):
    def decide(self, ctx: PaperContext) -> Sequence[Order]: ...
    def to_state(self) -> dict: ...
    def from_state(self, state: dict) -> None: ...


class CollectOnly:
    """No trades — run the loop purely to snapshot live chains."""

    def decide(self, ctx: PaperContext) -> Sequence[Order]:
        return []

    def to_state(self) -> dict:
        return {}

    def from_state(self, state: dict) -> None:
        pass


@dataclass
class PaperSession:
    cfg: AppConfig
    feed: QuoteFeed
    strategy: PaperStrategy
    index: str = "NIFTY"
    poll_seconds: int = 60
    market_open: time = time(9, 15)
    market_close: time = time(15, 30)
    force_squareoff: time = time(15, 0)   # session-level expiry-day backstop
    collect_expiries: int = 3             # archive this many listed expiries per tick
    flatten_alert_after: int = 3          # page owner after N unfilled flatten tries
    reconnect_after: int = 3              # attempt re-auth after N consecutive failures
    data_dir: Path = Path("data/live")
    state_path: Path = Path("data/live/paper_state.json")
    now_fn: Callable[[], datetime] | None = None   # injectable clock (IST)
    log: Callable[[str], None] = print
    page: Callable[[str], None] | None = None      # owner alert channel
    alerts: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.broker = PaperBroker(self.cfg.starting_capital, costs=self.cfg.costs)
        self.broker.authenticate()
        self.switch = KillSwitch(
            self.cfg.risk, alert=self._page, start_equity=self.cfg.starting_capital
        )
        self._last_marks: dict[LegKey, float] = {}
        self._flatten_attempts: dict[LegKey, int] = {}
        self._failures = 0
        self._restore()

    # -- time ---------------------------------------------------------------

    def _now(self) -> datetime:
        if self.now_fn is not None:
            return self.now_fn()
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Kolkata"))

    def trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.cfg.market.holidays

    def in_session(self, now: datetime) -> bool:
        return self.trading_day(now.date()) and self.market_open <= now.time() <= self.market_close

    # -- alerts / persistence ------------------------------------------------

    def _page(self, reason: str) -> None:
        self.alerts.append(reason)
        self.log(f"*** ALERT: {reason} ***")
        if self.page is not None:
            self.page(reason)

    def _persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "broker": self.broker.snapshot(),
            "switch": self.switch.snapshot(),
            "strategy": self.strategy.to_state(),
            "last_marks": {_key_str(k): v for k, v in self._last_marks.items()},
        }
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, self.state_path)  # atomic: a crash never truncates state

    def _restore(self) -> None:
        if not self.state_path.exists():
            return
        try:
            state = json.loads(self.state_path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            quarantine = self.state_path.with_suffix(".corrupt")
            os.replace(self.state_path, quarantine)
            self._page(f"state file corrupt ({exc}) — quarantined to {quarantine}")
            raise SystemExit(
                f"refusing to start: {self.state_path} was corrupt and may describe open "
                f"positions or a halted kill-switch. Inspect {quarantine} before restarting."
            ) from exc
        self.broker.restore(state["broker"])
        self.switch.restore(state["switch"])
        self.strategy.from_state(state["strategy"])
        self._last_marks = {
            _key_from_str(k): v for k, v in state.get("last_marks", {}).items()
        }
        self.log(
            f"restored session state: cash Rs {self.broker.margin_available():,.2f}, "
            f"{len(self.broker.book())} position(s), halted={self.switch.halted}"
        )

    # -- dataset snapshotting -------------------------------------------------

    def _snapshot_chain(self, now: datetime, chain: Mapping[LegKey, Quote]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / f"chain_{self.index}_{now:%Y%m%d}.csv"
        new = not path.exists()
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["ts", "index", "expiry", "strike", "right", "ltp", "bid", "ask"])
            for (index, exp, strike, right), q in sorted(
                chain.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][3])
            ):
                w.writerow([now.isoformat(), index, exp.isoformat(), strike,
                            right.value, q.ltp, q.bid, q.ask])

    # -- marks / risk -----------------------------------------------------------

    def _equity(self, book: list[BookPosition], chain: Mapping[LegKey, Quote]) -> float:
        """Cash plus signed book value. Marks carry: quote -> last mark -> entry
        basis; a liability is never valued at zero for lack of a quote."""
        equity = self.broker.margin_available()
        for pos in book:
            q = chain.get(pos.leg.key)
            if q is not None:
                self._last_marks[pos.leg.key] = q.ltp
            mark = self._last_marks.get(pos.leg.key, pos.entry_price)
            equity += pos.net * mark
        return equity

    @staticmethod
    def _book_legs(book: list[BookPosition]) -> list[BookLeg]:
        return [
            BookLeg(index=p.leg.index, expiry=p.leg.expiry, strike=p.leg.strike,
                    right=p.leg.right, signed_shares=p.net, entry_price=p.entry_price)
            for p in book
        ]

    def _validate_book(self, book: list[BookPosition]) -> None:
        legs = self._book_legs(book)
        naked = naked_exposure(legs)
        if naked is not None:
            self.switch.trip(
                f"naked short exposure in paper book ({naked}) — defined-risk ban (docs/01)"
            )
            return
        worst = worst_case_loss(legs)
        cap = self.cfg.risk.per_trade_max_loss_rupees
        if worst > cap:
            self.switch.trip(
                f"book worst-case loss Rs {worst:,.2f} exceeds per-trade cap Rs {cap:,.2f} (docs/04)"
            )

    # -- expiry -----------------------------------------------------------------

    def _listed_expiries(self, today: date) -> list[date]:
        """Exchange-listed expiries on/after today, ascending."""
        listed = sorted(d for d in self.feed.list_expiries(self.index) if d >= today)
        if not listed:
            raise RuntimeError(f"no listed {self.index} expiries on/after {today}")
        return listed

    def _current_expiry(self, today: date, listed: list[date] | None = None) -> date:
        """The exchange's own next listed expiry — survives holiday shifts.

        Callers that already hold a listing pass it in, so the front expiry and
        the archival window are always derived from the same snapshot: a listing
        that changed between two fetches could otherwise make them disagree
        about which expiry is tradeable.
        """
        expiry = (listed or self._listed_expiries(today))[0]
        computed = next_weekly_expiry(self.index, today, self.cfg.market.holidays)
        if expiry != computed:
            self.log(f"expiry {expiry} from exchange listing (calendar computed {computed})")
        return expiry

    # -- execution ----------------------------------------------------------------

    def _place(self, order: Order, today: date, book_by_key: dict[LegKey, BookPosition]) -> bool:
        """Place one order; returns False if the tick's remaining orders should stop."""
        existing = book_by_key.get(order.leg.key)
        if existing is not None and (existing.net > 0) != (order.leg.side is Side.BUY):
            shares = abs(existing.net)  # closing: size from what's actually held
        else:
            shares = order.leg.lots * self.cfg.market.lot_size(order.leg.index, today)
        result = self.broker.place_limit_order(order.leg, order.limit_price, shares)
        self.log(
            f"{order.leg.side.value} {order.leg.key} x{shares} @ {order.limit_price}: "
            f"{'filled' if result.filled else result.reason}"
        )
        if not result.filled:
            # A decide() batch is sequenced (wings before shorts, exits together):
            # placing later legs after an earlier one failed can create exactly
            # the exposure the ordering was designed to prevent. Stop the batch;
            # the strategy re-plans from the actual book next tick.
            if result.reason == "insufficient_funds":
                self._page(
                    f"paper order rejected for insufficient funds ({order.leg.key}) — "
                    "stopping this tick's remaining orders"
                )
            return False
        return True

    def _flatten(self, book: list[BookPosition], chain: Mapping[LegKey, Quote],
                 label: str) -> None:
        """Exit positions with escalation: the band widens on every retry and the
        owner is paged after `flatten_alert_after` unfilled attempts."""
        base_band = self.cfg.fills.protection_band_pct
        for pos in book:
            key = pos.leg.key
            attempt = self._flatten_attempts.get(key, 0) + 1
            self._flatten_attempts[key] = attempt
            q = chain.get(key)
            side = pos.leg.side.opposite
            # Band away from the side we must actually reach (ask when buying
            # back, bid when selling out); LTP only when depth is unavailable.
            if q is not None:
                touch = q.ask if side is Side.BUY else q.bid
                reference = float(touch) if touch else q.ltp
            else:
                reference = self._last_marks.get(key, pos.entry_price)
            band = min(base_band * attempt, _MAX_FLATTEN_BAND)
            limit = to_tick(protection_band_limit(reference, side, band), side)
            if q is None:
                self.log(f"{label}: no quote for {key} (attempt {attempt})")
            else:
                exit_leg = OptionLeg(
                    pos.leg.index, pos.leg.expiry, pos.leg.strike, pos.leg.right,
                    side, pos.leg.lots,
                )
                result = self.broker.place_limit_order(exit_leg, limit, abs(pos.net))
                self.log(
                    f"{label} {side.value} {key} x{abs(pos.net)} @ {limit} "
                    f"(band {band:.0%}, attempt {attempt}): "
                    f"{'filled' if result.filled else result.reason}"
                )
                if result.filled:
                    self._flatten_attempts.pop(key, None)
                    continue
                if result.reason == "insufficient_funds":
                    self._page(f"{label} blocked by insufficient funds on {key}")
            if attempt == self.flatten_alert_after:
                self._page(
                    f"{label} for {key} unfilled after {attempt} attempts "
                    f"(band now {band:.0%}) — manual attention needed"
                )

    # -- core ------------------------------------------------------------------

    def tick(self) -> None:
        now = self._now()
        today = now.date()
        self.broker.today = today

        book = self.broker.book()
        listed = self._listed_expiries(today)
        front = self._current_expiry(today, listed)
        # Archive several expiries even though only the front one is traded: a
        # contract's early life cannot be bought back once it expires, and no
        # vendor sells historical bid/ask (see issues #13/#14).
        expiries = set(listed[: max(1, self.collect_expiries)])
        expiries |= {p.leg.expiry for p in book if p.leg.expiry >= today}

        spot = self.feed.spot(self.index)
        chain: dict[LegKey, Quote] = {}
        for expiry in sorted(expiries):
            try:
                chain.update(self.feed.option_chain(self.index, expiry, spot=spot))
            except Exception as exc:
                # A far expiry failing must never cost us the tradeable front one.
                if expiry == front or any(p.leg.expiry == expiry for p in book):
                    raise
                self.log(f"chain fetch failed for {expiry} (archival only): {exc!r}")
        self._snapshot_chain(now, chain)
        self.broker.set_quotes(chain)  # full quotes: buys must reach the ask, sells the bid

        past = [p for p in book if p.leg.expiry < today]
        if past and not self.switch.halted:
            keys = ", ".join(str(p.leg.key) for p in past)
            self.switch.trip(f"position(s) past expiry with no settlement possible: {keys}")

        changed = False
        if self.switch.halted:
            self._flatten(book, chain, label="flatten")
            changed = True
        else:
            due = [
                p for p in book
                if p.leg.expiry == today and now.time() >= self.force_squareoff
            ]
            if due:
                self._flatten(due, chain, label="squareoff")
                changed = True
                book = self.broker.book()

            book_by_key = {p.leg.key: p for p in book}
            equity = self._equity(book, chain)
            ctx = PaperContext(
                now=now, index=self.index, expiry=front, spot=spot, chain=chain,
                positions=tuple(book), cash=self.broker.margin_available(), equity=equity,
                lot_size=self.cfg.market.lot_size(self.index, today),
                strike_step=self.cfg.market.strike_step(self.index),
            )
            for order in self.strategy.decide(ctx):
                changed = True
                if not self._place(order, today, book_by_key):
                    break
            self._validate_book(self.broker.book())

        final_book = self.broker.book() if changed else book
        equity = self._equity(final_book, chain)
        self.switch.update(today, equity)
        self.log(
            f"[{now:%H:%M:%S}] spot {spot:.1f} | equity Rs {equity:,.2f} | "
            f"cash Rs {self.broker.margin_available():,.2f} | "
            f"positions {len(final_book)} | halted {self.switch.halted}"
        )
        self._persist()

    def run(self) -> None:
        self.feed.connect()
        first_expiry = self._current_expiry(self._now().date())
        lot_master = self.feed.lot_size(self.index, first_expiry)
        lot_cfg = self.cfg.market.lot_size(self.index, self._now().date())
        if lot_master is not None and lot_master != lot_cfg:
            raise RuntimeError(
                f"lot size mismatch: exchange master says {lot_master}, config says "
                f"{lot_cfg} — fix [market.lot_sizes] before trading (docs/05)"
            )
        self.log(f"paper session up: {self.index}, lot {lot_cfg}, poll {self.poll_seconds}s")

        ticked_day: date | None = None
        poll = max(int(self.poll_seconds), 5)
        while True:
            now = self._now()
            if not self.trading_day(now.date()):
                time_mod.sleep(300)   # weekend/holiday: wait, never exit
                continue
            if now.time() < self.market_open:
                time_mod.sleep(30)
                continue
            if now.time() > self.market_close:
                if ticked_day == now.date():
                    self.log("market closed — session over")
                    break
                time_mod.sleep(300)   # started after close: wait for the next day
                continue

            try:
                self.tick()
                if self._failures:
                    self._page(f"feed recovered after {self._failures} failed tick(s)")
                self._failures = 0
            except Exception as exc:  # keep the session alive; escalate loudly
                self._failures += 1
                self.log(f"!! tick failed ({self._failures} consecutive): {exc!r}")
                if self._failures == self.reconnect_after:
                    self._page(
                        f"feed failing ({self._failures} consecutive ticks) — attempting re-auth"
                    )
                    try:
                        self.feed.reconnect()
                    except Exception as rexc:
                        self.log(f"re-auth failed: {rexc!r}")
                elif self._failures % 10 == 0:
                    self._page(f"feed STILL failing after {self._failures} ticks — check the session")
            ticked_day = now.date()
            time_mod.sleep(poll)
