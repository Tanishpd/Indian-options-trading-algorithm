from datetime import date, datetime

import pytest

from optionsbot.broker.paper import BookPosition
from optionsbot.config import RiskConfig
from optionsbot.feed.base import Quote
from optionsbot.instruments import OptionLeg, Right, Side
from optionsbot.paper.loop import PaperContext
from optionsbot.strategies.reference_condor import CondorParams, ReferenceCondor

EXPIRY = date(2026, 7, 14)
RISK = RiskConfig(per_trade_max_loss_rupees=2000.0)

# spot 25000, offset 1.5%: 25000*1.015 is 25374.999... in floating point, so the
# short call rounds to 25350 (not 25400); short put 24600. Wings one step (+-50).
SC, LC, SP, LP = 25350.0, 25400.0, 24600.0, 24550.0


def key(strike, right):
    return ("NIFTY", EXPIRY, strike, right)


def chain_quotes(sc, lc, sp, lp):
    return {
        key(SC, Right.CALL): Quote(ltp=sc), key(LC, Right.CALL): Quote(ltp=lc),
        key(SP, Right.PUT): Quote(ltp=sp), key(LP, Right.PUT): Quote(ltp=lp),
    }


def pos(strike, right, net, entry):
    side = Side.BUY if net > 0 else Side.SELL
    return BookPosition(
        leg=OptionLeg("NIFTY", EXPIRY, strike, right, side), net=net, entry_price=entry
    )


def full_book(sc=30.0, lc=18.0, sp=28.0, lp=16.0):
    """Realized credit = 30 + 28 - 18 - 16 = 24/share."""
    return (
        pos(LC, Right.CALL, 65, lc), pos(LP, Right.PUT, 65, lp),
        pos(SC, Right.CALL, -65, sc), pos(SP, Right.PUT, -65, sp),
    )


def ctx(now, chain, positions=(), spot=25000.0):
    return PaperContext(
        now=now, index="NIFTY", expiry=EXPIRY, spot=spot, chain=chain,
        positions=tuple(positions), cash=100000.0, equity=100000.0,
        lot_size=65, strike_step=50.0,
    )


def strategy():
    return ReferenceCondor(params=CondorParams(), risk=RISK)


ENTRY_TIME = datetime(2026, 7, 9, 11, 0)
GOOD_QUOTES = dict(sc=30.0, lc=18.0, sp=28.0, lp=16.0)


def test_entry_emits_full_condor_wings_first():
    s = strategy()
    orders = s.decide(ctx(ENTRY_TIME, chain_quotes(**GOOD_QUOTES)))
    # All four legs in one tick: ending a tick holding only the expensive
    # wings is itself a cap breach (learned live on 2026-07-15).
    assert len(orders) == 4
    assert [o.leg.side for o in orders[:2]] == [Side.BUY, Side.BUY]   # wings first
    assert [o.leg.side for o in orders[2:]] == [Side.SELL, Side.SELL]
    assert {o.leg.strike for o in orders} == {SC, LC, SP, LP}
    assert s.phase == "entering"
    assert {t["strike"] for t in s.targets} == {SC, LC, SP, LP}  # strikes locked
    # limits are padded to cross and on the 0.05 tick grid
    for o in orders:
        assert round(o.limit_price / 0.05, 6) == pytest.approx(round(o.limit_price / 0.05))


def test_entry_skipped_when_cap_would_be_breached():
    # credit = 10 + 9 - 5 - 4 = 10 -> worst (50-10)*65 = 2600 > 2000
    s = strategy()
    orders = s.decide(ctx(ENTRY_TIME, chain_quotes(sc=10, lc=5, sp=9, lp=4)))
    assert orders == []
    assert s.phase == "idle"
    assert any("per-trade cap" in m for m in s.log)


def test_entry_respects_dte_and_time_window():
    s = strategy()
    quotes = chain_quotes(**GOOD_QUOTES)
    assert s.decide(ctx(datetime(2026, 7, 13, 11, 0), quotes)) == []   # dte 1 < min 2
    assert s.decide(ctx(datetime(2026, 7, 9, 9, 30), quotes)) == []    # before window
    assert s.decide(ctx(datetime(2026, 7, 9, 14, 30), quotes)) == []   # after window


