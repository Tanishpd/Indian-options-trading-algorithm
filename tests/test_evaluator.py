"""Shadow evaluation and the forward record.

The harness exists so that future strategy claims rest on data nobody fitted
them to. That only holds if shadows are genuinely isolated, the record survives
a crash, and the report refuses to draw conclusions from too few observations.
Each test below pins one of those.
"""
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from optionsbot.backtest.engine import Order
from optionsbot.config import CostConfig, RiskConfig
from optionsbot.feed.base import Quote
from optionsbot.instruments import OptionLeg, Right, Side
from optionsbot.paper.evaluator import Evaluator
from optionsbot.paper.journal import Entry, Journal, read, strategies
from optionsbot.paper.loop import PaperContext
from optionsbot.strategies import registry

EXPIRY = date(2026, 7, 14)
NOW = datetime(2026, 7, 10, 11, 0)
SC, LC, SP, LP = 25350.0, 25400.0, 24600.0, 24550.0


def chain():
    def q(k, r, ltp, bid, ask):
        return (("NIFTY", EXPIRY, k, r), Quote(ltp=ltp, bid=bid, ask=ask))
    return dict([
        q(SC, Right.CALL, 30.0, 29.0, 31.0), q(LC, Right.CALL, 18.0, 17.0, 19.0),
        q(SP, Right.PUT, 28.0, 27.0, 29.0), q(LP, Right.PUT, 16.0, 15.0, 17.0),
    ])


def ctx(positions=()):
    return PaperContext(
        now=NOW, index="NIFTY", expiry=EXPIRY, spot=25000.0, chain=chain(),
        positions=tuple(positions), cash=100000.0, equity=100000.0,
        lot_size=65, strike_step=50.0,
    )


class Emit:
    """Emits a fixed order batch once, then nothing."""

    def __init__(self, orders, name="emit"):
        self._orders, self._done, self.phase = orders, False, "idle"
        self.name = name

    def decide(self, c):
        if self._done:
            return []
        self._done, self.phase = True, "entering"
        return self._orders

    def to_state(self):
        return {}

    def from_state(self, s):
        pass


class Boom:
    phase = "idle"

    def decide(self, c):
        raise RuntimeError("strategy exploded")

    def to_state(self):
        return {}

    def from_state(self, s):
        pass


def condor_orders():
    def leg(k, r, s):
        return OptionLeg("NIFTY", EXPIRY, k, r, s)
    return [
        Order(leg(LC, Right.CALL, Side.BUY), 19.0),
        Order(leg(LP, Right.PUT, Side.BUY), 17.0),
        Order(leg(SC, Right.CALL, Side.SELL), 29.0),
        Order(leg(SP, Right.PUT, Side.SELL), 27.0),
    ]


def build(tmp_path, specs, cap=2000.0):
    return Evaluator.build(specs, cash=100000.0, costs=CostConfig(),
                           per_trade_max_loss=cap, root=tmp_path, day=NOW.date())


# -- isolation ------------------------------------------------------------

def test_shadows_cannot_see_or_affect_each_other(tmp_path):
    """The whole comparison is void if one shadow's fills leak into another."""
    ev = build(tmp_path, [("a", Emit(condor_orders())), ("b", Emit([]))])
    ev.tick(ctx())
    ev.close()
    a, b = ev.shadows
    assert len(a.broker.book()) == 4        # a traded
    assert b.broker.book() == []            # b did not
    assert b.broker.margin_available() == b.start_cash   # and paid nothing


def test_one_strategy_crashing_halts_only_itself(tmp_path):
    """A session running five candidates must not be lost to one bad strategy."""
    ev = build(tmp_path, [("boom", Boom()), ("ok", Emit(condor_orders()))])
    ev.tick(ctx())
    ev.close()
    boom, ok = ev.shadows
    assert boom.halted.startswith("error")
    assert not ok.halted
    assert len(ok.broker.book()) == 4       # the healthy one still traded


# -- the invariants the real engine enforces ------------------------------

def test_shadow_refuses_a_naked_short(tmp_path):
    """A shadow allowed to do what the live engine forbids is evaluating a
    strategy that could never be run."""
    naked = [Order(OptionLeg("NIFTY", EXPIRY, SC, Right.CALL, Side.SELL), 29.0)]
    ev = build(tmp_path, [("naked", Emit(naked))])
    ev.tick(ctx())
    ev.close()
    sh = ev.shadows[0]
    assert sh.broker.book() == []
    assert any("naked" in m for m in sh.log)   # batch refused whole


def test_shadow_refuses_a_book_over_the_per_trade_cap(tmp_path):
    """Judged on the completed batch, so a legal structure is not refused for
    its intermediate states — and an illegal one is refused whole."""
    ev = build(tmp_path, [("big", Emit(condor_orders()))], cap=100.0)
    ev.tick(ctx())
    ev.close()
    sh = ev.shadows[0]
    assert sh.broker.book() == []
    assert any("cap" in m for m in sh.log)


