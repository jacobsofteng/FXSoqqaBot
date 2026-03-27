"""DataFeedProtocol: interface abstraction for live and backtest data sources.

Defines the structural typing contract that both LiveDataFeedAdapter (wrapping
real MT5 data) and BacktestDataFeed (replaying historical data) implement.
Signal modules depend on this protocol, not on concrete data sources.

Key shapes match existing buffer outputs:
- get_tick_arrays: same keys as TickBuffer.as_arrays() (time_msc, bid, ask, last, spread, volume_real)
- get_bar_arrays: dict[timeframe, same keys as BarBuffer.as_arrays()] (time, open, high, low, close, tick_volume)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from fxsoqqabot.core.events import DOMSnapshot


@runtime_checkable
class DataFeedProtocol(Protocol):
    """Protocol for all data feed implementations (live and backtest).

    Any class implementing these four methods satisfies the protocol
    via structural typing -- no explicit inheritance needed.
    """

    async def get_tick_arrays(self, symbol: str) -> dict[str, np.ndarray]:
        """Return tick data as numpy arrays.

        Keys: time_msc, bid, ask, last, spread, volume_real.
        Matches TickBuffer.as_arrays() output shape.
        """
        ...

    async def get_bar_arrays(
        self, symbol: str
    ) -> dict[str, dict[str, np.ndarray]]:
        """Return bar data as nested dict of numpy arrays.

        Outer keys: timeframe strings ("M1", "M5", "M15", "H1", "H4").
        Inner keys: time, open, high, low, close, tick_volume.
        Matches {tf: BarBuffer.as_arrays()} output shape.
        """
        ...

    async def get_dom(self, symbol: str) -> DOMSnapshot | None:
        """Return current DOM snapshot, or None if unavailable.

        Backtest mode always returns None unless DOM replay is implemented.
        """
        ...

    def check_tick_freshness(self, max_age_seconds: float = 10.0) -> bool:
        """Check if tick data is fresh enough for trading.

        In live mode, checks real time elapsed since last tick.
        In backtest mode, always returns True (time is deterministic).
        """
        ...
