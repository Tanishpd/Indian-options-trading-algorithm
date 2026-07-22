"""Read forward records and report what they actually support.

    python -m optionsbot.research.forward_report var/forward

This module exists to say "not yet" more often than it says anything else.

Every failure in this project was a result that looked real and was not
(docs/10-13): an IV filter that was three trades in one window; a risk cap
acting as a hidden premium selector worth Rs 4,474; a calendar spread 98% of
whose gross came from 5 of 49 trades; a stock-option result 90% of which was
ONE trade priced off FOUR contracts; and a naked strangle showing 21.5%/yr at
t = 2.49 with the holdout holding, which was uncompensated tail risk that one
gap would have ended.

That last one is why this report leads with power rather than with return. It
passed every test in this file. **The statistics could not distinguish a real
edge from insurance that had not yet paid out**, and no amount of forward data
fixes that on its own — it needs the observation window to contain the event.

So the report refuses to editorialise. It shows the number of observations, the
detectable effect size at that sample, the cost drag, and the worst outcome
seen — and it states plainly when the record cannot yet support a conclusion.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ..paper.journal import read, strategies

# Below this, a difference from zero is not measurable at any effect size worth
# trading. Chosen to be uncomfortable rather than reassuring.
MIN_CYCLES_FOR_ANY_CLAIM = 30


def _cycles(entries: list[dict]) -> list[dict]:
    """Collapse ticks into completed round trips, keyed by expiry.

    A cycle is closed when the book returns to flat having been non-flat. Ticks
    while flat carry no information about the strategy's edge.
    """
    out, open_cycle = [], None
    for e in entries:
        held = e.get("positions", 0) > 0
        if held and open_cycle is None:
            open_cycle = {"expiry": e["expiry"], "start": e["ts"],
                          "start_equity": e["equity"],
                          "start_costs": e["realised_costs"]}
        elif not held and open_cycle is not None:
            open_cycle.update(end=e["ts"], end_equity=e["equity"],
                              pnl=e["equity"] - open_cycle["start_equity"],
                              costs=e["realised_costs"] - open_cycle["start_costs"])
            out.append(open_cycle)
            open_cycle = None
    return out


def _drawdown(equity: list[float]) -> float:
    peak = worst = 0.0
    peak = equity[0] if equity else 0.0
    for x in equity:
        peak = max(peak, x)
        worst = max(worst, peak - x)
    return worst


def report_one(name: str, entries: list[dict], capital: float) -> None:
    entries = sorted(entries, key=lambda e: e["ts"])
    if not entries:
        print(f"\n{name}: no observations")
        return

    cycles = _cycles(entries)
    eq = [e["equity"] for e in entries]
    span_days = (datetime.fromisoformat(entries[-1]["ts"])
                 - datetime.fromisoformat(entries[0]["ts"])).days

    print(f"\n=== {name} ===")
    print(f"  observations   {len(entries):,} ticks over {span_days} days, "
          f"{len(cycles)} completed cycles")
    print(f"  equity         Rs {eq[-1]:,.0f}  (started Rs {eq[0]:,.0f})")
    print(f"  P&L            Rs {eq[-1] - eq[0]:>+,.0f}")
    print(f"  costs paid     Rs {entries[-1]['realised_costs']:,.0f}")
    print(f"  max drawdown   Rs {_drawdown(eq):,.0f}  "
          f"({100 * _drawdown(eq) / capital:.1f}% of capital)")

    halted = [e for e in entries if e.get("note", "").startswith("error")]
    if halted:
        print(f"  !! HALTED      {halted[-1]['note']}")

    if not cycles:
        print("  verdict        no completed cycle yet — nothing to assess")
        return

    pnl = [c["pnl"] for c in cycles]
    worst = min(pnl)
    print(f"  per cycle      mean Rs {statistics.mean(pnl):>+,.0f}   "
          f"worst Rs {worst:>+,.0f}")

    if len(pnl) < 2:
        print("  verdict        one cycle — no dispersion, nothing to assess")
        return

    sd = statistics.stdev(pnl)
    se = sd / len(pnl) ** 0.5
    t = statistics.mean(pnl) / se if se else float("nan")
    # Effect size this sample could detect at 80% power, two-sided.
    mde = 2.8 * se
    print(f"  dispersion     sd Rs {sd:,.0f}   t = {t:+.2f}")
    print(f"  detectable     Rs {mde:,.0f}/cycle at 80% power "
          f"— anything smaller is invisible at n={len(pnl)}")

    if len(cycles) < MIN_CYCLES_FOR_ANY_CLAIM:
        need = MIN_CYCLES_FOR_ANY_CLAIM - len(cycles)
        print(f"  verdict        NOT ASSESSABLE — {len(cycles)} cycles, "
              f"need {need} more before any claim is meaningful")
        return

    # Concentration: is the result carried by a handful of cycles?
    top = sorted(pnl, reverse=True)[:3]
    share = 100 * sum(top) / sum(pnl) if sum(pnl) else float("nan")
    print(f"  concentration  top 3 cycles are {share:.0f}% of total P&L "
          f"{'— FRAGILE' if share > 60 else ''}")

    print("  verdict        n is adequate; read t, drawdown, concentration and "
          "worst cycle together.")
    print("                 NOTE: a good t-statistic cannot rule out a "
          "short-gamma tail\n                 that has not occurred yet "
          "(docs/13). Check the worst cycle\n                 against what a "
          "gap twice that size would do.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path, help="forward-record directory")
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--strategy", default=None, help="limit to one strategy")
    args = ap.parse_args(argv)

    names = [args.strategy] if args.strategy else strategies(args.root)
    if not names:
        print(f"no forward records under {args.root}", file=sys.stderr)
        return 1

    grouped: dict[str, list[dict]] = defaultdict(list)
    for e in read(args.root, args.strategy):
        grouped[e["strategy"]].append(e)

    for name in names:
        report_one(name, grouped.get(name, []), args.capital)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