def test_shorts_ordered_only_after_both_wings_held():
    s = strategy()
    s.decide(ctx(ENTRY_TIME, chain_quotes(**GOOD_QUOTES)))              # sets targets

    wings = (pos(LC, Right.CALL, 65, 18.0), pos(LP, Right.PUT, 65, 16.0))
    orders = s.decide(ctx(ENTRY_TIME, chain_quotes(**GOOD_QUOTES), positions=wings))
    assert len(orders) == 2
    assert all(o.leg.side is Side.SELL for o in orders)
    assert {o.leg.strike for o in orders} == {SC, SP}

    one_wing = (pos(LC, Right.CALL, 65, 18.0),)
    s2 = strategy()
    s2.decide(ctx(ENTRY_TIME, chain_quotes(**GOOD_QUOTES)))
    orders = s2.decide(ctx(ENTRY_TIME, chain_quotes(**GOOD_QUOTES), positions=one_wing))
    assert all(o.leg.side is Side.BUY for o in orders)          # still completing wings
    assert {o.leg.strike for o in orders} == {LP}


def test_retry_uses_stored_strikes_when_spot_moves():
    s = strategy()
    s.decide(ctx(ENTRY_TIME, chain_quotes(**GOOD_QUOTES)))
    wings = (pos(LC, Right.CALL, 65, 18.0), pos(LP, Right.PUT, 65, 16.0))
    # spot has drifted 200 points — targets must NOT be recomputed
    orders = s.decide(
        ctx(ENTRY_TIME, chain_quotes(**GOOD_QUOTES), positions=wings, spot=25200.0)
    )
    assert {o.leg.strike for o in orders} == {SC, SP}


def test_full_book_transitions_to_holding():
    s = strategy()
    s.decide(ctx(ENTRY_TIME, chain_quotes(**GOOD_QUOTES)))
    orders = s.decide(ctx(ENTRY_TIME, chain_quotes(**GOOD_QUOTES), positions=full_book()))
    assert orders == []
    assert s.phase == "holding"


def test_entry_window_death_with_partial_book_exits():
    s = strategy()
    s.decide(ctx(ENTRY_TIME, chain_quotes(**GOOD_QUOTES)))
    wings = (pos(LC, Right.CALL, 65, 18.0), pos(LP, Right.PUT, 65, 16.0))
    late = datetime(2026, 7, 9, 14, 30)                          # past entry_end
    orders = s.decide(ctx(late, chain_quotes(**GOOD_QUOTES), positions=wings))
    assert s.phase == "exiting"
    assert all(o.leg.side is Side.SELL for o in orders)          # closing the longs
    assert {o.leg.strike for o in orders} == {LC, LP}


def test_stop_exit_on_share_of_max_loss():
    """Both triggers are measured in rupees against the book that exists.
    Realized credit Rs 1,560; worst case Rs 1,690; stop at 60% = Rs 1,014 lost."""
    s = strategy()
    s.phase = "holding"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    # P&L = -650 -975 -1040 +1625 = Rs 1,040 lost, past the threshold.
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(sc=46, lc=8, sp=3, lp=1),
            positions=full_book())
    )
    assert s.phase == "exiting"
    assert len(orders) == 4
    assert any("stop: loss Rs 1,040" in m for m in s.log)
    sides = {(o.leg.strike, o.leg.side) for o in orders}
    assert (SC, Side.BUY) in sides and (LC, Side.SELL) in sides   # shorts bought back


def test_no_stop_just_below_the_threshold():
    """Pins the level, not just the direction. Without this any fraction up to
    0.61 passes the suite and the stop's calibration is untested."""
    s = strategy()
    s.phase = "holding"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    # P&L = -650 -975 -975 +1625 = Rs 975 lost, just under the Rs 1,014 threshold.
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(sc=45, lc=8, sp=3, lp=1),
            positions=full_book())
    )
    assert s.phase == "holding" and orders == []


def test_no_profit_target_just_below_the_threshold():
    s = strategy()
    s.phase = "holding"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    # P&L = -910 -910 +1170 +1170 = +520, under 50% of the Rs 1,560 credit.
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(sc=12, lc=4, sp=10, lp=2),
            positions=full_book())
    )
    assert s.phase == "holding" and orders == []


