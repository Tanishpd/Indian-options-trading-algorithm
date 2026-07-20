"""Cost engine tests. Expected values are hand-computed literals — never
derived from the code under test (gate 2a discipline, docs/06)."""
from datetime import date

import pytest

from optionsbot.config import CostConfig
from optionsbot.costs import Fill, MIN_SUPPORTED_DATE, fill_costs, stt_rate_on
from optionsbot.instruments import Side

CFG = CostConfig()  # brokerage 20, txn 0.0003503, sebi 1e-6, stamp 3e-5, gst 0.18


def test_stt_rate_boundaries():
    assert stt_rate_on(date(2026, 3, 31)) == 0.0010
    assert stt_rate_on(date(2026, 4, 1)) == 0.0015
    assert stt_rate_on(date(2024, 11, 1)) == 0.0010


def test_pre_nov_2024_dates_are_banned():
    with pytest.raises(ValueError, match="pre-Nov-2024"):
        stt_rate_on(date(2024, 10, 31))
    with pytest.raises(ValueError):
        fill_costs(
            Fill(day=date(2024, 6, 1), side=Side.SELL, premium_per_share=50, shares=65), CFG
        )


def test_buy_side_fills_also_banned_pre_nov_2024():
    # The ban must hold on every fill, not just sells (STT's own code path).
    with pytest.raises(ValueError, match="pre-Nov-2024"):
        Fill(day=date(2024, 5, 1), side=Side.BUY, premium_per_share=50, shares=65)


def test_fill_coerces_string_side():
    f = Fill(day=date(2026, 7, 7), side="SELL", premium_per_share=50, shares=65)
    assert f.side is Side.SELL
    c = fill_costs(f, CFG)
    assert c.stt > 0.0  # a string side must not silently skip STT


def test_sell_fill_full_breakdown_hand_computed():
    # SELL 65 shares @ Rs 60 on 2026-07-07 (0.15% STT regime).
    # turnover = 3900
    # stt   = 3900 * 0.0015    = 5.85
    # txn   = 3900 * 0.0003503 = 1.36617
    # sebi  = 3900 * 0.000001  = 0.0039
    # gst   = 0.18 * (20 + 1.36617 + 0.0039) = 3.8466126
    # stamp = 0 (sell side)
    c = fill_costs(
        Fill(day=date(2026, 7, 7), side=Side.SELL, premium_per_share=60.0, shares=65), CFG
    )
    assert c.brokerage == 20.0
    assert c.stt == pytest.approx(5.85, abs=1e-9)
    assert c.txn == pytest.approx(1.36617, abs=1e-9)
    assert c.sebi == pytest.approx(0.0039, abs=1e-9)
    assert c.gst == pytest.approx(3.8466126, abs=1e-9)
    assert c.stamp == 0.0
    assert c.total == pytest.approx(31.0666826, abs=1e-9)


def test_buy_fill_full_breakdown_hand_computed():
    # BUY 65 shares @ Rs 25 on 2026-07-07.
    # turnover = 1625
    # stt   = 0 (buy side)
    # txn   = 1625 * 0.0003503 = 0.5692375
    # sebi  = 1625 * 0.000001  = 0.001625
    # gst   = 0.18 * (20 + 0.5692375 + 0.001625) = 3.70275525
    # stamp = 1625 * 0.00003   = 0.04875
    c = fill_costs(
        Fill(day=date(2026, 7, 7), side=Side.BUY, premium_per_share=25.0, shares=65), CFG
    )
    assert c.stt == 0.0
    assert c.txn == pytest.approx(0.5692375, abs=1e-9)
    assert c.sebi == pytest.approx(0.001625, abs=1e-9)
    assert c.gst == pytest.approx(3.70275525, abs=1e-9)
    assert c.stamp == pytest.approx(0.04875, abs=1e-9)
    assert c.total == pytest.approx(24.32236775, abs=1e-9)


def test_stt_regime_selected_by_fill_date():
    before = fill_costs(
        Fill(day=date(2026, 3, 31), side=Side.SELL, premium_per_share=100.0, shares=65), CFG
    )
    after = fill_costs(
        Fill(day=date(2026, 4, 1), side=Side.SELL, premium_per_share=100.0, shares=65), CFG
    )
    assert before.stt == pytest.approx(6.5)   # 6500 * 0.0010
    assert after.stt == pytest.approx(9.75)   # 6500 * 0.0015


def test_min_supported_date_constant():
    assert MIN_SUPPORTED_DATE == date(2024, 11, 1)
