"""Naked intraday strangle shadow strategy + the scoped naked carve-out.

Two properties matter: the strategy sells a 1% OTM strangle in the morning window and
buys it back at 15:25 the same day (never overnight); and the evaluator refuses that
naked batch UNLESS the shadow is explicitly opted into `allow_naked`.
"""
from datetime import date, datetime, time
from types import SimpleNamespace

from optionsbot.backtest.engine import Order
from optionsbot.config import CostConfig, RiskConfig
from optionsbot.instruments import OptionLeg, Right, Side
from optionsbot.paper.evaluator import Evaluator, Shadow
from optionsbot.paper.journal import Journal
from optionsbot.broker.paper import PaperBroker
from optionsbot.strategies.intraday_strangle import IntradayStrangle, StrangleParams

IDX, EXP, STEP = "NIFTY", date(2026, 7, 28), 50.0
RISK = RiskConfig(per_trade_max_loss_rupees=2000)          # strategy ignores it (naked)
ZERO = CostConfig(brokerage_per_order=0, txn_charge_rate=0, sebi_fee_rate=0,
                  stamp_duty_rate=0, gst_rate=0)


def q(ltp, bid=None, ask=None):
    return SimpleNamespace(ltp=ltp, bid=bid, ask=ask)


def ctx(now, spot, chain, positions=()):
    return SimpleNamespace(now=now, index=IDX, expiry=EXP, spot=spot, chain=chain,
                           positions=list(positions), lot_size=65, strike_step=STEP)


def short_pos(strike, right):
    return SimpleNamespace(leg=OptionLeg(IDX, EXP, strike, right, Side.SELL),
                           net=-65, entry_price=100.0)


def test_enters_naked_strangle_in_the_morning_window():
    s = IntradayStrangle(StrangleParams(), RISK)
    chain = {(IDX, EXP, 25250.0, Right.CALL): q(40, bid=39, ask=41),
             (IDX, EXP, 24750.0, Right.PUT): q(38, bid=37, ask=39)}
    orders = s.decide(ctx(datetime(2026, 7, 24, 9, 25), 25000.0, chain))
    assert len(orders) == 2
    assert all(o.leg.side is Side.SELL for o in orders)              # NAKED: both sold
    strikes = {(o.leg.strike, o.leg.right) for o in orders}
    assert strikes == {(25250.0, Right.CALL), (24750.0, Right.PUT)}  # 1% OTM each side
    assert s.phase == "holding"


def test_does_not_enter_after_the_window():
    s = IntradayStrangle(StrangleParams(), RISK)
    chain = {(IDX, EXP, 25250.0, Right.CALL): q(40), (IDX, EXP, 24750.0, Right.PUT): q(38)}
    assert s.decide(ctx(datetime(2026, 7, 24, 13, 0), 25000.0, chain)) == []
    assert s.phase == "idle"


def test_holds_then_squares_off_same_day():
    s = IntradayStrangle(StrangleParams(), RISK)
    s.phase = "holding"
    book = [short_pos(25250.0, Right.CALL), short_pos(24750.0, Right.PUT)]
    chain = {(IDX, EXP, 25250.0, Right.CALL): q(20, bid=19, ask=21),
             (IDX, EXP, 24750.0, Right.PUT): q(18, bid=17, ask=19)}
    # mid-day: still holding, no orders
    assert s.decide(ctx(datetime(2026, 7, 24, 13, 0), 25000.0, chain, book)) == []
    # 15:25: buy both legs back (BUY = opposite of the short)
    exits = s.decide(ctx(datetime(2026, 7, 24, 15, 25), 25000.0, chain, book))
    assert len(exits) == 2
    assert all(o.leg.side is Side.BUY for o in exits)               # closing the shorts


def test_done_latch_prevents_reentry_after_squareoff():
    s = IntradayStrangle(StrangleParams(), RISK)
    s.phase = "holding"                                             # was holding...
    chain = {(IDX, EXP, 25250.0, Right.CALL): q(40), (IDX, EXP, 24750.0, Right.PUT): q(38)}
    # ...now flat (square-off filled): transitions to done, no orders
    assert s.decide(ctx(datetime(2026, 7, 24, 15, 26), 25000.0, chain)) == []
    assert s.phase == "done"
    # even back inside the entry window it will not re-open
    assert s.decide(ctx(datetime(2026, 7, 24, 9, 30), 25000.0, chain)) == []


def _shadow(allow_naked, tmp_path):
    b = PaperBroker(100_000.0, costs=ZERO)
    b.authenticate(); b.today = date(2026, 7, 24)
    return Shadow(name="intraday-strangle", strategy=IntradayStrangle(StrangleParams(), RISK),
                  broker=b, journal=Journal(tmp_path, "intraday-strangle", date(2026, 7, 24)),
                  start_cash=100_000.0, allow_naked=allow_naked)


def _naked_batch():
    return [Order(OptionLeg(IDX, EXP, 25250.0, Right.CALL, Side.SELL), 40.0),
            Order(OptionLeg(IDX, EXP, 24750.0, Right.PUT, Side.SELL), 38.0)]


def test_evaluator_refuses_naked_batch_by_default(tmp_path):
    sh = _shadow(allow_naked=False, tmp_path=tmp_path)
    ev = Evaluator(shadows=[sh], costs=ZERO, per_trade_max_loss=2000.0, root=tmp_path)
    assert ev._batch_admissible(sh, _naked_batch(), ctx(datetime(2026, 7, 24, 9, 25), 25000.0, {})) is False


def test_evaluator_allows_naked_batch_when_opted_in(tmp_path):
    sh = _shadow(allow_naked=True, tmp_path=tmp_path)
    ev = Evaluator(shadows=[sh], costs=ZERO, per_trade_max_loss=2000.0, root=tmp_path)
    assert ev._batch_admissible(sh, _naked_batch(), ctx(datetime(2026, 7, 24, 9, 25), 25000.0, {})) is True
