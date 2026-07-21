"""PIPELINE-VALIDATION strategy — NOT a validated trading strategy.

A rules-based tight-wing weekly iron condor that exists so the paper loop has
something realistic to exercise. Its paper record does NOT count toward the
docs/06 gate-3 evidence.

Design (post-review): an explicit phase state machine driven by the broker
book, so lost strategy state is always recoverable from positions:

    idle -> entering (wings BUY first; shorts only once BOTH wings are held)
         -> holding  (credit derived from REALIZED entry basis, not quotes)
         -> exiting  (exit intent is sticky until the book is empty)
         -> idle

Entry strikes are chosen once and stored — retries never recompute from a
moved spot. All limits are padded to cross and snapped to the exchange tick
grid. Risk shape (docs/04): entries are skipped when the quoted credit would
put max loss above the per-trade cap, the realized book is re-checked against
the cap once complete, and everything exits by the square-off deadline on
expiry day (the session loop force-flattens as a backstop).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time

from ..backtest.engine import Order
from ..config import RiskConfig
from ..fills import to_tick
from ..instruments import OptionLeg, Right, Side
from ..risk.book import BookLeg, worst_case_loss


@dataclass(frozen=True)
class CondorParams:
    offset_pct: float = 0.015          # short strikes ~1.5% OTM each side
    wing_width_steps: int = 1          # wings this many strike-steps beyond shorts
    min_dte: int = 2                   # enter 2-6 days before expiry
    max_dte: int = 6
    entry_start: time = time(10, 0)    # avoid the open auction noise
    entry_end: time = time(14, 0)
    profit_target_frac: float = 0.5    # exit when buyback cost <= 50% of credit
    # Stop expressed as a share of MAX LOSS, not as a multiple of credit.
    # A credit multiple is not always reachable: a 2x stop on a 29-point credit
    # needs the structure to be worth 58 when a 50-point wing caps it at 50, so
    # the stop can never fire. Measured on real chains, a 2.0x stop was
    # unreachable in 45 of 72 cycles — the strategy ran effectively unstopped
    # 62% of the time (docs/11). A fraction of max loss is reachable by
    # construction and expresses the same intent.
    stop_loss_frac: float = 0.60       # exit once 60% of max loss is unrealised
    squareoff: time = time(14, 45)     # expiry-day hard exit (docs/05 rule 3)
    limit_pad: float = 0.005           # cross the touch price by 0.5% so limits fill
    pad_growth: float = 0.5            # extra pad per unfilled retry (x limit_pad)
    max_pad_mult: float = 5.0


def _round_strike(value: float, step: float) -> float:
    return round(value / step) * step


@dataclass
class ReferenceCondor:
    params: CondorParams
    risk: RiskConfig
    # persisted via to_state()/from_state(); recoverable from the book if lost
    phase: str = "idle"                        # idle | entering | holding | exiting
    targets: list[dict] = field(default_factory=list)  # [{"strike","right","side"}]
    attempts: int = 0                          # unfilled-retry counter (pads escalate)
    log: list[str] = field(default_factory=list)

    # -- persistence -----------------------------------------------------

    def to_state(self) -> dict:
        return {"phase": self.phase, "targets": self.targets, "attempts": self.attempts}

    def from_state(self, state: dict) -> None:
        self.phase = state.get("phase", "idle")
        self.targets = state.get("targets", [])
        self.attempts = state.get("attempts", 0)

    # -- helpers ---------------------------------------------------------

    def _say(self, msg: str) -> None:
        self.log.append(msg)

    def _reset(self) -> None:
        self.phase = "idle"
        self.targets = []
        self.attempts = 0

    def _pad(self) -> float:
        p = self.params
        mult = min(1 + self.attempts * p.pad_growth, p.max_pad_mult)
        return p.limit_pad * mult

    def _order(self, ctx, leg: OptionLeg) -> Order | None:
        q = ctx.chain.get(leg.key)
        if q is None:
            return None
        # Price from the side that must be reached (ask to buy, bid to sell),
        # then pad past it; LTP only when the feed gives no depth.
        touch = getattr(q, "ask" if leg.side is Side.BUY else "bid", None)
        base = float(touch) if touch else q.ltp
        pad = 1 + self._pad() if leg.side is Side.BUY else 1 - self._pad()
        return Order(leg, to_tick(base * pad, leg.side))

    def _leg(self, ctx, spec: dict) -> OptionLeg:
        return OptionLeg(
            ctx.index, ctx.expiry, spec["strike"], Right(spec["right"]), Side(spec["side"])
        )

    def _realized_credit(self, book) -> float:
        """Per-share credit actually received, from the book's entry basis."""
        return sum(
            (-p.entry_price if p.net > 0 else p.entry_price) for p in book
        )

    @staticmethod
    def _book_legs(book) -> list[BookLeg]:
        return [
            BookLeg(
                index=p.leg.index, expiry=p.leg.expiry, strike=p.leg.strike,
                right=p.leg.right, signed_shares=p.net, entry_price=p.entry_price,
            )
            for p in book
        ]

    def _entry_window_open(self, ctx) -> bool:
        p = self.params
        dte = (ctx.expiry - ctx.now.date()).days
        return p.min_dte <= dte <= p.max_dte and p.entry_start <= ctx.now.time() <= p.entry_end

    # -- decisions ---------------------------------------------------------

    def decide(self, ctx) -> list[Order]:
        book = list(ctx.positions)

        if not book:
            if self.phase != "idle":
                self._say(f"book flat — trade complete, leaving {self.phase}")
                self._reset()
            return self._maybe_enter(ctx)

        if not self.targets:
            # Strategy state was lost while positions survived: adopt the book.
            self.targets = [
                {"strike": p.leg.strike, "right": p.leg.right.value,
                 "side": (Side.BUY if p.net > 0 else Side.SELL).value}
                for p in book
            ]
            self.phase = "holding" if len(book) == 4 else "exiting"
            self._say(f"adopted {len(book)}-leg book from broker state -> {self.phase}")

        if self.phase == "entering":
            return self._continue_entry(ctx, book)
        if self.phase == "holding":
            self._check_exits(ctx, book)
        if self.phase == "exiting":
            return self._exit_orders(ctx, book)
        return []

    # -- entry -------------------------------------------------------------

    def _maybe_enter(self, ctx) -> list[Order]:
        if not self._entry_window_open(ctx):
            return []
        p = self.params
        step = ctx.strike_step
        sc = _round_strike(ctx.spot * (1 + p.offset_pct), step)
        sp = _round_strike(ctx.spot * (1 - p.offset_pct), step)
        width = p.wing_width_steps * step
        lc, lp = sc + width, sp - width
        if not (lp < sp < sc < lc):
            return []

        specs = [
            {"strike": lc, "right": Right.CALL.value, "side": Side.BUY.value},
            {"strike": lp, "right": Right.PUT.value, "side": Side.BUY.value},
            {"strike": sc, "right": Right.CALL.value, "side": Side.SELL.value},
            {"strike": sp, "right": Right.PUT.value, "side": Side.SELL.value},
        ]
        legs = [self._leg(ctx, s) for s in specs]
        quotes = [ctx.chain.get(leg.key) for leg in legs]
        if any(q is None for q in quotes):
            self._say("entry skipped: missing quotes")
            return []

        # Estimate the credit at prices actually obtainable (sell into the
        # bid, buy at the ask) so the per-trade cap check is not optimistic.
        def touch(leg, q):
            side_px = getattr(q, "bid" if leg.side is Side.SELL else "ask", None)
            return float(side_px) if side_px else q.ltp

        credit = sum(
            (touch(leg, q) if leg.side is Side.SELL else -touch(leg, q))
            for leg, q in zip(legs, quotes)
        )
        # A condor cannot be sold for more than its wing width, or for nothing.
        # Outside that the four legs quoted at different instants and the credit
        # is an artefact. The cap check below cannot catch it: an over-wing
        # credit makes `worst` negative, so it passes trivially and the bot
        # enters a real position on a price that never existed.
        if not (0.0 < credit < width):
            self._say(
                f"entry skipped: quoted credit {credit:.2f} outside (0, {width:.2f}) "
                f"— non-synchronous quotes"
            )
            return []

        worst = (width - credit) * ctx.lot_size
        if worst > self.risk.per_trade_max_loss_rupees:
            self._say(
                f"entry skipped: worst case Rs {worst:,.0f} > per-trade cap "
                f"Rs {self.risk.per_trade_max_loss_rupees:,.0f} (quoted credit {credit:.2f})"
            )
            return []

        self.targets = specs
        self.phase = "entering"
        self.attempts = 0
        self._say(f"entering condor {sc}/{lc} x {sp}/{lp}, quoted credit {credit:.2f}")
        # All four legs in ONE tick, wings first in the batch: ending a tick
        # with only the (expensive) wings held is itself a cap breach — the
        # loop stops the batch if any leg fails, and _continue_entry finishes
        # a partial build on later ticks.
        orders = [self._order(ctx, leg) for leg in legs]
        return [o for o in orders if o is not None]

    def _continue_entry(self, ctx, book) -> list[Order]:
        p = self.params
        expiry_day = ctx.now.date() == ctx.expiry
        window_dead = (
            not self._entry_window_open(ctx)
            or (expiry_day and ctx.now.time() >= p.squareoff)
        )
        if window_dead:
            self._say("entry window closed with a partial book — exiting what's held")
            self.phase = "exiting"
            self.attempts = 0
            return self._exit_orders(ctx, book)

        held = {(p_.leg.strike, p_.leg.right.value) for p_ in book}
        missing = [s for s in self.targets if (s["strike"], s["right"]) not in held]
        missing_wings = [s for s in missing if s["side"] == Side.BUY.value]
        missing_shorts = [s for s in missing if s["side"] == Side.SELL.value]

        if missing_wings:
            self.attempts += 1
            orders = [self._order(ctx, self._leg(ctx, s)) for s in missing_wings]
            return [o for o in orders if o is not None]
        if missing_shorts:
            self.attempts += 1
            orders = [self._order(ctx, self._leg(ctx, s)) for s in missing_shorts]
            return [o for o in orders if o is not None]

        self.phase = "holding"
        self.attempts = 0
        self._say(f"condor complete, realized credit {self._realized_credit(book):.2f}/share")
        return []

    # -- management ----------------------------------------------------------

    def _check_exits(self, ctx, book) -> None:
        p = self.params
        if ctx.now.date() == ctx.expiry and ctx.now.time() >= p.squareoff:
            self._say("square-off deadline on expiry day")
            self.phase = "exiting"
            return

        worst = worst_case_loss(self._book_legs(book))
        if worst > self.risk.per_trade_max_loss_rupees:
            self._say(
                f"realized book worst case Rs {worst:,.0f} exceeds cap — exiting"
            )
            self.phase = "exiting"
            return

        # Both triggers are evaluated in rupees against the book that actually
        # exists. Deriving max loss from params instead of from the held strikes
        # let a params/book divergence (a config edit across a restart, or the
        # adopt-from-book path) silently place the stop outside the range the
        # structure can reach — the same unreachable-stop failure in a new guise.
        # `worst` is the book's own worst case, already computed above.
        credit = sum(-p_.entry_price * p_.net for p_ in book)   # rupees received
        if credit <= 0 or worst <= 0:
            # Not silent: a book with no credit or no downside is either a data
            # fault or an arbitrage, and in both cases there is nothing for a
            # stop to protect. Squareoff and the loop backstops still apply.
            self._say(f"no stop basis: credit Rs {credit:,.0f}, worst Rs {worst:,.0f}")
            return
        quotes = [ctx.chain.get(p_.leg.key) for p_ in book]
        if any(q is None for q in quotes):
            return  # can't price an exit this tick
        pnl = sum((q.ltp - p_.entry_price) * p_.net for p_, q in zip(book, quotes))

        # A defined-risk structure cannot be worth less than -worst or more than
        # the credit taken. Outside that, the four legs last printed at different
        # instants and the difference is an artefact, not a price (docs/11). The
        # study rejects these; acting on one here would flatten a sound position.
        if not (-worst - 1e-6 <= pnl <= credit + 1e-6):
            self._say(f"ignoring unpriceable tick: implied P&L Rs {pnl:,.0f} "
                      f"outside [{-worst:,.0f}, {credit:,.0f}]")
            return

        if pnl >= p.profit_target_frac * credit:
            self._say(f"profit target: P&L Rs {pnl:,.0f} of Rs {credit:,.0f} credit")
            self.phase = "exiting"
        elif -pnl >= p.stop_loss_frac * worst:
            self._say(
                f"stop: loss Rs {-pnl:,.0f} >= {p.stop_loss_frac:.0%} "
                f"of max loss Rs {worst:,.0f}"
            )
            self.phase = "exiting"

    def _exit_orders(self, ctx, book) -> list[Order]:
        # Sticky until the book is empty: state clears only in decide() when flat.
        self.attempts += 1
        orders = []
        for p_ in book:
            exit_leg = OptionLeg(
                p_.leg.index, p_.leg.expiry, p_.leg.strike, p_.leg.right,
                p_.leg.side.opposite, p_.leg.lots,
            )
            order = self._order(ctx, exit_leg)
            if order is not None:
                orders.append(order)
        return orders
