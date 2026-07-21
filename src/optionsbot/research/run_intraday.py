"""Runner for the intraday condor study — regenerates the docs/11 figures.

    python -m optionsbot.research.run_intraday data/intraday/NIFTY

Exists because the first version of these findings was produced by a throwaway
script. A published number nobody can regenerate is not evidence, and docs/11 is
the project's evidence base (mandate rule 5).

Reports every configuration twice, with the per-trade cap applied and without.
That is not decoration: entry waits until the structure is cheap enough to fit
the cap, which makes the cap an undeclared "enter only when premium is rich"
filter. On the committed data it rejects 50.9% of candidate entry minutes and
drops the quiet weeks — traded cycles average 12.18% realised volatility against
7.20% for dropped ones. Reporting only the capped figure understates the loss by
about 40%.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from datetime import date, datetime
from pathlib import Path

from ..config import CostConfig, MarketConfig, RiskConfig
from ..data.intraday import read_csv
from .intraday_condor import IntradayParams, IntradayStudy, run_expiry

START = date(2024, 11, 1)          # lot sizes and expiry weekdays changed here
NO_CAP = RiskConfig(per_trade_max_loss_rupees=10 ** 9)


def cycles(root: Path) -> list[tuple[Path, date]]:
    out = []
    for path in sorted(root.glob("*_*.csv")):
        try:
            expiry = datetime.strptime(path.stem.split("_")[-1], "%Y%m%d").date()
        except ValueError:
            continue
        if expiry >= START:
            out.append((path, expiry))
    return out


def run(files, index: str, params: IntradayParams, costs: CostConfig,
        risk: RiskConfig, market: MarketConfig) -> IntradayStudy:
    trades, skipped = [], {}
    for path, expiry in files:
        bars = [b for b in read_csv(path) if b.expiry == expiry]
        trade, why = run_expiry(bars, expiry, market.lot_size(index, expiry),
                                params, costs, risk)
        if trade is not None:
            trades.append(trade)
        else:
            skipped[why] = skipped.get(why, 0) + 1
    return IntradayStudy(trades=trades, skipped=skipped)


def report(tag: str, study: IntradayStudy, start_capital: float) -> None:
    n = len(study.trades)
    if not n:
        print(f"{tag:<34} no trades ({study.skipped})")
        return
    nets = [t.net for t in study.trades]
    sd = statistics.stdev(nets) if n > 1 else 0.0
    t = statistics.mean(nets) / (sd / n ** 0.5) if sd else float("nan")
    mix = " ".join(f"{k}:{v}" for k, v in sorted(study.exits().items()))
    print(f"{tag:<34} n={n:>3} gross={study.gross:>9,.0f} costs={study.costs:>8,.0f} "
          f"net={study.net:>9,.0f} t={t:>5.2f} win={study.win_rate:>5.1f}% "
          f"dd={study.max_drawdown(start_capital):>8,.0f}  [{mix}]")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path, help="directory of per-expiry minute CSVs")
    ap.add_argument("--index", default="NIFTY")
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--slippage", type=float, default=IntradayParams().slippage_per_leg,
                    help="points given up per leg, each way (default models a real spread)")
    ap.add_argument("--targets", type=float, nargs="+", default=[0.25, 0.50, 0.75])
    ap.add_argument("--stops", type=float, nargs="+", default=[0.40, 0.60, 0.80])
    args = ap.parse_args(argv)

    files = cycles(args.root)
    if not files:
        print(f"no expiry files under {args.root}", file=sys.stderr)
        return 1
    print(f"{len(files)} expiry cycles, {files[0][1]} .. {files[-1][1]}, "
          f"slippage {args.slippage}/leg\n")

    costs, market = CostConfig(), MarketConfig()
    for tf in args.targets:
        for sf in args.stops:
            params = IntradayParams(profit_target_frac=tf, stop_loss_frac=sf,
                                    slippage_per_leg=args.slippage)
            for label, risk in (("cap on ", RiskConfig()), ("cap off", NO_CAP)):
                report(f"target {tf:.2f} stop {sf:.2f} {label}",
                       run(files, args.index, params, costs, risk, market),
                       args.capital)
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
