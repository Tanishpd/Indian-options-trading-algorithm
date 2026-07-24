"""Run several strategies concurrently against one live feed, in shadow.

Each strategy gets its own `PaperBroker`, its own cash, and its own book. None
of them can see or affect another, and none places a real order. One session
therefore produces N independent forward records for the cost of one market
data subscription — which is what makes honest comparison affordable.

Why shadow evaluation rather than picking one strategy and running it:

A backtest chooses its winner after seeing the data, which is how this project
produced six positive results that dissolved (docs/10-13). Running candidates
forward, side by side, on data none of them was fitted to, is the only
comparison that cannot be gamed. The cost of being wrong is a line in a log
file instead of a position.

The evaluator deliberately does NOT rank strategies or pick a winner. That
belongs to `optionsbot.research.forward_report`, after enough observations
exist to mean anything — and this project's own history says that is far more
observations than feels necessary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from ..backtest.engine import Order
from ..broker.paper import PaperBroker
from ..config import CostConfig
from ..instruments import Side
from ..risk.book import BookLeg, naked_exposure, worst_case_loss
from .journal import Entry, Journal
from .loop import PaperContext, PaperStrategy


def _ready_broker(cash: float, costs: CostConfig, day: date) -> PaperBroker:
    """A broker that can actually trade: authenticated, with the date set.

    `today` is not cosmetic — STT changed on 2026-04-01, so a broker without it
    refuses to fill rather than charge the wrong rate."""
    b = PaperBroker(cash=cash, costs=costs)
    b.authenticate()
    b.today = day
    return b



@dataclass
class Shadow:
    """One strategy under evaluation, with its own isolated book."""

    name: str
    strategy: PaperStrategy
    broker: PaperBroker
    journal: Journal
    start_cash: float
    costs_paid: float = 0.0
    halted: str = ""                 # non-empty once this shadow is stopped
    # EXPERIMENTAL escape hatch: when True this shadow bypasses the defined-risk
    # and per-trade-cap invariants, so a NAKED strategy can be measured forward.
    # It is safe ONLY because a shadow places no real orders and cannot touch the
    # live strategy or its kill-switch — this flag never reaches the live loop's
    # _validate_book. It must be opted in explicitly (--evaluate-naked) and is
    # deliberately loud in the log. Never set it for the primary live strategy.
    allow_naked: bool = False
    log: list[str] = field(default_factory=list)

    def equity(self, quotes) -> float:
        """Cash plus positions marked at the price they could be closed at."""
        total = self.broker.margin_available()
        for p in self.broker.book():
            q = quotes.get(p.leg.key)
            if q is None:
                continue
            # Mark where the exit would trade: buy back a short at the ask,
            # sell a long at the bid. Marking at LTP overstates a book you
            # would have to cross the spread to leave (the same error that
            # made the live stop fire on unobtainable prices, docs/11).
            side = Side.BUY if p.net < 0 else Side.SELL
            px = getattr(q, "ask" if side is Side.BUY else "bid", None)
            total += (float(px) if px else q.ltp) * p.net
        return total


@dataclass
class Evaluator:
    """Drives N shadows from one live context."""

    shadows: list[Shadow]
    costs: CostConfig
    per_trade_max_loss: float
    root: Path

    @classmethod
    def build(cls, specs: Sequence[tuple[str, PaperStrategy]], cash: float,
              costs: CostConfig, per_trade_max_loss: float,
              root: Path, day: date,
              allow_naked_names: frozenset[str] = frozenset()) -> "Evaluator":
        shadows = [
            Shadow(name=name, strategy=strat,
                   broker=_ready_broker(cash, costs, day),
                   journal=Journal(root, name, day), start_cash=cash,
                   allow_naked=name in allow_naked_names)
            for name, strat in specs
        ]
        return cls(shadows=shadows, costs=costs,
                   per_trade_max_loss=per_trade_max_loss, root=Path(root))

    def tick(self, ctx: PaperContext) -> None:
        """Advance every live shadow by one market observation."""
        for sh in self.shadows:
            if sh.halted:
                continue
            try:
                self._tick_one(sh, ctx)
            except Exception as exc:                     # noqa: BLE001
                # One strategy raising must not stop the others or lose the
                # session. Halt it, record why, and keep the rest running.
                sh.halted = f"error: {exc!r}"
                sh.log.append(sh.halted)
                self._record(sh, ctx, [], [], note=sh.halted)

    def _tick_one(self, sh: Shadow, ctx: PaperContext) -> None:
        sh.broker.set_quotes(dict(ctx.chain))
        own = PaperContext(
            now=ctx.now, index=ctx.index, expiry=ctx.expiry, spot=ctx.spot,
            chain=ctx.chain, positions=tuple(sh.broker.book()),
            cash=sh.broker.margin_available(), equity=sh.equity(ctx.chain),
            lot_size=ctx.lot_size, strike_step=ctx.strike_step,
        )
        orders: list[Order] = list(sh.strategy.decide(own))
        fills: list[dict] = []

        # Admissibility is judged on the WHOLE batch, not order by order. A
        # condor is emitted as four legs in one tick precisely because its
        # intermediate states are inadmissible: holding one wing alone breaches
        # the per-trade cap, and holding the shorts before the wings is naked.
        # Judging incrementally would refuse every multi-leg structure and
        # silently evaluate a strategy nobody could run (learned live,
        # 2026-07-15; see tests/test_reference_condor.py).
        if orders and not self._batch_admissible(sh, orders, ctx):
            self._record(sh, ctx, orders, [])
            return

        for order in orders:
            shares = order.leg.lots * ctx.lot_size
            before = sh.broker.margin_available()
            res = sh.broker.place_limit_order(order.leg, order.limit_price, shares)
            if not res.filled:
                sh.log.append(f"unfilled ({res.reason}): {order.leg.strike:.0f} "
                              f"{order.leg.right.value}")
                continue
            delta = sh.broker.margin_available() - before
            # OrderResult carries no cost field, so recover it from the cash
            # move: cash_delta = -sign*price*shares - cost, hence
            # cost = -(cash_delta + sign*price*shares). Recomputing it here
            # rather than re-deriving from CostConfig keeps this in lockstep
            # with whatever the broker actually charged.
            notional = order.leg.side.sign * res.fill_price * shares
            sh.costs_paid += -(delta + notional)
            fills.append({
                "strike": order.leg.strike, "right": order.leg.right.value,
                "side": order.leg.side.value, "shares": shares,
                "price": res.fill_price, "cash_delta": round(delta, 2),
            })

        self._record(sh, ctx, orders, fills)

    def _batch_admissible(self, sh: Shadow, orders: Sequence[Order],
                          ctx: PaperContext) -> bool:
        """The two invariants the live engine enforces (docs/04), applied to the
        book that would exist once the whole batch has filled.

        A shadow allowed to do what the real engine would refuse is not
        evaluating the strategy — it is evaluating one that could never be run.

        The one deliberate exception is an EXPERIMENTAL naked shadow (opted in via
        --evaluate-naked): it bypasses both invariants so an un-deployable strategy
        can still be measured forward. This never touches the live loop — a shadow
        places no real orders — but it is recorded loudly so the record can never be
        mistaken for a mandate-compliant one.
        """
        if sh.allow_naked:
            if "naked-eval" not in sh.log:
                sh.log.append("naked-eval")   # once: this shadow runs unconstrained
            return True

        legs = [
            BookLeg(index=p.leg.index, expiry=p.leg.expiry, strike=p.leg.strike,
                    right=p.leg.right, signed_shares=p.net, entry_price=p.entry_price)
            for p in sh.broker.book()
        ]
        for o in orders:
            shares = o.leg.lots * ctx.lot_size
            legs.append(BookLeg(
                index=o.leg.index, expiry=o.leg.expiry, strike=o.leg.strike,
                right=o.leg.right,
                signed_shares=shares if o.leg.side is Side.BUY else -shares,
                entry_price=o.limit_price))
        naked = naked_exposure(legs)
        if naked:
            sh.log.append(f"refused batch (naked): {naked}")
            return False
        worst = worst_case_loss(legs)
        if worst > self.per_trade_max_loss:
            sh.log.append(f"refused batch (cap): worst Rs {worst:,.0f}")
            return False
        return True

    def _record(self, sh: Shadow, ctx: PaperContext, orders, fills,
                note: str = "") -> None:
        sh.journal.append(Entry(
            ts=ctx.now, strategy=sh.name, index=ctx.index, expiry=ctx.expiry,
            spot=ctx.spot, phase=getattr(sh.strategy, "phase", ""),
            equity=round(sh.equity(ctx.chain), 2),
            cash=round(sh.broker.margin_available(), 2),
            realised_costs=round(sh.costs_paid, 2),
            positions=len(sh.broker.book()),
            orders=[{"strike": o.leg.strike, "right": o.leg.right.value,
                     "side": o.leg.side.value, "limit": o.limit_price}
                    for o in orders],
            fills=fills, note=note,
        ))

    def close(self) -> None:
        for sh in self.shadows:
            sh.journal.close()

    def summary(self, quotes) -> list[dict]:
        """Current standing. Deliberately not a ranking — see the module docstring."""
        return [
            {"strategy": sh.name,
             "equity": round(sh.equity(quotes), 2),
             "pnl": round(sh.equity(quotes) - sh.start_cash, 2),
             "costs": round(sh.costs_paid, 2),
             "positions": len(sh.broker.book()),
             "halted": sh.halted}
            for sh in self.shadows
        ]
