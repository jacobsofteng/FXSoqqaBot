"""DOM depth analysis (FLOW-03).

Processes DOMSnapshot entries to compute order book imbalance between
bid and ask sides. Detects large hidden orders when single entries
exceed average by 3x.
"""

from __future__ import annotations

import numpy as np

from fxsoqqabot.core.events import DOMSnapshot


def analyze_dom(
    dom: DOMSnapshot | None,
    min_depth: int = 5,
) -> tuple[float, float]:
    """Analyze DOM snapshot for order book imbalance.

    Separates entries by type: type=1 is sell (ask side),
    type=2 is buy (bid side) per MT5 BookInfo convention.

    Args:
        dom: DOM snapshot or None for graceful degradation.
        min_depth: Minimum depth levels for full confidence.

    Returns:
        Tuple of (imbalance_direction, confidence).
        imbalance_direction: [-1, +1], positive = bid-heavy (buying pressure).
        confidence: scaled by depth relative to min_depth.
        None or empty DOM returns (0.0, 0.0).
    """
    if dom is None or len(dom.entries) == 0:
        return (0.0, 0.0)

    # Separate by type: type=1 = sell (ask side), type=2 = buy (bid side)
    buy_entries = [e for e in dom.entries if e.type == 2]
    sell_entries = [e for e in dom.entries if e.type == 1]

    bid_volume = sum(e.volume_dbl for e in buy_entries)
    ask_volume = sum(e.volume_dbl for e in sell_entries)
    total_volume = bid_volume + ask_volume

    if total_volume == 0:
        return (0.0, 0.0)

    # Imbalance: positive = more on bid side (buying support)
    imbalance = (bid_volume - ask_volume) / total_volume

    # Check for large hidden orders (single entry > 3x average)
    all_volumes = [e.volume_dbl for e in dom.entries]
    avg_volume = np.mean(all_volumes) if all_volumes else 0.0
    _has_large_order = any(v > 3.0 * avg_volume for v in all_volumes) if avg_volume > 0 else False

    # Confidence scales with depth relative to min_depth
    total_levels = len(buy_entries) + len(sell_entries)
    confidence = min(1.0, total_levels / (2.0 * min_depth))

    return (float(imbalance), float(confidence))
