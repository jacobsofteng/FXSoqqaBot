"""Threshold-based regime classifier combining all chaos metrics.

CHAOS-06: Classifies the market into one of five discrete regime states
based on the outputs of the individual chaos metrics (Hurst, Lyapunov,
fractal dimension, Feigenbaum bifurcation, crowd entropy) plus price
direction.

Classification priority (ordered):
1. PRE_BIFURCATION: Feigenbaum proximity > config.bifurcation_threshold
2. HIGH_CHAOS: Lyapunov > config.lyapunov_chaos_threshold AND entropy > config.entropy_chaos_threshold
3. TRENDING_UP/DOWN: Hurst > config.hurst_trending_threshold (direction from price)
4. RANGING: Hurst < config.hurst_ranging_threshold
5. Default RANGING with low confidence
"""

from __future__ import annotations

from fxsoqqabot.config.models import ChaosConfig
from fxsoqqabot.signals.base import RegimeState


def classify_regime(
    hurst: float,
    hurst_conf: float,
    lyapunov: float,
    lyap_conf: float,
    fractal_dim: float,
    fractal_conf: float,
    bifurcation: float,
    bifurcation_conf: float,
    entropy: float,
    entropy_conf: float,
    price_direction: float,
    config: ChaosConfig | None = None,
) -> tuple[RegimeState, float]:
    """Classify the current market regime from chaos metric outputs.

    Args:
        hurst: Hurst exponent value (0-1).
        hurst_conf: Confidence of Hurst computation.
        lyapunov: Largest Lyapunov exponent.
        lyap_conf: Confidence of Lyapunov computation.
        fractal_dim: Fractal (correlation) dimension.
        fractal_conf: Confidence of fractal dimension computation.
        bifurcation: Feigenbaum bifurcation proximity score (0-1).
        bifurcation_conf: Confidence of bifurcation detection.
        entropy: Normalized Shannon entropy of returns (0-1).
        entropy_conf: Confidence of entropy computation.
        price_direction: Sign of recent price movement (+1, -1, or 0).
        config: ChaosConfig with regime thresholds. Uses defaults if None.

    Returns:
        (regime_state, confidence) tuple.
    """
    if config is None:
        config = ChaosConfig()  # Default thresholds match old hardcoded values

    # Priority 1: PRE_BIFURCATION
    if bifurcation > config.bifurcation_threshold and bifurcation_conf > 0.3:
        return (RegimeState.PRE_BIFURCATION, bifurcation * bifurcation_conf)

    # Priority 2: HIGH_CHAOS
    avg_chaos_conf = (lyap_conf + entropy_conf) / 2
    if (
        lyapunov > config.lyapunov_chaos_threshold
        and entropy > config.entropy_chaos_threshold
        and avg_chaos_conf > 0.3
    ):
        return (RegimeState.HIGH_CHAOS, avg_chaos_conf)

    # Priority 3: TRENDING
    if hurst > config.hurst_trending_threshold and hurst_conf > 0.2:
        if price_direction > 0:
            return (RegimeState.TRENDING_UP, hurst_conf)
        else:
            return (RegimeState.TRENDING_DOWN, hurst_conf)

    # Priority 4: RANGING
    if hurst < config.hurst_ranging_threshold and hurst_conf > 0.2:
        return (RegimeState.RANGING, hurst_conf)

    # Priority 5: Default -- ambiguous
    return (RegimeState.RANGING, 0.2)
