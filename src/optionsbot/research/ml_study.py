"""Does machine learning find an edge the statistics missed? (docs/19)

The owner asked whether "the best ML model" could rescue the intraday strangle. This
runs that question properly, on the real 345-day intraday dataset, and answers it three
ways so the null cannot be waved away:

1. **A wide sweep under honest out-of-sample discipline.** 14 model configs (regularized
   logistic at four strengths, ridge at three, gradient boosting, random forest, kNN,
   SVM) evaluated by true WALK-FORWARD: at each step the scaler AND the model are refit
   on the expanding training slice only, then used to predict the next block. No model
   ever sees its own test rows, and nothing is standardized using future data.
2. **A permutation null, resampled WITHIN the test region.** A model that trades k of
   the N out-of-sample days is compared against drawing k days at random from those same
   N days. The first version of this study shuffled labels across the WHOLE series and
   re-ran the walk-forward, which quietly dragged the profitable early regime into the
   test-window null, inflating it and therefore inflating every p-value (the winner's
   went 0.018 -> 0.875). Resample only from the pool the model actually chose from.
3. **A POSITIVE CONTROL.** A null is only worth believing if the harness could have
   found an edge had one existed, so the same machinery is re-run against a synthetic
   target with a deliberately injected signal. If it detects that and not the real
   thing, the real thing isn't there.

The result (docs/19): no model beats simply trading every day once multiple testing is
accounted for; the best is beaten by ~87% of pure noise; the Deflated Sharpe is far
below significance; and the highest-capacity model (gradient boosting) is the WORST —
the signature of overfitting 300-odd noisy samples. The positive control passes at
p=0.000, so the harness is not blind.

Requires the optional research extra (numpy/scikit-learn/scipy), which is deliberately
NOT a runtime dependency — the bot itself runs on the standard library:

    pip install -e '.[research]'
    python -m optionsbot.research.ml_study data/intraday/NIFTY
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

from ..config import CostConfig, MarketConfig
from .intraday_only import intraday_params, plan_days, run
from .run_intraday import cycles

SEED = 7
NDRAW = 20000          # random k-of-test-region draws forming the null
INIT_FRAC = 0.4        # first 40% of days seed the expanding window
STEP = 5               # predict 5 days, then refit


def _require_sklearn():
    """Import the research stack, or explain how to get it."""
    try:
        import numpy  # noqa: F401
        import sklearn  # noqa: F401
        from scipy.stats import norm  # noqa: F401
    except ImportError as exc:                       # pragma: no cover - env dependent
        raise SystemExit(
            "this study needs the optional research extra:\n"
            "    pip install -e '.[research]'\n"
            f"(missing: {exc.name})"
        ) from exc


def build_dataset(root: Path, slippage: float = 0.50):
    """Per-day feature rows + the strangle's realized net for that day.

    Every feature is knowable BEFORE the trade is managed: trailing realized vol and
    trend from prior closes, the overnight gap, the morning's credit (an implied-vol
    proxy), calendar position, and the previous days' results.
    """
    import numpy as np

    files = cycles(root)
    market, costs = MarketConfig(), CostConfig()
    plan, by_ed = plan_days(files)
    trades = run(plan, by_ed, lambda e: market.lot_size("NIFTY", e),
                 intraday_params(slippage_per_leg=slippage), costs)
    recs = sorted(({"date": t.entered_at.date(), "net": t.net, "credit": t.credit,
                    "espot": (t.short_call + t.short_put) / 2.0, "xspot": t.final_spot,
                    "dte": (t.expiry - t.entered_at.date()).days,
                    "dow": t.entered_at.weekday()} for t in trades),
                  key=lambda r: r["date"])

    def rvol(i, w):
        return statistics.pstdev(
            [recs[j]["espot"] / recs[j - 1]["espot"] - 1 for j in range(i - w + 1, i + 1)]
        )

    feats, nets, dates = [], [], []
    for i in range(20, len(recs)):
        feats.append([
            rvol(i, 5), rvol(i, 10), rvol(i, 20),
            recs[i]["espot"] / recs[i - 5]["espot"] - 1,
            recs[i]["espot"] / recs[i - 10]["espot"] - 1,
            recs[i]["espot"] / recs[i - 1]["xspot"] - 1,
            abs(recs[i]["espot"] / recs[i - 1]["xspot"] - 1),
            recs[i]["credit"],
            recs[i]["credit"] / (rvol(i, 5) + 1e-9),
            float(recs[i]["dte"]), float(recs[i]["dow"]),
            recs[i - 1]["net"], recs[i - 2]["net"],
        ])
        nets.append(recs[i]["net"])
        dates.append(recs[i]["date"])
    return np.array(feats), np.array(nets), dates


def walk_forward(X, y_cls, y_net, factory, kind, init_frac=INIT_FRAC, step=STEP):
    """Expanding-window OOS predictions. Refits scaler+model on [0:i] only — the one
    place leakage would enter, and the reason it cannot."""
    import numpy as np
    from sklearn.preprocessing import StandardScaler

    n = len(X)
    preds = np.zeros(n, dtype=bool)
    tested = np.zeros(n, dtype=bool)
    i = int(n * init_frac)
    while i < n:
        j = min(i + step, n)
        scaler = StandardScaler().fit(X[:i])                 # train slice ONLY
        model = factory()
        if kind == "cls":
            if len(np.unique(y_cls[:i])) < 2:
                p = np.ones(j - i, dtype=bool)
            else:
                model.fit(scaler.transform(X[:i]), y_cls[:i])
                p = model.predict(scaler.transform(X[i:j])).astype(bool)
        else:
            model.fit(scaler.transform(X[:i]), y_net[:i])
            p = model.predict(scaler.transform(X[i:j])) > 0
        preds[i:j] = p
        tested[i:j] = True
        i = j
    return preds, tested


def sweep():
    """The 14 configs. Deliberately spans capacity: heavily-regularized linear through
    tree ensembles and kernel SVM, so 'you didn't try a good enough model' is answered."""
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.svm import SVC

    return {
        "logistic C=.03": ("cls", lambda: LogisticRegression(C=0.03, max_iter=2000)),
        "logistic C=.1": ("cls", lambda: LogisticRegression(C=0.1, max_iter=2000)),
        "logistic C=.3": ("cls", lambda: LogisticRegression(C=0.3, max_iter=2000)),
        "logistic C=1": ("cls", lambda: LogisticRegression(C=1.0, max_iter=2000)),
        "ridge a=1": ("reg", lambda: Ridge(alpha=1.0)),
        "ridge a=10": ("reg", lambda: Ridge(alpha=10.0)),
        "ridge a=50": ("reg", lambda: Ridge(alpha=50.0)),
        "gboost d2": ("cls", lambda: GradientBoostingClassifier(
            max_depth=2, n_estimators=50, learning_rate=0.05, subsample=0.8, random_state=0)),
        "gboost d3": ("cls", lambda: GradientBoostingClassifier(
            max_depth=3, n_estimators=80, learning_rate=0.05, subsample=0.8, random_state=0)),
        "rforest d3": ("cls", lambda: RandomForestClassifier(
            max_depth=3, n_estimators=300, min_samples_leaf=10, random_state=0)),
        "rforest d5": ("cls", lambda: RandomForestClassifier(
            max_depth=5, n_estimators=300, min_samples_leaf=8, random_state=0)),
        "knn k=15": ("cls", lambda: KNeighborsClassifier(n_neighbors=15)),
        "svm rbf": ("cls", lambda: SVC(C=1.0, kernel="rbf")),
        "svm linear": ("cls", lambda: SVC(C=0.3, kernel="linear")),
    }


