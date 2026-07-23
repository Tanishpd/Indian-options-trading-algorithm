"""PRE-REGISTERED search set — frozen before any accept/reject evidence is seen.

This list is the whole discipline. The multiple-testing correction (Deflated
Sharpe, PBO, SPA) is only valid if K is the HONEST count of everything ever
tried. So the rule is: this file is committed BEFORE the cross-validation window
is touched, every config carries a one-line ex-ante economic mechanism, and no
config is added later. A new idea starts a fresh round with its own holdout — it
does not get appended here (docs/11's "keep the best backtest" trap; docs/15).

Column 0 is `base` — the benchmark to beat, NOT a trial. The other 19 are the
candidates; N_trials = 19 for the deflation.

Mechanisms, not hopes: each config attacks a specific, named weakness of plain
momentum (mostly its crash) with a mechanism from the literature, or is a
deliberate NEGATIVE CONTROL expected to lose (to confirm the harness discriminates
rather than rubber-stamps).
"""
from __future__ import annotations

from dataclasses import replace

from .strategy_search import StrategyConfig

# The real base momentum config (matches docs/14: 23.6% / 21.3% / 1.51 gross).
BASE = StrategyConfig(
    name="base",
    mechanism="Two vol-adjusted returns (6M,12M) z-scored & averaged; top-30 EW; "
              "monthly; cash below index 200-DMA. The benchmark to beat.",
    top_n=30, lookback_short=126, lookback_long=252,
    rank_mode="base", weight_mode="equal",
    regime_mode="price_sma", regime_sma=200, exposure_mode="binary",
)


