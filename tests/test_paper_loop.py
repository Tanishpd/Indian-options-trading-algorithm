from datetime import date, datetime, timedelta

import pytest

from conftest import ZERO_COSTS, make_cfg
from optionsbot.backtest.engine import Order
from optionsbot.feed.base import Quote
from optionsbot.instruments import OptionLeg, Right, Side
from optionsbot.paper.loop import CollectOnly, PaperContext, PaperSession

EXPIRY = date(2026, 7, 14)   # Tuesday — the weekly NIFTY expiry
NOW = datetime(2026, 7, 9, 11, 0)  # Thursday before

CALL_KEY = ("NIFTY", EXPIRY, 25900.0, Right.CALL)
CHAIN = {CALL_KEY: Quote(ltp=60.0, bid=59.5, ask=60.5)}


class FakeFeed:
    def __init__(self, chain=None, spot=25500.0, lot=65, expiries=None):
        self.chain = CHAIN if chain is None else chain
        self._spot, self._lot = spot, lot
        self._expiries = expiries or [EXPIRY]
        self.connected = False
        self.reconnects = 0
        self.requested = []
        self.fail_expiries = set()

    def connect(self):
        self.connected = True

    def reconnect(self):
        self.reconnects += 1

    def spot(self, index):
        return self._spot

    def list_expiries(self, index):
        return sorted(self._expiries)

    def option_chain(self, index, expiry, spot=None):
        if expiry in self.fail_expiries:
            raise RuntimeError(f"synthetic feed failure for {expiry}")
        self.requested.append(expiry)
        return {k: q for k, q in self.chain.items() if k[1] == expiry}

    def lot_size(self, index, expiry):
        return self._lot


class NullStrategy:
    def decide(self, ctx):
        return []

    def to_state(self):
        return {}

    def from_state(self, state):
        pass


class BuyOnce(NullStrategy):
    def __init__(self):
        self.done = False

    def decide(self, ctx: PaperContext):
        if self.done:
            return []
        self.done = True
        return [Order(OptionLeg("NIFTY", EXPIRY, 25900.0, Right.CALL, Side.BUY), 61.0)]

    def to_state(self):
        return {"done": self.done}

    def from_state(self, state):
        self.done = state.get("done", False)


class SellNaked(NullStrategy):
    def decide(self, ctx):
        return [Order(OptionLeg("NIFTY", EXPIRY, 25900.0, Right.CALL, Side.SELL), 59.0)]


def session(tmp_path, strategy, feed=None, cfg=None, now=NOW, log=None):
    return PaperSession(
        cfg=cfg or make_cfg(costs=ZERO_COSTS),
        feed=feed or FakeFeed(),
        strategy=strategy,
        data_dir=tmp_path / "live",
        state_path=tmp_path / "state.json",
        now_fn=lambda: now,
        log=log or (lambda msg: None),
    )


def test_tick_places_paper_trade_and_snapshots(tmp_path):
    s = session(tmp_path, BuyOnce())
    s.tick()

    (bp,) = s.broker.book()
    assert bp.net == 65 and bp.entry_price == 61.0
    assert s.broker.margin_available() == pytest.approx(100000.0 - 61.0 * 65)

    snap = tmp_path / "live" / f"chain_NIFTY_{NOW:%Y%m%d}.csv"
    assert snap.exists()
    lines = snap.read_text().splitlines()
    assert lines[0].startswith("ts,index,expiry,strike,right,ltp")
    assert len(lines) == 2

    assert (tmp_path / "state.json").exists()


def test_state_survives_restart(tmp_path):
    s = session(tmp_path, BuyOnce())
    s.tick()

    s2 = session(tmp_path, BuyOnce())
    (bp,) = s2.broker.book()
    assert bp.net == 65 and bp.entry_price == 61.0
    assert s2.strategy.done is True


def test_marks_persist_across_restart(tmp_path):
    # Session 1 marks the leg at 60; session 2's feed has NO quote for it.
    # With persisted marks the equity barely moves; with a 0.0 fallback the
    # long would be worth nothing and the tight drawdown cap would trip.
    s = session(tmp_path, BuyOnce())
    s.tick()

    cfg = make_cfg(max_dd=1000.0, costs=ZERO_COSTS)
    s2 = session(tmp_path, NullStrategy(), feed=FakeFeed(chain={}), cfg=cfg)
    s2.tick()
    assert not s2.switch.halted


