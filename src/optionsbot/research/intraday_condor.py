"""Intraday iron condor study on minute bars.

This tests the strategy the live bot ACTUALLY runs — entry inside a time
window, exit on a profit target or a stop, forced square-off on expiry day —
which end-of-day data structurally cannot evaluate (docs/10). At minute
granularity the ordering ambiguity that made EOD useless disappears: minutes
are checked in sequence, so whichever trigger is reached first is reached
first.

Correctness rules, each of which exists because violating it fabricates money:

- **A leg with zero volume in a minute cannot be traded.** Its price is a
  forward-filled carry, not a quote. Entry requires all four legs tradeable in
  the SAME minute; an exit that cannot be priced waits for the next minute
  rather than transacting at a stale number.
- **Triggers are evaluated on the cost to close the whole structure**, not on
  individual legs, because that is what the position is worth.
- **The stop is checked before the target** in any minute where both conditions
  hold. That is the conservative reading: a structure worth more than the stop
  threshold is a loss being taken, and assuming otherwise flatters the result.
- **No look-ahead.** Decisions at minute t use only bars at or before t.
- Costs come from the shared engine, charged on all eight fills.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from ..config import CostConfig, RiskConfig
from ..costs import Fill, fill_costs
from ..data.intraday import Bar
from ..instruments import Right, Side


@dataclass(frozen=True)
class IntradayParams:
    offset_pct: float = 0.008
    wing_points: float = 50.0
    strike_step: float = 50.0
    min_dte: int = 2
    max_dte: int = 6
    entry_start: time = time(10, 0)
    entry_end: time = time(14, 0)
    profit_target_frac: float = 0.50   # exit when cost-to-close <= 50% of credit
    # Share of MAX LOSS, not a multiple of credit: see reference_condor for why
    # a credit multiple is frequently unreachable and silently disables the stop.
    stop_loss_frac: float = 0.60
    # Trailing profit-lock (0 = off). Once the structure has been in profit, exit
    # if the unrealised profit gives back this fraction of its PEAK. It only ever
    # tightens a winner; the hard stop_loss still guards losses. Tested in the
    # docs/11 addendum — the owner asked whether the momentum trailing-stop result
    # carries over to options. It does (and worse): see docs/11.
    trail_stop_frac: float = 0.0
    squareoff: time = time(15, 0)      # expiry-day forced exit
    min_credit_frac: float = 0.0
    # Points given up per leg, each way. Defaults to a realistic 5 ticks rather
    # than zero: the source carries one price per minute with no bid/ask, so
    # this cost cannot be measured and must be assumed. Defaulting it to zero
    # made the honest run the one you had to remember to ask for, and the first
    # published figure was ~Rs 12,000 optimistic because of it (docs/11). Set it
    # to 0.0 explicitly to model a frictionless fill.
    slippage_per_leg: float = 0.25


@dataclass(frozen=True)
class IntradayTrade:
    expiry: date
    entered_at: datetime
    exited_at: datetime
    exit_reason: str                   # target | stop | trail | squareoff
    short_call: float
    short_put: float
    credit: float                      # per share, realised at entry
    exit_cost: float                   # per share, paid to close
    lot_size: int
    costs: float
    gross: float
    net: float

    @property
    def won(self) -> bool:
        return self.net > 0

    @property
    def minutes_held(self) -> int:
        return int((self.exited_at - self.entered_at).total_seconds() // 60)


@dataclass
class IntradayStudy:
    trades: list[IntradayTrade]
    skipped: dict[str, int]

    @property
    def net(self) -> float:
        return sum(t.net for t in self.trades)

    @property
    def gross(self) -> float:
        return sum(t.gross for t in self.trades)

    @property
    def costs(self) -> float:
        return sum(t.costs for t in self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return float("nan")
        return 100.0 * sum(t.won for t in self.trades) / len(self.trades)

    @property
    def total_cycles(self) -> int:
        return len(self.trades) + sum(self.skipped.values())

    def exits(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self.trades:
            out[t.exit_reason] = out.get(t.exit_reason, 0) + 1
        return out

    def max_drawdown(self, start_capital: float) -> float:
        if not self.trades:
            return float("nan")
        eq = peak = start_capital
        worst = 0.0
        for t in self.trades:
            eq += t.net
            peak = max(peak, eq)
            worst = max(worst, peak - eq)
        return worst


def _round_strike(value: float, step: float) -> float:
    return round(value / step) * step


def _structure(spot: float, p: IntradayParams) -> list[tuple[float, Right, Side]]:
    sc = _round_strike(spot * (1 + p.offset_pct), p.strike_step)
    sp = _round_strike(spot * (1 - p.offset_pct), p.strike_step)
    return [
        (sc, Right.CALL, Side.SELL), (sc + p.wing_points, Right.CALL, Side.BUY),
        (sp, Right.PUT, Side.SELL), (sp - p.wing_points, Right.PUT, Side.BUY),
    ]


def _quote(chain: dict, expiry: date, legs: list[tuple[float, Right, Side]]
           ) -> list[Bar] | None:
    """All four legs from one minute, or None if any is untradeable then."""
    bars = [chain.get((expiry, strike, right)) for strike, right, _ in legs]
    if any(b is None or not b.tradeable for b in bars):
        return None
    return bars


def _structure_price(bars: list[Bar], legs: list[tuple[float, Right, Side]]) -> float:
    """Net premium per share of the structure as quoted.

    One function, because entering and unwinding price the same thing: at entry
    it is the credit received, mid-trade it is the cost to close. They were two
    byte-identical functions, which meant any correction to leg-sign handling
    had to be made twice or the two ends would silently disagree.
    """
    return sum(
        (b.ltp if side is Side.SELL else -b.ltp) for b, (_, _, side) in zip(bars, legs)
    )


def _intrinsic_value(spot: float, legs: list[tuple[float, Right, Side]]) -> float:
    """Structure value at expiry against the settlement index, per share."""
    total = 0.0
    for strike, right, side in legs:
        v = max(0.0, spot - strike) if right is Right.CALL else max(0.0, strike - spot)
        total += v if side is Side.SELL else -v
    return total


def _within_bound(value: float, wing: float) -> bool:
    """A short condor is worth between 0 and its wing width. Values outside
    that come from differencing four prints that did not occur at the same
    instant — the trap documented in docs/10, which cost 17% of exits in the
    first version of this study."""
    return -1e-9 <= value <= wing + 1e-9


def _fill_costs(day: date, side: Side, price: float, shares: int,
                cfg: CostConfig) -> float:
    return fill_costs(Fill(day=day, side=side, premium_per_share=price,
                           shares=shares), cfg).total


def run_expiry(
    bars: list[Bar],
    expiry: date,
    lot_size: int,
    params: IntradayParams,
    costs: CostConfig,
    risk: RiskConfig,
) -> tuple[IntradayTrade | None, str]:
    """One condor for one expiry cycle. Returns (trade, reason-if-skipped)."""
    from ..data.intraday import by_minute

    minutes = by_minute([b for b in bars if b.expiry == expiry])
    if not minutes:
        return None, "no_data"

    entry: tuple[datetime, list[Bar], list[tuple[float, Right, Side]], float] | None = None
    best_value = float("inf")          # lowest cost-to-close since entry (peak profit)
    for ts in sorted(minutes):
        dte = (expiry - ts.date()).days
        if entry is None:
            if not (params.min_dte <= dte <= params.max_dte):
                continue
            if not (params.entry_start <= ts.time() <= params.entry_end):
                continue
            chain = minutes[ts]
            spot = next(iter(chain.values())).spot
            legs = _structure(spot, params)
            quoted = _quote(chain, expiry, legs)
            if quoted is None:
                continue                                  # not all legs tradeable
            # Bound-check what the MARKET quoted, before modelled costs are
            # applied. A credit above the wing width is free money and cannot
            # occur; it means the four legs printed at different instants.
            # Testing the post-slippage figure instead let a raw credit of 51 on
            # a 50-point wing pass as 50 — slippage laundering an impossible
            # price into an acceptable one. Leaving entry unchecked was worse
            # than leaving both ends unchecked: an inflated credit puts the stop
            # threshold above the wing, so the position runs unstopped to a
            # settled exit that books a guaranteed profit.
            if not _within_bound(_structure_price(quoted, legs), params.wing_points):
                continue
            credit = _structure_price(quoted, legs) - 4 * params.slippage_per_leg
            if credit <= 0:
                continue
            if credit < params.min_credit_frac * params.wing_points:
                continue
            if (params.wing_points - credit) * lot_size > risk.per_trade_max_loss_rupees:
                continue                                  # breaches the per-trade cap
            entry = (ts, quoted, legs, credit)
            continue

        entered_at, entry_bars, legs, credit = entry
        chain = minutes[ts]
        quoted = _quote(chain, expiry, legs)
        expiry_day = ts.date() == expiry
        must_close = expiry_day and ts.time() >= params.squareoff
        if quoted is None:
            if not must_close:
                continue                                  # cannot price an exit yet
            value = _intrinsic_value(next(iter(chain.values())).spot, legs)
            value += 4 * params.slippage_per_leg
        else:
            quoted_value = _structure_price(quoted, legs)
            if not _within_bound(quoted_value, params.wing_points):
                if not must_close:
                    continue                              # non-synchronous prints
                value = _intrinsic_value(next(iter(chain.values())).spot, legs)
                value += 4 * params.slippage_per_leg
            else:
                value = quoted_value + 4 * params.slippage_per_leg

        # Stop checked first: when both conditions hold in one minute, booking
        # the loss is the conservative reading. `value` includes exit slippage,
        # so the trailing lock is measured on the same honest mark.
        best_value = min(best_value, value)
        peak_profit = credit - best_value
        stop_at = credit + params.stop_loss_frac * (params.wing_points - credit)
        if value >= stop_at:
            reason = "stop"
        elif (params.trail_stop_frac > 0.0 and peak_profit > 1e-9
              and (credit - value) <= (1.0 - params.trail_stop_frac) * peak_profit):
            reason = "trail"                          # gave back too much of the peak
        elif value <= credit * (1 - params.profit_target_frac):
            reason = "target"
        elif must_close:
            reason = "squareoff"
        else:
            continue

        total = 0.0
        for b, (_, _, side) in zip(entry_bars, legs):
            total += _fill_costs(entered_at.date(), side, b.ltp, lot_size, costs)
        exit_prices = ([b.ltp for b in quoted] if quoted is not None
                       else [abs(value) / 4] * 4)        # settled: approximate per-leg base
        for px, (_, _, side) in zip(exit_prices, legs):
            total += _fill_costs(ts.date(), side.opposite, px, lot_size, costs)

        gross = (credit - value) * lot_size
        sc = next(s for s, r, sd in legs if r is Right.CALL and sd is Side.SELL)
        sp = next(s for s, r, sd in legs if r is Right.PUT and sd is Side.SELL)
        return IntradayTrade(
            expiry=expiry, entered_at=entered_at, exited_at=ts, exit_reason=reason,
            short_call=sc, short_put=sp, credit=credit, exit_cost=value,
            lot_size=lot_size, costs=total, gross=gross, net=gross - total,
        ), ""

    if entry is None:
        return None, "no_entry"

    # Holding at the end of the data is not an escape hatch. Deleting these
    # cycles removed only maximum-loss outcomes in the first version of this
    # study — survivorship bias severe enough to flip the sign of the result.
    # The position is settled at intrinsic value against the last observed spot.
    entered_at, entry_bars, legs, credit = entry
    last_ts = max(minutes)
    spot = next(iter(minutes[last_ts].values())).spot
    # Slippage applies here too. Charging it at entry and not at this exit
    # flattered precisely the maximum-loss cycles, which is what this path
    # exists to stop discarding.
    value = _intrinsic_value(spot, legs) + 4 * params.slippage_per_leg
    total = 0.0
    for b, (_, _, side) in zip(entry_bars, legs):
        total += _fill_costs(entered_at.date(), side, b.ltp, lot_size, costs)
    for (_, _, side) in legs:
        total += _fill_costs(last_ts.date(), side.opposite, max(value, 0.0) / 4,
                             lot_size, costs)
    gross = (credit - value) * lot_size
    sc = next(s for s, r, sd in legs if r is Right.CALL and sd is Side.SELL)
    sp = next(s for s, r, sd in legs if r is Right.PUT and sd is Side.SELL)
    return IntradayTrade(
        expiry=expiry, entered_at=entered_at, exited_at=last_ts,
        exit_reason="settled", short_call=sc, short_put=sp, credit=credit,
        exit_cost=value, lot_size=lot_size, costs=total, gross=gross,
        net=gross - total,
    ), ""
