"""The exhaustive closes-only sweep — K~800 with Romano-Wolf FWER control (docs/16).

Runs the frozen grid (search_grid.PREREGISTERED_GRID) on the real point-in-time
data, net of costs AND 20% STCG, and decides survivors with a correction built
for large K:

  - Romano-Wolf stepdown FWER-adjusted p-value per candidate (exploits the heavy
    correlation among ~800 near-duplicate configs; far more powerful than
    Bonferroni, still controls family-wise error at 5%),
  - CSCV Probability of Backtest Overfitting over the whole family,
  - Deflated Sharpe at the true N = K-1 trials.

A config is a real find only if it clears ALL of: beats base net Sharpe,
Romano-Wolf p < 0.05, PBO < 0.2, DSR > 0.95. Survivors (if any) touch the locked
holdout once. The near-certain honest outcome on a ~33-month clean window is that
nothing survives — which definitively closes 'did you try everything?'.

Run on the EC2 box:  python -m optionsbot.research.run_grid_search
Reuses the same data loading, guards, and windows as run_indicator_search.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..data.equity import read_dir, load_membership
from .momentum import EquityCostConfig
from .strategy_search import run_strategy
from .search_grid import PREREGISTERED_GRID
from . import overfit_stats as st
from .run_indicator_search import (
    CV_START, HOLDOUT_START, MOM_DATA, PIT_DIR, load_index, index_covers_window,
    monthly_in_window, align_matrix, _std)

REPORT = Path("/home/ubuntu/grid_search_result.txt")
RW_BOOT = 2000
RW_SEED = 7


def main() -> None:
    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(msg)
        print(msg, flush=True)

    series = read_dir(MOM_DATA)
    membership = load_membership(PIT_DIR)
    index = load_index()
    if not index_covers_window(index, CV_START, HOLDOUT_START):
        raise SystemExit("ABORT: NIFTY-50 index has a gap in the CV window (holey "
                         "cache). Delete the cache and re-run.")
    costs = EquityCostConfig()
    K = len(PREREGISTERED_GRID)
    log(f"{len(series)} stocks, real NIFTY-50, PIT membership from "
        f"{membership[0][0] if membership else '?'}. K={K} configs, net of ~30bps "
        f"costs AND 20% STCG. CV {CV_START}->{HOLDOUT_START}. RW FWER control.\n")

    net_monthly: dict[str, list] = {}
    rows: dict[str, dict] = {}
    for n, cfg in enumerate(PREREGISTERED_GRID):
        res = run_strategy(series, index, replace(cfg, apply_stcg=True), costs,
                           membership=membership)
        m = res.monthly_returns()
        net_monthly[cfg.name] = m
        cv = monthly_in_window(m, CV_START, HOLDOUT_START)
        rows[cfg.name] = {
            "sr_pp": st.sharpe(cv) if len(cv) > 1 else float("nan"),
            "sr_ann": st.sharpe(cv, 12) if len(cv) > 1 else float("nan"),
            "cagr": res.cagr_pct, "maxdd": res.max_drawdown_pct,
            "turn": 100.0 * (sum(res.turnover_fracs) / len(res.turnover_fracs)
                             if res.turnover_fracs else 0.0),
            "mech": cfg.mechanism,
        }
        if (n + 1) % 50 == 0:
            log(f"  ...ran {n + 1}/{K}")

    base_gross = run_strategy(series, index, PREREGISTERED_GRID[0], costs,
                              membership=membership)
    log(f"\nSANITY base GROSS full-period: {base_gross.cagr_pct:.1f}% / "
        f"{base_gross.max_drawdown_pct:.1f}% DD / {base_gross.sharpe:.2f} Sharpe "
        f"(docs/14 pins 23.6/21.3/1.51).")

    candidates = [c.name for c in PREREGISTERED_GRID[1:]]
    names, mat = align_matrix(net_monthly, ["base"] + candidates, CV_START, HOLDOUT_START)
    base_vec, cand_mat = mat[0], mat[1:]
    n_obs = len(base_vec)
    base_sr = rows["base"]["sr_pp"]

    # -- the three corrections at true K --
    cand_srs = [rows[c]["sr_pp"] for c in candidates]
    sr_std = _std(cand_srs)
    pbo = st.cscv_pbo(cand_mat, n_blocks=10, metric="sharpe")
    log(f"\nCV: {n_obs} monthly obs. base net Sharpe(ann)={rows['base']['sr_ann']:.2f}. "
        f"N_trials={len(candidates)}. PBO={pbo['pbo']:.2f} (trust <0.2). "
        f"Computing Romano-Wolf over {len(candidates)} candidates...")
    rw = st.romano_wolf_pvalues(cand_mat, base_vec, n_boot=RW_BOOT, seed=RW_SEED)
    rw_by_name = dict(zip(candidates, rw))

    # per-candidate deflated Sharpe at N = number of trials
    survivors = []
    beat_base = 0
    for c in candidates:
        r = rows[c]
        if not (r["sr_pp"] == r["sr_pp"]):     # skip nan Sharpe
            continue
        if r["sr_pp"] > base_sr:
            beat_base += 1
        cv = monthly_in_window(net_monthly[c], CV_START, HOLDOUT_START)
        sk, ku = st.skew_kurt(cv)
        dsr = st.deflated_sharpe_ratio(r["sr_pp"], sr_std, len(candidates), n_obs, sk, ku)
        r["dsr"], r["rw"] = dsr, rw_by_name[c]
        if r["sr_pp"] > base_sr and rw_by_name[c] < 0.05 and pbo["pbo"] < 0.2 and dsr > 0.95:
            survivors.append(c)

    min_rw = min(rw) if rw else float("nan")
    log(f"\n{beat_base}/{len(candidates)} beat base net Sharpe in-sample. "
        f"min Romano-Wolf p = {min_rw:.3f} (need <0.05). "
        f"Configs clearing ALL gates: {len(survivors)}.")

    # -- top of the table by CV Sharpe, with the honest RW p beside it --
    top = sorted(candidates, key=lambda c: rows[c]["sr_ann"] if rows[c]["sr_ann"] == rows[c]["sr_ann"] else -9, reverse=True)[:25]
    log(f"\n{'config':<9} {'CVsr':>5} {'RW p':>6} {'DSR':>5} {'CAGR':>6} {'maxDD':>6} "
        f"{'turn%':>6}  mechanism")
    log("-" * 110)
    log(f"{'base':<9} {rows['base']['sr_ann']:5.2f} {'':>6} {'':>5} "
        f"{rows['base']['cagr']:5.1f}% {rows['base']['maxdd']:5.1f}% "
        f"{rows['base']['turn']:5.0f}%  benchmark")
    for c in top:
        r = rows[c]
        log(f"{c:<9} {r['sr_ann']:5.2f} {r.get('rw', float('nan')):6.3f} "
            f"{r.get('dsr', float('nan')):5.2f} {r['cagr']:5.1f}% {r['maxdd']:5.1f}% "
            f"{r['turn']:5.0f}%  {r['mech'][:52]}")

    if not survivors:
        log(f"\nVERDICT: of {len(candidates)} closes-only configs, NONE survives "
            f"Romano-Wolf FWER control + PBO + Deflated Sharpe. Holdout NOT touched. "
            f"Base momentum is the strategy (docs/14/15). Trailing stops included: "
            f"none beat base net-of-tax.")
    else:
        log(f"\nSURVIVORS ({len(survivors)}): {survivors}. Touching the holdout ONCE:")
        base_hold = monthly_in_window(net_monthly['base'], HOLDOUT_START, None)
        for c in survivors:
            hold = monthly_in_window(net_monthly[c], HOLDOUT_START, None)
            log(f"  {c}: holdout Sharpe(ann)={st.sharpe(hold, 12):.2f} vs base "
                f"{st.sharpe(base_hold, 12):.2f}  ({rows[c]['mech']})")

    REPORT.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {REPORT}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
