from datetime import date

import pytest

from conftest import D1, ZERO_COSTS
from optionsbot.broker.paper import PaperBroker
from optionsbot.instruments import OptionLeg, Right, Side

EXPIRY = date(2026, 7, 14)
BUY_LEG = OptionLeg("NIFTY", EXPIRY, 25900, Right.CALL, Side.BUY)
SELL_LEG = OptionLeg("NIFTY", EXPIRY, 25900, Right.CALL, Side.SELL)


def broker(cash=100000.0, costs=ZERO_COSTS):
    b = PaperBroker(cash, costs=costs)
    b.authenticate()
    b.today = D1
    return b


def test_requires_authentication():
    b = PaperBroker(cash=100000.0, costs=ZERO_COSTS)
    b.today = D1
    b.set_quote(BUY_LEG, 60.0)
    with pytest.raises(RuntimeError, match="authenticate"):
        b.place_limit_order(BUY_LEG, 60.0, 65)


def test_requires_today_for_date_dependent_costs():
    b = PaperBroker(cash=100000.0, costs=ZERO_COSTS)
    b.authenticate()
    b.set_quote(BUY_LEG, 60.0)
    with pytest.raises(RuntimeError, match="today"):
        b.place_limit_order(BUY_LEG, 60.0, 65)


def test_fills_at_limit_never_at_better_market_price():
    b = broker()
    b.set_quote(BUY_LEG, 60.0)
    r = b.place_limit_order(BUY_LEG, 61.0, 65)
    assert r.filled and r.fill_price == 61.0     # conservative: limit, not market 60
    assert b.margin_available() == pytest.approx(100000.0 - 61.0 * 65)


def test_limit_respected():
    b = broker()
    b.set_quote(BUY_LEG, 60.0)
    r = b.place_limit_order(BUY_LEG, 59.0, 65)   # market above buy limit
    assert not r.filled and r.fill_price is None
    assert b.positions() == []


def test_netting_normalizes_side_to_sign():
    b = broker()
    b.set_quote(SELL_LEG, 60.0)
    b.place_limit_order(SELL_LEG, 60.0, 65)
    (pos_leg, net), = b.positions()
    assert net == -65 and pos_leg.side is Side.SELL

    b.set_quote(BUY_LEG, 60.0)
    b.place_limit_order(BUY_LEG, 60.0, 130)      # flip through zero
    (pos_leg, net), = b.positions()
    assert net == +65 and pos_leg.side is Side.BUY  # side matches the sign


def test_entry_basis_tracking():
    b = broker()
    b.set_quote(BUY_LEG, 60.0)
    b.place_limit_order(BUY_LEG, 60.0, 65)
    (bp,) = b.book()
    assert bp.entry_price == 60.0

    b.set_quote(BUY_LEG, 70.0)
    b.place_limit_order(BUY_LEG, 70.0, 65)       # add: weighted average
    (bp,) = b.book()
    assert bp.net == 130 and bp.entry_price == pytest.approx(65.0)

    b.set_quote(SELL_LEG, 80.0)
    b.place_limit_order(SELL_LEG, 80.0, 65)      # reduce: basis unchanged
    (bp,) = b.book()
    assert bp.net == 65 and bp.entry_price == pytest.approx(65.0)

    b.place_limit_order(SELL_LEG, 80.0, 130)     # flip: basis resets to flip price
    (bp,) = b.book()
    assert bp.net == -65 and bp.entry_price == pytest.approx(80.0)


def test_rejection_reasons():
    b = broker()
    r = b.place_limit_order(BUY_LEG, 61.0, 65)
    assert r.reason == "no_quote"
    b.set_quote(BUY_LEG, 60.0)
    r = b.place_limit_order(BUY_LEG, 59.0, 65)
    assert r.reason == "limit_not_crossed"
    poor = broker(cash=100.0)
    poor.set_quote(BUY_LEG, 60.0)
    r = poor.place_limit_order(BUY_LEG, 60.0, 65)
    assert r.reason == "insufficient_funds"


def test_snapshot_restore_preserves_basis():
    b = broker()
    b.set_quote(SELL_LEG, 60.0)
    b.place_limit_order(SELL_LEG, 60.0, 65)
    b2 = broker()
    b2.restore(b.snapshot())
    (bp,) = b2.book()
    assert bp.net == -65 and bp.entry_price == 60.0
    assert b2.margin_available() == b.margin_available()


def test_insufficient_cash_rejects_order():
    b = broker(cash=100.0)
    b.set_quote(BUY_LEG, 60.0)
    r = b.place_limit_order(BUY_LEG, 60.0, 65)
    assert not r.filled
    assert b.margin_available() == 100.0
    assert b.positions() == []


def test_costs_charged_by_default():
    b = PaperBroker(cash=100000.0)               # default CostConfig
    b.authenticate()
    b.today = D1
    b.set_quote(BUY_LEG, 60.0)
    r = b.place_limit_order(BUY_LEG, 60.0, 65)
    assert r.filled
    assert b.margin_available() < 100000.0 - 60.0 * 65  # premium plus real costs


class Q:
    """Feed-style quote with depth."""

    def __init__(self, ltp, bid=None, ask=None):
        self.ltp, self.bid, self.ask = ltp, bid, ask


def test_buy_must_reach_the_ask():
    b = broker()
    b.set_quote(BUY_LEG, Q(ltp=60.0, bid=59.5, ask=60.5))
    # A limit at LTP would have filled under the old LTP-only model.
    assert b.place_limit_order(BUY_LEG, 60.0, 65).reason == "limit_not_crossed"
    r = b.place_limit_order(BUY_LEG, 60.5, 65)
    assert r.filled and r.fill_price == 60.5


def test_sell_must_reach_the_bid():
    b = broker()
    b.set_quote(SELL_LEG, Q(ltp=60.0, bid=59.5, ask=60.5))
    assert b.place_limit_order(SELL_LEG, 60.0, 65).reason == "limit_not_crossed"
    r = b.place_limit_order(SELL_LEG, 59.5, 65)
    assert r.filled and r.fill_price == 59.5


def test_falls_back_to_ltp_without_depth():
    b = broker()
    b.set_quote(BUY_LEG, Q(ltp=60.0))          # no bid/ask from the feed
    assert b.place_limit_order(BUY_LEG, 60.0, 65).filled
    b2 = broker()
    b2.set_quote(BUY_LEG, 60.0)                # bare float still supported
    assert b2.place_limit_order(BUY_LEG, 60.0, 65).filled


def test_zero_depth_treated_as_missing():
    b = broker()
    b.set_quote(BUY_LEG, Q(ltp=60.0, bid=0.0, ask=0.0))   # untraded book
    assert b.place_limit_order(BUY_LEG, 60.0, 65).filled  # falls back to LTP
