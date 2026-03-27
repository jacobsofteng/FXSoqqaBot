"""Threshold-based regime classifier combining all chaos metrics.

CHAOS-06: Classifies the market into one of five discrete regime states
based on the outputs of the individual chaos metrics (Hurst, Lyapunov,
fractal dimension, Feigenbaum bifurcation, crowd entropy) plus price
direction.

Classification priority (ordered):
1. PRE_BIFURCATION: Feigenbaum proximity > 0.7
2. HIGH_CHAOS: Lyapunov > 0.5 AND entropy > 0.7
3. TRENDING_UP/DOWN: Hurst > 0.6 (direction from price)
4. RANGING: Hurst < 0.45
5. Default RANGING with low confidence
"""

from __future__ import annotations

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

    Returns:
        (regime_state, confidence) tuple.
    """
    # Priority 1: PRE_BIFURCATION
    if bifurcation > 0.7 and bifurcation_conf > 0.3:
        return (RegimeState.PRE_BIFURCATION, bifurcation * bifurcation_conf)

    # Priority 2: HIGH_CHAOS
    avg_chaos_conf = (lyap_conf + entropy_conf) / 2
    if lyapunov > 0.5 and entropy > 0.7 and avg_chaos_conf > 0.3:
        return (RegimeState.HIGH_CHAOS, avg_chaos_conf)

    # Priority 3: TRENDING
    if hurst > 0.6 and hurst_conf > 0.2:
        if price_direction > 0:
            return (RegimeState.TRENDING_UP, hurst_conf)
        else:
            return (RegimeState.TRENDING_DOWN, hurst_conf)

    # Priority 4: RANGING
    if hurst < 0.45 and hurst_conf > 0.2:
        return (RegimeState.RANGING, hurst_conf)

    # Priority 5: Default -- ambiguous
    return (RegimeState.RANGING, 0.2)
