"""Volatility compression/expansion phase transition detection.

Detects whether the market is in a volatility compression (energy
building, breakout imminent), expansion (energy releasing, move
in progress), or normal state using ATR-based analysis.

Implements QTIM-02 (timing estimation for move begin/end).

The "energy" concept: volatility compression stores energy like
a coiled spring. When compression breaks, it releases as a
directional move. The direction comes from other modules; timing
tells the fusion core WHEN the move is likely.
"""

from __future__ import annotations

import numpy as np


def compute_atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Compute Average True Range with Wilder smoothing.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    Wilder smoothing: ATR[i] = ATR[i-1] * (period-1)/period + TR[i]/period

    Args:
        high: Array of high prices.
        low: Array of low prices.
        close: Array of close prices.
        period: Smoothing period (default 14).

    Returns:
        ATR array with same length as input. First ``period`` values
        use simple average of TR. If len < period, all values are
        the simple average of available TR.
    """
    n = len(close)

    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]

    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )

    atr = np.empty(n, dtype=np.float64)

    if n <= period:
        # Not enough data for Wilder smoothing -- use simple average
        avg_tr = float(np.mean(tr))
        atr[:] = avg_tr
        return atr

    # First `period` values: simple average of TR
    initial_avg = float(np.mean(tr[:period]))
    atr[:period] = initial_avg

    # Wilder smoothing for remaining values
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


def detect_phase_transition(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    atr_period: int = 14,
    compression_threshold: float = 0.5,
    expansion_threshold: float = 2.0,
) -> tuple[str, float, float]:
    """Detect volatility phase transition state.

    Compares current ATR to the long-term average to determine
    whether the market is in compression (low vol, energy building),
    expansion (high vol, energy releasing), or normal state.

    Args:
        close: Array of close prices.
        high: Array of high prices.
        low: Array of low prices.
        atr_period: Period for ATR computation (default 14).
        compression_threshold: ATR ratio below which compression is
            detected (default 0.5 = ATR is 50% of average).
        expansion_threshold: ATR ratio above which expansion is
            detected (default 2.0 = ATR is 200% of average).

    Returns:
        (state, energy, confidence) where:
        - state: "compression", "expansion", or "normal".
        - energy: stored/releasing energy level (0.0 to ~1.0+).
        - confidence: data quality estimate from 0.0 to 1.0.
    """
    atr = compute_atr(high, low, close, atr_period)

    # Long-term ATR average
    long_term_avg = float(np.mean(atr))

    if long_term_avg < 1e-10:
        # Essentially zero volatility -- no meaningful state
        return "normal", 0.0, 0.0

    # Current ATR ratio vs long-term average
    current_ratio = float(atr[-1]) / long_term_avg

    if current_ratio < compression_threshold:
        state = "compression"
        energy = float(1.0 - current_ratio)  # Stored energy
    elif current_ratio > expansion_threshold:
        state = "expansion"
        energy = float(current_ratio - 1.0)  # Releasing energy
    else:
        state = "normal"
        energy = 0.0

    # Confidence: need enough data for meaningful ATR
    confidence = float(min(1.0, len(close) / (3 * atr_period)))

    return state, energy, confidence
