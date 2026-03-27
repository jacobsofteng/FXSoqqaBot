"""Fractal dimension computation for complexity measurement.

CHAOS-03: Correlation dimension via Grassberger-Procaccia algorithm.
Low fractal dimension (~1.0) indicates simple dynamics, high fractal
dimension (~2.0) indicates complex/random dynamics.

Inner distance matrix and correlation sums JIT-compiled via _numba_core.
Final RANSAC line fit via nolds.measures.poly_fit (called once per bar).
"""

from __future__ import annotations

import numpy as np
from nolds.measures import poly_fit as _nolds_poly_fit

from fxsoqqabot.signals.chaos._numba_core import _corr_dim_core, _delay_embedding


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
        data = np.ascontiguousarray(close_prices, dtype=np.float64)

        # Compute rvals: logarithmic range from 0.1*std to 0.5*std, factor 1.03
        sd = float(np.std(data, ddof=1))
        if sd == 0.0:
            return (1.5, 0.0)

        rvals_list: list[float] = []
        r = 0.1 * sd
        upper = 0.5 * sd
        while r < upper:
            rvals_list.append(r)
            r *= 1.03
        if len(rvals_list) == 0:
            return (1.5, 0.0)
        rvals = np.array(rvals_list, dtype=np.float64)

        # JIT-compiled delay embedding (lag=1 default)
        orbit = _delay_embedding(data, emb_dim, 1)

        # JIT-compiled correlation sums
        csums = _corr_dim_core(orbit, rvals)

        # Filter zeros
        nonzero = csums != 0
        rvals_nz = rvals[nonzero]
        csums_nz = csums[nonzero]

        if len(csums_nz) < 2:
            return (1.5, 0.0)

        # RANSAC line fit on log(r) vs log(C(r))
        poly = _nolds_poly_fit(np.log(rvals_nz), np.log(csums_nz), 1, fit="RANSAC")
        fd_val = float(poly[0])
    except Exception:
        return (1.5, 0.0)

    if not np.isfinite(fd_val):
        return (1.5, 0.0)

    # Clamp to valid range for 1D time series
    fd_val = float(np.clip(fd_val, 1.0, 2.0))

    # Confidence scales linearly with data length, max at 600 points
    confidence = float(min(1.0, len(close_prices) / 600.0))

    return (fd_val, confidence)
