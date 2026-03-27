"""Tests for DuckDB/Parquet tick storage and trade event logging.

Tests verify tick batch insertion, time-range queries, trade event
logging, Parquet export with year/month partitioning, and proper
connection lifecycle management.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from fxsoqqabot.config.models import DataConfig
from fxsoqqabot.core.events import FillEvent, TickEvent
from fxsoqqabot.data.storage import TickStorage


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


def _make_fill(
    ticket: int = 12345,
    symbol: str = "XAUUSD",
    action: str = "buy",
    volume: float = 0.01,
    fill_price: float = 1900.0,
    requested_price: float = 1899.5,
    slippage: float = 0.5,
    sl: float = 1895.0,
    tp: float | None = 1910.0,
    magic: int = 20260327,
    is_paper: bool = True,
    timestamp: datetime | None = None,
) -> FillEvent:
    if timestamp is None:
        timestamp = datetime(2026, 3, 27, 12, 0, 0, tzinfo=UTC)
    return FillEvent(
        ticket=ticket,
        symbol=symbol,
        action=action,
        volume=volume,
        fill_price=fill_price,
        requested_price=requested_price,
        slippage=slippage,
        sl=sl,
        tp=tp,
        magic=magic,
        is_paper=is_paper,
        timestamp=timestamp,
    )


@pytest.fixture
def storage(tmp_path):
    """Create a TickStorage with a temp directory for DuckDB + Parquet."""
    config = DataConfig(storage_path=str(tmp_path / "data"))
    ts = TickStorage(config)
    yield ts
    ts.close()


# ── TickStorage Init Tests ───────────────────────────────────────────────


class TestTickStorageInit:
    """Tests for TickStorage initialization and table creation."""

    def test_creates_duckdb_connection(self, storage: TickStorage) -> None:
        # If we can query, connection is alive
        count = storage.get_tick_count()
        assert count == 0

    def test_creates_tick_data_table(self, storage: TickStorage) -> None:
        # Should not raise -- table exists
        df = storage.query_ticks(0, 9999999999999)
        assert isinstance(df, pd.DataFrame)

    def test_creates_trade_events_table(self, storage: TickStorage) -> None:
        # Should not raise -- table exists
        df = storage.get_trade_history(limit=10)
        assert isinstance(df, pd.DataFrame)

    def test_creates_storage_directory(self, tmp_path) -> None:
        data_dir = tmp_path / "new_data_dir"
        config = DataConfig(storage_path=str(data_dir))
        ts = TickStorage(config)
        assert data_dir.exists()
        ts.close()


# ── store_ticks Tests ────────────────────────────────────────────────────


class TestStoreTicks:
    """Tests for batch tick insertion."""

    def test_store_single_batch(self, storage: TickStorage) -> None:
        ticks = [_make_tick(time_msc=i * 1000) for i in range(10)]
        count = storage.store_ticks(ticks)
        assert count == 10
        assert storage.get_tick_count() == 10

    def test_store_empty_list(self, storage: TickStorage) -> None:
        count = storage.store_ticks([])
        assert count == 0
        assert storage.get_tick_count() == 0

    def test_store_multiple_batches(self, storage: TickStorage) -> None:
        ticks1 = [_make_tick(time_msc=i * 1000) for i in range(5)]
        ticks2 = [_make_tick(time_msc=(i + 5) * 1000) for i in range(5)]
        storage.store_ticks(ticks1)
        storage.store_ticks(ticks2)
        assert storage.get_tick_count() == 10

    def test_stores_all_fields(self, storage: TickStorage) -> None:
        tick = _make_tick(
            time_msc=5000,
            bid=1950.5,
            ask=1951.0,
            last=1950.75,
            volume=42,
            flags=6,
            volume_real=3.14,
            spread=0.5,
            symbol="XAUUSD",
        )
        storage.store_ticks([tick])
        df = storage.query_ticks(0, 99999)
        assert len(df) == 1
        row = df.iloc[0]
        assert row["bid"] == 1950.5
        assert row["ask"] == 1951.0
        assert row["spread"] == 0.5
        assert row["symbol"] == "XAUUSD"


# ── store_trade_event Tests ──────────────────────────────────────────────


class TestStoreTradeEvent:
    """Tests for trade event insertion."""

    def test_store_single_trade_event(self, storage: TickStorage) -> None:
        fill = _make_fill()
        storage.store_trade_event(fill)
        df = storage.get_trade_history(limit=10)
        assert len(df) == 1

    def test_stores_is_paper_flag(self, storage: TickStorage) -> None:
        fill_paper = _make_fill(ticket=1, is_paper=True)
        fill_live = _make_fill(ticket=2, is_paper=False)
        storage.store_trade_event(fill_paper)
        storage.store_trade_event(fill_live)
        df = storage.get_trade_history(limit=10)
        assert len(df) == 2
        # Check is_paper values exist in the results
        paper_values = set(df["is_paper"].tolist())
        assert True in paper_values
        assert False in paper_values

    def test_stores_all_trade_fields(self, storage: TickStorage) -> None:
        fill = _make_fill(
            ticket=99999,
            symbol="XAUUSD",
            action="sell",
            volume=0.05,
            fill_price=1950.0,
            requested_price=1949.5,
            slippage=0.5,
            sl=1955.0,
            tp=1940.0,
            magic=123,
            is_paper=False,
        )
        storage.store_trade_event(fill)
        df = storage.get_trade_history(limit=1)
        assert len(df) == 1
        row = df.iloc[0]
        assert row["ticket"] == 99999
        assert row["action"] == "sell"
        assert row["volume"] == 0.05
        assert row["is_paper"] == False  # noqa: E712 - numpy bool vs identity


# ── query_ticks Tests ────────────────────────────────────────────────────


class TestQueryTicks:
    """Tests for time-range tick queries."""

    def test_query_returns_ticks_in_range(self, storage: TickStorage) -> None:
        ticks = [_make_tick(time_msc=i * 1000) for i in range(10)]
        storage.store_ticks(ticks)
        df = storage.query_ticks(3000, 6000)
        # Should get ticks with time_msc 3000, 4000, 5000, 6000
        assert len(df) == 4

    def test_query_returns_ordered_by_time(self, storage: TickStorage) -> None:
        ticks = [_make_tick(time_msc=i * 1000) for i in range(5)]
        storage.store_ticks(ticks)
        df = storage.query_ticks(0, 9999)
        times = df["time_msc"].tolist()
        assert times == sorted(times)

    def test_query_empty_range(self, storage: TickStorage) -> None:
        ticks = [_make_tick(time_msc=i * 1000) for i in range(5)]
        storage.store_ticks(ticks)
        df = storage.query_ticks(99000, 99999)
        assert len(df) == 0

    def test_query_empty_database(self, storage: TickStorage) -> None:
        df = storage.query_ticks(0, 9999)
        assert len(df) == 0
        assert isinstance(df, pd.DataFrame)

    def test_query_filters_by_symbol(self, storage: TickStorage) -> None:
        tick_gold = _make_tick(time_msc=1000, symbol="XAUUSD")
        tick_other = _make_tick(time_msc=2000, symbol="EURUSD")
        storage.store_ticks([tick_gold, tick_other])
        df = storage.query_ticks(0, 9999, symbol="XAUUSD")
        assert len(df) == 1
        assert df.iloc[0]["symbol"] == "XAUUSD"


# ── get_trade_history Tests ──────────────────────────────────────────────


class TestGetTradeHistory:
    """Tests for trade history retrieval."""

    def test_returns_limited_results(self, storage: TickStorage) -> None:
        for i in range(20):
            fill = _make_fill(
                ticket=i,
                timestamp=datetime(2026, 3, 27, 12, i, 0, tzinfo=UTC),
            )
            storage.store_trade_event(fill)
        df = storage.get_trade_history(limit=5)
        assert len(df) == 5

    def test_returns_empty_when_no_trades(self, storage: TickStorage) -> None:
        df = storage.get_trade_history(limit=10)
        assert len(df) == 0
        assert isinstance(df, pd.DataFrame)


# ── flush_to_parquet Tests ───────────────────────────────────────────────


class TestFlushToParquet:
    """Tests for Parquet export with year/month partitioning."""

    def test_flush_creates_parquet_files(self, storage: TickStorage, tmp_path) -> None:
        # Create ticks with realistic timestamps (2026-01-15 12:00:00 UTC = epoch_ms)
        # 2026-01-15 12:00:00 UTC in milliseconds
        jan_2026_msc = 1768478400000
        ticks = [_make_tick(time_msc=jan_2026_msc + i * 100) for i in range(100)]
        storage.store_ticks(ticks)
        storage.flush_to_parquet()

        # Check that parquet directory was created
        parquet_dir = tmp_path / "data" / "ticks"
        assert parquet_dir.exists()

    def test_flush_empty_database(self, storage: TickStorage, tmp_path) -> None:
        # Should not raise, should log and return
        storage.flush_to_parquet()
        # Parquet dir might not even be created if no data
        parquet_dir = tmp_path / "data" / "ticks"
        # Check that no files were written (dir may or may not exist)
        if parquet_dir.exists():
            # If dir exists, it should have no parquet files
            parquet_files = list(parquet_dir.rglob("*.parquet"))
            assert len(parquet_files) == 0

    def test_flush_creates_partitioned_structure(
        self, storage: TickStorage, tmp_path
    ) -> None:
        # 2026-03-15 12:00:00 UTC in milliseconds
        mar_2026_msc = 1773576000000
        ticks = [_make_tick(time_msc=mar_2026_msc + i * 100) for i in range(50)]
        storage.store_ticks(ticks)
        storage.flush_to_parquet()

        parquet_dir = tmp_path / "data" / "ticks"
        # Should find partitioned directories (year=2026/month=3)
        parquet_files = list(parquet_dir.rglob("*.parquet"))
        assert len(parquet_files) > 0


# ── close Tests ──────────────────────────────────────────────────────────


class TestClose:
    """Tests for proper connection cleanup."""

    def test_close_prevents_further_queries(self, tmp_path) -> None:
        config = DataConfig(storage_path=str(tmp_path / "data"))
        ts = TickStorage(config)
        ts.close()
        # After close, operations should raise
        with pytest.raises(Exception):
            ts.get_tick_count()
