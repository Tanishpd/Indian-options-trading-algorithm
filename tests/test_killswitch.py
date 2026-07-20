from datetime import date

import pytest

from optionsbot.config import RiskConfig
from optionsbot.risk.killswitch import KillSwitch

RISK = RiskConfig(max_drawdown_rupees=5000.0, daily_loss_limit_rupees=2000.0)
D1, D2, D3 = date(2026, 7, 7), date(2026, 7, 8), date(2026, 7, 9)


def test_trips_on_max_drawdown():
    alerts = []
    ks = KillSwitch(RISK, alert=alerts.append)
    ks.update(D1, 100000)
    ks.update(D2, 101000)   # new peak
    ks.update(D3, 95900)    # dd 5100 >= 5000
    assert ks.halted
    assert "max drawdown" in ks.halt_reason
    assert len(alerts) == 1


def test_trips_on_daily_loss():
    ks = KillSwitch(RiskConfig(max_drawdown_rupees=50000.0, daily_loss_limit_rupees=2000.0))
    ks.update(D1, 100000)
    ks.update(D2, 99500)
    ks.update(D3, 97400)    # day loss vs prev close 2100 >= 2000, dd 2600 < 50000
    assert ks.halted
    assert "daily loss" in ks.halt_reason


def test_stays_armed_inside_limits():
    ks = KillSwitch(RISK)
    ks.update(D1, 100000)
    ks.update(D2, 98500)    # dd 1500, day loss 1500
    assert not ks.halted


def test_alert_fires_exactly_once():
    alerts = []
    ks = KillSwitch(RISK, alert=alerts.append)
    ks.update(D1, 100000)
    ks.update(D2, 90000)
    ks.update(D3, 80000)    # already halted; ignored
    assert len(alerts) == 1


def test_seeded_switch_catches_day_one_loss():
    alerts = []
    ks = KillSwitch(RISK, alert=alerts.append, start_equity=100000.0)
    ks.update(D1, 92850.0)  # first-ever observation is already a breach
    assert ks.halted
    assert "max drawdown" in ks.halt_reason
    assert len(alerts) == 1


def test_seeded_switch_daily_limit_on_day_one():
    ks = KillSwitch(
        RiskConfig(max_drawdown_rupees=50000.0, daily_loss_limit_rupees=2000.0),
        start_equity=100000.0,
    )
    ks.update(D1, 97900.0)  # loss 2100 vs start
    assert ks.halted
    assert "daily loss" in ks.halt_reason


def test_public_trip_and_single_alert():
    alerts = []
    ks = KillSwitch(RISK, alert=alerts.append)
    ks.trip("naked book")
    ks.trip("again")  # already halted; ignored
    assert ks.halted and ks.halt_reason == "naked book"
    assert alerts == ["naked book"]


def test_snapshot_restore_roundtrip():
    ks = KillSwitch(RISK, start_equity=100000.0)
    ks.update(D1, 99000.0)
    ks.update(D2, 90000.0)   # trips
    assert ks.halted

    ks2 = KillSwitch(RISK)
    ks2.restore(ks.snapshot())
    assert ks2.halted and "max drawdown" in ks2.halt_reason
    ks2.update(D3, 100000.0)  # still halted; updates ignored
    assert ks2.halted


def test_rearm_requires_operator():
    ks = KillSwitch(RISK)
    ks.update(D1, 100000)
    ks.update(D2, 90000)
    assert ks.halted
    with pytest.raises(ValueError, match="operator"):
        ks.rearm("")
    ks.rearm("mohit", reset_peak=True)
    assert not ks.halted
    ks.update(D3, 89000)    # fresh peak baseline after reset
    assert not ks.halted
