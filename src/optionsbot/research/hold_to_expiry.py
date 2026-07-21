"""Hold-to-expiry iron condor study on free end-of-day data.

This deliberately studies the ONLY strategy shape end-of-day data can honestly
evaluate: enter at a close, exit at a close, no intraday triggers. Every rule
is decidable from one row per contract per day.

What that buys and what it costs:
- It answers whether defined-risk condors are viable *at all* after real
  transaction costs at this account size, using real prices.
- It says nothing about the live strategy, which exits on intraday profit
  targets and stops. EOD data cannot say which of the two was touched first
  when a day's range contains both, and that ordering decides the trade.
  Treat results here as a floor-level sanity check, not as validation of
  anything the paper loop does (docs/06).

Prices used are `last_traded` — a price someone actually transacted at.
Untraded contracts are excluded upstream by the ingester, so a leg that
never printed is a skipped trade rather than an imaginary fill.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..costs import Fill, fill_costs
from ..config import CostConfig, RiskConfig
from ..data.bhavcopy import EodRow
from ..instruments import Right, Side


@dataclass(frozen=True)
class CondorParams:
    offset_pct: float = 0.015      # short strikes this far OTM
    wing_points: float = 200.0     # wing distance from each short
    entry_days_before: int = 4     # trading days before expiry to enter
    strike_step: float = 50.0
    min_credit_frac: float = 0.0   # skip unless credit >= this share of wing width


@dataclass(frozen=True)
class Trade:
    expiry: date
    entry_day: date
    spot_at_entry: float
    spot_at_exit: float
    short_call: float
    short_put: float
    credit: float                  # per share, received at entry
    exit_cost: float               # per share, paid to close
    lot_size: int
    costs: float                   # rupees, all 8 fills
    gross: float                   # rupees, before costs
    net: float                     # rupees, after costs

    @property
    def won(self) -> bool:
        return self.net > 0


@dataclass
class Study:
    trades: list[Trade]
    skipped: dict[str, int]

    @property
    def total_cycles(self) -> int:
        """Expiries this run considered — trades plus every skip reason.

        A valid denominator within a single run. Not additive across
        partitions: an expiry straddling a walk-forward boundary is genuinely
        considered by both halves.
        """
        return len(self.trades) + sum(self.skipped.values())

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
        """NaN with no trades: a 0.0 sentinel is indistinguishable from a
        genuine 0% win rate in a parameter sweep."""
        if not self.trades:
            return float("nan")
        return 100.0 * sum(t.won for t in self.trades) / len(self.trades)

    def equity_curve(self, start_capital: float) -> list[float]:
        eq, out = start_capital, [start_capital]
        for t in self.trades:
            eq += t.net
            out.append(eq)
        return out

    def max_drawdown(self, start_capital: float) -> float:
        """NaN with no trades, so an empty configuration cannot surface in a
        sweep as a zero-drawdown strategy meeting the mandate."""
        if not self.trades:
            return float("nan")
        peak, worst = start_capital, 0.0
        for v in self.equity_curve(start_capital):
            peak = max(peak, v)
            worst = max(worst, peak - v)
        return worst


def _round_strike(value: float, step: float) -> float:
    return round(value / step) * step


def _leg_costs(day: date, side: Side, price: float, shares: int, cfg: CostConfig) -> float:
    return fill_costs(Fill(day=day, side=side, premium_per_share=price,
                           shares=shares), cfg).total


def run(
    by_day: dict[date, list[EodRow]],
    params: CondorParams,
    costs: CostConfig,
    risk: RiskConfig,
) -> Study:
    """One condor per expiry cycle, entered and exited at closing prices."""
    days = sorted(by_day)
    trades: list[Trade] = []
    skipped = {"expiry_outside_range": 0, "no_entry_day": 0, "missing_legs": 0,
               "over_cap": 0, "no_exit": 0, "untraded_leg": 0, "credit_too_thin": 0}

    indices = {r.index for rows in by_day.values() for r in rows}
    if len(indices) > 1:
        raise ValueError(
            f"by_day mixes indices {sorted(indices)}; run one index at a time so "
            "strike steps, lot sizes and spot levels are not conflated"
        )

    expiries = sorted({r.expiry for rows in by_day.values() for r in rows})
    for expiry in expiries:
        if expiry not in by_day:
            # Expiry day falls outside the loaded range, so the cycle cannot
            # be completed. Counted rather than dropped so every expiry the
            # study saw lands in exactly one bucket and total_cycles is a
            # trustworthy denominator. Note this is per-run: an expiry
            # straddling a walk-forward split is legitimately seen by both
            # halves, so the counts are not additive across partitions.
            skipped["expiry_outside_range"] += 1
            continue
        trading_days = [d for d in days if d < expiry]
        if len(trading_days) < params.entry_days_before:
            skipped["no_entry_day"] += 1
            continue
        entry_day = trading_days[-params.entry_days_before]

        entry_rows = {r.key: r for r in by_day[entry_day] if r.expiry == expiry}
        exit_rows = {r.key: r for r in by_day[expiry] if r.expiry == expiry}
        if not entry_rows:
            skipped["no_entry_day"] += 1
            continue

        first = next(iter(entry_rows.values()))
        spot = first.underlying
        index = first.index          # EodRow.key carries the real index
        sc = _round_strike(spot * (1 + params.offset_pct), params.strike_step)
        sp = _round_strike(spot * (1 - params.offset_pct), params.strike_step)
        lc, lp = sc + params.wing_points, sp - params.wing_points

        legs = [(sc, Right.CALL, Side.SELL), (lc, Right.CALL, Side.BUY),
                (sp, Right.PUT, Side.SELL), (lp, Right.PUT, Side.BUY)]
        keys = [(index, expiry, k, r) for k, r, _ in legs]
        entry = [entry_rows.get(k) for k in keys]
        exit_ = [exit_rows.get(k) for k in keys]
        if any(e is None for e in entry):
            skipped["missing_legs"] += 1
            continue
        if any(e is None for e in exit_):
            skipped["no_exit"] += 1
            continue
        # Untraded contracts have no achievable price. The ingester drops them
        # by default, but a caller passing traded_only=False would otherwise
        # reach arithmetic on None.
        if any(e.last_traded is None for e in (*entry, *exit_)):
            skipped["untraded_leg"] += 1
            continue

        lot = entry[0].lot_size
        credit = sum(
            (row.last_traded if side is Side.SELL else -row.last_traded)
            for row, (_, _, side) in zip(entry, legs)
        )
        # Value at expiry is INTRINSIC against the settlement index, not the
        # last traded price. The four legs last trade at different moments, so
        # differencing stale quotes produces spread values that violate the
        # arithmetic bound: one 2024-12-05 cycle showed a 59.7-point exit on a
        # 50-point wing, because both calls last printed well below intrinsic.
        exit_cost = sum(
            (row.mark if side is Side.SELL else -row.mark)
            for row, (_, _, side) in zip(exit_, legs)
        )
        # The risk cap is itself a credit floor (credit >= wing - cap/lot), so
        # the two rules are nested. Checking the cap FIRST means each counter
        # reports the cycles it alone rejected: with the filter first it would
        # absorb the cap's rejections and read as though the cap no longer
        # binds. Trade set and P&L are identical either way; only attribution
        # differs, and docs/10 relies on that attribution.
        worst_case = (params.wing_points - credit) * lot
        if worst_case > risk.per_trade_max_loss_rupees:
            skipped["over_cap"] += 1
            continue

        # Volatility filter, applied to EVERY surviving cycle as an explicit
        # rule so that an edge cannot be the cap's selection artifact (docs/10).
        # Guarded on > 0 so the 0.0 default is a true no-op: `credit < 0 * wing`
        # would otherwise drop net-debit cycles, which stale non-synchronous
        # prints do produce at wider offsets.
        if params.min_credit_frac > 0 and credit < params.min_credit_frac * params.wing_points:
            skipped["credit_too_thin"] += 1
            continue

        total_costs = 0.0
        for row, (_, _, side) in zip(entry, legs):
            total_costs += _leg_costs(entry_day, side, row.last_traded, lot, costs)
        # Exit costs are charged as if squaring off, which is conservative: a
        # cash settlement would avoid the brokerage but incur exercise STT,
        # whose mechanics this project treats as unverified (docs/05).
        for row, (_, _, side) in zip(exit_, legs):
            total_costs += _leg_costs(expiry, side.opposite, row.mark, lot, costs)

        gross = (credit - exit_cost) * lot
        trades.append(Trade(
            expiry=expiry, entry_day=entry_day, spot_at_entry=spot,
            spot_at_exit=next(iter(exit_rows.values())).underlying,
            short_call=sc, short_put=sp, credit=credit, exit_cost=exit_cost,
            lot_size=lot, costs=total_costs, gross=gross, net=gross - total_costs,
        ))

    return Study(trades=trades, skipped=skipped)