def test_stop_uses_the_held_strikes_not_the_params():
    """Regression. Deriving max loss from params rather than from the book let a
    params/book divergence put the stop beyond anything the structure could
    reach -- the unreachable-stop failure that ran the bot without a stop in 62%
    of cycles, reintroduced by a different route. Here params say the wings are
    4 steps wide; the book says 1. The book wins."""
    s = ReferenceCondor(params=CondorParams(wing_width_steps=4), risk=RISK)
    s.phase = "holding"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    # Rs 1,235 lost of a Rs 1,690 worst case (73%) -> stops. Against the params
    # width of 200 the threshold would sit at 129.6 points on a structure the
    # 50-point wing caps at 50: never reachable.
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(sc=52, lc=10, sp=2, lp=1),
            positions=full_book())
    )
    assert s.phase == "exiting" and len(orders) == 4


def test_impossible_quote_is_ignored_rather_than_traded_on():
    """A defined-risk book cannot lose more than its worst case. A value past
    that came from four legs printing at different instants, not from the
    market. Acting on it flattens a sound position and books a real loss."""
    s = strategy()
    s.phase = "holding"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    # Short call spikes to 120: implies Rs 5,850 lost on a Rs 1,690 max loss.
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(sc=120, lc=18, sp=28, lp=16),
            positions=full_book())
    )
    assert s.phase == "holding" and orders == []
    assert any("unpriceable tick" in m for m in s.log)


def test_stop_threshold_is_always_attainable():
    """The stop is a fraction of the book's own worst case, so it sits inside
    the range the structure can reach at every credit. The previous form -- a
    multiple of credit -- did not, and was unreachable in 45 of 72 real cycles."""
    from optionsbot.risk.book import worst_case_loss
    p = CondorParams()
    # Credits from thin to rich, all inside the 50-point wing.
    for legs in ((5, 2, 4, 1.5), (20, 8, 18, 7), (30, 14, 28, 13), (40, 22, 38, 20)):
        book = full_book(*[float(x) for x in legs])
        worst = worst_case_loss(ReferenceCondor._book_legs(book))
        assert 0 < p.stop_loss_frac * worst <= worst


def test_profit_target_exit_on_realized_credit():
    s = strategy()
    s.phase = "holding"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    # buyback = 5 + 4 - 1 - 0.5 = 7.5 <= 0.5 x 24
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(sc=5, lc=1, sp=4, lp=0.5),
            positions=full_book())
    )
    assert s.phase == "exiting" and len(orders) == 4


def test_squareoff_on_expiry_day():
    s = strategy()
    s.phase = "holding"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    orders = s.decide(
        ctx(datetime(2026, 7, 14, 14, 50), chain_quotes(sc=20, lc=10, sp=18, lp=9),
            positions=full_book())
    )
    assert s.phase == "exiting" and len(orders) == 4
    assert any("square-off" in m for m in s.log)


def test_lost_state_adopts_book_without_crashing():
    s = strategy()                    # phase=idle, targets=[] — state was wiped
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(sc=25, lc=15, sp=23, lp=13),
            positions=full_book())
    )
    assert s.phase == "holding"       # adopted; realized credit derived from basis
    assert orders == []
    assert any("adopted" in m for m in s.log)


def test_lost_state_with_partial_book_exits():
    s = strategy()
    partial = (pos(LC, Right.CALL, 65, 18.0),)
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(**GOOD_QUOTES), positions=partial)
    )
    assert s.phase == "exiting"
    assert len(orders) == 1 and orders[0].leg.side is Side.SELL


def test_exit_is_sticky_until_flat():
    s = strategy()
    s.phase = "exiting"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    remaining = (pos(SC, Right.CALL, -65, 30.0),)
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 12, 0), chain_quotes(**GOOD_QUOTES), positions=remaining)
    )
    assert len(orders) == 1 and orders[0].leg.side is Side.BUY   # keeps closing
    assert s.phase == "exiting"                                  # no re-entry

    # flat -> reset (checked outside the entry window so no fresh entry starts)
    orders = s.decide(ctx(datetime(2026, 7, 10, 14, 30), chain_quotes(**GOOD_QUOTES)))
    assert s.phase == "idle" and orders == []


