"""
Swing Detector — Module 5 (ATR-based ZigZag)

Foundation of the entire system. Every other module depends on accurate swings.
Uses H1 bars for primary swing detection, H4 for time structure, D1 for trend.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class Bar:
    """OHLCV bar with sequential index."""
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    bar_index: int


def bars_from_dataframe(df: pd.DataFrame) -> list[Bar]:
    """Convert a pandas OHLCV DataFrame (time-indexed) to list[Bar]."""
    bars = []
    for i, (t, row) in enumerate(df.iterrows()):
        bars.append(Bar(
            time=t.to_pydatetime() if hasattr(t, 'to_pydatetime') else t,
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=int(row.get('volume', 0)),
            bar_index=i,
        ))
    return bars


def detect_swings_atr(bars: list[Bar], atr_period: int = 14,
                      atr_multiplier: float = 1.5) -> list[dict]:
    """
    ATR-based ZigZag swing detector.

    Algorithm:
      1. Calculate ATR(14) as rolling average of True Range
      2. Threshold = ATR × multiplier
      3. Track current direction (up/down)
      4. When price moves > threshold from last swing in opposite direction,
         confirm a new swing point

    Args:
        bars: List of OHLCV bars
        atr_period: ATR lookback (default 14)
        atr_multiplier: Minimum move as multiple of ATR (default 1.5)

    Returns:
        List of swing dicts:
        [{'type': 'high'|'low', 'price': float, 'time': datetime,
          'bar_index': int, 'atr_at_swing': float}]
    """
    if len(bars) < atr_period + 1:
        return []

    # Calculate True Range
    trs = []
    for i in range(1, len(bars)):
        tr = max(
            bars[i].high - bars[i].low,
            abs(bars[i].high - bars[i - 1].close),
            abs(bars[i].low - bars[i - 1].close),
        )
        trs.append(tr)

    swings = []
    direction: Optional[str] = None  # None, 'up', 'down'
    last_high = bars[0].high
    last_high_idx = 0
    last_low = bars[0].low
    last_low_idx = 0

    for i in range(atr_period, len(bars)):
        # Rolling ATR
        start = max(0, i - atr_period)
        atr = sum(trs[start:i]) / min(i, atr_period)
        threshold = atr * atr_multiplier

        if bars[i].high > last_high:
            last_high = bars[i].high
            last_high_idx = i
        if bars[i].low < last_low:
            last_low = bars[i].low
            last_low_idx = i

        if direction != 'down' and last_high - bars[i].low > threshold:
            # Confirm swing HIGH — use bar's own bar_index (M5 global index)
            swings.append({
                'type': 'high',
                'price': last_high,
                'time': bars[last_high_idx].time,
                'bar_index': bars[last_high_idx].bar_index,
                'atr_at_swing': atr,
            })
            direction = 'down'
            last_low = bars[i].low
            last_low_idx = i

        elif direction != 'up' and bars[i].high - last_low > threshold:
            # Confirm swing LOW — use bar's own bar_index (M5 global index)
            swings.append({
                'type': 'low',
                'price': last_low,
                'time': bars[last_low_idx].time,
                'bar_index': bars[last_low_idx].bar_index,
                'atr_at_swing': atr,
            })
            direction = 'up'
            last_high = bars[i].high
            last_high_idx = i

    return swings


def detect_swings_df(df: pd.DataFrame, atr_period: int = 14,
                     atr_multiplier: float = 1.5) -> list[dict]:
    """Convenience: detect swings directly from a pandas OHLCV DataFrame."""
    bars = bars_from_dataframe(df)
    return detect_swings_atr(bars, atr_period, atr_multiplier)


# Legacy compatibility: keep old function name
def detect_swings(df: pd.DataFrame, atr_multiplier: float = 2.5,
                  atr_period: int = 14, min_bars_between: int = 3) -> pd.DataFrame:
    """Legacy wrapper returning a DataFrame for backwards compatibility."""
    swings = detect_swings_df(df, atr_period, atr_multiplier)
    if not swings:
        return pd.DataFrame(columns=['time', 'price', 'type', 'bar_index'])
    return pd.DataFrame(swings)
