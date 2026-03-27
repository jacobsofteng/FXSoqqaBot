"""Tests for rolling in-memory buffers (TickBuffer, BarBuffer, BarBufferSet).

Tests verify O(1) append with automatic eviction, numpy array extraction
for signal computation, and multi-timeframe bar buffer management.
"""

from __future__ import annotations

import numpy as np
import pytest

from fxsoqqabot.config.models import DataConfig
from fxsoqqabot.core.events import BarEvent, TickEvent
from fxsoqqabot.data.buffers import BarBuffer, BarBufferSet, TickBuffer


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_tick(
    time_msc: int = 1000,
    bid: float = 1900.0,
    ask: float = 1900.5,
    last: float = 1900.25,
    volume: int = 10,
    flags: int = 0,
    volume_real: float = 1.0,
    spread: float = 0.5,
    symbol: str = "XAUUSD",
) -> TickEvent:
    return TickEvent(
        symbol=symbol,
        time_msc=time_msc,
        bid=bid,
        ask=ask,
        last=last,
        volume=volume,
        flags=flags,
        volume_real=volume_real,
        spread=spread,
    )


def _make_bar(
    timeframe: str = "M1",
    time: int = 1000,
    open_: float = 1900.0,
    high: float = 1905.0,
    low: float = 1898.0,
    close: float = 1903.0,
    tick_volume: int = 500,
    spread: int = 5,
    real_volume: int = 0,
    symbol: str = "XAUUSD",
) -> BarEvent:
    return BarEvent(
        symbol=symbol,
        timeframe=timeframe,
        time=time,
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_volume=tick_volume,
        spread=spread,
        real_volume=real_volume,
    )


# ── TickBuffer Tests ─────────────────────────────────────────────────────


class TestTickBuffer:
    """Tests for TickBuffer rolling buffer."""

    def test_starts_empty(self) -> None:
        buf = TickBuffer(maxlen=100)
        assert len(buf) == 0

    def test_append_single_tick(self) -> None:
        buf = TickBuffer(maxlen=100)
        tick = _make_tick(time_msc=1000)
        buf.append(tick)
        assert len(buf) == 1

    def test_latest_returns_most_recent(self) -> None:
        buf = TickBuffer(maxlen=100)
        t1 = _make_tick(time_msc=1000)
        t2 = _make_tick(time_msc=2000)
        buf.append(t1)
        buf.append(t2)
        assert buf.latest is t2

    def test_latest_returns_none_when_empty(self) -> None:
        buf = TickBuffer(maxlen=100)
        assert buf.latest is None

    def test_overflow_evicts_oldest(self) -> None:
        buf = TickBuffer(maxlen=3)
        ticks = [_make_tick(time_msc=i * 1000) for i in range(5)]
        for t in ticks:
            buf.append(t)
        assert len(buf) == 3
        # Should have ticks 2, 3, 4 (0 and 1 evicted)
        assert buf.latest_n(3)[0].time_msc == 2000
        assert buf.latest_n(3)[2].time_msc == 4000

    def test_latest_n_returns_chronological_order(self) -> None:
        buf = TickBuffer(maxlen=100)
        for i in range(10):
            buf.append(_make_tick(time_msc=i * 1000))
        last_5 = buf.latest_n(5)
        assert len(last_5) == 5
        assert last_5[0].time_msc == 5000
        assert last_5[4].time_msc == 9000

    def test_latest_n_more_than_available(self) -> None:
        buf = TickBuffer(maxlen=100)
        buf.append(_make_tick(time_msc=1000))
        buf.append(_make_tick(time_msc=2000))
        result = buf.latest_n(10)
        assert len(result) == 2

    def test_as_arrays_returns_correct_keys(self) -> None:
        buf = TickBuffer(maxlen=100)
        buf.append(_make_tick(bid=1900.0, ask=1900.5, spread=0.5))
        arrays = buf.as_arrays()
        assert "bid" in arrays
        assert "ask" in arrays
        assert "spread" in arrays
        assert "time_msc" in arrays
        assert "last" in arrays
        assert "volume_real" in arrays

    def test_as_arrays_returns_numpy_arrays(self) -> None:
        buf = TickBuffer(maxlen=100)
        buf.append(_make_tick(bid=1900.0, ask=1900.5))
        arrays = buf.as_arrays()
        for key, arr in arrays.items():
            assert isinstance(arr, np.ndarray), f"{key} is not ndarray"

    def test_as_arrays_correct_values(self) -> None:
        buf = TickBuffer(maxlen=100)
        buf.append(_make_tick(bid=1900.0, ask=1900.5, spread=0.5, time_msc=5000))
        buf.append(_make_tick(bid=1901.0, ask=1901.3, spread=0.3, time_msc=6000))
        arrays = buf.as_arrays()
        np.testing.assert_array_equal(arrays["bid"], [1900.0, 1901.0])
        np.testing.assert_array_equal(arrays["ask"], [1900.5, 1901.3])
        np.testing.assert_array_equal(arrays["spread"], [0.5, 0.3])
        np.testing.assert_array_equal(arrays["time_msc"], [5000, 6000])

    def test_as_arrays_empty_buffer(self) -> None:
        buf = TickBuffer(maxlen=100)
        arrays = buf.as_arrays()
        for key, arr in arrays.items():
            assert len(arr) == 0, f"{key} should be empty"
            assert isinstance(arr, np.ndarray)

    def test_extend_adds_multiple(self) -> None:
        buf = TickBuffer(maxlen=100)
        ticks = [_make_tick(time_msc=i * 1000) for i in range(5)]
        buf.extend(ticks)
        assert len(buf) == 5

    def test_clear(self) -> None:
        buf = TickBuffer(maxlen=100)
        buf.append(_make_tick())
        buf.clear()
        assert len(buf) == 0


