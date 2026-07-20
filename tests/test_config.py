from datetime import date
from pathlib import Path

import pytest

from optionsbot.config import FillConfig, load_config

DEFAULT_TOML = Path(__file__).parent.parent / "config" / "default.toml"


def test_default_config_loads():
    cfg = load_config(DEFAULT_TOML)
    assert cfg.starting_capital == 100000.0
    assert cfg.costs.brokerage_per_order == 20.0
    assert cfg.risk.max_drawdown_rupees == 5000.0
    assert cfg.risk.per_trade_max_loss_rupees == 2000.0
    assert cfg.fills.protection_band_pct == 0.05
    assert cfg.market.holidays == frozenset()


def test_lot_size_is_date_dependent():
    cfg = load_config(DEFAULT_TOML)
    assert cfg.market.lot_size("NIFTY", date(2024, 12, 1)) == 25
    assert cfg.market.lot_size("NIFTY", date(2025, 6, 1)) == 75
    assert cfg.market.lot_size("NIFTY", date(2026, 7, 1)) == 65
    with pytest.raises(ValueError, match="no lot-size schedule"):
        cfg.market.lot_size("SENSEX", date(2026, 7, 1))


def test_unknown_keys_raise(tmp_path):
    p = tmp_path / "typo.toml"
    p.write_text("[capital]\nstarting_rupess = 500000.0\n")  # typo'd key
    with pytest.raises(ValueError, match="starting_rupess"):
        load_config(p)

    p2 = tmp_path / "typo2.toml"
    p2.write_text("[risk]\nmax_drawdown_rupee = 5000.0\n")
    with pytest.raises(ValueError, match="max_drawdown_rupee"):
        load_config(p2)


def test_native_and_string_toml_dates_both_accepted(tmp_path):
    p = tmp_path / "holidays.toml"
    p.write_text('[market]\nholidays = [2026-10-02, "2026-11-09"]\n')
    cfg = load_config(p)
    assert cfg.market.holidays == frozenset({date(2026, 10, 2), date(2026, 11, 9)})


def test_int_lot_size_becomes_constant_schedule(tmp_path):
    p = tmp_path / "lots.toml"
    p.write_text("[market.lot_sizes]\nNIFTY = 65\n")
    cfg = load_config(p)
    assert cfg.market.lot_size("NIFTY", date(2025, 1, 1)) == 65
    assert cfg.market.lot_size("NIFTY", date(2026, 7, 1)) == 65


def test_protection_band_validated():
    with pytest.raises(ValueError, match="protection_band_pct"):
        FillConfig(protection_band_pct=5)  # meant 5% but wrote 5
