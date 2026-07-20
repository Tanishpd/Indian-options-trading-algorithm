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


def test_stop_exit_on_realized_credit():
    s = strategy()
    s.phase, s.targets = "holding", [{"strike": k, "right": r, "side": sd} for k, r, sd in []]
    s.targets = [{"strike": SC, "right": "CE", "side": "SELL"}]  # non-empty sentinel
    book = full_book()                                            # realized credit 24
    # buyback = 90 + 4 - 30 - 1 = 63 >= 2 x 24
    orders = s.decide(
        ctx(datetime(2026, 7, 10, 11, 0), chain_quotes(sc=90, lc=30, sp=4, lp=1),
            positions=book)
    )
    assert s.phase == "exiting"
    assert len(orders) == 4
    sides = {(o.leg.strike, o.leg.side) for o in orders}
    assert (SC, Side.BUY) in sides and (LC, Side.SELL) in sides   # shorts bought back


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
