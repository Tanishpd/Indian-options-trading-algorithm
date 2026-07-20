from datetime import date

import pytest

from optionsbot.instruments import (
    OptionLeg,
    Right,
    Side,
    Structure,
    assert_within_per_trade_cap,
    credit_spread,
    iron_condor,
    max_loss,
)

EXPIRY = date(2026, 7, 14)


def test_naked_short_is_unconstructable():
    with pytest.raises(ValueError, match="naked short"):
        Structure(
            name="naked_call",
            legs=(OptionLeg("NIFTY", EXPIRY, 26000, Right.CALL, Side.SELL),),
        )


def test_partially_covered_short_is_unconstructable():
    with pytest.raises(ValueError, match="naked short"):
        Structure(
            name="ratio",
            legs=(
                OptionLeg("NIFTY", EXPIRY, 26000, Right.CALL, Side.SELL, lots=2),
                OptionLeg("NIFTY", EXPIRY, 26200, Right.CALL, Side.BUY, lots=1),
            ),
        )


def test_iron_condor_constructs_and_validates_ordering():
    ic = iron_condor("NIFTY", EXPIRY, short_call=25900, long_call=26100,
                     short_put=25100, long_put=24900)
    assert len(ic.legs) == 4
    with pytest.raises(ValueError, match="long_put < short_put < short_call < long_call"):
        iron_condor("NIFTY", EXPIRY, short_call=26100, long_call=25900,
                    short_put=25100, long_put=24900)


def test_credit_spread_direction_enforced():
    credit_spread("NIFTY", EXPIRY, Right.CALL, short_strike=25900, long_strike=26100)
    with pytest.raises(ValueError, match="above"):
        credit_spread("NIFTY", EXPIRY, Right.CALL, short_strike=25900, long_strike=25700)
    with pytest.raises(ValueError, match="below"):
        credit_spread("NIFTY", EXPIRY, Right.PUT, short_strike=25100, long_strike=25300)


def test_max_loss_iron_condor_hand_computed():
    # 200-wide wings both sides, credit 68/share, lot 65:
    # max loss/share = 200 - 68 = 132 -> Rs 8,580
    ic = iron_condor("NIFTY", EXPIRY, 25900, 26100, 25100, 24900)
    assert max_loss(ic, net_credit_per_share=68.0, lot_size=65) == pytest.approx(8580.0)


def test_max_loss_scales_with_lots():
    # 2-lot bull call spread bought at 30/share per unit: total debit/share is
    # 60, so the true worst case is 60 * 65 = Rs 3,900 (not 1,950).
    s = Structure(
        name="bull_call_2lot",
        legs=(
            OptionLeg("NIFTY", EXPIRY, 25900, Right.CALL, Side.BUY, lots=2),
            OptionLeg("NIFTY", EXPIRY, 26100, Right.CALL, Side.SELL, lots=2),
        ),
    )
    assert max_loss(s, net_credit_per_share=-60.0, lot_size=65) == pytest.approx(3900.0)


def test_max_loss_sums_independent_groups():
    # NIFTY put spread + SENSEX call spread: no single underlying price can
    # max out both, but each group can realise its own worst case.
    # Worst payoff = -200 - 200; credit 50 -> loss (400-50)*65 = Rs 22,750.
    s = Structure(
        name="two_index_combo",
        legs=(
            OptionLeg("NIFTY", EXPIRY, 25100, Right.PUT, Side.SELL),
            OptionLeg("NIFTY", EXPIRY, 24900, Right.PUT, Side.BUY),
            OptionLeg("SENSEX", EXPIRY, 79000, Right.CALL, Side.SELL),
            OptionLeg("SENSEX", EXPIRY, 79200, Right.CALL, Side.BUY),
        ),
    )
    assert max_loss(s, net_credit_per_share=50.0, lot_size=65) == pytest.approx(22750.0)


def test_string_right_and_side_are_coerced_to_enums():
    l = OptionLeg("NIFTY", EXPIRY, 25900, "CE", "BUY")
    assert l.right is Right.CALL
    assert l.side is Side.BUY
    with pytest.raises(ValueError):
        OptionLeg("NIFTY", EXPIRY, 25900, "CALL", "BUY")  # invalid enum value


def test_datetime_expiry_rejected():
    from datetime import datetime
    with pytest.raises(TypeError, match="datetime.date"):
        OptionLeg("NIFTY", datetime(2026, 7, 14), 25900, Right.CALL, Side.BUY)


def test_side_sign_and_opposite():
    assert Side.BUY.sign == 1 and Side.SELL.sign == -1
    assert Side.BUY.opposite is Side.SELL and Side.SELL.opposite is Side.BUY


def test_max_loss_debit_spread_is_the_debit():
    # Bull call spread bought for a 30/share debit: worst case loses the debit.
    s = Structure(
        name="bull_call",
        legs=(
            OptionLeg("NIFTY", EXPIRY, 25900, Right.CALL, Side.BUY),
            OptionLeg("NIFTY", EXPIRY, 26100, Right.CALL, Side.SELL),
        ),
    )
    assert max_loss(s, net_credit_per_share=-30.0, lot_size=65) == pytest.approx(1950.0)


def test_per_trade_cap_rejects_wide_wings():
    ic = iron_condor("NIFTY", EXPIRY, 25900, 26100, 25100, 24900)
    with pytest.raises(ValueError, match="per-trade cap"):
        assert_within_per_trade_cap(ic, net_credit_per_share=68.0, lot_size=65, cap_rupees=2000.0)
    # Tight wings pass: 50-wide, credit 20 -> loss (50-20)*65 = 1950 <= 2000
    tight = iron_condor("NIFTY", EXPIRY, 25900, 25950, 25100, 25050)
    assert_within_per_trade_cap(tight, net_credit_per_share=20.0, lot_size=65, cap_rupees=2000.0)


def test_universe_enforced_on_legs():
    with pytest.raises(ValueError, match="permitted universe"):
        OptionLeg("BANKNIFTY", EXPIRY, 50000, Right.CALL, Side.BUY)
