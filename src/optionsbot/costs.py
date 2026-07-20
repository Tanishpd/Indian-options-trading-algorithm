"""Cost engine — implements docs/05 exactly.

STT rates are dated, SEBI/NSE-verified constants and deliberately not
configurable. All other rates come from CostConfig and must be verified
against the broker's contract note.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .config import CostConfig
from .instruments import Side

# docs/06 rule: pre-Nov-2024 market data is unrepresentative (lot sizes,
# weekly-expiry universe) and must not be costed. Enforced on every Fill
# regardless of side, and again at the data loader and engine day loop.
MIN_SUPPORTED_DATE = date(2024, 11, 1)

STT_CHANGE = date(2026, 4, 1)
STT_RATE_BEFORE = 0.0010  # post-Oct-2024 rate, verified
STT_RATE_AFTER = 0.0015   # Budget 2026 rate from Apr 1, 2026, verified


def ensure_supported_date(day: date) -> None:
    if day < MIN_SUPPORTED_DATE:
        raise ValueError(
            f"{day} is before {MIN_SUPPORTED_DATE}: pre-Nov-2024 data is banned "
            "from backtests (docs/06-backtesting-and-validation.md)"
        )


def stt_rate_on(day: date) -> float:
    ensure_supported_date(day)
    return STT_RATE_AFTER if day >= STT_CHANGE else STT_RATE_BEFORE


@dataclass(frozen=True)
class Fill:
    day: date
    side: Side
    premium_per_share: float
    shares: int  # lots * lot_size

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", Side(self.side))
        ensure_supported_date(self.day)

    @property
    def turnover(self) -> float:
        return self.premium_per_share * self.shares


@dataclass(frozen=True)
class CostBreakdown:
    brokerage: float
    stt: float
    txn: float
    sebi: float
    gst: float
    stamp: float

    @property
    def total(self) -> float:
        return self.brokerage + self.stt + self.txn + self.sebi + self.gst + self.stamp


def fill_costs(fill: Fill, cfg: CostConfig) -> CostBreakdown:
    """All charges for one executed order (one leg, one direction)."""
    turnover = fill.turnover
    stt = turnover * stt_rate_on(fill.day) if fill.side is Side.SELL else 0.0
    txn = turnover * cfg.txn_charge_rate
    sebi = turnover * cfg.sebi_fee_rate
    gst = cfg.gst_rate * (cfg.brokerage_per_order + txn + sebi)
    stamp = turnover * cfg.stamp_duty_rate if fill.side is Side.BUY else 0.0
    return CostBreakdown(
        brokerage=cfg.brokerage_per_order, stt=stt, txn=txn, sebi=sebi, gst=gst, stamp=stamp
    )
