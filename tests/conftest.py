"""Shared test builders."""
from datetime import date

import pytest

from optionsbot.backtest.data import QuoteBar
from optionsbot.config import (
    AppConfig, CostConfig, FillConfig, MarketConfig, RiskConfig,
)
from optionsbot.instruments import OptionLeg, Right, Side

EXPIRY = date(2026, 7, 14)
D1, D2, D3, D4 = (date(2026, 7, 7), date(2026, 7, 8), date(2026, 7, 9), date(2026, 7, 10))

# Brokerage + STT only: keeps hand arithmetic transparent (gate 2a).
BARE_COSTS = CostConfig(
    brokerage_per_order=20.0, txn_charge_rate=0.0, sebi_fee_rate=0.0,
    stamp_duty_rate=0.0, gst_rate=0.0,
)
ZERO_COSTS = CostConfig(
    brokerage_per_order=0.0, txn_charge_rate=0.0, sebi_fee_rate=0.0,
    stamp_duty_rate=0.0, gst_rate=0.0,
)


def flat_bar(day, strike, right, price, expiry=EXPIRY, index="NIFTY"):
    return QuoteBar(day=day, index=index, expiry=expiry, strike=strike,
                    right=right, open=price, high=price, low=price, close=price)


def ohlc_bar(day, strike, right, o, h, l, c, expiry=EXPIRY, index="NIFTY"):
    return QuoteBar(day=day, index=index, expiry=expiry, strike=strike,
                    right=right, open=o, high=h, low=l, close=c)


def leg(strike, right, side, expiry=EXPIRY, index="NIFTY", lots=1):
    return OptionLeg(index, expiry, strike, right, side, lots)


def make_cfg(
    max_dd=5000.0, daily=2000.0, per_trade=50000.0, band=0.0, costs=BARE_COSTS,
    holidays=frozenset(),
):
    return AppConfig(
        starting_capital=100000.0,
        costs=costs,
        risk=RiskConfig(
            max_drawdown_rupees=max_dd,
            daily_loss_limit_rupees=daily,
            per_trade_max_loss_rupees=per_trade,
        ),
        fills=FillConfig(protection_band_pct=band),
        market=MarketConfig(
            holidays=frozenset(holidays),
            lot_schedules={"NIFTY": ((date(2024, 11, 1), 65),)},
        ),
    )
