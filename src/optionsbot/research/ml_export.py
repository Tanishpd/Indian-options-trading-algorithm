"""Freeze a trained gating model into a stdlib-loadable artifact (docs/19 forward test).

The offline study (docs/19) found no ML edge in HISTORY. This exports a model anyway so
the question can be re-asked FORWARD, where the data does not exist yet and therefore
cannot be overfit — the same reasoning that justifies the whole shadow-evaluator harness.

Design constraints that shape this file:

- **The box is stdlib-only** (`dependencies = []`). scikit-learn trains here, offline, and
  ships nothing but numbers: feature means/stds, coefficients, an intercept and a
  threshold. Inference on the box is a dot product through `math.exp` — no numpy.
- **Only live-computable features.** The study's 13 features include the previous two
  days' strategy P&L, which the live strategy cannot know without depending on another
  shadow's journal. The first 11 features need nothing but ~20 days of daily spot history
  and the morning's own quoted credit, so those are what get frozen.
- **Pre-registered choice, not a tuned one.** Regularized logistic at C=0.1, threshold
  0.5, trained on every available day. Picking the config that gated most attractively
  in the backtest would be the exact selection bias this project exists to avoid.

Whatever gate rate this produces live is the honest answer — including "it trades every
day", which would itself be the finding that the model cannot discriminate.

    pip install -e '.[research]'
    python -m optionsbot.research.ml_export config/ml_gate.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .ml_study import build_dataset

# The live-computable prefix of build_dataset's feature vector (it appends the two
# lagged-net features last, which the live strategy cannot compute).
LIVE_FEATURES = [
    "rvol5", "rvol10", "rvol20", "trend5", "trend10",
    "gap", "abs_gap", "credit", "credit_over_rvol", "dte", "dow",
]
C = 0.1
THRESHOLD = 0.5


def train_and_export(root: Path, out: Path, slippage: float = 0.50) -> dict:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    X, ynet, dates = build_dataset(root, slippage=slippage)
    X = X[:, : len(LIVE_FEATURES)]                 # drop the lagged-net columns
    y = (ynet > 0).astype(int)

    scaler = StandardScaler().fit(X)
    model = LogisticRegression(C=C, max_iter=2000).fit(scaler.transform(X), y)

    artifact = {
        "kind": "logistic",
        "features": LIVE_FEATURES,
        "mean": [float(v) for v in scaler.mean_],
        "std": [float(v) if v else 1.0 for v in scaler.scale_],
        "coef": [float(v) for v in model.coef_[0]],
        "intercept": float(model.intercept_[0]),
        "threshold": THRESHOLD,
        "trained_on": {
            "days": int(len(X)),
            "through": str(dates[-1]),
            "slippage_per_leg": slippage,
            "C": C,
            "positive_rate": float(y.mean()),
        },
        "note": ("Frozen gate for forward testing only. docs/19 found NO ML edge in "
                 "history; this exists so the question can be re-asked on data that did "
                 "not exist at training time. Inference is pure stdlib."),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2) + "\n")
    return artifact


def main(argv=None) -> int:
    try:
        import sklearn  # noqa: F401
    except ImportError:
        raise SystemExit("needs the research extra:  pip install -e '.[research]'")
    out = Path(argv[0]) if argv else Path("config/ml_gate.json")
    root = Path(argv[1]) if argv and len(argv) > 1 else Path("data/intraday/NIFTY")
    a = train_and_export(root, out)
    print(f"wrote {out}")
    print(f"  trained on {a['trained_on']['days']} days through {a['trained_on']['through']}"
          f" (slippage {a['trained_on']['slippage_per_leg']}/leg, "
          f"{100*a['trained_on']['positive_rate']:.1f}% positive)")
    print(f"  features: {', '.join(a['features'])}")
    print(f"  threshold {a['threshold']}  |  inference is a dot product (stdlib only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
