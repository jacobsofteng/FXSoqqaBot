"""Fractal dimension computation for complexity measurement.

CHAOS-03: Correlation dimension via Grassberger-Procaccia algorithm.
Low fractal dimension (~1.0) indicates simple dynamics, high fractal
dimension (~2.0) indicates complex/random dynamics.

Uses nolds.corr_dim as the core computation.
"""

from __future__ import annotations

import numpy as np
import nolds


def compute_fractal_dimension(
    close_prices: np.ndarray,
    emb_dim: int = 10,
    min_length: int = 200,
) -> tuple[float, float]:
    """Compute the fractal (correlation) dimension from close prices.

    Args:
        close_prices: 1D array of close prices.
        emb_dim: Embedding dimension for phase-space reconstruction.
        min_length: Minimum data points required. Below this,
            returns (1.5, 0.0) -- midrange assumption with zero confidence.

    Returns:
        (fractal_dim, confidence) where fractal_dim is clamped to
        [1.0, 2.0] for 1D time series and confidence scales linearly
        from 0.0 to 1.0 at 600 data points.
    """
    if len(close_prices) < min_length:
        return (1.5, 0.0)

    try:
        fd_val = float(nolds.corr_dim(close_prices, emb_dim=emb_dim))
    except Exception:
        return (1.5, 0.0)

    if not np.isfinite(fd_val):
        return (1.5, 0.0)

    # Clamp to valid range for 1D time series
    fd_val = float(np.clip(fd_val, 1.0, 2.0))

    # Confidence scales linearly with data length, max at 600 points
    confidence = float(min(1.0, len(close_prices) / 600.0))

    return (fd_val, confidence)
