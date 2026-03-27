"""BacktestDataFeed: historical data feed implementing DataFeedProtocol.

Loads M1 bars from a pandas DataFrame and synthesizes tick_arrays +
multi-timeframe bar_arrays for signal modules.

Per D-02: synthesizes approximate tick data from M1 bars with
bar_only flag reducing confidence (same degradation pattern as
DOM-less order flow from Phase 2).

Anti-lookahead: only bars with time <= current_time are visible (Pitfall 1).

Key shapes match existing buffer outputs:
- get_tick_arrays: same keys as TickBuffer.as_arrays() (time_msc, bid, ask, last, spread, volume_real)
- get_bar_arrays: dict[timeframe, same keys as BarBuffer.as_arrays()] (time, open, high, low, close, tick_volume)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterator

import numpy as np
import pandas as pd

from fxsoqqabot.backtest.clock import BacktestClock
from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.core.events import DOMSnapshot


# Buffer sizes per timeframe (matches DataConfig.bar_buffer_sizes defaults)
_BAR_BUFFER_SIZES = {
    "M1": 1440,
    "M5": 288,
    "M15": 96,
    "H1": 24,
    "H4": 6,
}

# Resampling factors: how many M1 bars per bar of this timeframe
_RESAMPLE_FACTORS = {
    "M5": 5,
    "M15": 15,
    "H1": 60,
    "H4": 240,
}


class BacktestDataFeed:
    """Historical data feed implementing DataFeedProtocol.

    Loads M1 bars from a pandas DataFrame and synthesizes tick_arrays +
    multi-timeframe bar_arrays for signal modules.

    Per D-02: synthesizes approximate tick data from M1 bars with reduced
    confidence (same degradation pattern as DOM-less order flow from Phase 2).

    Anti-lookahead: only bars where time <= current bar time are visible.
    """

    def __init__(
        self,
        bars_df: pd.DataFrame,
        config: BacktestConfig,
        clock: BacktestClock,
    ) -> None:
        """Initialize from a DataFrame of M1 bars sorted by time ascending.

        Args:
            bars_df: M1 bar DataFrame with columns time, open, high, low, close, volume.
            config: Backtest configuration (spread model, symbol, etc.).
            clock: BacktestClock for deterministic time.
        """
        self._config = config
        self._clock = clock
        self._current_idx = 0
        self._rng = np.random.default_rng(config.mc_seed + 1)  # Different seed from executor

        # Pre-compute numpy arrays from bars for efficient slicing
        self._times = bars_df["time"].values.astype(np.int64)
        self._opens = bars_df["open"].values.astype(np.float64)
        self._highs = bars_df["high"].values.astype(np.float64)
        self._lows = bars_df["low"].values.astype(np.float64)
        self._closes = bars_df["close"].values.astype(np.float64)
        self._volumes = bars_df["volume"].values.astype(np.int64)
        self._n_bars = len(bars_df)

    def advance_bar(self, bar_idx: int) -> dict:
        """Advance to bar at index, update internal state. Return bar dict.

        Args:
            bar_idx: Index into the M1 bar array.

        Returns:
            Bar dict with keys: time, open, high, low, close, volume.
        """
        self._current_idx = bar_idx
        return {
            "time": int(self._times[bar_idx]),
            "open": float(self._opens[bar_idx]),
            "high": float(self._highs[bar_idx]),
            "low": float(self._lows[bar_idx]),
            "close": float(self._closes[bar_idx]),
            "volume": int(self._volumes[bar_idx]),
        }

    async def get_tick_arrays(self, symbol: str) -> dict[str, np.ndarray]:
        """Synthesize tick arrays from recent M1 bars per D-02.

        For each recent M1 bar, creates one synthetic tick:
          time_msc = time * 1000
          bid = close
          ask = close + sampled_spread
          last = close
          spread = sampled_spread
          volume_real = float(tick_volume)

        Uses bars from (current_idx - buffer_size) to current_idx (inclusive).

        Args:
            symbol: Instrument symbol (for protocol conformance).

        Returns:
            Dict with keys: time_msc, bid, ask, last, spread, volume_real.
            All values are numpy arrays.
        """
        empty = {
            k: np.array([], dtype=np.float64)
            for k in ("time_msc", "bid", "ask", "last", "spread", "volume_real")
        }

        if self._current_idx < 0 or self._n_bars == 0:
            return empty

        # Determine slice: from (current_idx - buffer + 1) to current_idx (inclusive)
        # Use tick buffer equivalent -- synthesize from recent M1 bars
        tick_buf_size = min(self._current_idx + 1, _BAR_BUFFER_SIZES["M1"])
        start = max(0, self._current_idx - tick_buf_size + 1)
        end = self._current_idx + 1  # exclusive

        n = end - start
        if n == 0:
            return empty

        times_slice = self._times[start:end]
        closes_slice = self._closes[start:end]
        volumes_slice = self._volumes[start:end]

        # Synthesize spreads for each tick
        spreads = np.empty(n, dtype=np.float64)
        for i in range(n):
            hour_utc = datetime.fromtimestamp(int(times_slice[i]), tz=UTC).hour
            spreads[i] = self._config.spread_model.sample_spread(hour_utc, self._rng)

        # Build tick arrays matching TickBuffer.as_arrays() keys
        time_msc = (times_slice * 1000).astype(np.int64)
        bid = closes_slice.copy()
        ask = closes_slice + spreads
        last = closes_slice.copy()
        volume_real = volumes_slice.astype(np.float64)

        return {
            "time_msc": time_msc,
            "bid": bid,
            "ask": ask,
            "last": last,
            "spread": spreads,
            "volume_real": volume_real,
        }

    async def get_bar_arrays(
        self, symbol: str
    ) -> dict[str, dict[str, np.ndarray]]:
        """Build multi-timeframe bar arrays from M1 data up to current bar.

        M1: direct slice of recent bars (up to 1440).
        M5/M15/H1/H4: resample M1 bars in groups.

        CRITICAL: only uses bars where index <= current_idx (no lookahead per Pitfall 1).

        Each inner dict has keys: time, open, high, low, close, tick_volume (as np.ndarray).

        Args:
            symbol: Instrument symbol (for protocol conformance).

        Returns:
            Dict[timeframe_str, Dict[key, np.ndarray]].
        """
        result: dict[str, dict[str, np.ndarray]] = {}

        # M1: direct slice of recent bars
        m1_count = min(self._current_idx + 1, _BAR_BUFFER_SIZES["M1"])
        m1_start = max(0, self._current_idx + 1 - m1_count)
        m1_end = self._current_idx + 1

        result["M1"] = self._slice_bars(m1_start, m1_end)

        # Higher timeframes: resample M1 bars
        for tf, factor in _RESAMPLE_FACTORS.items():
            max_bars = _BAR_BUFFER_SIZES[tf]
            # We need factor * max_bars M1 bars to produce max_bars of this TF
            m1_needed = factor * max_bars
            tf_m1_count = min(self._current_idx + 1, m1_needed)
            tf_start = max(0, self._current_idx + 1 - tf_m1_count)
            tf_end = self._current_idx + 1

            result[tf] = self._resample_bars(tf_start, tf_end, factor)

        return result

    def _slice_bars(self, start: int, end: int) -> dict[str, np.ndarray]:
        """Slice M1 bar arrays from start to end (exclusive).

        Returns dict matching BarBuffer.as_arrays() output shape.
        """
        if start >= end:
            return {
                k: np.array([], dtype=np.float64)
                for k in ("time", "open", "high", "low", "close", "tick_volume")
            }

        return {
            "time": self._times[start:end].copy(),
            "open": self._opens[start:end].copy(),
            "high": self._highs[start:end].copy(),
            "low": self._lows[start:end].copy(),
            "close": self._closes[start:end].copy(),
            "tick_volume": self._volumes[start:end].copy(),
        }

    def _resample_bars(
        self, start: int, end: int, factor: int
    ) -> dict[str, np.ndarray]:
        """Resample M1 bars into higher timeframe bars.

        Groups M1 bars in chunks of `factor`, computing OHLCV for each group:
        - time: first bar's time in the group
        - open: first bar's open
        - high: max of all highs in group
        - low: min of all lows in group
        - close: last bar's close
        - tick_volume: sum of all volumes in group

        Only complete groups are included to avoid partial bars.
        """
        n = end - start
        if n < factor:
            return {
                k: np.array([], dtype=np.float64)
                for k in ("time", "open", "high", "low", "close", "tick_volume")
            }

        # Trim to complete groups
        n_complete = (n // factor) * factor
        trim_start = end - n_complete  # Trim from the beginning (oldest bars)

        times_s = self._times[trim_start:end]
        opens_s = self._opens[trim_start:end]
        highs_s = self._highs[trim_start:end]
        lows_s = self._lows[trim_start:end]
        closes_s = self._closes[trim_start:end]
        vols_s = self._volumes[trim_start:end]

        n_groups = n_complete // factor

        # Reshape into groups
        times_g = times_s.reshape(n_groups, factor)
        opens_g = opens_s.reshape(n_groups, factor)
        highs_g = highs_s.reshape(n_groups, factor)
        lows_g = lows_s.reshape(n_groups, factor)
        closes_g = closes_s.reshape(n_groups, factor)
        vols_g = vols_s.reshape(n_groups, factor)

        return {
            "time": times_g[:, 0].copy(),  # First bar's time
            "open": opens_g[:, 0].copy(),  # First bar's open
            "high": highs_g.max(axis=1),  # Max high
            "low": lows_g.min(axis=1),  # Min low
            "close": closes_g[:, -1].copy(),  # Last bar's close
            "tick_volume": vols_g.sum(axis=1),  # Sum of volumes
        }

    async def get_dom(self, symbol: str) -> DOMSnapshot | None:
        """Always returns None -- no DOM in historical data.

        Args:
            symbol: Instrument symbol (for protocol conformance).

        Returns:
            None.
        """
        return None

    def check_tick_freshness(self, max_age_seconds: float = 10.0) -> bool:
        """Always True in backtest mode.

        Time is deterministic in backtesting -- freshness is meaningless.

        Args:
            max_age_seconds: Ignored in backtest mode.

        Returns:
            True always.
        """
        return True

    def iterate(
        self, start_idx: int, end_idx: int
    ) -> Iterator[tuple[int, dict]]:
        """Generator yielding (bar_idx, bar_dict) for replay loop.

        Args:
            start_idx: Starting bar index (inclusive).
            end_idx: Ending bar index (exclusive).

        Yields:
            Tuples of (bar_index, bar_dict).
        """
        for idx in range(start_idx, min(end_idx, self._n_bars)):
            yield idx, self.advance_bar(idx)