def preregistered() -> list[StrategyConfig]:
    """The 20 configs, base first. Frozen — see module docstring."""
    return [
        BASE,

        # -- H1 vol-target exposure (Barroso-Santa-Clara): momentum crashes when
        #    its own vol spikes; de-lever then. The strongest literature edge and
        #    a direct hit on the binding 21% drawdown. --
        replace(BASE, name="vt_pure",
                mechanism="H1: vol-target 15% on index realized vol, no 200-DMA. "
                          "Scale exposure down when vol is high; never lever.",
                regime_mode="none", exposure_mode="vol_target",
                target_vol=0.15, vol_lookback=63, exposure_floor=0.0, exposure_cap=1.0),
        replace(BASE, name="vt_floor",
                mechanism="H1: vol-target 15% with a 0.3 exposure floor, no 200-DMA. "
                          "De-lever in vol spikes but keep compounding.",
                regime_mode="none", exposure_mode="vol_target",
                target_vol=0.15, vol_lookback=63, exposure_floor=0.3, exposure_cap=1.0),
        replace(BASE, name="vt_regime",
                mechanism="H1: vol-target 15% ON TOP of the 200-DMA gate — both "
                          "crash defenses stacked.",
                regime_mode="price_sma", exposure_mode="vol_target",
                target_vol=0.15, vol_lookback=63, exposure_floor=0.0, exposure_cap=1.0),

        # -- H2 residual (idiosyncratic) momentum (Blitz-Huij-Martens): strip the
        #    market-beta component that drives crashes; rank on stock-specific trend. --
        replace(BASE, name="resid",
                mechanism="H2: residual momentum — rank on the Sharpe of returns "
                          "orthogonalised to NIFTY-50 (6M,12M). Keeps the 200-DMA.",
                rank_mode="residual", resid_lookback=252),
        replace(BASE, name="resid_vt",
                mechanism="H2xH1: residual momentum ranking + vol-target sizing — "
                          "crash-robust ranking and crash-robust exposure together.",
                rank_mode="residual", regime_mode="none",
                exposure_mode="vol_target", target_vol=0.15, exposure_floor=0.3),

        # -- H3 200-DMA SLOPE replacement: 'is the average rising' kills the
        #    sideways whipsaw of the price>MA test. Tested as a REPLACEMENT. --
        replace(BASE, name="slope21",
                mechanism="H3: regime = index 200-DMA slope over 21d > 0 (replaces "
                          "price>200-DMA). Removes flat-market whipsaw.",
                regime_mode="slope_sma", slope_k=21),
        replace(BASE, name="slope63",
                mechanism="H3: regime = index 200-DMA slope over 63d > 0. Slower, "
                          "fewer toggles.",
                regime_mode="slope_sma", slope_k=63),

        # -- H4 universe breadth regime: the median stock deteriorates before the
        #    cap-weighted index price; catches tops the price misses. --
        replace(BASE, name="breadth",
                mechanism="H4: risk-on when >50% of the universe is above its own "
                          "50-DMA (replaces price>200-DMA). Measures participation.",
                regime_mode="breadth", breadth_ma=50, breadth_thresh=0.5),
        replace(BASE, name="breadth_and",
                mechanism="H4: breadth>50% AND price>200-DMA — both must agree to "
                          "be invested.",
                regime_mode="breadth", breadth_ma=50, breadth_thresh=0.5,
                breadth_combine=True),

        # -- H5 12-1 skip-month momentum (Jegadeesh-Titman): drop the most recent
        #    month from the 12M term to avoid the 1-month reversal contamination. --
        replace(BASE, name="skip21",
                mechanism="H5: 12-1 momentum — long-term term skips the most recent "
                          "21d (short-term reversal). Cleaner trend measure.",
                rank_mode="skip_month", skip=21),
        replace(BASE, name="skip42",
                mechanism="H5: 12-2 momentum — skip the most recent 42d.",
                rank_mode="skip_month", skip=42),

        # -- H6 inverse-vol weighting: de-emphasise the jumpiest winners (mild
        #    low-vol lean) without changing which names are held. --
        replace(BASE, name="invvol",
                mechanism="H6: size the top-30 by inverse 63d vol instead of equal "
                          "weight. A low-vol tilt on the drawdown.",
                weight_mode="inverse_vol", weight_vol_span=63),

        # -- H7 trend-quality tilt (Da-Gurun-Warachka frog-in-the-pan): prefer
        #    smooth, persistent winners over jumpy ones. --
        replace(BASE, name="trendq",
                mechanism="H7: blend the momentum score 50/50 with log-price trend "
                          "R^2 — keep winners, prefer the persistent kind.",
                rank_mode="trend_quality", tq_span=126, tq_weight=0.5),

        # -- H8 cross-sectional dispersion regime: momentum pays when stocks move
        #    apart, not together. Conditions on whether momentum ITSELF pays. --
        replace(BASE, name="dispersion",
                mechanism="H8: de-risk to the floor when cross-sectional dispersion "
                          "falls below its trailing median (macro-driven tape).",
                regime_mode="dispersion", disp_span=63, disp_warmup=12,
                exposure_floor=0.3),

        # -- Index-trend replacement + refinements --
        replace(BASE, name="macd_regime",
                mechanism="Index MACD(12,26,9) line>signal as the regime (replaces "
                          "price>200-DMA). A faster trend gate.",
                regime_mode="macd"),
        replace(BASE, name="downside",
                mechanism="Rank on return / DOWNSIDE deviation (Sortino denominator) "
                          "instead of total vol — penalise only bad volatility.",
                rank_mode="downside"),
        replace(BASE, name="score_prop",
                mechanism="Weight the top-30 proportional to momentum score — lean "
                          "into the strongest names.",
                weight_mode="score_prop"),

        # -- NEGATIVE CONTROLS: expected to LOSE. If the harness crowns one, the
        #    harness is broken. --
        replace(BASE, name="ctrl_no_regime",
                mechanism="CONTROL: no regime filter at all. Should show the worst "
                          "drawdown — confirms the 200-DMA's value and that the "
                          "harness ranks a known-worse config below base.",
                regime_mode="none"),
        replace(BASE, name="ctrl_top50",
                mechanism="CONTROL: top-50 instead of top-30 — over-diversified, "
                          "dilutes the momentum signal. Expected to underperform.",
                top_n=50),
    ]


PREREGISTERED = preregistered()
