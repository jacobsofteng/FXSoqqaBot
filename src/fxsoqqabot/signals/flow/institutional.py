"""Institutional footprint detection (FLOW-04, D-14).

Combines statistical anomaly detection (absorption, iceberg reload) with
volume profile clustering from tick data. Identifies institutional buying
and selling activity through volume and price pattern analysis.
"""

from __future__ import annotations

import numpy as np


def detect_institutional_footprints(
    bid: np.ndarray,
    ask: np.ndarray,
    last: np.ndarray,
    volume_real: np.ndarray,
    spread: np.ndarray,
    time_msc: np.ndarray,
    volume_threshold: float = 3.0,
    price_tolerance: float = 0.5,
    min_repeats: int = 3,
) -> tuple[float, float, dict]:
    """Detect institutional footprints from tick data.

    Combines three detection methods:
    - Absorption: large volume without price movement
    - Iceberg reload: repeated large volume at same price level
    - Volume profile: high-volume price nodes indicating institutional levels

    Args:
        bid: Array of bid prices.
        ask: Array of ask prices.
        last: Array of last trade prices.
        volume_real: Array of tick volumes.
        spread: Array of bid-ask spreads.
        time_msc: Array of millisecond timestamps.
        volume_threshold: Std devs above mean for "large" volume.
        price_tolerance: Points range for "same price level" grouping.
        min_repeats: Minimum repetitions at same level for iceberg.

    Returns:
        Tuple of (institutional_score, confidence, signals_dict).
        Score: -1 to +1 (positive = institutional buying, negative = selling).
        Confidence: 0 to 1.
        signals_dict: Details of each detection component.
        Empty arrays return (0.0, 0.0, {}).
    """
    if len(bid) == 0:
        return (0.0, 0.0, {})

    n = len(bid)
    if n < 5:
        return (0.0, 0.0, {})

    mean_vol = float(np.mean(volume_real))
    std_vol = float(np.std(volume_real))

    # Large volume threshold
    if std_vol > 0:
        large_vol_threshold = mean_vol + volume_threshold * std_vol
    else:
        large_vol_threshold = mean_vol * 2.0

    large_mask = volume_real > large_vol_threshold

    # ─── Absorption detection ──────────────────────────────────────
    # Large volume without price movement
    price_changes = np.abs(np.diff(last))
    if len(price_changes) > 0:
        atr_proxy = float(np.mean(price_changes)) if np.mean(price_changes) > 0 else 1.0
    else:
        atr_proxy = 1.0

    # Absorption: large volume ticks where price barely moved
    # We check the price change at each tick (shifted by 1)
    absorption_count = 0
    absorption_buy_vol = 0.0
    absorption_sell_vol = 0.0
    if len(price_changes) > 0:
        # Align large_mask with price_changes (skip first tick)
        large_aligned = large_mask[1:]
        small_move = price_changes < 0.1 * atr_proxy
        absorption_mask = large_aligned & small_move
        absorption_count = int(np.sum(absorption_mask))

        if absorption_count > 0:
            # Determine direction of absorption
            absorption_idx = np.where(absorption_mask)[0] + 1  # offset back
            absorption_lasts = last[absorption_idx]
            absorption_bids = bid[absorption_idx]
            absorption_asks = ask[absorption_idx]
            absorption_vols = volume_real[absorption_idx]

            buy_abs = absorption_lasts >= absorption_asks
            sell_abs = absorption_lasts <= absorption_bids
            absorption_buy_vol = float(np.sum(absorption_vols[buy_abs]))
            absorption_sell_vol = float(np.sum(absorption_vols[sell_abs]))

    # Expected number of large volume ticks by chance
    expected_large = max(1, int(n * 0.01))  # ~1% expected to be large by chance
    absorption_score = min(1.0, absorption_count / max(expected_large, 1))

    # ─── Iceberg reload detection ──────────────────────────────────
    # Group large-volume ticks by price level
    large_indices = np.where(large_mask)[0]
    iceberg_score = 0.0
    iceberg_levels: list[dict] = []

    if len(large_indices) > 0:
        large_prices = last[large_indices]
        large_volumes = volume_real[large_indices]

        # Group by price level within tolerance
        visited = np.zeros(len(large_indices), dtype=bool)

        for i in range(len(large_indices)):
            if visited[i]:
                continue
            level_price = large_prices[i]
            # Find all large ticks within price_tolerance
            within_tol = np.abs(large_prices - level_price) <= price_tolerance
            within_tol &= ~visited
            level_count = int(np.sum(within_tol))

            if level_count >= min_repeats:
                level_vol = float(np.sum(large_volumes[within_tol]))
                iceberg_levels.append({
                    "price": float(level_price),
                    "count": level_count,
                    "volume": level_vol,
                })
                iceberg_score = max(
                    iceberg_score,
                    min(1.0, level_count / (2.0 * min_repeats)),
                )
            visited[within_tol] = True

    # ─── Volume profile clustering ─────────────────────────────────
    # Compute volume-at-price profile
    price_range = float(np.max(last) - np.min(last))
    volume_profile_score = 0.0
    volume_profile_levels: list[dict] = []

    if price_range > 0 and n > 10:
        n_bins = min(50, max(10, n // 10))
        bin_edges = np.linspace(float(np.min(last)), float(np.max(last)), n_bins + 1)
        bin_indices = np.digitize(last, bin_edges) - 1
        bin_indices = np.clip(bin_indices, 0, n_bins - 1)

        volume_profile = np.zeros(n_bins, dtype=np.float64)
        for i in range(n):
            volume_profile[bin_indices[i]] += volume_real[i]

        mean_bin_vol = float(np.mean(volume_profile))
        std_bin_vol = float(np.std(volume_profile))

        if std_bin_vol > 0:
            high_vol_bins = volume_profile > mean_bin_vol + 2.0 * std_bin_vol
            high_vol_count = int(np.sum(high_vol_bins))
            volume_profile_score = min(1.0, high_vol_count / max(1, n_bins // 10))

            for b_idx in np.where(high_vol_bins)[0]:
                bin_center = (bin_edges[b_idx] + bin_edges[b_idx + 1]) / 2.0
                volume_profile_levels.append({
                    "price": float(bin_center),
                    "volume": float(volume_profile[b_idx]),
                })

    # ─── Combine scores ───────────────────────────────────────────
    raw_score = (
        0.4 * absorption_score
        + 0.3 * iceberg_score
        + 0.3 * volume_profile_score
    )

    # Direction: positive if institutional buying detected
    total_inst_buy = absorption_buy_vol
    total_inst_sell = absorption_sell_vol

    # Add iceberg direction from tick classification at iceberg levels
    for level in iceberg_levels:
        level_price = level["price"]
        level_mask = np.abs(last - level_price) <= price_tolerance
        level_lasts = last[level_mask]
        level_bids = bid[level_mask]
        level_asks = ask[level_mask]
        level_vols = volume_real[level_mask]

        buy_at_level = level_lasts >= level_asks
        sell_at_level = level_lasts <= level_bids
        total_inst_buy += float(np.sum(level_vols[buy_at_level]))
        total_inst_sell += float(np.sum(level_vols[sell_at_level]))

    total_inst = total_inst_buy + total_inst_sell
    if total_inst > 0:
        direction = (total_inst_buy - total_inst_sell) / total_inst
    else:
        # Fall back to overall delta direction
        buy_mask = last >= ask
        sell_mask_all = last <= bid
        buy_vol = float(np.sum(volume_real[buy_mask]))
        sell_vol = float(np.sum(volume_real[sell_mask_all]))
        total = buy_vol + sell_vol
        direction = (buy_vol - sell_vol) / total if total > 0 else 0.0

    institutional_score = float(np.clip(direction * raw_score, -1.0, 1.0))

    # Confidence from how strong the signals are
    confidence = min(1.0, raw_score)

    signals_dict: dict = {
        "absorption": {
            "count": absorption_count,
            "score": absorption_score,
            "buy_vol": absorption_buy_vol,
            "sell_vol": absorption_sell_vol,
        },
        "iceberg": {
            "levels": iceberg_levels,
            "score": iceberg_score,
        },
        "volume_profile": {
            "levels": volume_profile_levels,
            "score": volume_profile_score,
        },
        "raw_score": raw_score,
    }

    return (institutional_score, confidence, signals_dict)
