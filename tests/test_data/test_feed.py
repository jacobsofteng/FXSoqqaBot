"""Tests for MarketDataFeed -- tick, bar, and DOM retrieval with graceful degradation.

Tests verify:
- Tick data conversion to TickEvent with computed spread
- Bar data conversion to BarEvent for all timeframes
- DOM graceful degradation per DATA-02 (empty DOMSnapshot, not crash)
- DOM warning rate limiting (warn once, not per call)
- Multi-timeframe bar fetching for M1/M5/M15/H1/H4
- Stale tick detection per Pitfall 7
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from fxsoqqabot.config.models import DataConfig
from fxsoqqabot.core.events import BarEvent, DOMEntry, DOMSnapshot, TickEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TICK_DTYPE = np.dtype([
    ("time", "i8"),
    ("bid", "f8"),
    ("ask", "f8"),
    ("last", "f8"),
    ("volume", "i8"),
    ("time_msc", "i8"),
    ("flags", "i4"),
    ("volume_real", "f8"),
])

BAR_DTYPE = np.dtype([
    ("time", "i8"),
    ("open", "f8"),
    ("high", "f8"),
    ("low", "f8"),
    ("close", "f8"),
    ("tick_volume", "i8"),
    ("spread", "i4"),
    ("real_volume", "i8"),
])


@pytest.fixture
def data_config():
    """DataConfig with defaults."""
    return DataConfig()


@pytest.fixture
def mock_bridge():
    """Mock MT5Bridge with AsyncMock methods."""
    bridge = MagicMock()
    bridge.get_ticks = AsyncMock()
    bridge.get_rates = AsyncMock()
    bridge.get_dom = AsyncMock()
    bridge.get_symbol_info = AsyncMock()
    bridge.get_symbol_tick = AsyncMock()
    return bridge


@pytest.fixture
def sample_tick_data():
    """Sample tick data as numpy structured array (mimics MT5 output)."""
    return np.array(
        [
            (1000, 2000.50, 2001.00, 2000.75, 10, 1711540000000, 6, 10.0),
            (1001, 2000.60, 2001.10, 2000.80, 5, 1711540000100, 2, 5.0),
        ],
        dtype=TICK_DTYPE,
    )


@pytest.fixture
def sample_bar_data():
    """Sample bar data as numpy structured array (mimics MT5 output)."""
    return np.array(
        [
            (1711540000, 2000.00, 2005.00, 1998.00, 2003.00, 500, 10, 0),
            (1711540060, 2003.00, 2006.00, 2001.00, 2004.50, 300, 8, 0),
        ],
        dtype=BAR_DTYPE,
    )


# ---------------------------------------------------------------------------
# Test: fetch_ticks()
# ---------------------------------------------------------------------------


class TestFetchTicks:
    """MarketDataFeed.fetch_ticks() tests."""

    async def test_converts_to_tick_events(self, mock_bridge, data_config, sample_tick_data):
        """fetch_ticks() converts raw MT5 numpy rows to TickEvent list with computed spread."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_bridge.get_ticks.return_value = sample_tick_data

        feed = MarketDataFeed(mock_bridge, data_config)
        events = await feed.fetch_ticks("XAUUSD", count=100)

        assert len(events) == 2
        assert all(isinstance(e, TickEvent) for e in events)

        # Check first tick
        assert events[0].symbol == "XAUUSD"
        assert events[0].bid == 2000.50
        assert events[0].ask == 2001.00
        assert events[0].spread == pytest.approx(0.50)  # ask - bid
        assert events[0].time_msc == 1711540000000
        assert events[0].last == 2000.75
        assert events[0].volume == 10
        assert events[0].flags == 6
        assert events[0].volume_real == 10.0

        # Check second tick spread
        assert events[1].spread == pytest.approx(0.50)

    async def test_returns_empty_on_none(self, mock_bridge, data_config):
        """fetch_ticks() returns empty list when MT5 returns None (silent failure)."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_bridge.get_ticks.return_value = None

        feed = MarketDataFeed(mock_bridge, data_config)
        events = await feed.fetch_ticks("XAUUSD")

        assert events == []

    async def test_returns_empty_on_empty_array(self, mock_bridge, data_config):
        """fetch_ticks() returns empty list when MT5 returns empty array."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_bridge.get_ticks.return_value = np.array([], dtype=TICK_DTYPE)

        feed = MarketDataFeed(mock_bridge, data_config)
        events = await feed.fetch_ticks("XAUUSD")

        assert events == []

    async def test_updates_last_tick_time(self, mock_bridge, data_config, sample_tick_data):
        """fetch_ticks() updates _last_tick_time_msc for freshness checks."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_bridge.get_ticks.return_value = sample_tick_data

        feed = MarketDataFeed(mock_bridge, data_config)
        await feed.fetch_ticks("XAUUSD")

        assert feed._last_tick_time_msc == 1711540000100  # Last tick's time_msc


# ---------------------------------------------------------------------------
# Test: fetch_bars()
# ---------------------------------------------------------------------------


class TestFetchBars:
    """MarketDataFeed.fetch_bars() tests."""

    async def test_converts_to_bar_events(self, mock_bridge, data_config, sample_bar_data):
        """fetch_bars() converts raw MT5 numpy array to BarEvent list."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_bridge.get_rates.return_value = sample_bar_data

        feed = MarketDataFeed(mock_bridge, data_config)
        events = await feed.fetch_bars("XAUUSD", "M1", count=100)

        assert len(events) == 2
        assert all(isinstance(e, BarEvent) for e in events)

        assert events[0].symbol == "XAUUSD"
        assert events[0].timeframe == "M1"
        assert events[0].open == 2000.00
        assert events[0].high == 2005.00
        assert events[0].low == 1998.00
        assert events[0].close == 2003.00
        assert events[0].tick_volume == 500
        assert events[0].spread == 10
        assert events[0].real_volume == 0

    async def test_returns_empty_on_none(self, mock_bridge, data_config):
        """fetch_bars() returns empty list when MT5 returns None."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_bridge.get_rates.return_value = None

        feed = MarketDataFeed(mock_bridge, data_config)
        events = await feed.fetch_bars("XAUUSD", "M5")

        assert events == []

    async def test_returns_empty_on_unknown_timeframe(self, mock_bridge, data_config):
        """fetch_bars() returns empty list for unknown timeframe string."""
        from fxsoqqabot.data.feed import MarketDataFeed

        feed = MarketDataFeed(mock_bridge, data_config)
        events = await feed.fetch_bars("XAUUSD", "W1")

        assert events == []
        mock_bridge.get_rates.assert_not_called()

    async def test_uses_default_count_from_config(self, mock_bridge, data_config, sample_bar_data):
        """fetch_bars() defaults count to bar_buffer_sizes[timeframe] from config."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_bridge.get_rates.return_value = sample_bar_data

        feed = MarketDataFeed(mock_bridge, data_config)
        await feed.fetch_bars("XAUUSD", "M1")

        # M1 default count is 1440 from DataConfig
        call_args = mock_bridge.get_rates.call_args
        assert call_args[0][3] == 1440  # count positional arg