def test_equity_marks_where_the_exit_would_trade(tmp_path):
    """Marking at LTP overstates a book you must cross the spread to leave —
    the same error that made the live stop fire on unobtainable prices."""
    ev = build(tmp_path, [("a", Emit(condor_orders()))])
    ev.tick(ctx())
    sh = ev.shadows[0]
    marked = sh.equity(chain())
    # shorts marked at ask (worse), longs at bid (worse) than LTP in both cases
    ltp_marked = sh.broker.margin_available() + sum(chain()[p.leg.key].ltp * p.net
                                      for p in sh.broker.book())
    assert marked < ltp_marked
    ev.close()


# -- the forward record ---------------------------------------------------

def test_journal_survives_a_truncated_final_line(tmp_path):
    """A hard kill mid-write must cost one tick, not the whole record."""
    j = Journal(tmp_path, "s", NOW.date())
    for i in range(3):
        j.append(Entry(ts=NOW, strategy="s", index="NIFTY", expiry=EXPIRY,
                       spot=25000.0 + i, phase="holding", equity=100000.0,
                       cash=100000.0, realised_costs=0.0, positions=0))
    j.close()
    with open(j.path, "a") as fh:
        fh.write('{"ts": "2026-07-10T11:00:00", "strat')   # killed mid-line
    rows = list(read(tmp_path, "s"))
    assert len(rows) == 3                      # the good lines still read


def test_journal_is_append_only_across_sessions(tmp_path):
    """History must not be rewritten by a restart."""
    for spot in (25000.0, 25100.0):
        with Journal(tmp_path, "s", NOW.date()) as j:
            j.append(Entry(ts=NOW, strategy="s", index="NIFTY", expiry=EXPIRY,
                           spot=spot, phase="", equity=1.0, cash=1.0,
                           realised_costs=0.0, positions=0))
    rows = list(read(tmp_path, "s"))
    assert [r["spot"] for r in rows] == [25000.0, 25100.0]


def test_evaluator_records_every_tick_including_refusals(tmp_path):
    ev = build(tmp_path, [("a", Emit(condor_orders()))], cap=100.0)
    ev.tick(ctx())
    ev.close()
    rows = list(read(tmp_path, "a"))
    assert len(rows) == 1
    assert rows[0]["orders"] and not rows[0]["fills"]      # tried, refused
    assert strategies(tmp_path) == ["a"]


# -- the registry ---------------------------------------------------------

def test_registry_lists_and_builds():
    names = registry.available()
    assert "reference-condor" in names and "tail-condor" in names
    s = registry.build("tail-condor", RiskConfig())
    assert s.params.offset_pct == pytest.approx(0.026)


def test_registry_refuses_an_unregistered_name():
    """A strategy that is not registered cannot be run — the correct default
    for something that places orders."""
    with pytest.raises(KeyError) as e:
        registry.build("does-not-exist", RiskConfig())
    assert "available:" in str(e.value)


# -- the report's refusal to over-claim -----------------------------------

def test_report_refuses_to_assess_a_short_record(tmp_path, capsys):
    from optionsbot.research.forward_report import report_one

    entries, eq = [], 100000.0
    for i in range(6):                              # 3 completed cycles
        held = i % 2 == 0
        eq += 50 if held else 0
        entries.append({"ts": datetime(2026, 7, 10, 10, i).isoformat(),
                        "strategy": "s", "expiry": EXPIRY.isoformat(),
                        "equity": eq, "realised_costs": 10.0 * i,
                        "positions": 4 if held else 0, "note": ""})
    report_one("s", entries, capital=100000.0)
    out = capsys.readouterr().out
    assert "NOT ASSESSABLE" in out
    assert "need" in out


def test_a_legal_condor_is_not_refused_for_its_intermediate_states(tmp_path):
    """Regression. Judging orders one at a time refused every multi-leg
    structure: one wing alone breaches the cap, and the shorts before the wings
    are naked. Only the completed batch is admissible, which is why the live
    strategy emits all four legs in a single tick (learned live 2026-07-15)."""
    ev = build(tmp_path, [("condor", Emit(condor_orders()))], cap=2000.0)
    ev.tick(ctx())
    ev.close()
    sh = ev.shadows[0]
    assert len(sh.broker.book()) == 4
    assert not [m for m in sh.log if "refused" in m]


def test_session_shadow_failure_cannot_stop_the_live_strategy():
    """A shadow is an observer. If evaluation breaks, the live session must
    carry on — the whole point is that adding candidates costs nothing."""
    from optionsbot.paper.loop import PaperSession
    import inspect

    src = inspect.getsource(PaperSession.tick)
    # the evaluator call is guarded and precedes live order placement
    assert "self.evaluator.tick(ctx)" in src
    guard = src.index("self.evaluator.tick(ctx)")
    assert "try:" in src[max(0, guard - 200):guard]
    assert src.index("self.strategy.decide(ctx)") > guard
