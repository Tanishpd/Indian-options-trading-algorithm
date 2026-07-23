"""Disciplined indicator search — the box driver (docs/15).

Runs the frozen K=20 pre-registration (search_configs.PREREGISTERED) on the real
point-in-time data and applies the overfitting correction. The whole design is in
one place so the discipline is auditable:

  Tier 2 CROSS-VALIDATION (2022-09-30 -> 2025-06-30, PIT-clean): every candidate
    competes here, net of costs AND 20% STCG. A candidate is a real find only if
    it (a) beats base NET Sharpe, (b) survives the Deflated Sharpe correction for
    N=19 trials (DSR > 0.95), (c) sits in a low-overfitting search (PBO < 0.2),
    and (d) beats base in White's Reality Check (SPA p < 0.05).
  Tier 3 LOCKED HOLDOUT (2025-07-01 -> end): touched ONCE, on the single winner
    selected in Tier 2, or not at all if nothing clears CV.

Run on the EC2 box where the data lives:  python -m optionsbot.research.run_indicator_search
It refuses to run while a live paper session holds the Angel token, and never
falls back to the crude proxy index (docs/14).
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from ..data.equity import Series, load_membership, read_dir, read_series
from .momentum import EquityCostConfig
from .strategy_search import StrategyConfig, run_strategy
from .search_configs import PREREGISTERED
from . import overfit_stats as st

CV_START = date(2022, 9, 30)          # point-in-time-clean window opens here
HOLDOUT_START = date(2025, 7, 1)      # final ~12 months, touched once
MOM_DATA = Path("/home/ubuntu/mom_data")
PIT_DIR = Path("/home/ubuntu/nifty200_pit")
INDEX_CACHE = Path("/home/ubuntu/nifty50.csv")
NIFTY50_TOKEN = "99926000"
REPORT = Path("/home/ubuntu/indicator_search_result.txt")


# -- pure, testable helpers ------------------------------------------------

def monthly_in_window(monthly: list[tuple[date, float]], lo: date,
                      hi: date | None) -> list[float]:
    """The return values whose month-end date falls in (lo, hi]. `lo` is
    exclusive so the first in-window return is measured from a mark at/after lo."""
    return [r for d, r in monthly if d > lo and (hi is None or d <= hi)]


def align_matrix(monthlies: dict[str, list[tuple[date, float]]], names: list[str],
                 lo: date, hi: date | None) -> tuple[list[str], list[list[float]]]:
    """Build a name-ordered return matrix over the common month-end dates in the
    window, so every row is the same length on the same clock (needed by PBO/SPA)."""
    per_name = {n: dict(monthlies[n]) for n in names}
    common = sorted(set.intersection(*(set(d.keys()) for d in per_name.values())))
    common = [d for d in common if d > lo and (hi is None or d <= hi)]
    return names, [[per_name[n][d] for d in common] for n in names]


def fetch_windows(start: date, end: date, years: int = 5) -> list[tuple[date, date]]:
    """CONTIGUOUS (lo, hi) fetch windows covering [start, end] with no gaps.

    The first version advanced `lo` by `years` from `hi` instead of from `hi+1
    day`, which skipped an entire `years`-long block of history and left the
    index cache with a multi-year hole — silently corrupting the regime filter
    and residual momentum across exactly that span. This helper exists so that
    bug is a one-line, unit-tested invariant: consecutive windows must abut."""
    out: list[tuple[date, date]] = []
    lo = start
    while lo <= end:
        hi = min(date(lo.year + years, lo.month, lo.day), end)
        out.append((lo, hi))
        lo = hi + timedelta(days=1)
    return out


# -- data loading (box only) -----------------------------------------------

def _paper_session_running() -> bool:
    return subprocess.run(["pgrep", "-f", "optionsbot.paper"],
                          capture_output=True).returncode == 0


def load_index() -> Series:
    """Real NIFTY 50, cached to CSV so re-runs never re-hit Angel. Never the
    equal-weight proxy — it produced spurious cash signals (docs/14)."""
    if INDEX_CACHE.exists():
        return read_series(INDEX_CACHE, symbol="NIFTY50")
    if _paper_session_running():
        raise SystemExit("ABORT: live paper session holds the Angel token; not fetching.")
    import time
    from ..paper.credentials import load_credentials       # box-only imports
    from ..data.fetch_angel_history import _connect
    creds = load_credentials(None, aws_secret="tradingbot/angel", aws_region="ap-south-1")
    client = _connect(creds)
    seen: dict[str, float] = {}
    for lo, hi in fetch_windows(date(2016, 1, 1), date.today()):
        time.sleep(0.6)
        p = client.getCandleData({"exchange": "NSE", "symboltoken": NIFTY50_TOKEN,
                                  "interval": "ONE_DAY", "fromdate": f"{lo} 09:15",
                                  "todate": f"{hi} 15:30"})
        for row in (p or {}).get("data") or []:
            seen[str(row[0])[:10]] = float(row[4])
    if not seen:
        raise SystemExit("ABORT: NIFTY-50 fetch returned nothing.")
    ordered = sorted(seen)
    INDEX_CACHE.write_text("date,close\n" + "\n".join(f"{d},{seen[d]}" for d in ordered))
    return Series("NIFTY50", tuple(date.fromisoformat(d) for d in ordered),
                  tuple(seen[d] for d in ordered))


# -- the run ----------------------------------------------------------------

def _log(lines: list[str], msg: str) -> None:
    lines.append(msg)
    print(msg, flush=True)


def index_covers_window(index: Series, lo: date, hi: date, min_days: int = 100) -> bool:
    """The index must actually have bars across [lo, hi]. A cache with a gap here
    silently freezes the regime filter at a stale value and corrupts the whole
    CV — so refuse to run rather than trust a holey index."""
    return sum(1 for d in index.dates if lo <= d <= hi) >= min_days


def main() -> None:
    lines: list[str] = []
    series = read_dir(MOM_DATA)
    membership = load_membership(PIT_DIR)
    index = load_index()
    if not index_covers_window(index, CV_START, HOLDOUT_START):
        raise SystemExit(
            f"ABORT: NIFTY-50 index has too few bars in the CV window "
            f"{CV_START}..{HOLDOUT_START} (holey cache). Delete {INDEX_CACHE} and "
            f"re-run to re-fetch a contiguous series.")
    costs = EquityCostConfig()
    _log(lines, f"{len(series)} stocks, real NIFTY-50, PIT membership from "
                f"{membership[0][0] if membership else '?'}. Net of ~30bps costs "
                f"AND 20% STCG. CV {CV_START}->{HOLDOUT_START}, holdout after.\n")

    # Net-of-tax run for every config (this is the bar); gross base for the headline.
    net_monthly: dict[str, list[tuple[date, float]]] = {}
    rows: dict[str, dict] = {}
    for cfg in PREREGISTERED:
        net = run_strategy(series, index, replace(cfg, apply_stcg=True), costs,
                           membership=membership)
        m = net.monthly_returns()
        net_monthly[cfg.name] = m
        cv = monthly_in_window(m, CV_START, HOLDOUT_START)
        rows[cfg.name] = {
            "cv_sr_pp": st.sharpe(cv) if len(cv) > 1 else float("nan"),
            "cv_sr_ann": st.sharpe(cv, 12) if len(cv) > 1 else float("nan"),
            "cagr": net.cagr_pct, "maxdd": net.max_drawdown_pct,
            "turnover": 100.0 * (sum(net.turnover_fracs) / len(net.turnover_fracs)
                                 if net.turnover_fracs else 0.0),
            "tax": net.tax_paid, "n_cv": len(cv),
        }
        _log(lines, f"  ran {cfg.name:<14} CVsr(ann)={rows[cfg.name]['cv_sr_ann']:5.2f} "
                    f"fullCAGR={net.cagr_pct:5.1f}% fullDD={net.max_drawdown_pct:4.1f}%")

    base_gross = run_strategy(series, index, PREREGISTERED[0], costs, membership=membership)
    _log(lines, f"\nSANITY base GROSS full-period: {base_gross.cagr_pct:.1f}% CAGR / "
                f"{base_gross.max_drawdown_pct:.1f}% DD / {base_gross.sharpe:.2f} Sharpe "
                f"(docs/14 pinned 23.6/21.3/1.51).")

    # -- Tier 2 statistics on the CV window --
    candidates = [c.name for c in PREREGISTERED[1:]]
    names, mat = align_matrix(net_monthly, candidates, CV_START, HOLDOUT_START)
    _, base_and_mat = align_matrix(net_monthly, ["base"] + candidates, CV_START, HOLDOUT_START)
    base_vec, cand_mat = base_and_mat[0], base_and_mat[1:]
    n_obs = len(base_vec)

    cv_srs = [rows[n]["cv_sr_pp"] for n in names]
    sr_std = _std(cv_srs)
    base_sr_pp = rows["base"]["cv_sr_pp"]

    pbo = st.cscv_pbo(cand_mat, n_blocks=10, metric="sharpe")
    spa_p = st.reality_check_pvalue(cand_mat, base_vec, block_len=6.0, n_boot=5000, seed=7)

    _log(lines, f"\nCV window: {n_obs} monthly obs. base net Sharpe(ann)="
                f"{rows['base']['cv_sr_ann']:.2f}. N_trials={len(names)}. "
                f"PBO={pbo['pbo']:.2f} (trust <0.2). SPA p={spa_p:.3f} (>0.05 => "
                f"nothing beats base).")

    _log(lines, f"\n{'config':<14} {'CVsr':>5} {'DSR':>5} {'>base?':>6} {'fullCAGR':>8} "
                f"{'fullDD':>6} {'turn%':>6}  mechanism")
    _log(lines, "-" * 100)
    verdicts = []
    for n in ["base"] + names:
        r = rows[n]
        if n == "base":
            dsr = float("nan")
        else:
            sk, ku = st.skew_kurt(monthly_in_window(net_monthly[n], CV_START, HOLDOUT_START))
            dsr = st.deflated_sharpe_ratio(r["cv_sr_pp"], sr_std, len(names), n_obs, sk, ku)
        beats = "" if n == "base" else ("YES" if r["cv_sr_pp"] > base_sr_pp else "no")
        mech = next(c.mechanism for c in PREREGISTERED if c.name == n)
        _log(lines, f"{n:<14} {r['cv_sr_ann']:5.2f} {dsr:5.2f} {beats:>6} "
                    f"{r['cagr']:7.1f}% {r['maxdd']:5.1f}% {r['turnover']:5.0f}%  {mech[:40]}")
        if n != "base":
            verdicts.append((n, r["cv_sr_pp"], dsr))

    # -- selection: best CV Sharpe that clears every gate --
    winners = [(n, sr, dsr) for n, sr, dsr in verdicts
               if sr > base_sr_pp and dsr > 0.95 and pbo["pbo"] < 0.2 and spa_p < 0.05]
    winners.sort(key=lambda x: x[1], reverse=True)

    if not winners:
        _log(lines, "\nVERDICT: nothing beats base net-of-tax by a significant margin. "
                    "Holdout NOT touched. Ship base momentum (or the index fund to "
                    "avoid the STCG drag, docs/14 Option A).")
    else:
        win = winners[0][0]
        wcfg = next(c for c in PREREGISTERED if c.name == win)
        hold = monthly_in_window(net_monthly[win], HOLDOUT_START, None)
        base_hold = monthly_in_window(net_monthly["base"], HOLDOUT_START, None)
        _log(lines, f"\nWINNER on CV: {win}. Touching the holdout ONCE:")
        _log(lines, f"  {win}: holdout Sharpe(ann)={st.sharpe(hold, 12):.2f} vs "
                    f"base {st.sharpe(base_hold, 12):.2f}  ({wcfg.mechanism})")
        _log(lines, "  A holdout miss is the verdict; there is no re-search.")

    REPORT.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {REPORT}")


def _std(xs: list[float]) -> float:
    import statistics
    xs = [x for x in xs if x == x]           # drop nan
    return statistics.pstdev(xs) if len(xs) > 1 else 0.0


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
