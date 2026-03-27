"""Rolling in-memory buffers for ticks and bars (DATA-05, DATA-06).

Provides fixed-size rolling buffers using collections.deque(maxlen=N)
for O(1) append with automatic oldest-eviction. Signal modules access
recent data via numpy array extraction for vectorized computation.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from fxsoqqabot.config.models import DataConfig
from fxsoqqabot.core.events import BarEvent, TickEvent


class TickBuffer:
    """Rolling fixed-size buffer of TickEvents using collections.deque(maxlen=N).

    O(1) append with automatic oldest-eviction per DATA-06.
    """

    def __init__(self, maxlen: int = 10000) -> None:
        self._deque: deque[TickEvent] = deque(maxlen=maxlen)

    def append(self, tick: TickEvent) -> None:
        """Add a single TickEvent to the buffer."""
        self._deque.append(tick)

    def extend(self, ticks: list[TickEvent]) -> None:
        """Add multiple TickEvents to the buffer."""
        self._deque.extend(ticks)

    @property
    def latest(self) -> TickEvent | None:
        """Return the most recent tick, or None if empty."""
        return self._deque[-1] if self._deque else None

    def latest_n(self, n: int) -> list[TickEvent]:
        """Return last n ticks in chronological order."""
        if n >= len(self._deque):
            return list(self._deque)
        return list(self._deque)[-n:]

    def as_arrays(self) -> dict[str, np.ndarray]:
        """Convert buffer to numpy arrays for signal computation.

        Returns dict with keys: time_msc, bid, ask, last, spread, volume_real.
        """
        if not self._deque:
            return {
                k: np.array([], dtype=np.float64)
                for k in ("time_msc", "bid", "ask", "last", "spread", "volume_real")
            }
        return {
            "time_msc": np.array(
                [t.time_msc for t in self._deque], dtype=np.int64
            ),
            "bid": np.array([t.bid for t in self._deque], dtype=np.float64),
            "ask": np.array([t.ask for t in self._deque], dtype=np.float64),
            "last": np.array([t.last for t in self._deque], dtype=np.float64),
            "spread": np.array(
                [t.spread for t in self._deque], dtype=np.float64
            ),
            "volume_real": np.array(
                [t.volume_real for t in self._deque], dtype=np.float64
            ),
        }

    def __len__(self) -> int:
        return len(self._deque)

    def clear(self) -> None:
        """Remove all ticks from the buffer."""
        self._deque.clear()


class BarBuffer:
    """Rolling fixed-size buffer of BarEvents for a single timeframe."""

    def __init__(self, timeframe: str, maxlen: int = 1440) -> None:
        self.timeframe = timeframe
        self._deque: deque[BarEvent] = deque(maxlen=maxlen)

    def append(self, bar: BarEvent) -> None:
        """Add a single BarEvent to the buffer."""
        self._deque.append(bar)

    def extend(self, bars: list[BarEvent]) -> None:
        """Add multiple BarEvents to the buffer."""
        self._deque.extend(bars)

    @property
    def latest(self) -> BarEvent | None:
        """Return the most recent bar, or None if empty."""
        return self._deque[-1] if self._deque else None

    def latest_n(self, n: int) -> list[BarEvent]:
        """Return last n bars in chronological order."""
        if n >= len(self._deque):
            return list(self._deque)
        return list(self._deque)[-n:]

    def as_arrays(self) -> dict[str, np.ndarray]:
        """Convert buffer to numpy arrays for signal computation.

        Returns dict with keys: time, open, high, low, close, tick_volume.
        """
        if not self._deque:
            return {
                k: np.array([], dtype=np.float64)
                for k in ("time", "open", "high", "low", "close", "tick_volume")
            }
        return {
            "time": np.array(
                [b.time for b in self._deque], dtype=np.int64
            ),
            "open": np.array(
                [b.open for b in self._deque], dtype=np.float64
            ),
            "high": np.array(
                [b.high for b in self._deque], dtype=np.float64
            ),
            "low": np.array(
                [b.low for b in self._deque], dtype=np.float64
            ),
            "close": np.array(
                [b.close for b in self._deque], dtype=np.float64
            ),
            "tick_volume": np.array(
                [b.tick_volume for b in self._deque], dtype=np.int64
            ),
        }

    def __len__(self) -> int:
        return len(self._deque)


class BarBufferSet:
    """Collection of BarBuffers, one per configured timeframe per DATA-06."""

    def __init__(self, config: DataConfig) -> None:
        self._buffers: dict[str, BarBuffer] = {
            tf: BarBuffer(tf, maxlen=size)
            for tf, size in config.bar_buffer_sizes.items()
        }

    def __getitem__(self, timeframe: str) -> BarBuffer:
        """Get the BarBuffer for a specific timeframe."""
        return self._buffers[timeframe]

    def update(self, timeframe: str, bars: list[BarEvent]) -> None:
        """Bulk-append bars to the buffer for the given timeframe.

        Silently ignores unknown timeframes.
        """
        if timeframe in self._buffers:
            self._buffers[timeframe].extend(bars)

    @property
    def timeframes(self) -> list[str]:
        """Return list of configured timeframes."""
        return list(self._buffers.keys())
