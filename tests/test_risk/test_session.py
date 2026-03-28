"""Tests for the session time filter per RISK-06.

Tests verify:
- Trading allowed within configured windows (default London-NY 13:00-17:00 UTC)
- Trading blocked outside windows
- Start is inclusive, end is exclusive
- Multiple windows supported
- Session date respects reset_hour per D-10
- Week start date returns Monday
- Time until next window calculation
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fxsoqqabot.config.models import SessionConfig
from fxsoqqabot.risk.session import SessionFilter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_config() -> SessionConfig:
    """Default SessionConfig with London-NY overlap window."""
    return SessionConfig()


@pytest.fixture
def session_filter(session_config: SessionConfig) -> SessionFilter:
    """SessionFilter with default config."""
    return SessionFilter(session_config)


@pytest.fixture
def multi_window_config() -> SessionConfig:
    """SessionConfig with two trading windows.

    Note: defaults now match this config (08:00-12:00 + 13:00-17:00).
    These tests are kept for explicit multi-window coverage.
    """
    return SessionConfig(
        windows=[
            {"start": "08:00", "end": "12:00"},
            {"start": "13:00", "end": "17:00"},
        ]
    )


@pytest.fixture
def multi_window_filter(multi_window_config: SessionConfig) -> SessionFilter:
    """SessionFilter with two windows."""
    return SessionFilter(multi_window_config)


# ---------------------------------------------------------------------------
# Test: Trading allowed within windows
# ---------------------------------------------------------------------------


class TestTradingAllowed:
    """Tests for is_trading_allowed method."""

    def test_allowed_at_14_00_utc(self, session_filter: SessionFilter) -> None:
        """14:00 UTC is within default window (13:00-17:00)."""
        now = datetime(2026, 3, 27, 14, 0, 0, tzinfo=timezone.utc)
        assert session_filter.is_trading_allowed(now) is True

    def test_allowed_at_08_00_utc(self, session_filter: SessionFilter) -> None:
        """08:00 UTC is the start of the London window (inclusive)."""
        now = datetime(2026, 3, 27, 8, 0, 0, tzinfo=timezone.utc)
        assert session_filter.is_trading_allowed(now) is True

    def test_blocked_at_18_00_utc(self, session_filter: SessionFilter) -> None:
        """18:00 UTC is after the window."""
        now = datetime(2026, 3, 27, 18, 0, 0, tzinfo=timezone.utc)
        assert session_filter.is_trading_allowed(now) is False

    def test_allowed_at_13_00_exactly(self, session_filter: SessionFilter) -> None:
        """13:00 UTC exactly is allowed (start is inclusive)."""
        now = datetime(2026, 3, 27, 13, 0, 0, tzinfo=timezone.utc)
        assert session_filter.is_trading_allowed(now) is True

    def test_blocked_at_17_00_exactly(self, session_filter: SessionFilter) -> None:
        """17:00 UTC exactly is blocked (end is exclusive)."""
        now = datetime(2026, 3, 27, 17, 0, 0, tzinfo=timezone.utc)
        assert session_filter.is_trading_allowed(now) is False

    def test_allowed_at_16_59(self, session_filter: SessionFilter) -> None:
        """16:59 UTC is the last allowed minute."""
        now = datetime(2026, 3, 27, 16, 59, 0, tzinfo=timezone.utc)
        assert session_filter.is_trading_allowed(now) is True

    def test_blocked_at_12_59(self, session_filter: SessionFilter) -> None:
        """12:59 UTC is between London and London-NY windows (lunch gap)."""
        now = datetime(2026, 3, 27, 12, 59, 0, tzinfo=timezone.utc)
        assert session_filter.is_trading_allowed(now) is False

    def test_london_lunch_gap_blocked(self, session_filter: SessionFilter) -> None:
        """12:00-13:00 UTC gap is blocked per D-15 (London lunch, low liquidity)."""
        lunch_time = datetime(2026, 3, 28, 12, 30, tzinfo=timezone.utc)
        assert session_filter.is_trading_allowed(lunch_time) is False

    def test_allowed_at_10_00_london_session(self, session_filter: SessionFilter) -> None:
        """10:00 UTC is within the London session window (08:00-12:00)."""
        now = datetime(2026, 3, 27, 10, 0, 0, tzinfo=timezone.utc)
        assert session_filter.is_trading_allowed(now) is True


# ---------------------------------------------------------------------------
# Test: Multiple windows
# ---------------------------------------------------------------------------


class TestMultipleWindows:
    """Tests for multiple trading windows support."""

    def test_allowed_in_first_window(
        self, multi_window_filter: SessionFilter
    ) -> None:
        """09:00 UTC is within first window (08:00-12:00)."""
        now = datetime(2026, 3, 27, 9, 0, 0, tzinfo=timezone.utc)
        assert multi_window_filter.is_trading_allowed(now) is True

    def test_allowed_in_second_window(
        self, multi_window_filter: SessionFilter
    ) -> None:
        """15:00 UTC is within second window (13:00-17:00)."""
        now = datetime(2026, 3, 27, 15, 0, 0, tzinfo=timezone.utc)
        assert multi_window_filter.is_trading_allowed(now) is True

    def test_blocked_between_windows(
        self, multi_window_filter: SessionFilter
    ) -> None:
        """12:30 UTC is between the two windows."""
        now = datetime(2026, 3, 27, 12, 30, 0, tzinfo=timezone.utc)
        assert multi_window_filter.is_trading_allowed(now) is False

    def test_blocked_before_all_windows(
        self, multi_window_filter: SessionFilter
    ) -> None:
        """06:00 UTC is before all windows."""
        now = datetime(2026, 3, 27, 6, 0, 0, tzinfo=timezone.utc)
        assert multi_window_filter.is_trading_allowed(now) is False

    def test_blocked_after_all_windows(
        self, multi_window_filter: SessionFilter
    ) -> None:
        """20:00 UTC is after all windows."""
        now = datetime(2026, 3, 27, 20, 0, 0, tzinfo=timezone.utc)
        assert multi_window_filter.is_trading_allowed(now) is False


# ---------------------------------------------------------------------------
# Test: Session date with reset_hour per D-10
# ---------------------------------------------------------------------------


class TestSessionDate:
    """Tests for get_session_date respecting reset_hour."""

    def test_session_date_same_day(self, session_filter: SessionFilter) -> None:
        """At 14:00 UTC with reset_hour=0, session date is today."""
        now = datetime(2026, 3, 27, 14, 0, 0, tzinfo=timezone.utc)
        assert session_filter.get_session_date(now) == "2026-03-27"

    def test_session_date_before_reset(self) -> None:
        """At 23:00 UTC with reset_hour=5, session date is today
        (hour >= reset_hour)."""
        config = SessionConfig(reset_hour=5)
        sf = SessionFilter(config)
        now = datetime(2026, 3, 27, 23, 0, 0, tzinfo=timezone.utc)
        assert sf.get_session_date(now) == "2026-03-27"

    def test_session_date_rolls_back(self) -> None:
        """At 03:00 UTC with reset_hour=5, session belongs to previous day
        (hour < reset_hour)."""
        config = SessionConfig(reset_hour=5)
        sf = SessionFilter(config)
        now = datetime(2026, 3, 27, 3, 0, 0, tzinfo=timezone.utc)
        assert sf.get_session_date(now) == "2026-03-26"

    def test_session_date_at_reset_hour(self) -> None:
        """At reset_hour exactly, session is today (hour >= reset_hour)."""
        config = SessionConfig(reset_hour=5)
        sf = SessionFilter(config)
        now = datetime(2026, 3, 27, 5, 0, 0, tzinfo=timezone.utc)
        assert sf.get_session_date(now) == "2026-03-27"


# ---------------------------------------------------------------------------
# Test: Week start date
# ---------------------------------------------------------------------------


class TestWeekStartDate:
    """Tests for get_week_start_date returning Monday."""

    def test_week_start_on_wednesday(self, session_filter: SessionFilter) -> None:
        """Wednesday 2026-03-25 -> Monday 2026-03-23."""
        # March 25 2026 is a Wednesday (weekday=2)
        now = datetime(2026, 3, 25, 14, 0, 0, tzinfo=timezone.utc)
        assert session_filter.get_week_start_date(now) == "2026-03-23"

    def test_week_start_on_monday(self, session_filter: SessionFilter) -> None:
        """Monday itself -> same Monday."""
        # March 23 2026 is a Monday (weekday=0)
        now = datetime(2026, 3, 23, 10, 0, 0, tzinfo=timezone.utc)
        assert session_filter.get_week_start_date(now) == "2026-03-23"

    def test_week_start_on_friday(self, session_filter: SessionFilter) -> None:
        """Friday 2026-03-27 -> Monday 2026-03-23."""
        now = datetime(2026, 3, 27, 14, 0, 0, tzinfo=timezone.utc)
        assert session_filter.get_week_start_date(now) == "2026-03-23"


# ---------------------------------------------------------------------------
# Test: Time until next window
# ---------------------------------------------------------------------------


class TestTimeUntilNextWindow:
    """Tests for time_until_next_window calculation."""

    def test_returns_zero_when_in_window(
        self, session_filter: SessionFilter
    ) -> None:
        """Currently in a window -> returns 0.0."""
        now = datetime(2026, 3, 27, 14, 0, 0, tzinfo=timezone.utc)
        assert session_filter.time_until_next_window(now) == 0.0

    def test_returns_seconds_until_window_today(
        self, session_filter: SessionFilter
    ) -> None:
        """Before window today -> returns seconds until window opens."""
        now = datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc)
        # 12:00 -> 13:00 = 3600 seconds
        assert session_filter.time_until_next_window(now) == 3600.0

    def test_returns_seconds_until_window_tomorrow(
        self, session_filter: SessionFilter
    ) -> None:
        """After all windows today -> returns seconds until tomorrow's window."""
        now = datetime(2026, 3, 27, 18, 0, 0, tzinfo=timezone.utc)
        # 18:00 -> next day 08:00 = 14 * 3600 = 50400 seconds
        assert session_filter.time_until_next_window(now) == 50400.0

    def test_picks_nearest_window(
        self, multi_window_filter: SessionFilter
    ) -> None:
        """Between windows, picks the nearest upcoming one."""
        now = datetime(2026, 3, 27, 12, 30, 0, tzinfo=timezone.utc)
        # 12:30 -> 13:00 = 30 minutes = 1800 seconds
        assert multi_window_filter.time_until_next_window(now) == 1800.0
