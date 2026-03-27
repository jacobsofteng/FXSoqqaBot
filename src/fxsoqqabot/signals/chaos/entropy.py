"""Crowd entropy computation via Shannon entropy on return distributions.

CHAOS-05: Measures the entropy of the log-return distribution to detect
crowd panic (high entropy = uncertainty/disorder) vs orderly markets
(low entropy = concentrated/trending).

Uses scipy.stats.entropy for Shannon entropy computation.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import entropy as scipy_entropy


def compute_crowd_entropy(
    close_prices: np.ndarray,
    bins: int = 50,
    min_length: int = 100,
) -> tuple[float, float]:
    """Compute normalized Shannon entropy of the return distribution.

    Args:
        close_prices: 1D array of close prices (must be > 0 for log).
        bins: Number of histogram bins for return distribution.
        min_length: Minimum data points required. Below this,
            returns (0.5, 0.0) -- mid-range assumption with zero confidence.

    Returns:
        (entropy_value, confidence) where entropy_value is normalized
        to [0, 1] by dividing by max possible entropy (log(bins)).
        Confidence scales linearly from 0.0 to 1.0 at 500 data points.
    """
    if len(close_prices) < min_length:
        return (0.5, 0.0)

    try:
        # Filter out non-positive prices to avoid log issues
        valid_prices = close_prices[close_prices > 0]
        if len(valid_prices) < min_length:
            return (0.5, 0.0)

        # Compute log returns
        log_returns = np.diff(np.log(valid_prices))

        if len(log_returns) < 2:
            return (0.5, 0.0)

        # Create histogram (probability distribution)
        counts, _ = np.histogram(log_returns, bins=bins)

        # Convert counts to probabilities (filter zero bins)
        probabilities = counts[counts > 0] / counts.sum()

        # Shannon entropy via scipy
        raw_entropy = float(scipy_entropy(probabilities))

        # Normalize by max possible entropy = log(bins)
        max_entropy = np.log(bins)
        if max_entropy <= 0:
            return (0.5, 0.0)

        normalized = float(np.clip(raw_entropy / max_entropy, 0.0, 1.0))

        # Confidence scales linearly with data length
        confidence = float(min(1.0, len(close_prices) / 500.0))

        return (normalized, confidence)

    except Exception:
        return (0.5, 0.0)
