"""DuckDB/Parquet storage for tick data and trade events (DATA-05).

Tick data stored in DuckDB tables and periodically flushed to Parquet files
partitioned by year/month for efficient time-range queries. Trade events
logged with is_paper flag for paper/live distinction.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import structlog

from fxsoqqabot.config.models import DataConfig
from fxsoqqabot.core.events import FillEvent, TickEvent


class TickStorage:
    """DuckDB/Parquet storage for tick data and trade events per DATA-05.

    Tick data stored in DuckDB tables and periodically flushed to Parquet files
    partitioned by year/month for efficient time-range queries.
    """

    def __init__(self, config: DataConfig) -> None:
        self._config = config
        self._storage_path = Path(config.storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._logger = structlog.get_logger().bind(component="tick_storage")

        self._db = duckdb.connect(str(self._storage_path / "analytics.duckdb"))
        self._init_tables()

    def _init_tables(self) -> None:
        """Create tables if they don't exist."""
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS tick_data (
                time_msc BIGINT,
                bid DOUBLE,
                ask DOUBLE,
                last_price DOUBLE,
                volume BIGINT,
                flags INTEGER,
                volume_real DOUBLE,
                spread DOUBLE,
                symbol VARCHAR
            )
        """)

        self._db.execute("""
            CREATE TABLE IF NOT EXISTS trade_events (
                event_time TIMESTAMP,
                ticket BIGINT,
                symbol VARCHAR,
                action VARCHAR,
                volume DOUBLE,
                fill_price DOUBLE,
                requested_price DOUBLE,
                slippage DOUBLE,
                sl DOUBLE,
                tp DOUBLE,
                magic INTEGER,
                is_paper BOOLEAN
            )
        """)

    def store_ticks(self, ticks: list[TickEvent]) -> int:
        """Batch insert tick events. Returns count inserted."""
        if not ticks:
            return 0
        records = [
            (
                t.time_msc,
                t.bid,
                t.ask,
                t.last,
                t.volume,
                t.flags,
                t.volume_real,
                t.spread,
                t.symbol,
            )
            for t in ticks
        ]
        self._db.executemany(
            "INSERT INTO tick_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            records,
        )
        return len(records)

    def store_trade_event(self, fill: FillEvent) -> None:
        """Insert a single trade event."""
        self._db.execute(
            "INSERT INTO trade_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                fill.timestamp.isoformat(),
                fill.ticket,
                fill.symbol,
                fill.action,
                fill.volume,
                fill.fill_price,
                fill.requested_price,
                fill.slippage,
                fill.sl,
                fill.tp,
                fill.magic,
                fill.is_paper,
            ],
        )

    def query_ticks(
        self, start_msc: int, end_msc: int, symbol: str = "XAUUSD"
    ) -> pd.DataFrame:
        """Query ticks in time range. Returns pandas DataFrame."""
        return self._db.execute(
            "SELECT * FROM tick_data WHERE time_msc >= ? AND time_msc <= ? "
            "AND symbol = ? ORDER BY time_msc",
            [start_msc, end_msc, symbol],
        ).fetchdf()

    def get_trade_history(self, limit: int = 100) -> pd.DataFrame:
        """Get recent trade events."""
        return self._db.execute(
            "SELECT * FROM trade_events ORDER BY event_time DESC LIMIT ?",
            [limit],
        ).fetchdf()

    def flush_to_parquet(self) -> None:
        """Export tick_data to partitioned Parquet files.

        Partitions by year/month as configured.
        """
        parquet_path = self._storage_path / "ticks"
        parquet_path.mkdir(parents=True, exist_ok=True)
        count = self._db.execute("SELECT COUNT(*) FROM tick_data").fetchone()[0]
        if count == 0:
            self._logger.info("no_ticks_to_flush")
            return
        # Add partition columns from time_msc and export
        self._db.execute(f"""
            COPY (
                SELECT *,
                    EXTRACT(YEAR FROM epoch_ms(time_msc)) AS year,
                    EXTRACT(MONTH FROM epoch_ms(time_msc)) AS month
                FROM tick_data
            )
            TO '{parquet_path.as_posix()}/'
            (FORMAT PARQUET, PARTITION_BY (year, month), OVERWRITE_OR_IGNORE true)
        """)
        self._logger.info(
            "ticks_flushed_to_parquet", count=count, path=str(parquet_path)
        )

    def get_tick_count(self) -> int:
        """Return total number of stored ticks."""
        return self._db.execute("SELECT COUNT(*) FROM tick_data").fetchone()[0]

    def close(self) -> None:
        """Close DuckDB connection."""
        self._db.close()
