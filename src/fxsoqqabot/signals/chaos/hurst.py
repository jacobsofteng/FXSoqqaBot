"""Hurst exponent computation for trend/mean-reversion classification.

CHAOS-01: Rolling Hurst exponent classifies the market as trending
(H > 0.6), mean-reverting (H < 0.4), or random walk (H ~ 0.5).

Inner R/S loop JIT-compiled via _numba_core for backtest performance.
Final RANSAC line fit via nolds.measures.poly_fit (called once per bar).
"""

from __future__ import annotations

import math

import numpy as np
from nolds.measures import poly_fit as _nolds_poly_fit

from fxsoqqabot.signals.chaos._numba_core import _rs_values


def _expected_rs(n: int) -> float:
    """Anis-Lloyd-Peters expected R/S for white noise.

    Replicates nolds.expected_rs(n) exactly.
    """
    front = (n - 0.5) / n
    i_arr = np.arange(1, n)
    back = float(np.sum(np.sqrt((n - i_arr) / i_arr)))
    if n <= 340:
        middle = math.gamma((n - 1) * 0.5) / math.sqrt(math.pi) / math.gamma(n * 0.5)
    else:
        middle = 1.0 / math.sqrt(n * math.pi * 0.5)
    return front * middle * back


def _logmid_n(max_n: int, ratio: float = 0.25, nsteps: int = 15) -> np.ndarray:
    """Logarithmically spaced midrange values. Replicates nolds.logmid_n."""
    l = np.log(max_n)
    span = l * ratio
    start = l * (1 - ratio) * 0.5
    midrange = start + 1.0 * np.arange(nsteps) / nsteps * span
    nvals = np.round(np.exp(midrange)).astype(np.int32)
    return np.unique(nvals)


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
        data = np.ascontiguousarray(close_prices, dtype=np.float64)
        total_N = len(data)

        # Compute nvals (same as nolds.logmid_n default)
        nvals = _logmid_n(total_N, ratio=0.25, nsteps=15)

        # JIT-compiled R/S computation over all nvals
        rsvals = _rs_values(data, nvals, True)

        # Filter NaN values
        not_nan = ~np.isnan(rsvals)
        rsvals = rsvals[not_nan]
        nvals = nvals[not_nan]

        if len(rsvals) == 0:
            return (0.5, 0.0)

        # Log transform
        xvals = np.log(nvals.astype(np.float64))
        yvals = np.log(rsvals)

        # Anis-Lloyd-Peters correction (corrected=True)
        correction = np.array([_expected_rs(int(n)) for n in nvals])
        yvals = yvals - np.log(correction)

        # RANSAC line fit (not jittable, called once)
        poly = _nolds_poly_fit(xvals, yvals, 1, fit="RANSAC")

        hurst_val = float(poly[0] + 0.5)
    except Exception:
        return (0.5, 0.0)

    # Clamp to valid range
    hurst_val = float(np.clip(hurst_val, 0.0, 1.0))

    # Confidence scales linearly with data length, max at 500 points
    confidence = float(min(1.0, len(close_prices) / 500.0))

    return (hurst_val, confidence)