def test_state_roundtrip():
    s = strategy()
    s.decide(ctx(ENTRY_TIME, chain_quotes(**GOOD_QUOTES)))
    s2 = strategy()
    s2.from_state(s.to_state())
    assert s2.phase == "entering"
    assert s2.targets == s.targets


class DepthQuote:
    def __init__(self, ltp, bid, ask):
        self.ltp, self.bid, self.ask = ltp, bid, ask


def depth_chain(sc, lc, sp, lp, spread=0.5):
    """Quotes with a bid/ask spread around each LTP."""
    def q(x):
        return DepthQuote(x, round(x - spread / 2, 2), round(x + spread / 2, 2))
    return {
        key(SC, Right.CALL): q(sc), key(LC, Right.CALL): q(lc),
        key(SP, Right.PUT): q(sp), key(LP, Right.PUT): q(lp),
    }


def test_credit_estimated_at_executable_prices():
    # LTP credit would be 24.00; selling the bid and buying the ask gives
    # 24.00 - 4 x 0.25 = 23.00, so the cap check sees the honest number.
    s = strategy()
    s.decide(ctx(ENTRY_TIME, depth_chain(**GOOD_QUOTES)))
    assert any("quoted credit 23.00" in m for m in s.log)


def test_orders_price_from_the_touch_not_ltp():
    s = strategy()
    orders = s.decide(ctx(ENTRY_TIME, depth_chain(**GOOD_QUOTES)))
    buys = {o.leg.strike: o.limit_price for o in orders if o.leg.side is Side.BUY}
    # Long call: ask 18.25, padded up 0.5% -> 18.35 on the tick grid (>= ask).
    assert buys[LC] >= 18.25
    sells = {o.leg.strike: o.limit_price for o in orders if o.leg.side is Side.SELL}
    # Short call: bid 29.75, padded down -> at or below the bid so it crosses.
    assert sells[SC] <= 29.75


# -- boundary and guard coverage ------------------------------------------
# Each test below exists because a mutation survived the suite without it.
# Asserting only one point on the far side of a threshold pins the direction
# but not the level, and a stop whose level is untested is how this strategy
# shipped with an unreachable one.


def test_triggers_fire_at_exact_equality():
    """Both comparisons are >=. With >, a position sitting exactly at its stated
    stop rides on: the threshold silently becomes unreachable at its own level."""
    # credit Rs 1,560, worst Rs 1,690. Stop at exactly 60% = Rs 1,014 lost.
    s = strategy()
    s.phase = "holding"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(sc=1.60, lc=1.0, sp=40.0, lp=1.0),
            positions=full_book())
    )
    assert s.phase == "exiting" and len(orders) == 4

    # Target at exactly 50% of the Rs 1,560 credit = Rs 780 gained.
    s2 = strategy()
    s2.phase = "holding"
    s2.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    orders = s2.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(sc=13.0, lc=1.0, sp=1.0, lp=1.0),
            positions=full_book())
    )
    assert s2.phase == "exiting" and len(orders) == 4


def test_bound_is_oriented_loss_down_profit_up():
    """The bound is -worst <= pnl <= credit. Inverting it to -credit <= pnl <=
    worst passes every other test in this file, and suppresses real stops: the
    book can lose more than its credit, which the inverted form calls
    impossible."""
    s = strategy()
    s.phase = "holding"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    # Rs 1,625 lost: past the Rs 1,560 credit, inside the Rs 1,690 worst case.
    # Legal under the true bound, rejected as impossible under the inverted one.
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(sc=57.0, lc=8.0, sp=1.0, lp=1.0),
            positions=full_book())
    )
    assert s.phase == "exiting" and len(orders) == 4
    assert any("stop" in m for m in s.log)


