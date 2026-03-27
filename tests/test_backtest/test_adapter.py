"""Tests for LiveDataFeedAdapter wrapping existing buffer infrastructure.

TDD RED phase: Tests define the expected adapter behavior that bridges
existing TickBuffer + BarBufferSet to the DataFeedProtocol interface.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from fxsoqqabot.backtest.adapter import LiveDataFeedAdapter
from fxsoqqabot.config.models import DataConfig
from fxsoqqabot.core.events import BarEvent, TickEvent
from fxsoqqabot.data.buffers import BarBufferSet, TickBuffer
from fxsoqqabot.data.protocol import DataFeedProtocol


@pytest.fixture
def tick_buffer() -> TickBuffer:
    """Create a TickBuffer populated with 5 synthetic ticks."""
    buf = TickBuffer(maxlen=100)
    now_msc = int(datetime.now(UTC).timestamp() * 1000)
    for i in range(5):
        buf.append(
            TickEvent(
                symbol="XAUUSD",
                time_msc=now_msc + i * 100,
                bid=2000.0 + i * 0.1,
                ask=2000.5 + i * 0.1,
                last=2000.25 + i * 0.1,
                volume=1,
                flags=0,
                volume_real=0.01,
                spread=0.5,
            )
        )
    return buf


@pytest.fixture
def bar_buffer_set() -> BarBufferSet:
    """Create a BarBufferSet with M1 buffer populated with 3 bars."""
    config = DataConfig()
    bbs = BarBufferSet(config)
    for i in range(3):
        bbs.update(
            "M1",
            [
                BarEvent(
                    symbol="XAUUSD",
                    timeframe="M1",
                    time=1700000000 + i * 60,
                    open=2000.0 + i,
                    high=2001.0 + i,
                    low=1999.0 + i,
                    close=2000.5 + i,
                    tick_volume=100 + i,
                    spread=5,
                    real_volume=0,
                )
            ],
        )
    return bbs


class TestLiveDataFeedAdapterProtocol:
    """Test 1: LiveDataFeedAdapter satisfies DataFeedProtocol."""

    def test_isinstance_check(
        self, tick_buffer: TickBuffer, bar_buffer_set: BarBufferSet
    ) -> None:
        """LiveDataFeedAdapter must be an instance of DataFeedProtocol."""
        adapter = LiveDataFeedAdapter(
            tick_buffer=tick_buffer,
            bar_buffers=bar_buffer_set,
            symbol="XAUUSD",
        )
        assert isinstance(adapter, DataFeedProtocol)


class TestGetTickArrays:
    """Test 2: get_tick_arrays returns correct dict from TickBuffer."""

    @pytest.mark.asyncio
    async def test_returns_correct_keys(
        self, tick_buffer: TickBuffer, bar_buffer_set: BarBufferSet
    ) -> None:
        """get_tick_arrays should return dict with all expected keys."""
        adapter = LiveDataFeedAdapter(
            tick_buffer=tick_buffer, bar_buffers=bar_buffer_set
        )
        result = await adapter.get_tick_arrays("XAUUSD")
        expected_keys = {"time_msc", "bid", "ask", "last", "spread", "volume_real"}
        assert set(result.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_returns_correct_lengths(
        self, tick_buffer: TickBuffer, bar_buffer_set: BarBufferSet
    ) -> None:
        """Arrays should have length matching number of ticks in buffer."""
        adapter = LiveDataFeedAdapter(
            tick_buffer=tick_buffer, bar_buffers=bar_buffer_set
        )
        result = await adapter.get_tick_arrays("XAUUSD")
        for key, arr in result.items():
            assert len(arr) == 5, f"Expected 5 for {key}, got {len(arr)}"

    @pytest.mark.asyncio
    async def test_returns_numpy_arrays(
        self, tick_buffer: TickBuffer, bar_buffer_set: BarBufferSet
    ) -> None:
        """All values should be numpy ndarrays."""
        adapter = LiveDataFeedAdapter(
            tick_buffer=tick_buffer, bar_buffers=bar_buffer_set
        )
        result = await adapter.get_tick_arrays("XAUUSD")
        for key, arr in result.items():
            assert isinstance(arr, np.ndarray), f"{key} should be ndarray"


class TestGetBarArrays:
    """Test 3: get_bar_arrays returns nested dict from BarBufferSet."""

    @pytest.mark.asyncio
    async def test_returns_timeframe_keys(
        self, tick_buffer: TickBuffer, bar_buffer_set: BarBufferSet
    ) -> None:
        """Outer dict should have timeframe keys matching configured timeframes."""
        adapter = LiveDataFeedAdapter(
            tick_buffer=tick_buffer, bar_buffers=bar_buffer_set
        )
        result = await adapter.get_bar_arrays("XAUUSD")
        assert "M1" in result
        assert "M5" in result

    @pytest.mark.asyncio
    async def test_inner_dict_has_correct_keys(
        self, tick_buffer: TickBuffer, bar_buffer_set: BarBufferSet
    ) -> None:
        """Inner dicts should have bar array keys."""
        adapter = LiveDataFeedAdapter(
            tick_buffer=tick_buffer, bar_buffers=bar_buffer_set
        )
        result = await adapter.get_bar_arrays("XAUUSD")
        expected_keys = {"time", "open", "high", "low", "close", "tick_volume"}
        assert set(result["M1"].keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_m1_has_correct_length(
        self, tick_buffer: TickBuffer, bar_buffer_set: BarBufferSet
    ) -> None:
        """M1 arrays should have length 3 (we added 3 bars)."""
        adapter = LiveDataFeedAdapter(
            tick_buffer=tick_buffer, bar_buffers=bar_buffer_set
        )
        result = await adapter.get_bar_arrays("XAUUSD")
        assert len(result["M1"]["close"]) == 3


class TestGetDom:
    """Test 4: get_dom returns None (current engine behavior)."""

    @pytest.mark.asyncio
    async def test_returns_none(
        self, tick_buffer: TickBuffer, bar_buffer_set: BarBufferSet
    ) -> None:
        """get_dom should return None matching current live engine behavior."""
        adapter = LiveDataFeedAdapter(
            tick_buffer=tick_buffer, bar_buffers=bar_buffer_set
        )
        result = await adapter.get_dom("XAUUSD")
        assert result is None


class TestCheckTickFreshness:
    """Test 5: check_tick_freshness works for recent and stale ticks."""

    def test_fresh_tick_returns_true(
        self, tick_buffer: TickBuffer, bar_buffer_set: BarBufferSet
    ) -> None:
        """Recent ticks (within 10s) should be considered fresh."""
        adapter = LiveDataFeedAdapter(
            tick_buffer=tick_buffer, bar_buffers=bar_buffer_set
        )
        # tick_buffer has ticks with timestamps near now
        assert adapter.check_tick_freshness(max_age_seconds=10.0) is True

    def test_stale_tick_returns_false(
        self, bar_buffer_set: BarBufferSet
    ) -> None:
        """Old ticks (>10s ago) should be considered stale."""
        old_buf = TickBuffer(maxlen=100)
        # Add tick from 1 minute ago
        old_time_msc = int(datetime.now(UTC).timestamp() * 1000) - 60_000
        old_buf.append(
            TickEvent(
                symbol="XAUUSD",
                time_msc=old_time_msc,
                bid=2000.0,
                ask=2000.5,
                last=2000.25,
                volume=1,
                flags=0,
                volume_real=0.01,
                spread=0.5,
            )
        )
        adapter = LiveDataFeedAdapter(
            tick_buffer=old_buf, bar_buffers=bar_buffer_set
        )
        assert adapter.check_tick_freshness(max_age_seconds=10.0) is False

    def test_empty_buffer_returns_false(
        self, bar_buffer_set: BarBufferSet
    ) -> None:
        """Empty tick buffer should be considered stale."""
        empty_buf = TickBuffer(maxlen=100)
        adapter = LiveDataFeedAdapter(
            tick_buffer=empty_buf, bar_buffers=bar_buffer_set
        )
        assert adapter.check_tick_freshness() is False
