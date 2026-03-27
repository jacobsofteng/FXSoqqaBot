"""Hurst exponent computation for trend/mean-reversion classification.

CHAOS-01: Rolling Hurst exponent classifies the market as trending
(H > 0.6), mean-reverting (H < 0.4), or random walk (H ~ 0.5).

Uses nolds.hurst_rs (rescaled range method) as the core computation.
"""

from __future__ import annotations

import numpy as np
import nolds


def compute_hurst(
    close_prices: np.ndarray,
    min_length: int = 100,
) -> tuple[float, float]:
    """Compute the Hurst exponent from close prices.

    Args:
        close_prices: 1D array of close prices.
        min_length: Minimum data points required. Below this,
            returns (0.5, 0.0) -- random walk assumption with zero
            confidence.

    Returns:
        (hurst_value, confidence) where hurst_value is clamped to
        [0.0, 1.0] and confidence scales linearly from 0.0 to 1.0
        at 500 data points.
    """
    if len(close_prices) < min_length:
        return (0.5, 0.0)

    try:
        hurst_val = float(nolds.hurst_rs(close_prices, corrected=True, unbiased=True))
    except Exception:
        return (0.5, 0.0)

    # Clamp to valid range
    hurst_val = float(np.clip(hurst_val, 0.0, 1.0))

    # Confidence scales linearly with data length, max at 500 points
    confidence = float(min(1.0, len(close_prices) / 500.0))

    return (hurst_val, confidence)