# ---------------------------------------------------------------------------
# Test: fetch_dom() -- graceful degradation per DATA-02
# ---------------------------------------------------------------------------


class TestFetchDom:
    """MarketDataFeed.fetch_dom() tests -- graceful degradation."""

    async def test_converts_to_dom_snapshot(self, mock_bridge, data_config):
        """fetch_dom() converts BookInfo entries to DOMSnapshot with DOMEntry tuples."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_entries = [
            SimpleNamespace(type=1, price=2001.00, volume=50, volume_dbl=50.0),
            SimpleNamespace(type=2, price=2000.50, volume=30, volume_dbl=30.0),
        ]
        mock_bridge.get_dom.return_value = mock_entries

        feed = MarketDataFeed(mock_bridge, data_config)
        snapshot = await feed.fetch_dom("XAUUSD")

        assert isinstance(snapshot, DOMSnapshot)
        assert snapshot.symbol == "XAUUSD"
        assert len(snapshot.entries) == 2
        assert isinstance(snapshot.entries[0], DOMEntry)
        assert snapshot.entries[0].type == 1
        assert snapshot.entries[0].price == 2001.00
        assert snapshot.entries[0].volume == 50
        assert snapshot.entries[0].volume_dbl == 50.0
        assert snapshot.entries[1].type == 2

    async def test_returns_empty_snapshot_on_none(self, mock_bridge, data_config):
        """fetch_dom() returns DOMSnapshot with empty entries when DOM unavailable."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_bridge.get_dom.return_value = None

        feed = MarketDataFeed(mock_bridge, data_config)
        snapshot = await feed.fetch_dom("XAUUSD")

        assert isinstance(snapshot, DOMSnapshot)
        assert snapshot.symbol == "XAUUSD"
        assert snapshot.time_msc == 0
        assert snapshot.entries == ()

    async def test_returns_empty_snapshot_on_empty_list(self, mock_bridge, data_config):
        """fetch_dom() returns DOMSnapshot with empty entries for empty DOM."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_bridge.get_dom.return_value = []

        feed = MarketDataFeed(mock_bridge, data_config)
        snapshot = await feed.fetch_dom("XAUUSD")

        assert snapshot.entries == ()
        assert snapshot.time_msc == 0

    async def test_logs_warning_once_for_empty_dom(self, mock_bridge, data_config):
        """fetch_dom() logs warning on first empty DOM, not repeatedly."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_bridge.get_dom.return_value = None

        feed = MarketDataFeed(mock_bridge, data_config)

        # First call should set _dom_warned
        await feed.fetch_dom("XAUUSD")
        assert feed._dom_warned is True

        # Subsequent calls should not re-warn (we just verify flag is set)
        await feed.fetch_dom("XAUUSD")
        assert feed._dom_warned is True


