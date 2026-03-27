"""Lyapunov exponent computation for dynamical stability measurement.

CHAOS-02: Largest Lyapunov exponent via Rosenstein algorithm. Positive
values indicate chaotic/unstable dynamics, negative values indicate
stable dynamics, ~0 is neutral.

Uses nolds.lyap_r (Rosenstein algorithm) as the core computation.
"""

from __future__ import annotations

import numpy as np
import nolds


def compute_lyapunov(
    close_prices: np.ndarray,
    emb_dim: int = 10,
    min_length: int = 300,
) -> tuple[float, float]:
    """Compute the largest Lyapunov exponent from close prices.

    Args:
        close_prices: 1D array of close prices.
        emb_dim: Embedding dimension for phase-space reconstruction.
        min_length: Minimum data points required. Below this,
            returns (0.0, 0.0) -- neutral assumption with zero confidence.

    Returns:
        (lyapunov_value, confidence) where confidence scales linearly
        from 0.0 to 1.0 at 3x min_length data points.
    """
    if len(close_prices) < min_length:
        return (0.0, 0.0)

    try:
        lyap_val = float(nolds.lyap_r(close_prices, emb_dim=emb_dim, fit="RANSAC"))
    except Exception:
        return (0.0, 0.0)

    if not np.isfinite(lyap_val):
        return (0.0, 0.0)

    # Confidence scales linearly with data length
    confidence = float(min(1.0, len(close_prices) / (min_length * 3)))

    return (float(lyap_val), confidence)
