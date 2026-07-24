"""ML study harness (docs/19). Skipped unless the optional research extra is present.

The property worth pinning is not "the model is accurate" — it is that the harness is
HONEST and has POWER: no look-ahead in the walk-forward, and it detects a genuine
signal when one exists. A null result from a blind harness would mean nothing.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("sklearn")

import numpy as np  # noqa: E402

from optionsbot.research.ml_study import walk_forward  # noqa: E402


def _logistic():
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression(C=1.0, max_iter=2000)


def test_walk_forward_only_tests_the_out_of_sample_tail():
    """The first init_frac of the series is training seed and is never scored."""
    rng = np.random.default_rng(0)
    X = rng.normal(size=(100, 3))
    net = rng.normal(size=100)
    preds, tested = walk_forward(X, (net > 0).astype(int), net, _logistic, "cls",
                                 init_frac=0.4, step=5)
    assert not tested[:40].any()          # seed region never scored
    assert tested[40:].all()              # everything after is OOS
    assert len(preds) == len(tested) == 100


def test_walk_forward_detects_an_injected_signal():
    """POSITIVE CONTROL in miniature: when the label is a clean function of a feature,
    the harness must find it. If this fails, no null it produces is believable."""
    rng = np.random.default_rng(1)
    X = rng.normal(size=(300, 3))
    # feature 0 fully determines the payoff (plus mild noise)
    net = np.where(X[:, 0] < 0, 100.0, -100.0) + rng.normal(0, 20, 300)
    preds, tested = walk_forward(X, (net > 0).astype(int), net, _logistic, "cls")
    gated = net[tested & preds].sum()
    base = net[tested].sum()
    assert gated > base                    # gating beat trading everything
    assert gated > 0                       # and it is genuinely profitable
    # it should be selecting mostly the winning days
    chosen = net[tested & preds]
    assert (chosen > 0).mean() > 0.8


def test_walk_forward_finds_nothing_in_pure_noise():
    """Mirror image: with no relationship, gated P&L must not be systematically
    better than trading everything (guards against leakage manufacturing signal)."""
    rng = np.random.default_rng(2)
    X = rng.normal(size=(300, 3))
    net = rng.normal(0, 100, 300)          # target independent of X
    preds, tested = walk_forward(X, (net > 0).astype(int), net, _logistic, "cls")
    gated = net[tested & preds].sum()
    # a leak would let it "predict" noise and post a large positive edge
    assert abs(gated) < 4 * abs(net[tested]).std() * np.sqrt(tested.sum())