def test_naked_paper_book_trips_switch(tmp_path):
    s = session(tmp_path, SellNaked(), cfg=make_cfg(max_dd=50000.0, daily=50000.0, costs=ZERO_COSTS))
    s.tick()
    assert s.switch.halted
    assert "naked short" in s.switch.halt_reason
    assert s.alerts


def test_book_cap_trips_switch(tmp_path):
    # A lone long call is defined-risk but its worst case (the full debit,
    # 61 * 65 = Rs 3,965) exceeds a Rs 2,000 per-trade cap.
    cfg = make_cfg(max_dd=50000.0, daily=50000.0, per_trade=2000.0, costs=ZERO_COSTS)
    s = session(tmp_path, BuyOnce(), cfg=cfg)
    s.tick()
    assert s.switch.halted
    assert "per-trade cap" in s.switch.halt_reason


def test_halted_session_flattens_with_escalation_alert(tmp_path):
    s = session(tmp_path, BuyOnce())
    s.tick()
    assert len(s.broker.book()) == 1

    s.switch.trip("manual test halt")
    s.tick()                                    # flatten path: quote present -> fills
    assert s.broker.book() == []


def test_flatten_pages_owner_after_unfilled_attempts(tmp_path):
    s = session(tmp_path, BuyOnce())
    s.tick()
    s.switch.trip("manual test halt")
    s.feed.chain = {}                           # no quotes: flatten can't fill
    for _ in range(3):
        s.tick()
    assert any("unfilled after 3" in a for a in s.alerts)
    assert len(s.broker.book()) == 1            # honestly still open


def test_position_past_expiry_trips_switch(tmp_path):
    s = session(tmp_path, BuyOnce())
    s.tick()

    after = datetime(2026, 7, 15, 10, 0)        # Wednesday after expiry
    s2 = session(tmp_path, NullStrategy(),
                 feed=FakeFeed(chain={}, expiries=[date(2026, 7, 21)]), now=after)
    s2.tick()
    assert s2.switch.halted
    assert "past expiry" in s2.switch.halt_reason


def test_force_squareoff_on_expiry_day(tmp_path):
    s = session(tmp_path, BuyOnce())
    s.tick()

    expiry_afternoon = datetime(2026, 7, 14, 15, 5)
    s2 = session(tmp_path, NullStrategy(), now=expiry_afternoon)
    s2.tick()                                   # infrastructure backstop, no strategy
    assert s2.broker.book() == []
    assert not s2.switch.halted


def test_insufficient_funds_pages_and_stops_tick(tmp_path):
    class DoubleBuyer(NullStrategy):
        def decide(self, ctx):
            leg = OptionLeg("NIFTY", EXPIRY, 25900.0, Right.CALL, Side.BUY)
            return [Order(leg, 61.0), Order(leg, 61.0)]

    cfg = make_cfg(costs=ZERO_COSTS)
    s = session(tmp_path, DoubleBuyer(), cfg=cfg)
    s.broker._cash = 100.0                      # can't afford even one
    s.tick()
    assert any("insufficient funds" in a for a in s.alerts)
    assert s.broker.book() == []


def test_exit_sized_from_held_net_not_lot_config(tmp_path):
    class CloseWithWrongLots(NullStrategy):
        def __init__(self):
            self.tick_no = 0

        def decide(self, ctx):
            self.tick_no += 1
            leg_buy = OptionLeg("NIFTY", EXPIRY, 25900.0, Right.CALL, Side.BUY)
            leg_sell = OptionLeg("NIFTY", EXPIRY, 25900.0, Right.CALL, Side.SELL, lots=2)
            return [Order(leg_buy, 61.0)] if self.tick_no == 1 else [Order(leg_sell, 59.0)]

    s = session(tmp_path, CloseWithWrongLots())
    s.tick()
    assert s.broker.book()[0].net == 65
    s.tick()                                    # closing order sized from net, not lots*lot
    assert s.broker.book() == []


