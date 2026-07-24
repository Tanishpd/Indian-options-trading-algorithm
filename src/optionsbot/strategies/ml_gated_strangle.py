"""EXPERIMENTAL ML-gated intraday strangle — a forward test, not a recommendation.

Runs the same naked intraday strangle as `intraday_strangle`, but each morning asks a
FROZEN model whether to trade at all. It exists to answer, forward, the question docs/19
answered backward: does an ML gate add anything?

Why this design is the informative one: it runs as a shadow ALONGSIDE the ungated
`intraday-strangle` shadow, on the same feed, on the same days. The difference between
the two forward records IS the ML contribution — no statistics needed to read it.

Constraints it respects:

- **Stdlib-only inference.** The model ships as means/stds/coefficients (see
  `research.ml_export`); scoring is a dot product through `math.exp`. No numpy on the box.
- **Only live-computable features.** Trailing realized vol and trend, the overnight gap,
  the morning's own quoted credit, and calendar position — all derivable from ~20 days of
  daily spot history plus today's chain.
- **Honest warm-up.** Shadows are rebuilt fresh each session-day, so the daily history
  lives in a small JSON file the strategy maintains itself. Until it holds `min_history`
  days it records and does NOT trade — an untrained gate must not quietly become
  "always trade".
- **Naked, like its ungated twin**, so it must be opted in via `--evaluate-naked`.

docs/19's verdict stands: no ML edge was found in history, and the power analysis says
this dataset could not certify a mandate-sized one. Nothing under roughly two years of
forward record should be read as evidence here.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path

from ..backtest.engine import Order
from ..config import RiskConfig
from ..fills import to_tick
from ..instruments import OptionLeg, Right, Side


@dataclass(frozen=True)
class MlGateParams:
    model_path: Path = Path("config/ml_gate.json")
    history_path: Path = Path("data/live/ml_daily_history.json")
    min_history: int = 20              # days of spot history before the gate may act
    offset_pct: float = 0.01
    entry_after: time = time(9, 20)
    entry_before: time = time(12, 0)
    squareoff: time = time(15, 25)
    strike_step: float = 50.0
    limit_pad: float = 0.01


def _touch(q, side: Side) -> float:
    px = getattr(q, "ask" if side is Side.BUY else "bid", None)
    return float(px) if px else q.ltp


def _round_strike(value: float, step: float) -> float:
    return round(value / step) * step


def _pstdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def load_model(path: Path) -> dict | None:
    try:
        m = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if m.get("kind") != "logistic" or not m.get("coef"):
        return None
    return m


def score(model: dict, feats: dict[str, float]) -> float:
    """P(profitable day) from the frozen logistic gate. Pure stdlib.

    A missing feature falls back to its training mean, i.e. contributes nothing — the
    safe default, since a silently-zeroed feature would otherwise shift the decision.
    """
    z = float(model["intercept"])
    for name, mu, sd, w in zip(model["features"], model["mean"], model["std"], model["coef"]):
        z += w * ((feats.get(name, mu) - mu) / (sd or 1.0))
    z = max(-60.0, min(60.0, z))            # keep exp() in range
    return 1.0 / (1.0 + math.exp(-z))


def build_features(history: list[dict], spot: float, credit: float, dte: int, dow: int) -> dict | None:
    """Features from prior days' spots plus today's own entry data. `history` is oldest
    first, each {date, entry_spot, exit_spot}. Returns None if history is too short."""
    if len(history) < 20:
        return None
    es = [h["entry_spot"] for h in history[-20:]] + [spot]
    rets = [es[i] / es[i - 1] - 1 for i in range(1, len(es))]

    def rvol(w: int) -> float:
        return _pstdev(rets[-w:])

    r5 = rvol(5)
    return {
        "rvol5": r5, "rvol10": rvol(10), "rvol20": rvol(20),
        "trend5": spot / es[-6] - 1, "trend10": spot / es[-11] - 1,
        "gap": spot / history[-1]["exit_spot"] - 1,
        "abs_gap": abs(spot / history[-1]["exit_spot"] - 1),
        "credit": credit,
        "credit_over_rvol": credit / (r5 + 1e-9),
        "dte": float(dte), "dow": float(dow),
    }


@dataclass
class MlGatedStrangle:
    params: MlGateParams
    risk: RiskConfig                   # unused (naked, no cap) — registry uniformity
    phase: str = "idle"                # idle | holding | done | skipped
    log: list = field(default_factory=list)
    _model: dict | None = None
    _loaded: bool = False

    def to_state(self) -> dict:
        return {"phase": self.phase}

    def from_state(self, state: dict) -> None:
        self.phase = state.get("phase", "idle")

    # -- daily history, persisted outside the (daily-rebuilt) shadow ----------

    def _history(self) -> list[dict]:
        try:
            h = json.loads(Path(self.params.history_path).read_text())
            return h if isinstance(h, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _record_day(self, day: date, entry_spot: float, exit_spot: float) -> None:
        h = [r for r in self._history() if r.get("date") != day.isoformat()]
        h.append({"date": day.isoformat(), "entry_spot": entry_spot, "exit_spot": exit_spot})
        h = sorted(h, key=lambda r: r["date"])[-60:]
        p = Path(self.params.history_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(h))
        tmp.replace(p)

    def _order(self, ctx, strike: float, right: Right, side: Side) -> Order | None:
        leg = OptionLeg(ctx.index, ctx.expiry, strike, right, side)
        q = ctx.chain.get(leg.key)
        if q is None:
            return None
        base = _touch(q, side)
        pad = (1 + self.params.limit_pad) if side is Side.BUY else (1 - self.params.limit_pad)
        return Order(leg, to_tick(base * pad, side))

    # -- decision ------------------------------------------------------------

    def decide(self, ctx) -> list[Order]:
        p = self.params
        now_t = ctx.now.time()

        if not self._loaded:
            self._model = load_model(p.model_path)
            self._loaded = True
            if self._model is None:
                self.log.append(f"no usable gate model at {p.model_path} — will not trade")

        book = list(ctx.positions)
        if book:
            if now_t >= p.squareoff:
                self._record_day(ctx.now.date(),
                                 (book[0].leg.strike + book[-1].leg.strike) / 2.0, ctx.spot)
                orders = [self._order(ctx, b.leg.strike, b.leg.right, b.leg.side.opposite)
                          for b in book]
                return [o for o in orders if o is not None]
            return []

        if self.phase == "holding":
            self.phase = "done"
        if self.phase in ("done", "skipped"):
            # A skipped day still has to close out its history entry, or tomorrow's gap
            # feature is computed against this morning's spot instead of tonight's close.
            if self.phase == "skipped" and now_t >= p.squareoff:
                h = self._history()
                if h and h[-1].get("date") == ctx.now.date().isoformat():
                    self._record_day(ctx.now.date(), h[-1]["entry_spot"], ctx.spot)
                    self.phase = "done"
            return []
        if not (p.entry_after <= now_t <= p.entry_before):
            return []
        if self._model is None:
            return []

        sc = _round_strike(ctx.spot * (1 + p.offset_pct), p.strike_step)
        sp = _round_strike(ctx.spot * (1 - p.offset_pct), p.strike_step)
        call = self._order(ctx, sc, Right.CALL, Side.SELL)
        put = self._order(ctx, sp, Right.PUT, Side.SELL)
        if call is None or put is None:
            return []

        credit = _touch(ctx.chain[call.leg.key], Side.SELL) + _touch(ctx.chain[put.leg.key], Side.SELL)
        hist = self._history()
        feats = build_features(hist, ctx.spot, credit,
                               (ctx.expiry - ctx.now.date()).days, ctx.now.weekday())
        if feats is None:
            # Warm-up: record the day's spot so history accrues, but do not trade.
            self.phase = "skipped"
            self._record_day(ctx.now.date(), ctx.spot, ctx.spot)
            self.log.append(f"warm-up: {len(hist)}/{p.min_history} days of history")
            return []

        prob = score(self._model, feats)
        if prob < self._model.get("threshold", 0.5):
            self.phase = "skipped"
            self._record_day(ctx.now.date(), ctx.spot, ctx.spot)
            self.log.append(f"gate SKIP (p={prob:.3f})")
            return []

        self.phase = "holding"
        self.log.append(f"gate TRADE (p={prob:.3f})")
        return [call, put]
