"""EXPERIMENTAL naked intraday short strangle — NOT a mandate-compliant strategy.

Sells a ~1% OTM call AND put near the open and squares off the SAME day by 15:25.
It holds nothing to protect the shorts, so it is **naked** — which docs/01 bans for
real trading, and which the live kill-switch (and the evaluator's normal
admissibility check) refuse. It exists ONLY to be run as an isolated paper SHADOW,
explicitly opted in via `--evaluate-naked`, so the owner can watch the "no overnight"
strategy (docs/17) forward on live data:

- its own simulated book, **never places a real order**, cannot touch the live
  strategy or its kill-switch;
- shadows rebuild fresh each session-day, so "no overnight" is structural, and the
  15:25 square-off below realizes each day's P&L cleanly;
- one lot on the shadow's ₹1L book — the per-lot daily P&L is the honest primitive
  (scale by lots for the ₹6L/4-lot sizing the backtest used).

The backtest verdict stands (docs/17/18): in-sample ~30% was one regime's luck, it
went negative out-of-sample, and it is a slippage bet. The forward record is the
cheapest possible way to watch that confirm itself — a losing line costs nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time

from ..backtest.engine import Order
from ..config import RiskConfig
from ..fills import to_tick
from ..instruments import OptionLeg, Right, Side


@dataclass(frozen=True)
class StrangleParams:
    offset_pct: float = 0.01           # sell ~1% OTM each side
    entry_after: time = time(9, 20)    # open once the auction settles
    entry_before: time = time(12, 0)   # don't open a fresh strangle late in the day
    squareoff: time = time(15, 25)     # flat before the close — NEVER hold overnight
    strike_step: float = 50.0
    limit_pad: float = 0.01            # cross the touch by 1% so limits fill


def _touch(q, side: Side) -> float:
    """The price this side must reach: ask to buy, bid to sell; LTP if no depth."""
    px = getattr(q, "ask" if side is Side.BUY else "bid", None)
    return float(px) if px else q.ltp


def _round_strike(value: float, step: float) -> float:
    return round(value / step) * step


@dataclass
class IntradayStrangle:
    params: StrangleParams
    risk: RiskConfig                   # accepted for registry uniformity; NOT used (naked, no cap)
    phase: str = "idle"                # idle | holding | done — per session-day
    log: list = field(default_factory=list)

    # -- persistence (per session-day; shadows start fresh each morning) --

    def to_state(self) -> dict:
        return {"phase": self.phase}

    def from_state(self, state: dict) -> None:
        self.phase = state.get("phase", "idle")

    # -- helpers --

    def _order(self, ctx, strike: float, right: Right, side: Side) -> Order | None:
        leg = OptionLeg(ctx.index, ctx.expiry, strike, right, side)
        q = ctx.chain.get(leg.key)
        if q is None:
            return None
        base = _touch(q, side)
        pad = (1 + self.params.limit_pad) if side is Side.BUY else (1 - self.params.limit_pad)
        return Order(leg, to_tick(base * pad, side))

    # -- decision --

    def decide(self, ctx) -> list[Order]:
        book = list(ctx.positions)
        now_t = ctx.now.time()

        if book:
            # Square off the whole book at/after the deadline; otherwise hold. There
            # is no stop and no target: the strategy under test is hold-to-squareoff.
            if now_t >= self.params.squareoff:
                orders = [self._order(ctx, p.leg.strike, p.leg.right, p.leg.side.opposite)
                          for p in book]
                return [o for o in orders if o is not None]
            return []

        # Flat.
        if self.phase == "holding":
            self.phase = "done"          # square-off filled -> finished for the day
        if self.phase == "done":
            return []
        if not (self.params.entry_after <= now_t <= self.params.entry_before):
            return []

        # Enter the naked strangle: sell a ~1% OTM call AND put in one batch.
        sc = _round_strike(ctx.spot * (1 + self.params.offset_pct), self.params.strike_step)
        sp = _round_strike(ctx.spot * (1 - self.params.offset_pct), self.params.strike_step)
        call = self._order(ctx, sc, Right.CALL, Side.SELL)
        put = self._order(ctx, sp, Right.PUT, Side.SELL)
        if call is None or put is None:
            return []                    # can't quote both legs this tick; try next
        self.phase = "holding"
        return [call, put]