def test_batch_stops_after_first_unfilled_order(tmp_path):
    class LowballThenValid(NullStrategy):
        def decide(self, ctx):
            leg = OptionLeg("NIFTY", EXPIRY, 25900.0, Right.CALL, Side.BUY)
            return [Order(leg, 50.0),   # below market 60 -> not crossed
                    Order(leg, 61.0)]   # must NOT be placed after the failure

    s = session(tmp_path, LowballThenValid())
    s.tick()
    assert s.broker.book() == []        # second order never reached the broker


def test_corrupt_state_refuses_to_start(tmp_path):
    state = tmp_path / "state.json"
    state.write_text('{"broker": {"cash": 96')  # torn write
    with pytest.raises(SystemExit, match="refusing to start"):
        PaperSession(
            cfg=make_cfg(costs=ZERO_COSTS), feed=FakeFeed(), strategy=NullStrategy(),
            data_dir=tmp_path / "live", state_path=state,
            now_fn=lambda: NOW, log=lambda m: None,
        )
    assert (tmp_path / "state.corrupt").exists()


def test_halted_state_survives_restart(tmp_path):
    s = session(tmp_path, CollectOnly())
    s.switch.trip("test")
    s._persist()

    s2 = session(tmp_path, CollectOnly())
    assert s2.switch.halted and s2.switch.halt_reason == "test"


def test_trading_day_and_session_bounds(tmp_path):
    holiday = date(2026, 7, 10)
    s = session(tmp_path, CollectOnly(), cfg=make_cfg(costs=ZERO_COSTS, holidays={holiday}))
    assert s.in_session(datetime(2026, 7, 9, 9, 15))
    assert s.in_session(datetime(2026, 7, 9, 15, 30))
    assert not s.in_session(datetime(2026, 7, 9, 9, 0))
    assert not s.in_session(datetime(2026, 7, 11, 11, 0))   # Saturday
    assert not s.in_session(datetime(2026, 7, 10, 11, 0))   # exchange holiday
    assert not s.trading_day(holiday)


def test_expiry_taken_from_exchange_listing(tmp_path):
    # Tuesday 2026-07-14 is a holiday-shifted week: exchange lists Monday 13th.
    shifted = date(2026, 7, 13)
    feed = FakeFeed(chain={}, expiries=[shifted, date(2026, 7, 21)])
    s = session(tmp_path, CollectOnly(), feed=feed)
    assert s._current_expiry(NOW.date()) == shifted


NEXT_1, NEXT_2, NEXT_3 = date(2026, 7, 21), date(2026, 7, 28), date(2026, 8, 4)


def multi_expiry_feed():
    """Quotes across four listed expiries."""
    chain = {}
    for exp in (EXPIRY, NEXT_1, NEXT_2, NEXT_3):
        chain[("NIFTY", exp, 25900.0, Right.CALL)] = Quote(ltp=60.0, bid=59.5, ask=60.5)
    return FakeFeed(chain=chain, expiries=[EXPIRY, NEXT_1, NEXT_2, NEXT_3])


def test_archives_several_expiries_but_trades_the_front(tmp_path):
    feed = multi_expiry_feed()
    s = session(tmp_path, NullStrategy(), feed=feed)
    s.tick()

    # Three listed expiries archived (default collect_expiries=3), not just one.
    assert feed.requested == [EXPIRY, NEXT_1, NEXT_2]
    snap = (tmp_path / "live" / f"chain_NIFTY_{NOW:%Y%m%d}.csv").read_text().splitlines()
    assert len(snap) == 4                       # header + one quote per expiry
    assert {line.split(",")[2] for line in snap[1:]} == {
        EXPIRY.isoformat(), NEXT_1.isoformat(), NEXT_2.isoformat()
    }


def test_strategy_sees_only_the_front_expiry(tmp_path):
    seen = []

    class Watcher(NullStrategy):
        def decide(self, ctx):
            seen.append(ctx.expiry)
            return []

    s = session(tmp_path, Watcher(), feed=multi_expiry_feed())
    s.tick()
    assert seen == [EXPIRY]


def test_far_expiry_failure_does_not_break_the_tick(tmp_path):
    feed = multi_expiry_feed()
    feed.fail_expiries = {NEXT_2}               # archival-only expiry is broken
    s = session(tmp_path, BuyOnce(), feed=feed)
    s.tick()                                    # must still trade the front expiry
    assert len(s.broker.book()) == 1


