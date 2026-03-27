"""Clock Protocol and implementations for live and backtest time control.

Provides deterministic time for backtesting (BacktestClock) and real wall
time for live trading (WallClock). All time-dependent code should depend
on the Clock protocol, not on datetime.now() directly.

Usage:
    # Live trading
    clock = WallClock()

    # Backtesting -- time advances only when told to
    clock = BacktestClock()
    clock.advance(1705318200000)  # Set to specific timestamp
    print(clock.now())  # 2024-01-15 12:30:00+00:00
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Protocol for time sources.

    Abstracts time so the same code runs in live (real time) and
    backtest (deterministic time) modes.
    """

    def now(self) -> datetime:
        """Return current time as timezone-aware UTC datetime."""
        ...

    def now_msc(self) -> int:
        """Return current time as milliseconds since epoch."""
        ...


class WallClock:
    """Real wall clock for live trading.

    Delegates to datetime.now(UTC) for actual system time.
    """

    def now(self) -> datetime:
        """Return current UTC wall time."""
        return datetime.now(UTC)

    def now_msc(self) -> int:
        """Return current UTC wall time in milliseconds since epoch."""
        return int(datetime.now(UTC).timestamp() * 1000)


class BacktestClock:
    """Deterministic clock for backtesting.

    Time starts at 0 and only advances when explicitly told via advance().
    This ensures reproducible backtest execution regardless of real wall time.
    """

    def __init__(self) -> None:
        self._current_time_msc: int = 0

    def advance(self, time_msc: int) -> None:
        """Set the clock to a specific millisecond timestamp.

        Args:
            time_msc: Milliseconds since epoch to set as current time.
        """
        self._current_time_msc = time_msc

    def now(self) -> datetime:
        """Return current backtest time as timezone-aware UTC datetime."""
        return datetime.fromtimestamp(self._current_time_msc / 1000, tz=UTC)

    def now_msc(self) -> int:
        """Return current backtest time in milliseconds since epoch."""
        return self._current_time_msc
