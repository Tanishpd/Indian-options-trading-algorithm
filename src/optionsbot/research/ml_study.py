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


def positive_control(X):
    """Re-run the harness against an injected edge. If this is not detected, a null on
    the real data would mean nothing.

    Uses its OWN generator: sharing the sweep's `rng` made the synthetic target depend on
    how many draws the sweep had already consumed, so changing NDRAW silently changed
    this experiment (and left stale numbers in the writeup).

    NOTE the limit of this check: the injected edge is large. It proves the harness is
    not BROKEN; it does not prove sensitivity at the effect size actually of interest.
    See `power_table` for that.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    rng = np.random.default_rng(SEED + 1)                  # independent of the sweep
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


def _null_moments(pool, k):
    """Exact finite-population mean/sd of a k-of-N sum drawn without replacement."""
    import numpy as np

    N = len(pool)
    mu = k * pool.mean()
    sd = pool.std(ddof=1) * np.sqrt(k * (N - k) / (N - 1))
    return float(mu), float(sd)


def romano_wolf(pool, masks, observed, rng, ndraw=50000):
    """Romano-Wolf / Westfall-Young max-T adjusted p for the BEST config.

    Bonferroni is the wrong tool here twice over: it ignores the severe dependence
    between 14 near-identical configs, and for a model that skips only 1 of N days the
    smallest attainable p is 1/N — which can exceed the Bonferroni bar, making the
    "rejection" a resolution artifact rather than evidence. Max-T fixes both by using
    ONE permutation per draw applied to every config (preserving cross-model
    dependence) and studentizing so configs with different k are comparable. This is
    also the correction docs/16 already adopted for this project.
    """
    import numpy as np

    N = len(pool)
    stats, moments = [], []
    for m, obs in zip(masks, observed):
        k = int(m.sum())
        if not (0 < k < N):
            continue
        mu, sd = _null_moments(pool, k)
        if sd <= 0:
            continue
        stats.append((m, (obs - mu) / sd))
        moments.append((k, mu, sd))
    if not stats:
        return float("nan")
    t_obs = max(t for _, t in stats)
    hits = 0
    for _ in range(ndraw):
        perm = rng.permutation(pool)                       # ONE draw, shared by all
        t_max = max((perm[m].sum() - mu) / sd
                    for (m, _), (k, mu, sd) in zip(stats, moments))
        if t_max >= t_obs:
            hits += 1
    return hits / ndraw


def power_table(pool, ks=(50, 100, 150, 193), alpha=0.05, bar=None):
    """Minimum detectable improvement at 80% power, per gate size.

    The point the positive control cannot make: what size of REAL edge this sample
    could actually certify. If that number dwarfs a mandate-sized edge, the study can
    only rule out a large edge — which is the honest (and more damning) reading.
    """
    import numpy as np
    from scipy.stats import norm

    z_pow = norm.ppf(0.80)
    out = []
    for k in ks:
        if not (0 < k < len(pool)):
            continue
        _, sd = _null_moments(pool, k)
        mde_a = (norm.ppf(1 - alpha) + z_pow) * sd
        mde_b = (norm.ppf(1 - bar) + z_pow) * sd if bar else float("nan")
        out.append((k, sd, mde_a, mde_b))
    return out


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
        preds, tested = walk_forward(X, ycls, ynet, fac, kind)   # computed ONCE, cached
        sel = tested & preds
        g = float(ynet[sel].sum())
        r = ynet[sel].astype(float)
        sr = 0.0 if len(r) < 2 or r.std() == 0 else float(r.mean() / r.std())
        p = null_p(g, int(sel.sum()))
        results.append((name, g, int(sel.sum()), sr, kind, fac, p, sel))
        print(f"  {name:<16} {g:>11,.0f} {str(int(sel.sum()))+'/'+str(days):>9} "
              f"{sr:>9.3f} {g - base:>+9,.0f} {p:>8.4f}")

    results.sort(key=lambda t: -t[1])
    best = results[0]
    p_perm = best[6]
    print(f"\nBest by OOS net: {best[0]} ({best[1]:,.0f}, vs base {best[1]-base:+,.0f}), "
          f"marginal p={p_perm:.4f} vs random selection of the same {best[2]} days.")
    skipped = ynet[tested0 & ~best[7]]
    if len(skipped) <= 5 and len(skipped) > 0:
        worse = int((pool <= skipped.min()).sum())
        print(f"  NB: it skipped only {len(skipped)} day(s) "
              f"({', '.join(f'{v:,.0f}' for v in skipped)}) — one decision, not a strategy. "
              f"That day ranks {worse} of {days} worst, so the exact p is {worse}/{days}"
              f"={worse/days:.4f}, and the FLOOR for any 1-skip model is 1/{days}"
              f"={1/days:.5f}.")

    # Romano-Wolf max-T across the whole family — the correction docs/16 uses, and the
    # one that is not defeated by the 1/N resolution floor above.
    rw = romano_wolf(pool, [t[7][tested0] for t in results],
                     [t[1] for t in results], rng)
    print(f"Romano-Wolf adjusted p (best of K={len(results)}, dependence-aware): {rw:.3f}"
          f"  <- headline; Bonferroni {0.05/len(configs):.5f} is unreachable for a 1-skip model")

    r = ynet[best[7]].astype(float)
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

    pc_base, pc_gated, pc_p = positive_control(X)
    print(f"\nPOSITIVE CONTROL (LARGE injected edge): base {pc_base:,.0f} -> gated "
          f"{pc_gated:,.0f} ({pc_gated-pc_base:+,.0f}), p={pc_p:.3f}")
    print(f"  harness is not blind: {'YES' if (pc_gated > pc_base and pc_p < 0.05) else 'NO'}"
          f" (proves integrity, NOT sensitivity at a small effect — see power below)")

    print(f"\nPOWER — minimum detectable improvement at 80% power (1 lot, {days} OOS days):")
    print(f"  {'gate size k':>12} {'null sd':>10} {'MDE @a=.05':>12} {'MDE @Bonf':>12}")
    for k, sd, mde_a, mde_b in power_table(pool, bar=0.05 / len(configs)):
        print(f"  {str(k)+'/'+str(days):>12} {sd:>10,.0f} {mde_a:>12,.0f} {mde_b:>12,.0f}")
    print("  A mandate-sized edge (~20-25%/yr, i.e. ~Rs 19k over this window) is BELOW")
    print("  these thresholds: this sample cannot certify one even if it existed.")

    # INIT_FRAC is a free parameter and the BENCHMARK is sensitive to it (the model's
    # own contribution is not). Disclosing it stops "an already-losing stretch" from
    # being quoted as a property of the period rather than of where the cut was placed.
    print("\nFREE-PARAMETER CHECK — always-trade net by INIT_FRAC (benchmark is cut-dependent):")
    for f in (0.30, 0.35, 0.40, 0.45, 0.50):
        m = np.zeros(n, dtype=bool); m[int(n * f):] = True
        print(f"  INIT_FRAC={f:.2f}: {int(m.sum()):>3} OOS days, always-trade "
              f"{float(ynet[m].sum()):>+9,.0f}")

    profitable = sum(1 for t in results if t[1] > 0)
    print(f"\nVERDICT: {profitable}/{len(results)} models profitable; best Romano-Wolf "
          f"adjusted p = {rw:.3f}. No usable edge — and note the load-bearing fact is the")
    print("economic one (nothing made money), not the p-value. See docs/19.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