# ── BarBuffer Tests ──────────────────────────────────────────────────────


class TestBarBuffer:
    """Tests for BarBuffer single-timeframe rolling buffer."""

    def test_starts_empty(self) -> None:
        buf = BarBuffer("M1", maxlen=1440)
        assert len(buf) == 0

    def test_append_single_bar(self) -> None:
        buf = BarBuffer("M1", maxlen=1440)
        bar = _make_bar(timeframe="M1", time=1000)
        buf.append(bar)
        assert len(buf) == 1

    def test_latest_returns_most_recent(self) -> None:
        buf = BarBuffer("M1", maxlen=1440)
        b1 = _make_bar(time=1000)
        b2 = _make_bar(time=2000)
        buf.append(b1)
        buf.append(b2)
        assert buf.latest is b2

    def test_latest_returns_none_when_empty(self) -> None:
        buf = BarBuffer("M1", maxlen=1440)
        assert buf.latest is None

    def test_overflow_evicts_oldest(self) -> None:
        buf = BarBuffer("M1", maxlen=3)
        bars = [_make_bar(time=i * 60) for i in range(5)]
        for b in bars:
            buf.append(b)
        assert len(buf) == 3
        assert buf.latest_n(3)[0].time == 120  # bars 2, 3, 4 remain

    def test_as_arrays_returns_correct_keys(self) -> None:
        buf = BarBuffer("M1", maxlen=100)
        buf.append(_make_bar())
        arrays = buf.as_arrays()
        assert "time" in arrays
        assert "open" in arrays
        assert "high" in arrays
        assert "low" in arrays
        assert "close" in arrays
        assert "tick_volume" in arrays

    def test_as_arrays_returns_numpy_arrays(self) -> None:
        buf = BarBuffer("M1", maxlen=100)
        buf.append(_make_bar())
        arrays = buf.as_arrays()
        for key, arr in arrays.items():
            assert isinstance(arr, np.ndarray), f"{key} is not ndarray"

    def test_as_arrays_correct_values(self) -> None:
        buf = BarBuffer("M1", maxlen=100)
        buf.append(_make_bar(open_=1900.0, high=1905.0, low=1898.0, close=1903.0))
        arrays = buf.as_arrays()
        np.testing.assert_array_equal(arrays["open"], [1900.0])
        np.testing.assert_array_equal(arrays["high"], [1905.0])
        np.testing.assert_array_equal(arrays["low"], [1898.0])
        np.testing.assert_array_equal(arrays["close"], [1903.0])

    def test_as_arrays_empty_buffer(self) -> None:
        buf = BarBuffer("M1", maxlen=100)
        arrays = buf.as_arrays()
        for key, arr in arrays.items():
            assert len(arr) == 0

    def test_timeframe_stored(self) -> None:
        buf = BarBuffer("H4", maxlen=6)
        assert buf.timeframe == "H4"

    def test_extend_adds_multiple(self) -> None:
        buf = BarBuffer("M1", maxlen=100)
        bars = [_make_bar(time=i * 60) for i in range(5)]
        buf.extend(bars)
        assert len(buf) == 5

    def test_latest_n_chronological(self) -> None:
        buf = BarBuffer("M1", maxlen=100)
        for i in range(10):
            buf.append(_make_bar(time=i * 60))
        last_3 = buf.latest_n(3)
        assert len(last_3) == 3
        assert last_3[0].time == 420
        assert last_3[2].time == 540


# ── BarBufferSet Tests ───────────────────────────────────────────────────


class TestBarBufferSet:
    """Tests for BarBufferSet multi-timeframe buffer manager."""

    def test_creates_buffers_from_config(self) -> None:
        config = DataConfig()
        bset = BarBufferSet(config)
        assert set(bset.timeframes) == {"M1", "M5", "M15", "H1", "H4"}

    def test_getitem_returns_bar_buffer(self) -> None:
        config = DataConfig()
        bset = BarBufferSet(config)
        buf = bset["M1"]
        assert isinstance(buf, BarBuffer)
        assert buf.timeframe == "M1"

    def test_getitem_raises_keyerror_for_unknown_timeframe(self) -> None:
        config = DataConfig()
        bset = BarBufferSet(config)
        with pytest.raises(KeyError):
            _ = bset["D1"]

    def test_update_bulk_appends_bars(self) -> None:
        config = DataConfig()
        bset = BarBufferSet(config)
        bars = [_make_bar(timeframe="M5", time=i * 300) for i in range(5)]
        bset.update("M5", bars)
        assert len(bset["M5"]) == 5

    def test_update_ignores_unknown_timeframe(self) -> None:
        config = DataConfig()
        bset = BarBufferSet(config)
        bars = [_make_bar(timeframe="D1", time=0)]
        # Should not raise
        bset.update("D1", bars)

    def test_buffer_sizes_match_config(self) -> None:
        config = DataConfig()
        bset = BarBufferSet(config)
        # M1 has maxlen 1440
        m1_buf = bset["M1"]
        for i in range(1500):
            m1_buf.append(_make_bar(timeframe="M1", time=i * 60))
        assert len(m1_buf) == 1440  # maxlen enforced
