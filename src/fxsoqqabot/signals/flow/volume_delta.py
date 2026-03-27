"""Cumulative volume delta computation from tick data (FLOW-01).

Classifies each tick as buy-initiated (last >= ask), sell-initiated
(last <= bid), or ambiguous (between bid and ask) per Research Pitfall 3.
Accumulates buy/sell volume over a rolling window.
"""

from __future__ import annotations

import numpy as np


def compute_volume_delta(
    bid: np.ndarray,
    ask: np.ndarray,
    last: np.ndarray,
    volume_real: np.ndarray,
    window: int = 100,
) -> tuple[float, float, float, float]:
    """Compute cumulative volume delta from tick arrays.

    Classifies ticks as buy-initiated if last >= ask (lifting the offer),
    sell-initiated if last <= bid (hitting the bid). Ticks between bid
    and ask are ambiguous.

    Args:
        bid: Array of bid prices.
        ask: Array of ask prices.
        last: Array of last trade prices.
        volume_real: Array of tick volumes.
        window: Number of recent ticks to use.

    Returns:
        Tuple of (cumulative_delta, buy_volume, sell_volume, ambiguous_pct).
        Empty arrays return (0.0, 0.0, 0.0, 1.0).
    """
    if len(bid) == 0:
        return (0.0, 0.0, 0.0, 1.0)

    # Slice to last `window` ticks
    bid_w = bid[-window:]
    ask_w = ask[-window:]
    last_w = last[-window:]
    vol_w = volume_real[-window:]

    n = len(bid_w)

    # Classify ticks: buy if last >= ask, sell if last <= bid
    buy_mask = last_w >= ask_w
    sell_mask = last_w <= bid_w
    ambiguous_mask = ~buy_mask & ~sell_mask

    buy_vol = float(np.sum(vol_w[buy_mask]))
    sell_vol = float(np.sum(vol_w[sell_mask]))
    ambiguous_count = int(np.sum(ambiguous_mask))

    cum_delta = buy_vol - sell_vol
    ambiguous_pct = ambiguous_count / n if n > 0 else 1.0

    return (cum_delta, buy_vol, sell_vol, ambiguous_pct)
