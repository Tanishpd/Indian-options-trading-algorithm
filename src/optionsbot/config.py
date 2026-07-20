"""Typed configuration loaded from TOML. Every tunable number lives in config.

Unknown keys in any section raise: a typo'd key silently reverting to a
default is how a 5-lakh account gets sized like a 1-lakh one.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path
from typing import Any, Mapping

# NIFTY lot-size history within the supported data window. Effective dates are
# approximations of the contract-revision calendar — verify against NSE
# circulars (NSE/FAOP/64625 for 25->75, NSE/FAOP/70616 for 75->65) before
# trusting backtests that span a changeover.
DEFAULT_NIFTY_LOTS: tuple[tuple[date, int], ...] = (
    (date(2024, 11, 1), 25),
    (date(2025, 1, 2), 75),
    (date(2026, 1, 1), 65),
)

LotSchedule = tuple[tuple[date, int], ...]

MIN_SCHEDULE_START = date(2024, 11, 1)  # mirrors costs.MIN_SUPPORTED_DATE


@dataclass(frozen=True)
class CostConfig:
    brokerage_per_order: float = 20.0
    # Unverified by research — confirm against broker contract note (docs/05).
    txn_charge_rate: float = 0.0003503
    sebi_fee_rate: float = 0.000001
    stamp_duty_rate: float = 0.00003
    gst_rate: float = 0.18


@dataclass(frozen=True)
class RiskConfig:
    max_drawdown_rupees: float = 5000.0
    daily_loss_limit_rupees: float = 2000.0
    per_trade_max_loss_rupees: float = 2000.0


@dataclass(frozen=True)
class FillConfig:
    protection_band_pct: float = 0.05

    def __post_init__(self) -> None:
        if not 0.0 <= self.protection_band_pct < 1.0:
            raise ValueError(
                f"protection_band_pct must be in [0, 1); got {self.protection_band_pct} "
                "(a band of 0.05 means 5%)"
            )


@dataclass(frozen=True)
class MarketConfig:
    holidays: frozenset[date] = frozenset()
    lot_schedules: Mapping[str, LotSchedule] = field(
        default_factory=lambda: {"NIFTY": DEFAULT_NIFTY_LOTS}
    )
    strike_steps: Mapping[str, float] = field(
        default_factory=lambda: {"NIFTY": 50.0, "SENSEX": 100.0}
    )

    def strike_step(self, index: str) -> float:
        try:
            return self.strike_steps[index]
        except KeyError:
            raise ValueError(
                f"no strike step configured for {index!r} — add it to [market.strike_steps]"
            ) from None

    def lot_size(self, index: str, on: date) -> int:
        """Lot size for `index` in force on date `on` — lot sizes are date-dependent."""
        schedule = self.lot_schedules.get(index)
        if not schedule:
            raise ValueError(
                f"no lot-size schedule configured for {index!r} — add it to "
                "[market.lot_sizes] once confirmed from exchange circulars"
            )
        size: int | None = None
        for effective, lots in schedule:
            if effective <= on:
                size = lots
        if size is None:
            raise ValueError(f"no lot size for {index!r} in force on {on} (schedule starts later)")
        return size


@dataclass(frozen=True)
class AppConfig:
    starting_capital: float = 100000.0
    costs: CostConfig = field(default_factory=CostConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    fills: FillConfig = field(default_factory=FillConfig)
    market: MarketConfig = field(default_factory=MarketConfig)


def _coerce_date(value: Any) -> date:
    # tomllib parses unquoted TOML dates natively; quoted strings arrive as str.
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _strict_section(raw: Mapping[str, Any], name: str, cls: type) -> Any:
    data = dict(raw.get(name, {}))
    allowed = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"unknown key(s) {unknown} in [{name}] — allowed: {sorted(allowed)}")
    return cls(**data)


def _parse_lot_schedules(raw: Mapping[str, Any]) -> dict[str, LotSchedule]:
    schedules: dict[str, LotSchedule] = {}
    for index, spec in raw.items():
        if isinstance(spec, int):
            schedules[index] = ((MIN_SCHEDULE_START, spec),)
        else:
            entries = sorted(
                (_coerce_date(e["from"]), int(e["size"])) for e in spec
            )
            if not entries:
                raise ValueError(f"empty lot-size schedule for {index!r}")
            schedules[index] = tuple(entries)
    return schedules


def load_config(path: str | Path) -> AppConfig:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    capital = dict(raw.get("capital", {}))
    unknown = sorted(set(capital) - {"starting_rupees"})
    if unknown:
        raise ValueError(f"unknown key(s) {unknown} in [capital] — allowed: ['starting_rupees']")

    market_raw = dict(raw.get("market", {}))
    unknown = sorted(set(market_raw) - {"holidays", "lot_sizes", "strike_steps"})
    if unknown:
        raise ValueError(
            f"unknown key(s) {unknown} in [market] — allowed: ['holidays', 'lot_sizes', 'strike_steps']"
        )

    market_kwargs: dict[str, Any] = {}
    if "holidays" in market_raw:
        market_kwargs["holidays"] = frozenset(_coerce_date(d) for d in market_raw["holidays"])
    if "lot_sizes" in market_raw:
        market_kwargs["lot_schedules"] = _parse_lot_schedules(market_raw["lot_sizes"])
    if "strike_steps" in market_raw:
        market_kwargs["strike_steps"] = {
            k: float(v) for k, v in market_raw["strike_steps"].items()
        }

    return AppConfig(
        starting_capital=capital.get("starting_rupees", AppConfig.starting_capital),
        costs=_strict_section(raw, "costs", CostConfig),
        risk=_strict_section(raw, "risk", RiskConfig),
        fills=_strict_section(raw, "fills", FillConfig),
        market=MarketConfig(**market_kwargs),
    )