def test_front_expiry_failure_still_raises(tmp_path):
    feed = multi_expiry_feed()
    feed.fail_expiries = {EXPIRY}               # the tradeable expiry is broken
    s = session(tmp_path, NullStrategy(), feed=feed)
    with pytest.raises(RuntimeError, match="synthetic feed failure"):
        s.tick()


def test_held_expiry_is_always_fetched(tmp_path):
    """A position beyond the archival window must still be quoted every tick,
    otherwise it could never be marked or closed."""
    far = date(2026, 9, 1)
    chain = {
        ("NIFTY", EXPIRY, 25900.0, Right.CALL): Quote(ltp=60.0, bid=59.5, ask=60.5),
        ("NIFTY", far, 25900.0, Right.CALL): Quote(ltp=60.0, bid=59.5, ask=60.5),
    }
    feed = FakeFeed(chain=chain, expiries=[EXPIRY, NEXT_1, NEXT_2, far])

    # Seed a held far-dated position through the persisted state file.
    seed = session(tmp_path, NullStrategy(), feed=feed)
    seed.broker.set_quote(OptionLeg("NIFTY", far, 25900.0, Right.CALL, Side.BUY), 60.0)
    seed.broker.today = NOW.date()
    seed.broker.place_limit_order(
        OptionLeg("NIFTY", far, 25900.0, Right.CALL, Side.BUY), 60.5, 65
    )
    seed._persist()

    feed.requested.clear()
    s = session(tmp_path, NullStrategy(), feed=feed,
                cfg=make_cfg(max_dd=500000.0, daily=500000.0, per_trade=500000.0,
                             costs=ZERO_COSTS))
    s.tick()
    assert far in feed.requested          # beyond collect_expiries, but held
    assert EXPIRY in feed.requested       # front expiry still archived


class FlakyFeed(FakeFeed):
    """Fails the first N option_chain calls, then behaves."""

    def __init__(self, fail_first=1, **kw):
        super().__init__(**kw)
        self.remaining_failures = fail_first

    def option_chain(self, index, expiry, spot=None):
        if self.remaining_failures:
            self.remaining_failures -= 1
            raise RuntimeError("synthetic transient outage")
        return super().option_chain(index, expiry, spot=spot)


def test_run_pages_on_recovery_after_failures(tmp_path, monkeypatch):
    """run() must tell the owner when the feed comes back, not only when it breaks."""
    import optionsbot.paper.loop as loop_mod

    monkeypatch.setattr(loop_mod.time_mod, "sleep", lambda _s: None)
    # run()'s startup consumes two clock reads before the loop begins.
    clock = {"t": datetime(2026, 7, 9, 15, 25)}

    def advancing_now():
        now = clock["t"]
        clock["t"] = now + timedelta(minutes=1)
        return now

    feed = FlakyFeed(fail_first=1, chain=CHAIN, expiries=[EXPIRY])
    s = PaperSession(
        cfg=make_cfg(costs=ZERO_COSTS), feed=feed, strategy=NullStrategy(),
        data_dir=tmp_path / "live", state_path=tmp_path / "state.json",
        now_fn=advancing_now, log=lambda m: None, poll_seconds=5,
    )
    s.reconnect_after = 99          # keep the failure path from paging first
    s.run()

    assert any("feed recovered after 1 failed tick" in a for a in s.alerts)


def test_expiry_listing_fetched_once_per_tick(tmp_path):
    """front and the archival window must come from one listing snapshot."""
    feed = multi_expiry_feed()
    calls = {"n": 0}
    inner = feed.list_expiries

    def counting(index):
        calls["n"] += 1
        return inner(index)

    feed.list_expiries = counting
    session(tmp_path, NullStrategy(), feed=feed).tick()
    assert calls["n"] == 1


def test_collect_expiries_is_configurable(tmp_path):
    feed = multi_expiry_feed()
    s = session(tmp_path, NullStrategy(), feed=feed)
    s.collect_expiries = 1
    s.tick()
    assert feed.requested == [EXPIRY]        # front only

    feed.requested.clear()
    s.collect_expiries = 4
    s.tick()
    assert feed.requested == [EXPIRY, NEXT_1, NEXT_2, NEXT_3]
