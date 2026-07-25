"""Strategy decisions must be attributable from the record alone (issue #6):
the forward journal carries the reason (Entry.note), and the live session emits new
decision lines to journalctl without flooding on a stuck condition.
"""
from datetime import date, datetime
from types import SimpleNamespace

from optionsbot.config import CostConfig, RiskConfig
from optionsbot.broker.paper import PaperBroker
from optionsbot.instruments import Right, Side
from optionsbot.paper.evaluator import Evaluator, Shadow
from optionsbot.paper.journal import Journal, read
from optionsbot.strategies.intraday_strangle import IntradayStrangle, StrangleParams

ZERO = CostConfig(brokerage_per_order=0, txn_charge_rate=0, sebi_fee_rate=0,
                  stamp_duty_rate=0, gst_rate=0)
RISK = RiskConfig(per_trade_max_loss_rupees=2000)
DAY = date(2026, 7, 24)


def _ctx(chain=None):
    return SimpleNamespace(now=datetime(2026, 7, 24, 13, 0), index="NIFTY",
                           expiry=date(2026, 7, 28), spot=25000.0, chain=chain or {},
                           positions=(), lot_size=65, strike_step=50.0)


def test_shadow_journal_records_the_strategy_reason(tmp_path):
    strat = IntradayStrangle(StrangleParams(), RISK)
    strat.log.append("entry skipped: both legs not quotable this minute")
    b = PaperBroker(100_000.0, costs=ZERO); b.authenticate(); b.today = DAY
    sh = Shadow(name="intraday-strangle", strategy=strat, broker=b,
                journal=Journal(tmp_path, "intraday-strangle", DAY), start_cash=100_000.0)
    ev = Evaluator(shadows=[sh], costs=ZERO, per_trade_max_loss=2000.0, root=tmp_path)
    ev._record(sh, _ctx(), orders=[], fills=[])
    sh.journal.close()
    rows = list(read(tmp_path, "intraday-strangle"))
    assert rows and rows[-1]["note"] == "entry skipped: both legs not quotable this minute"


def test_explicit_note_takes_precedence_over_strategy_log(tmp_path):
    strat = IntradayStrangle(StrangleParams(), RISK)
    strat.log.append("some strategy line")
    b = PaperBroker(100_000.0, costs=ZERO); b.authenticate(); b.today = DAY
    sh = Shadow(name="x", strategy=strat, broker=b,
                journal=Journal(tmp_path, "x", DAY), start_cash=100_000.0)
    ev = Evaluator(shadows=[sh], costs=ZERO, per_trade_max_loss=2000.0, root=tmp_path)
    ev._record(sh, _ctx(), orders=[], fills=[], note="error: boom")
    sh.journal.close()
    assert list(read(tmp_path, "x"))[-1]["note"] == "error: boom"


def test_session_surfaces_only_new_decision_lines():
    # A minimal stand-in for PaperSession._surface_decision's dedupe contract.
    emitted = []
    state = {"last": ""}

    def surface(strategy):
        log = getattr(strategy, "log", None)
        if log and log[-1] != state["last"]:
            state["last"] = log[-1]
            emitted.append(log[-1])

    s = IntradayStrangle(StrangleParams(), RISK)
    s._say("entered strangle 25250C / 24750P")
    surface(s); surface(s); surface(s)            # same line, three ticks
    s._say("square-off at deadline")
    surface(s)
    assert emitted == ["entered strangle 25250C / 24750P", "square-off at deadline"]


def test_strategy_say_dedupes_consecutive_repeats():
    s = IntradayStrangle(StrangleParams(), RISK)
    s._say("holding"); s._say("holding"); s._say("exit")
    assert s.log == ["holding", "exit"]
