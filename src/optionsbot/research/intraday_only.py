"""Intraday-only short strangle: never hold a position overnight (docs/17 addendum).

Answers "what if we don't take overnight positions at all?" Each trading day is its
own cycle — sell a ~1% OTM strangle on the nearest weekly near the open, and be flat
by 15:25 the SAME day (or an intraday stop fires first). Removing the overnight hold
removes the overnight-gap ruin (you are flat every night, and a stop CAN act because
there is a mark every minute — unlike a gap you cannot trade through). But it also
forgoes the overnight/weekend theta that is the actual edge, and pays entry+exit
costs ~5x per week instead of once per cycle.

The finding (docs/17): in-sample on the full window it looks like the best options
produced here — ~30% CAGR at ~18% maxDD — but that number does not survive scrutiny:

  1. It is a pure execution bet. The per-day edge is thin (~₹3/share net), paid ~345
     times a year, so it dies by ~20 ticks/leg of slippage (breakeven ≈ ₹1.00/leg).
  2. It is entirely one regime. Split the window in half and it is +74% in H1 and
     NEGATIVE in H2 — out-of-sample there is no edge.

So this reuses the strangle engine's leg/costing helpers to make the negative result
reproducible, not to recommend the strategy. Run it and read all three tables:

    python -m optionsbot.research.intraday_only data/intraday/NIFTY
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, time
from pathlib import Path

from ..config import CostConfig, MarketConfig
from ..data.intraday import Bar, by_minute, read_csv
from .intraday_condor import _intrinsic_value, _quote, _structure_price
from .run_intraday import cycles
from .short_strangle import StrangleParams, StrangleTrade, _book, _legs

CAPITAL = 600_000.0
MARGIN_PER_LOT = 140_000.0                    # naked-strangle margin; VERIFY with broker
MAX_LOTS = int(CAPITAL // MARGIN_PER_LOT)     # 4
DATA_FLOOR = date(2024, 11, 1)                # docs/06: pre-Nov-2024 data is banned

# Intraday window: enter as early as sane (most decay to capture) and exit as late as
# sane (be flat before the close). This is deliberately the MOST favourable window —
# if the edge fails here it fails everywhere.
_ENTRY = dict(entry_start=time(9, 20), entry_end=time(12, 0), squareoff=time(15, 25))


def intraday_params(offset_pct: float = 0.01, slippage_per_leg: float = 0.25,
                    stop_loss_mult: float = 0.0) -> StrangleParams:
    """A StrangleParams with the intraday-only entry/exit window."""
    return StrangleParams(offset_pct=offset_pct, slippage_per_leg=slippage_per_leg,
                          stop_loss_mult=stop_loss_mult, **_ENTRY)


def plan_days(files, floor: date = DATA_FLOOR):
    """For each trading day, the nearest weekly expiry to sell — own-expiry bars only.
    Returns (plan, by_ed) where plan is [(day, expiry)] and by_ed maps (expiry, day)
    to that day's bars."""
    by_ed: dict[tuple, list[Bar]] = defaultdict(list)
    avail: dict[date, set] = defaultdict(set)
    for path, expiry in files:
        for b in read_csv(path):
            if b.expiry == expiry:
                by_ed[(expiry, b.ts.date())].append(b)
                avail[b.ts.date()].add(expiry)
    plan = []
    for d in sorted(avail):
        if d < floor:
            continue
        cands = [e for e in avail[d] if e >= d]
        if cands:
            plan.append((d, min(cands)))          # sell the nearest not-yet-expired weekly
    return plan, by_ed


def run_day(bars: list[Bar], expiry: date, lot_size: int, p: StrangleParams,
            costs: CostConfig) -> StrangleTrade | None:
    """One intraday-only cycle: enter in the window, flat by squareoff the SAME day,
    or an intraday stop. Never holds overnight."""
    minutes = by_minute(bars)
    if not minutes:
        return None
    order = sorted(minutes)
    entry = None
    for ts in order:
        if entry is None:
            if not (p.entry_start <= ts.time() <= p.entry_end):
                continue
            chain = minutes[ts]
            spot = next(iter(chain.values())).spot
            legs = _legs(spot, p)
            q = _quote(chain, expiry, legs)
            if q is None:
                continue
            credit = _structure_price(q, legs) - 2 * p.slippage_per_leg
            if credit <= 0:
                continue
            entry = (ts, q, legs, credit)
            continue

        entered_at, ebars, legs, credit = entry
        chain = minutes[ts]
        spot = next(iter(chain.values())).spot
        force = ts.time() >= p.squareoff or ts == order[-1]   # flat before the close
        q = _quote(chain, expiry, legs)
        if q is None:
            if not force:
                continue                                       # cannot mark; wait
            value = _intrinsic_value(spot, legs) + 2 * p.slippage_per_leg
            return _book(expiry, entered_at, ebars, legs, credit, value, spot, ts,
                         "squareoff", None, lot_size, costs, False)
        value = _structure_price(q, legs) + 2 * p.slippage_per_leg
        if p.stop_loss_mult > 0 and value >= credit * p.stop_loss_mult and not force:
            return _book(expiry, entered_at, ebars, legs, credit, value, spot, ts,
                         "stop", q, lot_size, costs, False)  # a stop CAN act intraday
        if force:
            return _book(expiry, entered_at, ebars, legs, credit, value, spot, ts,
                         "squareoff", q, lot_size, costs, False)
    return None