# ---------------------------------------------------------------------------
# Test: fetch_multi_timeframe_bars()
# ---------------------------------------------------------------------------


class TestFetchMultiTimeframeBars:
    """MarketDataFeed.fetch_multi_timeframe_bars() tests."""

    async def test_fetches_all_five_timeframes(self, mock_bridge, data_config, sample_bar_data):
        """fetch_multi_timeframe_bars() fetches M1, M5, M15, H1, H4."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_bridge.get_rates.return_value = sample_bar_data

        feed = MarketDataFeed(mock_bridge, data_config)
        result = await feed.fetch_multi_timeframe_bars("XAUUSD")

        assert isinstance(result, dict)
        assert set(result.keys()) == {"M1", "M5", "M15", "H1", "H4"}
        for tf, bars in result.items():
            assert all(isinstance(b, BarEvent) for b in bars)
            assert all(b.timeframe == tf for b in bars)

    async def test_returns_empty_lists_on_failure(self, mock_bridge, data_config):
        """fetch_multi_timeframe_bars() returns empty lists when MT5 fails."""
        from fxsoqqabot.data.feed import MarketDataFeed

        mock_bridge.get_rates.return_value = None

        feed = MarketDataFeed(mock_bridge, data_config)
        result = await feed.fetch_multi_timeframe_bars("XAUUSD")

        assert all(len(bars) == 0 for bars in result.values())


# ---------------------------------------------------------------------------
# Test: check_tick_freshness()
# ---------------------------------------------------------------------------


class TestCheckTickFreshness:
    """MarketDataFeed.check_tick_freshness() -- stale data detection per Pitfall 7."""

    async def test_returns_false_when_no_ticks_received(self, mock_bridge, data_config):
        """check_tick_freshness() returns False when no ticks have been received yet."""
        from fxsoqqabot.data.feed import MarketDataFeed

        feed = MarketDataFeed(mock_bridge, data_config)
        assert feed.check_tick_freshness() is False

    async def test_returns_false_when_tick_is_stale(self, mock_bridge, data_config):
        """check_tick_freshness() returns False when latest tick is older than threshold."""
        from fxsoqqabot.data.feed import MarketDataFeed

        feed = MarketDataFeed(mock_bridge, data_config)
        # Set last tick time to 30 seconds ago
        now_msc = int(datetime.now(timezone.utc).timestamp() * 1000)
        feed._last_tick_time_msc = now_msc - 30_000  # 30 seconds old

        assert feed.check_tick_freshness(max_age_seconds=10.0) is False

    async def test_returns_true_when_tick_is_fresh(self, mock_bridge, data_config):
        """check_tick_freshness() returns True when latest tick is within threshold."""
        from fxsoqqabot.data.feed import MarketDataFeed

        feed = MarketDataFeed(mock_bridge, data_config)
        # Set last tick time to 1 second ago
        now_msc = int(datetime.now(timezone.utc).timestamp() * 1000)
        feed._last_tick_time_msc = now_msc - 1_000  # 1 second old

        assert feed.check_tick_freshness(max_age_seconds=10.0) is True
