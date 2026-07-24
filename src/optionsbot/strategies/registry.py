"""Strategy registry — select strategies by name rather than by import.

The paper loop previously constructed `ReferenceCondor` directly, which meant
evaluating a second strategy required editing the entrypoint. The point of this
harness is to compare strategies on live forward data, so they have to be
addressable by name from a CLI or a config file.

Registration is explicit rather than by import-scanning: a strategy that is not
listed here cannot be run, which is the correct default for something that
places orders.
"""
from __future__ import annotations

from typing import Callable

from ..config import RiskConfig

# name -> (factory, one-line description shown by --list-strategies)
_REGISTRY: dict[str, tuple[Callable[..., object], str]] = {}


def register(name: str, description: str) -> Callable:
    """Decorate a factory that builds a configured strategy instance."""

    def wrap(factory: Callable) -> Callable:
        if name in _REGISTRY:
            raise ValueError(f"strategy {name!r} is already registered")
        _REGISTRY[name] = (factory, description)
        return factory

    return wrap


def available() -> dict[str, str]:
    """name -> description, for listing."""
    return {n: d for n, (_, d) in sorted(_REGISTRY.items())}


def build(name: str, risk: RiskConfig, **overrides):
    """Instantiate a registered strategy, or fail with the list of valid names."""
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise KeyError(f"unknown strategy {name!r}; available: {known}")
    factory, _ = _REGISTRY[name]
    return factory(risk=risk, **overrides)


# -- built-in strategies -------------------------------------------------


@register("reference-condor",
          "Pipeline-validation condor, shorts ~1.5% OTM. NOT a validated strategy.")
def _reference_condor(risk: RiskConfig, **kw):
    from .reference_condor import CondorParams, ReferenceCondor

    return ReferenceCondor(params=CondorParams(**kw), risk=risk)


@register("tail-condor",
          "Far-OTM condor, shorts ~2.6% out, held to settlement. The one structure "
          "with a measured out-of-sample edge (docs/13) — and it is small: ~1.5-2%/yr.")
def _tail_condor(risk: RiskConfig, **kw):
    from .reference_condor import CondorParams, ReferenceCondor

    # Far enough out to reach the region that actually carries premium (docs/12),
    # and held rather than managed: the intraday triggers were what the study
    # measured as neutral-to-harmful on this structure.
    params = dict(offset_pct=0.026, profit_target_frac=1.0, stop_loss_frac=1.0)
    params.update(kw)
    return ReferenceCondor(params=CondorParams(**params), risk=risk)


@register("collect-only", "Places no orders; snapshots live chains for research.")
def _collect_only(risk: RiskConfig, **kw):
    from ..paper.loop import CollectOnly

    return CollectOnly()


@register("ml-intraday-strangle",
          "EXPERIMENTAL ML-GATED naked intraday strangle: a frozen logistic gate decides "
          "whether to trade each day. NOT mandate-compliant — naked. Shadow-only via "
          "--evaluate-naked; run it BESIDE intraday-strangle so the difference between "
          "the two forward records is the ML contribution (docs/19).")
def _ml_intraday_strangle(risk: RiskConfig, **kw):
    from .ml_gated_strangle import MlGatedStrangle, MlGateParams

    return MlGatedStrangle(params=MlGateParams(**kw), risk=risk)


@register("intraday-strangle",
          "EXPERIMENTAL naked intraday short strangle (no overnight, 1% OTM, flat by "
          "15:25). NOT mandate-compliant — naked. Shadow-only via --evaluate-naked; "
          "the backtest says regime luck / no durable edge (docs/17/18).")
def _intraday_strangle(risk: RiskConfig, **kw):
    from .intraday_strangle import IntradayStrangle, StrangleParams

    return IntradayStrangle(params=StrangleParams(**kw), risk=risk)