def positive_control(X, rng):
    """Re-run the harness against an injected edge. If this is not detected, a null on
    the real data would mean nothing."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    trend = X[:, 3]                                        # the 5-day trend column
    synth = np.where(trend < 0, 400.0, -400.0) + rng.normal(0, 300, len(X))
    cls = (synth > 0).astype(int)
    fac, kind = (lambda: LogisticRegression(C=0.1, max_iter=2000)), "cls"
    preds, tested = walk_forward(X, cls, synth, fac, kind)
    base = float(synth[tested].sum())
    gated = float(synth[tested & preds].sum())
    pool = synth[tested]
    k = int((tested & preds).sum())
    if not (0 < k < len(pool)):
        return base, gated, float("nan")
    draws = np.array([rng.choice(pool, k, replace=False).sum() for _ in range(NDRAW)])
    return base, gated, float(np.mean(draws >= gated))


def main(argv=None) -> int:
    _require_sklearn()
    import numpy as np
    from scipy.stats import kurtosis, norm, skew

    root = Path(argv[0]) if argv else Path("data/intraday/NIFTY")
    if not cycles(root):
        print(f"no expiry files under {root}", file=sys.stderr)
        return 1
    rng = np.random.default_rng(SEED)
    X, ynet, _ = build_dataset(root)
    ycls = (ynet > 0).astype(int)
    n = len(X)

    tested0 = np.zeros(n, dtype=bool)
    tested0[int(n * INIT_FRAC):] = True
    base = float(ynet[tested0].sum())
    days = int(tested0.sum())
    configs = sweep()
    print(f"{n} usable days; walk-forward OOS over {days} days (refit every {STEP}).")
    print(f"ALWAYS-TRADE OOS net = {base:,.0f} (1 lot). {len(configs)} configs tried.\n")
    pool = ynet[tested0].astype(float)

    def null_p(gated: float, k: int) -> float:
        """Draw k days at random FROM THE TEST REGION — the pool the model chose from."""
        if not (0 < k < len(pool)):
            return float("nan")
        draws = np.array([rng.choice(pool, k, replace=False).sum() for _ in range(NDRAW)])
        return float(np.mean(draws >= gated))

    print(f"  {'model':<16} {'gated net':>11} {'trades':>9} {'daily SR':>9} {'vs base':>9} {'p':>8}")
    print("  " + "-" * 70)

    results = []
    for name, (kind, fac) in configs.items():
        preds, tested = walk_forward(X, ycls, ynet, fac, kind)
        sel = tested & preds
        g = float(ynet[sel].sum())
        r = ynet[sel].astype(float)
        sr = 0.0 if len(r) < 2 or r.std() == 0 else float(r.mean() / r.std())
        p = null_p(g, int(sel.sum()))
        results.append((name, g, int(sel.sum()), sr, kind, fac, p))
        print(f"  {name:<16} {g:>11,.0f} {str(int(sel.sum()))+'/'+str(days):>9} "
              f"{sr:>9.3f} {g - base:>+9,.0f} {p:>8.4f}")

    results.sort(key=lambda t: -t[1])
    best = results[0]
    p_perm = best[6]
    print(f"\nBest by OOS net: {best[0]} ({best[1]:,.0f}, vs base {best[1]-base:+,.0f}), "
          f"p={p_perm:.4f} against random selection of the same {best[2]} days.")
    skipped = ynet[tested0 & ~walk_forward(X, ycls, ynet, best[5], best[4])[0]]
    if len(skipped) <= 5:
        print(f"  NB: it skipped only {len(skipped)} day(s) "
              f"({', '.join(f'{v:,.0f}' for v in skipped)}) — that is one decision, not a strategy.")

    sel = walk_forward(X, ycls, ynet, best[5], best[4])
    r = ynet[sel[1] & sel[0]].astype(float)
    if len(r) > 2 and r.std() > 0:
        sr, T = r.mean() / r.std(), len(r)
        srs = np.array([t[3] for t in results])
        var_sr = float(srs.var()) or 1e-6
        K = len(configs)
        emc = 0.5772156649
        z = (1 - emc) * norm.ppf(1 - 1.0 / K) + emc * norm.ppf(1 - 1.0 / (K * np.e))
        sr0 = np.sqrt(var_sr) * z
        num = (sr - sr0) * np.sqrt(T - 1)
        den = np.sqrt(1 - float(skew(r)) * sr + (float(kurtosis(r, fisher=False)) - 1) / 4.0 * sr ** 2)
        print(f"Deflated Sharpe (best of K={K}, T={T}): DSR={float(norm.cdf(num/den)):.3f} "
              f"(need > 0.95; benchmark SR0={sr0:.3f}, observed SR={sr:.3f}).")

    pc_base, pc_gated, pc_p = positive_control(X, rng)
    print(f"\nPOSITIVE CONTROL (injected edge): base {pc_base:,.0f} -> gated {pc_gated:,.0f} "
          f"({pc_gated-pc_base:+,.0f}), permutation p={pc_p:.3f}")
    print(f"  harness has power: {'YES' if (pc_gated > pc_base and pc_p < 0.05) else 'NO'}")

    survived = best[1] > base and p_perm < 0.05 / len(configs)
    print(f"\nVERDICT: any model beats always-trade AND clears Bonferroni? "
          f"{'YES' if survived else 'NO'} — see docs/19.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
