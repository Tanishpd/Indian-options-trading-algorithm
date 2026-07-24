"""Naked short strangle — the undefined-risk way to chase 50%+ (docs/17).

The owner asked, with the drawdown cap and defined-risk rule explicitly lifted
and ₹6L of capital, whether options can target 50%+ a year. This is the honest
vehicle for that question: sell an OTM call AND an OTM put each weekly cycle,
collect the premium, hold to expiry. It harvests theta and the variance risk
premium (docs/12) — and it is SHORT the tail those same studies showed is where
the money and the ruin both live. There are no wings; the loss is unbounded.

This module measures it on the real NIFTY chains (the same data as the condor),
net of honest costs, so the return AND the tail can be put side by side. It
reuses the condor's leg helpers — a strangle is just the condor's two short legs
with the protective wings removed, which is precisely what makes it dangerous.

Nothing here caps per-trade loss: the whole point is to show what removing that
cap costs. Position sizing and the crash stress test live in run_strangle.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from ..config import CostConfig
from ..data.intraday import Bar, by_minute
from ..instruments import Right, Side
from .intraday_condor import (
    _fill_costs, _intrinsic_value, _quote, _round_strike, _structure_price)


@dataclass(frozen=True)
class StrangleParams:
    offset_pct: float = 0.015          # sell ~1.5% OTM each side (~1 weekly sigma)
    strike_step: float = 50.0
    min_dte: int = 2
    max_dte: int = 6
    entry_start: time = time(10, 0)
    entry_end: time = time(14, 0)
    slippage_per_leg: float = 0.25     # honest default; the source has no bid/ask
    # Protective wings (0 = naked strangle). When > 0, at the SAME entry minute and
    # the SAME short strikes we ALSO buy a long call `wing_points` above the short
    # call and a long put `wing_points` below the short put — turning the position
    # into an iron condor. This is the apples-to-apples hedge test (docs/17): the
    # only thing that changes versus naked is the wings, so the wing's true effect
    # on return AND tail is isolated. Crucially, if the wing strikes are NOT
    # tradeable at that minute (deep-OTM strikes often have zero volume) we do NOT
    # skip the cycle — we trade it NAKED and flag it. That is the honest "hedge
    # when you can" case, and it exposes why requiring all four legs (as the condor
    # engine does) silently drops the un-hedgeable weeks and flatters the tail.
    wing_points: float = 0.0
    # Exit management (all 0 = hold naked to expiry, the undefined-risk baseline).
    # A stop-loss caps a GRIND but not a GAP: intra-cycle marks come from the data,
    # so a jump between the last bar of one day and the first of the next books the
    # exit at the gapped price, not the stop level — exactly how a real gap fills.
    stop_loss_mult: float = 0.0        # exit when cost-to-close >= mult x credit
    profit_target_frac: float = 0.0    # exit when cost-to-close <= (1-frac) x credit
    trail_stop_frac: float = 0.0       # exit if profit gives back this frac of its peak
    squareoff: time = time(15, 0)      # expiry-day forced exit


@dataclass(frozen=True)
class StrangleTrade:
    expiry: date
    entered_at: datetime
    exited_at: datetime
    exit_reason: str                   # settled | stop | trail | target | squareoff
    short_call: float
    short_put: float
    credit: float                      # per share, collected at entry
    exit_value: float                  # per share, paid to close / owed at settlement
    final_spot: float                  # spot at the exit
    lot_size: int
    costs: float
    gross: float
    net: float
    hedged: bool = False               # were protective wings actually in place?

    @property
    def breached(self) -> bool:
        """Did the index finish outside the strikes (some intrinsic owed)? Measured
        on the spot vs strikes, not exit_value, which carries slippage even when
        both legs expire worthless."""
        return self.final_spot > self.short_call or self.final_spot < self.short_put

    @property
    def won(self) -> bool:
        return self.net > 0


def _legs(spot: float, p: StrangleParams) -> list[tuple[float, Right, Side]]:
    sc = _round_strike(spot * (1 + p.offset_pct), p.strike_step)
    sp = _round_strike(spot * (1 - p.offset_pct), p.strike_step)
    return [(sc, Right.CALL, Side.SELL), (sp, Right.PUT, Side.SELL)]


def _wing_legs(short_legs: list[tuple[float, Right, Side]], wing_points: float
               ) -> list[tuple[float, Right, Side]]:
    """The two long protective wings, `wing_points` beyond each short strike."""
    sc = next(s for s, r, sd in short_legs if r is Right.CALL)
    sp = next(s for s, r, sd in short_legs if r is Right.PUT)
    return [(sc + wing_points, Right.CALL, Side.BUY),
            (sp - wing_points, Right.PUT, Side.BUY)]


def _book(expiry, entered_at, entry_bars, legs, credit, value, final_spot,
          exited_at, reason, quoted, lot_size, costs, hedged) -> StrangleTrade:
    """Realise the trade: entry fills (sell both legs) + exit fills (buy them back
    at the quoted ltp, or settle each leg at intrinsic when quoted is None)."""
    total = 0.0
    for b, (_, _, side) in zip(entry_bars, legs):
        total += _fill_costs(entered_at.date(), side, b.ltp, lot_size, costs)
    if quoted is not None:
        for b, (_, _, side) in zip(quoted, legs):
            total += _fill_costs(exited_at.date(), side.opposite, b.ltp, lot_size, costs)
    else:
        for strike, right, side in legs:
            v = (max(0.0, final_spot - strike) if right is Right.CALL
                 else max(0.0, strike - final_spot))
            total += _fill_costs(exited_at.date(), side.opposite, v, lot_size, costs)
    gross = (credit - value) * lot_size
    sc = next(s for s, r, sd in legs if r is Right.CALL)
    sp = next(s for s, r, sd in legs if r is Right.PUT)
    return StrangleTrade(
        expiry=expiry, entered_at=entered_at, exited_at=exited_at, exit_reason=reason,
        short_call=sc, short_put=sp, credit=credit, exit_value=value,
        final_spot=final_spot, lot_size=lot_size, costs=total, gross=gross,
        net=gross - total, hedged=hedged)


def run_cycle(bars: list[Bar], expiry: date, lot_size: int, params: StrangleParams,
              costs: CostConfig) -> tuple[StrangleTrade | None, str]:
    """One short strangle for one expiry. With all exit params 0 it holds naked to
    expiry (undefined risk); a stop/target/trail exits intra-cycle on the minute
    marks. Returns (trade, reason-if-skipped)."""
    minutes = by_minute([b for b in bars if b.expiry == expiry])
    if not minutes:
        return None, "no_data"

    manage = (params.stop_loss_mult > 0.0 or params.profit_target_frac > 0.0
              or params.trail_stop_frac > 0.0)
    entry = None
    best_value = float("inf")          # lowest cost-to-close (peak profit) so far
    for ts in sorted(minutes):
        if entry is None:
            dte = (expiry - ts.date()).days
            if not (params.min_dte <= dte <= params.max_dte):
                continue
            if not (params.entry_start <= ts.time() <= params.entry_end):
                continue
            chain = minutes[ts]
            spot = next(iter(chain.values())).spot
            legs = _legs(spot, params)
            quoted = _quote(chain, expiry, legs)
            if quoted is None:
                continue
            hedged = False
            if params.wing_points > 0.0:            # try to bolt on protective wings
                wlegs = _wing_legs(legs, params.wing_points)
                wquoted = _quote(chain, expiry, wlegs)
                if wquoted is not None:             # wings tradeable this minute
                    legs = legs + wlegs             # SAME shorts + long wings = condor
                    quoted = quoted + wquoted
                    hedged = True
                # else: wings not tradeable -> trade NAKED this cycle (flagged), do
                # NOT skip. Skipping is exactly the survivorship the condor engine
                # falls into; staying naked is what the trader actually faces.
            credit = _structure_price(quoted, legs) - len(legs) * params.slippage_per_leg
            if credit <= 0:
                continue
            entry = (ts, quoted, legs, credit, hedged)
            if not manage:
                break                                 # hold to expiry
            continue

        entered_at, entry_bars, legs, credit, hedged = entry
        chain = minutes[ts]
        spot = next(iter(chain.values())).spot
        if ts.date() == expiry and ts.time() >= params.squareoff:
            value = _intrinsic_value(spot, legs) + len(legs) * params.slippage_per_leg
            return _book(expiry, entered_at, entry_bars, legs, credit, value, spot,
                         ts, "squareoff", None, lot_size, costs, hedged), ""  # settle intrinsic
        quoted = _quote(chain, expiry, legs)
        if quoted is None:
            continue                                  # cannot mark for a stop/target
        value = _structure_price(quoted, legs) + len(legs) * params.slippage_per_leg
        best_value = min(best_value, value)
        peak_profit = credit - best_value
        if params.stop_loss_mult > 0.0 and value >= credit * params.stop_loss_mult:
            reason = "stop"                           # caps a grind, NOT a gap
        elif (params.trail_stop_frac > 0.0 and peak_profit > 1e-9
              and (credit - value) <= (1.0 - params.trail_stop_frac) * peak_profit):
            reason = "trail"
        elif (params.profit_target_frac > 0.0
              and value <= credit * (1.0 - params.profit_target_frac)):
            reason = "target"
        else:
            continue
        return _book(expiry, entered_at, entry_bars, legs, credit, value, spot,
                     ts, reason, quoted, lot_size, costs, hedged), ""

    if entry is None:
        return None, "no_entry"

    # Held to the end of the data without an exit firing: settle at expiry
    # intrinsic against the last observed spot. Naked, this value is UNBOUNDED
    # above; hedged, the long wings cap it at the wing width.
    entered_at, entry_bars, legs, credit, hedged = entry
    last_ts = max(minutes)
    final_spot = next(iter(minutes[last_ts].values())).spot
    value = _intrinsic_value(final_spot, legs) + len(legs) * params.slippage_per_leg
    return _book(expiry, entered_at, entry_bars, legs, credit, value, final_spot,
                 last_ts, "settled", None, lot_size, costs, hedged), ""


@dataclass
class StrangleStudy:
    trades: list[StrangleTrade]
    skipped: dict[str, int]

    @property
    def net(self) -> float:
        return sum(t.net for t in self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return float("nan")
        return 100.0 * sum(t.won for t in self.trades) / len(self.trades)

    @property
    def worst_cycle(self) -> float:
        return min((t.net for t in self.trades), default=float("nan"))

    def exits(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self.trades:
            out[t.exit_reason] = out.get(t.exit_reason, 0) + 1
        return out

    def equity_curve(self, start_capital: float, lots: int) -> list[float]:
        """Equity after each cycle, holding `lots` lots (net per lot scales by
        lots since every cycle is one structure). Starts at start_capital."""
        eq = start_capital
        out = [eq]
        for t in self.trades:
            eq += t.net * lots               # t.net is one lot (lot_size shares); scale by lots
            out.append(eq)
        return out

    def max_drawdown(self, start_capital: float, lots: int) -> float:
        eq = peak = start_capital
        worst = 0.0
        for t in self.trades:
            eq += t.net * lots
            peak = max(peak, eq)
            worst = max(worst, peak - eq)
        return worst