def test_profit_target_level_is_pinned_both_sides():
    """Without the near-side case any target in 0.34-0.68 passes the suite."""
    for quotes, should_exit in (
        (dict(sc=12.0, lc=1.0, sp=1.0, lp=1.0), True),    # Rs 845 >= Rs 780
        (dict(sc=14.0, lc=1.0, sp=1.0, lp=1.0), False),   # Rs 715 <  Rs 780
    ):
        s = strategy()
        s.phase = "holding"
        s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
        s.decide(ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(**quotes),
                     positions=full_book()))
        assert (s.phase == "exiting") is should_exit, quotes


def test_no_stop_basis_guard_holds_rather_than_exits():
    """A zero-credit book has nothing for a stop to protect. Deleting the guard
    makes the target test `0 >= 0.5 * 0` true, so the bot exits immediately on
    a book it should simply hold."""
    flat = full_book(sc=10.0, lc=10.0, sp=10.0, lp=10.0)   # credit exactly Rs 0
    # A zero-credit 50-wide condor risks Rs 3,250, which trips the per-trade cap
    # first and exits for a different (correct) reason. Widen the cap so this
    # test reaches the guard it is actually about.
    s = ReferenceCondor(params=CondorParams(),
                        risk=RiskConfig(per_trade_max_loss_rupees=5000.0))
    s.phase = "holding"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(sc=10, lc=10, sp=10, lp=10),
            positions=flat)
    )
    assert s.phase == "holding" and orders == []
    assert any("no stop basis" in m for m in s.log)


def test_entry_refused_when_quoted_credit_exceeds_the_wing():
    """An over-wing credit is four legs quoted at different instants. It makes
    the cap check's `worst` negative, so that check passes trivially and the bot
    would enter a real position on a price that never existed."""
    s = strategy()
    # credit = 80 + 80 - 25 - 25 = 110 on a 50-point wing
    orders = s.decide(ctx(ENTRY_TIME, chain_quotes(sc=80, lc=25, sp=80, lp=25)))
    assert orders == [] and s.phase == "idle"
    assert any("non-synchronous quotes" in m for m in s.log)


def depth_quotes(**legs):
    """Chain with real depth: (ltp, bid, ask) per leg."""
    q = {}
    for name, (ltp, bid, ask) in legs.items():
        strike, right = {"sc": (SC, Right.CALL), "lc": (LC, Right.CALL),
                         "sp": (SP, Right.PUT), "lp": (LP, Right.PUT)}[name]
        q[key(strike, right)] = Quote(ltp=ltp, bid=bid, ask=ask)
    return q


def test_exit_triggers_mark_where_the_exit_order_must_trade():
    """A short is bought back at the ask and a long sold at the bid, so that is
    where the trigger has to read. Marking at LTP fired the stop on a price the
    exit could not obtain — on a wide book the gap was Rs 393 against a Rs 1,690
    max loss, a fifth of the risk budget the stop exists to govern.

    These quotes are built so the two readings disagree: at the touch the book
    is down Rs 1,202 (past the Rs 1,014 stop); at LTP it looks like Rs 585."""
    chain = depth_quotes(sc=(42.0, 40.0, 48.0), lc=(10.0, 8.0, 12.0),
                         sp=(2.0, 1.0, 3.0), lp=(1.0, 0.5, 1.5))
    s = strategy()
    s.phase = "holding"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    orders = s.decide(ctx(datetime(2026, 7, 10, 11, 0), chain, positions=full_book()))
    assert s.phase == "exiting" and len(orders) == 4
    assert any("stop: loss Rs 1,202" in m for m in s.log)


def test_log_does_not_grow_without_bound_on_a_stuck_condition():
    """The guard paths repeat identically for as long as their condition holds
    and nothing drains this list; 500 ticks once produced 500 identical lines."""
    flat = full_book(sc=10.0, lc=10.0, sp=10.0, lp=10.0)      # credit Rs 0
    s = ReferenceCondor(params=CondorParams(),
                        risk=RiskConfig(per_trade_max_loss_rupees=5000.0))
    s.phase = "holding"
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]
    for _ in range(500):
        s.decide(ctx(datetime(2026, 7, 10, 11, 0),
                     chain_quotes(sc=10, lc=10, sp=10, lp=10), positions=flat))
    assert len(s.log) == 1                                    # repeats collapse
    assert any("no stop basis" in m for m in s.log)
