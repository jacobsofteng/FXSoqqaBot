"""LiveDataFeedAdapter: wraps existing buffer infrastructure as DataFeedProtocol.

Uses the adapter pattern to bridge existing MarketDataFeed + TickBuffer +
BarBufferSet (Phase 1 infrastructure) to the DataFeedProtocol interface.
This allows the TradingEngine and signal modules to operate through the
protocol abstraction without modifying any existing live trading code.

The BacktestDataFeed (Phase 3 Plan 02) will implement DataFeedProtocol
directly, replaying historical data through the same interface.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from fxsoqqabot.core.events import DOMSnapshot
from fxsoqqabot.data.buffers import BarBufferSet, TickBuffer


class LiveDataFeedAdapter:
    """Adapter wrapping TickBuffer + BarBufferSet to implement DataFeedProtocol.

    Uses the adapter pattern (recommended by research) to keep existing
    live trading code untouched. The TradingEngine can use this adapter,
    and BacktestDataFeed implements the same Protocol directly.

    This class satisfies DataFeedProtocol via structural typing -- it has
    all four required methods with matching signatures.
    """

    def __init__(
        self,
        tick_buffer: TickBuffer,
        bar_buffers: BarBufferSet,
        symbol: str = "XAUUSD",
    ) -> None:
        self._tick_buffer = tick_buffer
        self._bar_buffers = bar_buffers
        self._symbol = symbol

    async def get_tick_arrays(self, symbol: str) -> dict[str, np.ndarray]:
        """Return tick data as numpy arrays from the underlying TickBuffer.

        Keys match TickBuffer.as_arrays(): time_msc, bid, ask, last,
        spread, volume_real.
        """
        return self._tick_buffer.as_arrays()

    async def get_bar_arrays(
        self, symbol: str
    ) -> dict[str, dict[str, np.ndarray]]:
        """Return bar data as nested dict from the underlying BarBufferSet.

        Outer keys are timeframe strings ("M1", "M5", etc.).
        Inner keys match BarBuffer.as_arrays(): time, open, high, low,
        close, tick_volume.
        """
        return {
            tf: self._bar_buffers[tf].as_arrays()
            for tf in self._bar_buffers.timeframes
        }

    async def get_dom(self, symbol: str) -> DOMSnapshot | None:
        """Return None -- DOM is not currently captured in live engine buffers.

        When DOM buffering is added in a future phase, this method can be
        updated to return the latest DOMSnapshot.
        """
        return None

    def check_tick_freshness(self, max_age_seconds: float = 10.0) -> bool:
        """Check if the latest tick in the buffer is recent enough.

        Args:
            max_age_seconds: Maximum acceptable age in seconds.

        Returns:
            True if latest tick is within threshold, False if stale or
            no ticks in buffer.
        """
        latest = self._tick_buffer.latest
        if latest is None:
            return False
        now_msc = int(datetime.now(UTC).timestamp() * 1000)
        age_ms = now_msc - latest.time_msc
        return age_ms < max_age_seconds * 1000
