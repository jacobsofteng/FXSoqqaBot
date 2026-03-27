"""Session time filter per RISK-06.

Only allows trading during configured session windows
(default: London-NY overlap 13:00-17:00 UTC).
Also provides session date/week boundaries for circuit breaker resets per D-10.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import structlog

from fxsoqqabot.config.models import SessionConfig


class SessionFilter:
    """Session time filter per RISK-06.

    Only allows trading during configured session windows
    (default: London-NY overlap 13:00-17:00 UTC).
    Also provides session date/week boundaries for circuit breaker
    resets per D-10.
    """

    def __init__(self, config: SessionConfig) -> None:
        self._config = config
        self._logger = structlog.get_logger().bind(component="session_filter")
        self._windows = self._parse_windows()

    def _parse_windows(self) -> list[tuple[time, time]]:
        """Parse window strings into time tuples."""
        windows: list[tuple[time, time]] = []
        for w in self._config.windows:
            start_parts = w["start"].split(":")
            end_parts = w["end"].split(":")
            start = time(int(start_parts[0]), int(start_parts[1]))
            end = time(int(end_parts[0]), int(end_parts[1]))
            windows.append((start, end))
        return windows

    def is_trading_allowed(self, now: datetime | None = None) -> bool:
        """Check if current time is within any trading window.

        Start is inclusive, end is exclusive.

        Args:
            now: Current time. Defaults to UTC now.

        Returns:
            True if trading is allowed at the given time.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        current_time = now.time()
        for start, end in self._windows:
            if start <= current_time < end:
                return True
        return False

    def get_session_date(self, now: datetime | None = None) -> str:
        """Return session date string (YYYY-MM-DD) respecting reset_hour per D-10.

        If current hour < reset_hour, session belongs to previous day.

        Args:
            now: Current time. Defaults to UTC now.

        Returns:
            Session date as YYYY-MM-DD string.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        if now.hour < self._config.reset_hour:
            session_dt = now - timedelta(days=1)
        else:
            session_dt = now
        return session_dt.strftime("%Y-%m-%d")

    def get_week_start_date(self, now: datetime | None = None) -> str:
        """Return Monday's date for the current trading week.

        Args:
            now: Current time. Defaults to UTC now.

        Returns:
            Monday date as YYYY-MM-DD string.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        monday = now - timedelta(days=now.weekday())
        return monday.strftime("%Y-%m-%d")

    def time_until_next_window(self, now: datetime | None = None) -> float:
        """Return seconds until next trading window opens.

        Returns 0.0 if currently in a window.

        Args:
            now: Current time. Defaults to UTC now.

        Returns:
            Seconds until next window opens, or 0.0 if in a window.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        if self.is_trading_allowed(now):
            return 0.0

        current_time = now.time()
        min_wait = float("inf")

        for start, _end in self._windows:
            if start > current_time:
                # Window is later today
                today_start = now.replace(
                    hour=start.hour,
                    minute=start.minute,
                    second=0,
                    microsecond=0,
                )
                wait = (today_start - now).total_seconds()
            else:
                # Window is tomorrow
                tomorrow_start = (now + timedelta(days=1)).replace(
                    hour=start.hour,
                    minute=start.minute,
                    second=0,
                    microsecond=0,
                )
                wait = (tomorrow_start - now).total_seconds()
            min_wait = min(min_wait, wait)

        return min_wait
