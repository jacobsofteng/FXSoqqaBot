"""Bid-ask aggression imbalance detection (FLOW-02) and HFT signatures (FLOW-05).

Measures the ratio of volume hitting ask vs bid over a sliding window with
z-score significance testing. Also detects HFT acceleration signatures from
tick velocity and spread widening patterns.
"""

from __future__ import annotations

import numpy as np


def compute_aggression_imbalance(
    bid: np.ndarray,
    ask: np.ndarray,
    last: np.ndarray,
    volume_real: np.ndarray,
    window: int = 200,
) -> tuple[float, float, float]:
    """Compute bid-ask aggression imbalance with z-score significance.

    For each tick in the window, volume hitting the ask (last >= ask) is
    buy aggression, volume hitting the bid (last <= bid) is sell aggression.

    Args:
        bid: Array of bid prices.
        ask: Array of ask prices.
        last: Array of last trade prices.
        volume_real: Array of tick volumes.
        window: Number of recent ticks to analyze.

    Returns:
        Tuple of (imbalance_ratio, zscore, confidence).
        imbalance_ratio: [-1, +1], positive = buy-dominant.
        zscore: significance of the imbalance.
        confidence: min(1.0, abs(zscore) / 3.0).
        Empty arrays return (0.0, 0.0, 0.0).
    """
    if len(bid) == 0:
        return (0.0, 0.0, 0.0)

    # Slice to last `window` ticks
    bid_w = bid[-window:]
    ask_w = ask[-window:]
    last_w = last[-window:]
    vol_w = volume_real[-window:]

    n = len(bid_w)

    # Classify and accumulate volume
    buy_mask = last_w >= ask_w
    sell_mask = last_w <= bid_w

    buy_vol = float(np.sum(vol_w[buy_mask]))
    sell_vol = float(np.sum(vol_w[sell_mask]))
    total_vol = buy_vol + sell_vol

    if total_vol == 0:
        return (0.0, 0.0, 0.0)

    # Overall imbalance ratio
    imbalance_ratio = (buy_vol - sell_vol) / total_vol

    # Compute rolling imbalance per tick for z-score
    # Each tick contributes +volume (buy) or -volume (sell) or 0 (ambiguous)
    per_tick_imbalance = np.zeros(n, dtype=np.float64)
    per_tick_imbalance[buy_mask] = vol_w[buy_mask]
    per_tick_imbalance[sell_mask] = -vol_w[sell_mask]

    mean_imb = float(np.mean(per_tick_imbalance))
    std_imb = float(np.std(per_tick_imbalance))

    if std_imb == 0:
        # Zero variance with nonzero mean means perfect unanimity --
        # this is the strongest possible signal
        if mean_imb != 0:
            zscore = float(np.sign(mean_imb)) * 10.0  # saturate
        else:
            zscore = 0.0
    else:
        zscore = mean_imb / (std_imb / np.sqrt(n))

    confidence = min(1.0, abs(zscore) / 3.0)

    return (imbalance_ratio, zscore, confidence)


def detect_hft_signatures(
    time_msc: np.ndarray,
    spread: np.ndarray,
    volume_real: np.ndarray,
    tick_velocity_threshold: float = 5.0,
    spread_widen_multiplier: float = 2.0,
) -> tuple[bool, float]:
    """Detect HFT acceleration signatures from tick data.

    HFT signature = tick velocity > mean + threshold * std AND
    spread > mean_spread * multiplier simultaneously.

    Args:
        time_msc: Array of millisecond timestamps.
        spread: Array of bid-ask spreads.
        volume_real: Array of tick volumes.
        tick_velocity_threshold: Standard deviations above mean for velocity.
        spread_widen_multiplier: Multiple of mean spread for widening.

    Returns:
        Tuple of (is_hft_detected, confidence).
        Empty/single arrays return (False, 0.0).
    """
    if len(time_msc) < 2:
        return (False, 0.0)

    # Compute inter-tick time deltas in seconds
    dt_ms = np.diff(time_msc.astype(np.float64))
    # Avoid division by zero
    dt_sec = np.maximum(dt_ms / 1000.0, 1e-6)

    # Tick velocity: ticks per second (inverse of inter-tick time)
    tick_velocity = 1.0 / dt_sec

    mean_vel = float(np.mean(tick_velocity))
    std_vel = float(np.std(tick_velocity))

    if std_vel == 0:
        return (False, 0.0)

    velocity_threshold = mean_vel + tick_velocity_threshold * std_vel

    # Spread analysis (use spread[1:] to align with diff indices)
    spread_aligned = spread[1:]
    mean_spread = float(np.mean(spread))

    if mean_spread == 0:
        return (False, 0.0)

    spread_threshold = mean_spread * spread_widen_multiplier

    # HFT: both velocity spike AND spread widening simultaneously
    hft_mask = (tick_velocity > velocity_threshold) & (
        spread_aligned > spread_threshold
    )

    hft_count = int(np.sum(hft_mask))

    if hft_count == 0:
        return (False, 0.0)

    # Confidence based on how many ticks show HFT signature
    # and how far above thresholds they are
    hft_velocities = tick_velocity[hft_mask]
    max_excess = float(np.max((hft_velocities - velocity_threshold) / std_vel))
    confidence = min(1.0, max_excess / tick_velocity_threshold)
    confidence = max(0.0, confidence)

    return (True, confidence)