def run(plan, by_ed, lot_of, p: StrangleParams, costs: CostConfig) -> list[StrangleTrade]:
    out = []
    for d, e in plan:
        t = run_day(by_ed[(e, d)], e, lot_of(e), p, costs)
        if t is not None:
            out.append(t)
    return out


def _metrics(trades, lots, years):
    eq = peak = CAPITAL
    worst = 0.0
    curve = [eq]
    for t in trades:
        eq += t.net * lots
        peak = max(peak, eq)
        worst = max(worst, peak - eq)
        curve.append(eq)
    ruin = min(curve) <= 0
    cagr = None if (ruin or curve[-1] <= 0) else 100 * ((curve[-1] / CAPITAL) ** (1 / years) - 1)
    return cagr, 100 * worst / CAPITAL, ruin


def _cagr(c, ruin):
    return "RUIN" if ruin else (f"{c:.1f}%" if c is not None else "n/a")


def _years(plan):
    return max((plan[-1][0] - plan[0][0]).days / 365.25, 1e-9)


def base_table(plan, by_ed, lot_of, costs) -> None:
    years = _years(plan)
    print(f"A) INTRADAY-ONLY, 1% OTM, {MAX_LOTS} lots, {len(plan)} days ({years:.2f}y):")
    for label, stop in [("no stop (flat 15:25)", 0.0), ("stop 2x credit", 2.0),
                        ("stop 1.5x credit", 1.5)]:
        trades = run(plan, by_ed, lot_of, intraday_params(stop_loss_mult=stop), costs)
        if not trades:
            print(f"   {label:<22} no trades"); continue
        c, dd, ruin = _metrics(trades, MAX_LOTS, years)
        net = sum(t.net for t in trades) * MAX_LOTS
        win = 100 * sum(1 for t in trades if t.net > 0) / len(trades)
        worst = min(t.net for t in trades) * MAX_LOTS
        print(f"   {label:<22} CAGR {_cagr(c, ruin):>7} | maxDD {dd:>3.0f}% | "
              f"win {win:>4.1f}% | worst ₹{worst:>9,.0f} | net ₹{net:>11,.0f}")


def slippage_table(plan, by_ed, lot_of, costs) -> None:
    years = _years(plan)
    print("\nB) SLIPPAGE SENSITIVITY (no stop) — the whole return is an execution bet:")
    for slip in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0):
        trades = run(plan, by_ed, lot_of, intraday_params(slippage_per_leg=slip), costs)
        c, dd, ruin = _metrics(trades, MAX_LOTS, years)
        net = sum(t.net for t in trades) * MAX_LOTS
        print(f"   {slip:.2f}/leg ({int(slip / 0.05):>2} ticks): CAGR {_cagr(c, ruin):>7} | "
              f"maxDD {dd:>3.0f}% | net ₹{net:>11,.0f}")
    print("   breakeven ≈ ₹1.00/leg; clears 20-25% only inside ₹0.25-0.50/leg.")


def oos_table(plan, by_ed, lot_of, costs) -> None:
    print("\nC) OUT-OF-SAMPLE SPLIT (no stop) — edge must hold in BOTH halves to be real:")
    mid = len(plan) // 2
    for slip in (0.25, 0.5):
        print(f"   slippage {slip:.2f}/leg:")
        for name, sub in [("H1", plan[:mid]), ("H2", plan[mid:])]:
            if not sub:
                continue
            trades = run(sub, by_ed, lot_of, intraday_params(slippage_per_leg=slip), costs)
            c, dd, ruin = _metrics(trades, MAX_LOTS, _years(sub))
            net = sum(t.net for t in trades) * MAX_LOTS
            print(f"     {name} {sub[0][0]}..{sub[-1][0]}  CAGR {_cagr(c, ruin):>7} | "
                  f"maxDD {dd:>3.0f}% | net ₹{net:>11,.0f}")


def main(argv=None) -> int:
    root = Path(argv[0]) if argv else Path("data/intraday/NIFTY")
    files = cycles(root)
    if not files:
        print(f"no expiry files under {root}", file=sys.stderr)
        return 1
    market, costs = MarketConfig(), CostConfig()
    lot_of = lambda e: market.lot_size("NIFTY", e)
    plan, by_ed = plan_days(files)
    if not plan:
        print("no tradeable days after the data floor", file=sys.stderr)
        return 1
    print(f"Intraday-only short strangle (never hold overnight). ₹{CAPITAL:,.0f}, "
          f"margin ~₹{MARGIN_PER_LOT:,.0f}/lot (VERIFY), {MAX_LOTS} lots, honest costs.\n")
    base_table(plan, by_ed, lot_of, costs)
    slippage_table(plan, by_ed, lot_of, costs)
    oos_table(plan, by_ed, lot_of, costs)
    print("\nVerdict: the in-sample ~30% is entirely H1 regime luck (H2 negative) AND a")
    print("pure execution bet (dead by ~20 ticks/leg). No durable edge — see docs/17.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
