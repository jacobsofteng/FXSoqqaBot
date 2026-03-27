"""Market data feed: ticks, bars, and DOM retrieval with graceful degradation.

Retrieves and converts raw MT5 data into typed event objects:
- TickEvent with computed spread (DATA-01)
- BarEvent for five timeframes M1/M5/M15/H1/H4 (DATA-03)
- DOMSnapshot with graceful degradation when DOM unavailable (DATA-02)
- Stale tick detection for disconnection awareness (Pitfall 7)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

from fxsoqqabot.config.models import DataConfig
from fxsoqqabot.core.events import BarEvent, DOMEntry, DOMSnapshot, TickEvent

if TYPE_CHECKING:
    from fxsoqqabot.execution.mt5_bridge import MT5Bridge

# MT5 timeframe constants mapping.
# These match the numeric values of mt5.TIMEFRAME_* constants.
TIMEFRAME_MAP: dict[str, int] = {
    "M1": 1,      # mt5.TIMEFRAME_M1
    "M5": 5,      # mt5.TIMEFRAME_M5
    "M15": 15,    # mt5.TIMEFRAME_M15
    "H1": 16385,  # mt5.TIMEFRAME_H1
    "H4": 16388,  # mt5.TIMEFRAME_H4
}


class MarketDataFeed:
    """Retrieves and converts market data from MT5 into typed events.

    Handles:
    - Tick data polling (DATA-01)
    - DOM depth snapshots with graceful degradation (DATA-02)
    - Multi-timeframe bar data (DATA-03)
    - Stale data detection (Pitfall 7)
    """

    def __init__(self, bridge: MT5Bridge, config: DataConfig) -> None:
        self._bridge = bridge
        self._config = config
        self._logger = structlog.get_logger().bind(component="data_feed")
        self._dom_warned = False  # Rate-limit DOM empty warnings
        self._last_tick_time_msc: int = 0

    async def fetch_ticks(
        self, symbol: str, count: int = 100
    ) -> list[TickEvent]:
        """Fetch recent ticks, convert to TickEvent list.

        Computes spread as ask - bid for each tick.
        Returns empty list on MT5 failure (per Pitfall 1: silent failures).
        """
        raw = await self._bridge.get_ticks(
            symbol, datetime.now(timezone.utc), count
        )
        if raw is None or len(raw) == 0:
            self._logger.warning("no_tick_data", symbol=symbol)
            return []

        events: list[TickEvent] = []
        for row in raw:
            event = TickEvent(
                symbol=symbol,
                time_msc=int(row["time_msc"]),
                bid=float(row["bid"]),
                ask=float(row["ask"]),
                last=float(row["last"]),
                volume=int(row["volume"]),
                flags=int(row["flags"]),
                volume_real=float(row["volume_real"]),
                spread=float(row["ask"] - row["bid"]),
            )
            events.append(event)

        if events:
            self._last_tick_time_msc = events[-1].time_msc

        return events

    async def fetch_bars(
        self, symbol: str, timeframe: str, count: int | None = None
    ) -> list[BarEvent]:
        """Fetch bars for a single timeframe, convert to BarEvent list.

        Args:
            symbol: Trading symbol (e.g., "XAUUSD").
            timeframe: Timeframe string ("M1", "M5", "M15", "H1", "H4").
            count: Number of bars. Defaults to bar_buffer_sizes[timeframe].

        Returns:
            List of BarEvent, empty on failure or unknown timeframe.
        """
        if count is None:
            count = self._config.bar_buffer_sizes.get(timeframe, 100)

        tf_const = TIMEFRAME_MAP.get(timeframe)
        if tf_const is None:
            self._logger.error("unknown_timeframe", timeframe=timeframe)
            return []

        raw = await self._bridge.get_rates(
            symbol, tf_const, datetime.now(timezone.utc), count
        )
        if raw is None or len(raw) == 0:
            self._logger.warning(
                "no_bar_data", symbol=symbol, timeframe=timeframe
            )
            return []

        return [
            BarEvent(
                symbol=symbol,
                timeframe=timeframe,
                time=int(row["time"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                tick_volume=int(row["tick_volume"]),
                spread=int(row["spread"]),
                real_volume=int(row["real_volume"]),
            )
            for row in raw
        ]

    async def fetch_multi_timeframe_bars(
        self, symbol: str
    ) -> dict[str, list[BarEvent]]:
        """Fetch bars for all configured timeframes (M1, M5, M15, H1, H4).

        Per DATA-03: multi-timeframe bar data for signal computation.
        """
        result: dict[str, list[BarEvent]] = {}
        for tf in self._config.bar_buffer_sizes:
            result[tf] = await self.fetch_bars(symbol, tf)
        return result

    async def fetch_dom(self, symbol: str) -> DOMSnapshot:
        """Fetch DOM depth. Returns DOMSnapshot with empty entries if unavailable.

        Per DATA-02: graceful degradation when DOM data is limited or
        unavailable from broker feed. Never raises, never crashes.

        Warning is logged once on first empty DOM result to avoid log spam.
        """
        raw = await self._bridge.get_dom(symbol)
        if raw is None or len(raw) == 0:
            if not self._dom_warned:
                self._logger.warning(
                    "dom_unavailable_degrading_to_tick_only", symbol=symbol
                )
                self._dom_warned = True
            return DOMSnapshot(symbol=symbol, time_msc=0, entries=())

        entries = tuple(
            DOMEntry(
                type=item.type,
                price=item.price,
                volume=item.volume,
                volume_dbl=item.volume_dbl,
            )
            for item in raw
        )
        return DOMSnapshot(
            symbol=symbol,
            time_msc=int(datetime.now(timezone.utc).timestamp() * 1000),
            entries=entries,
        )

    def check_tick_freshness(self, max_age_seconds: float = 10.0) -> bool:
        """Check if the latest tick is fresh enough.

        Per Pitfall 7: stale data indicates possible disconnection.
        Should be called periodically to detect connection issues.

        Args:
            max_age_seconds: Maximum acceptable tick age in seconds.

        Returns:
            True if latest tick is within threshold, False if stale or
            no ticks received yet.
        """
        if self._last_tick_time_msc == 0:
            return False
        now_msc = int(datetime.now(timezone.utc).timestamp() * 1000)
        age_seconds = (now_msc - self._last_tick_time_msc) / 1000.0
        return age_seconds < max_age_seconds
