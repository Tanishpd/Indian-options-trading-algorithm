"""ML-gated intraday strangle. Three properties matter, and none of them is accuracy:

1. The stdlib inference must agree with the library that trained the model — a silent
   drift there would forward-test a different model than the one measured offline.
2. The gate must actually gate (skip when the score is below threshold).
3. An untrained gate must NOT quietly degrade into "always trade" — with too little
   history, or no model file, it must sit out.
"""
import json
from datetime import date, datetime, time
from types import SimpleNamespace

import pytest

from optionsbot.config import RiskConfig
from optionsbot.instruments import OptionLeg, Right, Side
from optionsbot.strategies.ml_gated_strangle import (
    MlGateParams, MlGatedStrangle, build_features, load_model, score)

IDX, EXP, STEP = "NIFTY", date(2026, 7, 28), 50.0
RISK = RiskConfig(per_trade_max_loss_rupees=2000)

MODEL = {
    "kind": "logistic",
    "features": ["a", "b"],
    "mean": [0.0, 10.0], "std": [1.0, 2.0],
    "coef": [1.5, -0.5], "intercept": 0.25,
    "threshold": 0.5,
}


def q(ltp, bid=None, ask=None):
    return SimpleNamespace(ltp=ltp, bid=bid, ask=ask)


def ctx(now, spot, chain, positions=()):
    return SimpleNamespace(now=now, index=IDX, expiry=EXP, spot=spot, chain=chain,
                           positions=list(positions), lot_size=65, strike_step=STEP)


def full_chain(ts, spot=25000.0):
    return {(IDX, EXP, 25250.0, Right.CALL): q(40, bid=39, ask=41),
            (IDX, EXP, 24750.0, Right.PUT): q(38, bid=37, ask=39)}


def hist(n, start=25000.0):
    """n days of flat-ish spot history, oldest first."""
    return [{"date": f"2026-06-{d+1:02d}", "entry_spot": start + d, "exit_spot": start + d}
            for d in range(n)]


def test_score_matches_a_hand_computed_logistic():
    import math
    # z = 0.25 + 1.5*((2-0)/1) + (-0.5)*((14-10)/2) = 0.25 + 3.0 - 1.0 = 2.25
    expected = 1 / (1 + math.exp(-2.25))
    assert score(MODEL, {"a": 2.0, "b": 14.0}) == pytest.approx(expected)


def test_score_falls_back_to_the_training_mean_for_a_missing_feature():
    # 'b' missing -> contributes 0; z = 0.25 + 1.5*2 = 3.25
    import math
    assert score(MODEL, {"a": 2.0}) == pytest.approx(1 / (1 + math.exp(-3.25)))


def test_build_features_needs_enough_history():
    assert build_features(hist(5), 25000.0, 80.0, 3, 1) is None      # too short
    f = build_features(hist(25), 25100.0, 80.0, 3, 1)
    assert f is not None
    assert set(f) >= {"rvol5", "trend5", "gap", "credit", "dte", "dow"}
    assert f["credit"] == 80.0 and f["dte"] == 3.0


def test_warmup_blocks_trading_and_records_history(tmp_path):
    p = MlGateParams(model_path=tmp_path / "m.json",
                     history_path=tmp_path / "h.json", offset_pct=0.01)
    (tmp_path / "m.json").write_text(json.dumps(MODEL))
    s = MlGatedStrangle(params=p, risk=RISK)
    out = s.decide(ctx(datetime(2026, 7, 24, 9, 25), 25000.0, full_chain(None)))
    assert out == []                                   # no history yet -> must not trade
    assert s.phase == "skipped"
    assert json.loads((tmp_path / "h.json").read_text())   # but it recorded the day


def test_missing_model_file_means_no_trading(tmp_path):
    p = MlGateParams(model_path=tmp_path / "absent.json", history_path=tmp_path / "h.json")
    s = MlGatedStrangle(params=p, risk=RISK)
    assert s.decide(ctx(datetime(2026, 7, 24, 9, 25), 25000.0, full_chain(None))) == []
    assert s._model is None


def test_gate_skips_when_score_below_threshold(tmp_path):
    # coefficients zero, intercept very negative -> p ~ 0 -> always skip
    m = dict(MODEL, features=["rvol5"], mean=[0.0], std=[1.0], coef=[0.0], intercept=-20.0)
    p = MlGateParams(model_path=tmp_path / "m.json", history_path=tmp_path / "h.json")
    (tmp_path / "m.json").write_text(json.dumps(m))
    (tmp_path / "h.json").write_text(json.dumps(hist(25)))
    s = MlGatedStrangle(params=p, risk=RISK)
    assert s.decide(ctx(datetime(2026, 7, 24, 9, 25), 25000.0, full_chain(None))) == []
    assert s.phase == "skipped"


def test_gate_trades_when_score_above_threshold(tmp_path):
    m = dict(MODEL, features=["rvol5"], mean=[0.0], std=[1.0], coef=[0.0], intercept=20.0)
    p = MlGateParams(model_path=tmp_path / "m.json", history_path=tmp_path / "h.json")
    (tmp_path / "m.json").write_text(json.dumps(m))
    (tmp_path / "h.json").write_text(json.dumps(hist(25)))
    s = MlGatedStrangle(params=p, risk=RISK)
    orders = s.decide(ctx(datetime(2026, 7, 24, 9, 25), 25000.0, full_chain(None)))
    assert len(orders) == 2
    assert all(o.leg.side is Side.SELL for o in orders)   # naked, both sold
    assert s.phase == "holding"


def test_squares_off_same_day(tmp_path):
    m = dict(MODEL, features=["rvol5"], mean=[0.0], std=[1.0], coef=[0.0], intercept=20.0)
    p = MlGateParams(model_path=tmp_path / "m.json", history_path=tmp_path / "h.json")
    (tmp_path / "m.json").write_text(json.dumps(m))
    (tmp_path / "h.json").write_text(json.dumps(hist(25)))
    s = MlGatedStrangle(params=p, risk=RISK)
    s.phase = "holding"
    book = [SimpleNamespace(leg=OptionLeg(IDX, EXP, 25250.0, Right.CALL, Side.SELL),
                            net=-65, entry_price=40.0),
            SimpleNamespace(leg=OptionLeg(IDX, EXP, 24750.0, Right.PUT, Side.SELL),
                            net=-65, entry_price=38.0)]
    exits = s.decide(ctx(datetime(2026, 7, 24, 15, 25), 25000.0, full_chain(None), book))
    assert len(exits) == 2
    assert all(o.leg.side is Side.BUY for o in exits)     # buying the shorts back
