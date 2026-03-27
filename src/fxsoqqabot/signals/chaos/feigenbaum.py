"""Feigenbaum bifurcation proximity detection via period-doubling ratios.

CHAOS-04: Detects proximity to period-doubling bifurcation by measuring
how close the ratio of successive peak interval differences is to the
Feigenbaum delta constant (4.669201609).

This is novel territory with LOW confidence -- implementation is
deliberately kept simple per research guidance.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import argrelextrema

# Feigenbaum's universal constant (first kind -- delta)
FEIGENBAUM_DELTA = 4.669201609


def detect_bifurcation_proximity(
    close_prices: np.ndarray,
    order: int = 5,
) -> tuple[float, float]:
    """Detect proximity to period-doubling bifurcation.

    Finds peaks in the price series, computes intervals between
    successive peaks, then measures how close the ratio of successive
    interval differences approaches the Feigenbaum delta constant.

    Args:
        close_prices: 1D array of close prices.
        order: Number of points on each side for peak detection
            (passed to scipy.signal.argrelextrema).

    Returns:
        (proximity_score, confidence) where proximity_score is 0-1
        (1.0 = ratio matches Feigenbaum delta exactly) and confidence
        scales linearly from 0.0 to 1.0 at 10 computed ratios.
    """
    if len(close_prices) < 50:
        return (0.0, 0.0)

    try:
        # Find local maxima (peaks)
        peak_indices = argrelextrema(close_prices, np.greater, order=order)[0]

        if len(peak_indices) < 4:
            return (0.0, 0.0)

        # Compute intervals between successive peaks
        intervals = np.diff(peak_indices).astype(float)

        if len(intervals) < 2:
            return (0.0, 0.0)

        # Compute differences of successive intervals
        interval_diffs = np.diff(intervals)

        # Avoid division by zero
        valid_mask = np.abs(interval_diffs[1:]) > 1e-10
        if not np.any(valid_mask):
            return (0.0, 0.0)

        # Compute ratios of successive interval differences
        ratios = np.abs(interval_diffs[:-1][valid_mask] / interval_diffs[1:][valid_mask])

        if len(ratios) < 1:
            return (0.0, 0.0)

        # Average ratio -- how close to Feigenbaum delta?
        avg_ratio = float(np.mean(ratios))
        proximity = 1.0 - min(1.0, abs(avg_ratio - FEIGENBAUM_DELTA) / FEIGENBAUM_DELTA)
        proximity = float(np.clip(proximity, 0.0, 1.0))

        # Confidence scales with number of ratios computed
        confidence = float(min(1.0, len(ratios) / 10.0))

        return (proximity, confidence)

    except Exception:
        return (0.0, 0.0)
