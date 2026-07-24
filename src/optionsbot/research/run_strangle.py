"""Measure the naked short strangle for the ₹6L / 50%+ question (docs/17).

    python -m optionsbot.research.run_strangle data/intraday/NIFTY

Two studies. First: return vs the tail across strike offsets, holding to expiry
(the raw undefined-risk baseline). Second — because a real trader always runs a
stop — the SAME strangle at 1.5% OTM under a set of exit rules (stop-loss,
stop+target, trailing lock), so the owner can see whether risk management earns
its keep. Then a crash stress test: what a single 2%/6%/13% gap does, and the
crucial point that a stop-loss caps a GRIND but NOT a GAP.

No result here is a recommendation to sell naked options; it is a measurement of
the strategy the mandate forbids, so the cost of removing the cap is explicit.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

from ..config import CostConfig, MarketConfig
from ..data.intraday import read_csv
from .run_intraday import cycles
from .short_strangle import StrangleParams, StrangleStudy, run_cycle

CAPITAL = 600_000.0
MARGIN_PER_LOT = 140_000.0     # NIFTY naked-strangle SPAN+exposure, ~; VERIFY with broker
MAX_LOTS = int(CAPITAL // MARGIN_PER_LOT)


def load_all(files) -> list:
    return [(expiry, [b for b in read_csv(path) if b.expiry == expiry])
            for path, expiry in files]


def run(cached, lot_of, params: StrangleParams, costs: CostConfig) -> StrangleStudy:
    trades, skipped = [], {}
    for expiry, bars in cached:
        trade, why = run_cycle(bars, expiry, lot_of(expiry), params, costs)
        if trade is not None:
            trades.append(trade)
        else:
            skipped[why] = skipped.get(why, 0) + 1
    return StrangleStudy(trades=trades, skipped=skipped)


def _ann(study: StrangleStudy, lots: int, years: float) -> str:
    end = study.equity_curve(CAPITAL, lots)[-1]
    if min(study.equity_curve(CAPITAL, lots)) <= 0:
        return "RUINED"
    return f"{100 * ((end / CAPITAL) ** (1 / years) - 1):.1f}%"


def line(name: str, study: StrangleStudy, years: float) -> None:
    if not study.trades:
        print(f"  {name:<28} no trades"); return
    dd = study.max_drawdown(CAPITAL, MAX_LOTS)
    worst = study.worst_cycle * MAX_LOTS
    mix = " ".join(f"{k}:{v}" for k, v in sorted(study.exits().items()))
    print(f"  {name:<28} ann {_ann(study, MAX_LOTS, years):>7} | maxDD "
          f"{100*dd/CAPITAL:>3.0f}% | worst {100*worst/CAPITAL:>4.0f}% | "
          f"win {study.win_rate:>4.1f}% | {mix}")


def offset_table(cached, lot_of, costs, years) -> None:
    print("A) RETURN vs TAIL by strike offset (hold to expiry, no stop):")
    for off in (0.010, 0.015, 0.020):
        study = run(cached, lot_of, StrangleParams(offset_pct=off), costs)
        print(f"  offset {off*100:.1f}% OTM:")
        for lots in (1, MAX_LOTS):
            end = study.equity_curve(CAPITAL, lots)[-1]
            dd = study.max_drawdown(CAPITAL, lots)
            print(f"    {lots} lot: ann {_ann(study, lots, years):>7}  "
                  f"maxDD ₹{dd:>9,.0f} ({100*dd/CAPITAL:>3.0f}%)  "
                  f"worst ₹{study.worst_cycle*lots:>9,.0f}")


def management_table(cached, lot_of, costs, years) -> None:
    off = 0.015
    print(f"\nB) EXIT MANAGEMENT at {off*100:.1f}% OTM, {MAX_LOTS} lots "
          f"(₹{MAX_LOTS*MARGIN_PER_LOT:,.0f} margin) — the 50%-target sizing:")
    configs = [
        ("hold to expiry (no stop)", StrangleParams(offset_pct=off)),
        ("stop 2x credit", StrangleParams(offset_pct=off, stop_loss_mult=2.0)),
        ("stop 3x credit", StrangleParams(offset_pct=off, stop_loss_mult=3.0)),
        ("stop 2x + target 50%",
         StrangleParams(offset_pct=off, stop_loss_mult=2.0, profit_target_frac=0.5)),
        ("trail 50% profit-lock", StrangleParams(offset_pct=off, trail_stop_frac=0.5)),
    ]
    for name, p in configs:
        line(name, run(cached, lot_of, p, costs), years)


def stress(cached, lot_of, costs) -> None:
    study = run(cached, lot_of, StrangleParams(offset_pct=0.015), costs)
    if not study.trades:
        return
    credit = statistics.median(t.credit for t in study.trades)
    spot = statistics.median(t.final_spot for t in study.trades)
    offset = statistics.median((t.short_call - t.short_put) / 2.0 for t in study.trades) / spot
    sc, sp = spot * (1 + offset), spot * (1 - offset)
    lot = lot_of(cached[-1][0])
    print(f"\nC) CRASH STRESS — open strangle spot ~{spot:,.0f}, strikes "
          f"~{sp:,.0f}/{sc:,.0f}, credit ~₹{credit:.0f}, lot {lot}. A stop-loss does"
          f"\n   NOT help here: a gap jumps past the strike overnight, so you exit at"
          f"\n   the gapped price — the loss below is what you eat, stop or no stop.")
    for label, gap in [("-2% (ordinary bad week)", -0.02),
                       ("-6% (2024 election, intraday)", -0.06),
                       ("-13% (2020 COVID, worst day)", -0.13)]:
        final = spot * (1 + gap)
        intrinsic = max(0.0, final - sc) + max(0.0, sp - final)
        loss1 = (credit - intrinsic) * lot
        lossN = loss1 * MAX_LOTS
        print(f"   {label:<32} 1 lot ₹{loss1:>9,.0f} ({100*loss1/CAPITAL:>5.0f}%)   "
              f"{MAX_LOTS} lots ₹{lossN:>10,.0f} ({100*lossN/CAPITAL:>5.0f}%)")


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]) if argv else Path("data/intraday/NIFTY")
    files = cycles(root)
    if not files:
        print(f"no expiry files under {root}", file=sys.stderr)
        return 1
    years = (files[-1][1] - files[0][1]).days / 365.25
    market, costs = MarketConfig(), CostConfig()
    lot_of = lambda e: market.lot_size("NIFTY", e)
    cached = load_all(files)
    print(f"{len(files)} NIFTY weekly cycles, {files[0][1]}..{files[-1][1]} "
          f"({years:.2f}y), ₹{CAPITAL:,.0f}, margin ~₹{MARGIN_PER_LOT:,.0f}/lot "
          f"(VERIFY), max {MAX_LOTS} lots, honest slippage.\n")
    offset_table(cached, lot_of, costs, years)
    management_table(cached, lot_of, costs, years)
    stress(cached, lot_of, costs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
