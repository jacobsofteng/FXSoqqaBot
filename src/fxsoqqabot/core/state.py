"""SQLite state persistence for crash recovery per D-07.

Uses WAL mode for crash safety per Pitfall 6.
Stores: circuit breaker state, open positions, trade journal, account snapshots.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import aiosqlite
import structlog
from pydantic import BaseModel


class BreakerState(str, Enum):
    """Circuit breaker operational state."""

    ACTIVE = "active"
    TRIPPED = "tripped"
    KILLED = "killed"


class CircuitBreakerSnapshot(BaseModel):
    """Full circuit breaker state persisted to SQLite per D-07."""

    daily_pnl: float = 0.0
    daily_starting_equity: float = 0.0
    weekly_pnl: float = 0.0
    equity_high_water_mark: float = 0.0
    consecutive_losses: int = 0
    daily_trade_count: int = 0
    last_equity: float = 0.0
    last_equity_time: str = ""
    session_date: str = ""
    week_start_date: str = ""
    kill_switch: BreakerState = BreakerState.ACTIVE
    daily_drawdown: BreakerState = BreakerState.ACTIVE
    loss_streak: BreakerState = BreakerState.ACTIVE
    rapid_equity_drop: BreakerState = BreakerState.ACTIVE
    max_trades: BreakerState = BreakerState.ACTIVE
    spread_spike: BreakerState = BreakerState.ACTIVE


class PositionRecord(BaseModel):
    """Position record stored in SQLite for crash recovery per D-07."""

    ticket: int
    symbol: str
    type: int
    volume: float
    open_price: float
    sl: float = 0.0
    tp: float | None = None
    magic: int = 0
    open_time: str = ""


class TradeJournalEntry(BaseModel):
    """Trade record for journal."""

    ticket: int
    symbol: str
    action: str
    volume: float
    open_price: float
    close_price: float = 0.0
    sl: float = 0.0
    tp: float | None = None
    pnl: float = 0.0
    slippage: float = 0.0
    spread_at_entry: float = 0.0
    open_time: str = ""
    close_time: str = ""
    hold_duration_seconds: float = 0.0
    magic: int = 0
    comment: str = ""


class StateManager:
    """SQLite state persistence for crash recovery per D-07.

    Uses WAL mode for crash safety per Pitfall 6.
    Stores: circuit breaker state, open positions, trade journal, account snapshots.
    """

    def __init__(self, db_path: str | Path = "data/state.db") -> None:
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self._logger = structlog.get_logger().bind(component="state_manager")

    async def initialize(self) -> None:
        """Create database with WAL mode and all tables."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        # WAL mode for crash safety per Pitfall 6
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA busy_timeout=5000")

        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS circuit_breaker_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                daily_pnl REAL DEFAULT 0.0,
                daily_starting_equity REAL DEFAULT 0.0,
                weekly_pnl REAL DEFAULT 0.0,
                equity_high_water_mark REAL DEFAULT 0.0,
                consecutive_losses INTEGER DEFAULT 0,
                daily_trade_count INTEGER DEFAULT 0,
                last_equity REAL DEFAULT 0.0,
                last_equity_time TEXT DEFAULT '',
                session_date TEXT DEFAULT '',
                week_start_date TEXT DEFAULT '',
                kill_switch TEXT DEFAULT 'active',
                daily_drawdown TEXT DEFAULT 'active',
                loss_streak TEXT DEFAULT 'active',
                rapid_equity_drop TEXT DEFAULT 'active',
                max_trades TEXT DEFAULT 'active',
                spread_spike TEXT DEFAULT 'active',
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS positions (
                ticket INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                type INTEGER NOT NULL,
                volume REAL NOT NULL,
                open_price REAL NOT NULL,
                sl REAL DEFAULT 0.0,
                tp REAL,
                magic INTEGER DEFAULT 0,
                open_time TEXT DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS trade_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket INTEGER,
                symbol TEXT,
                action TEXT,
                volume REAL,
                open_price REAL,
                close_price REAL DEFAULT 0.0,
                sl REAL DEFAULT 0.0,
                tp REAL,
                pnl REAL DEFAULT 0.0,
                slippage REAL DEFAULT 0.0,
                spread_at_entry REAL DEFAULT 0.0,
                open_time TEXT DEFAULT '',
                close_time TEXT DEFAULT '',
                hold_duration_seconds REAL DEFAULT 0.0,
                magic INTEGER DEFAULT 0,
                comment TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS account_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equity REAL,
                balance REAL,
                margin REAL,
                free_margin REAL,
                margin_level REAL,
                timestamp TEXT DEFAULT (datetime('now'))
            );

            INSERT OR IGNORE INTO circuit_breaker_state (id) VALUES (1);
        """)
        await self._db.commit()
        self._logger.info("state_db_initialized", path=str(self._db_path))

    async def save_breaker_state(self, snapshot: CircuitBreakerSnapshot) -> None:
        """Persist circuit breaker state."""
        assert self._db is not None
        await self._db.execute(
            """
            UPDATE circuit_breaker_state SET
                daily_pnl=?, daily_starting_equity=?, weekly_pnl=?,
                equity_high_water_mark=?, consecutive_losses=?,
                daily_trade_count=?, last_equity=?, last_equity_time=?,
                session_date=?, week_start_date=?,
                kill_switch=?, daily_drawdown=?, loss_streak=?,
                rapid_equity_drop=?, max_trades=?, spread_spike=?,
                updated_at=datetime('now')
            WHERE id=1
            """,
            [
                snapshot.daily_pnl,
                snapshot.daily_starting_equity,
                snapshot.weekly_pnl,
                snapshot.equity_high_water_mark,
                snapshot.consecutive_losses,
                snapshot.daily_trade_count,
                snapshot.last_equity,
                snapshot.last_equity_time,
                snapshot.session_date,
                snapshot.week_start_date,
                snapshot.kill_switch.value,
                snapshot.daily_drawdown.value,
                snapshot.loss_streak.value,
                snapshot.rapid_equity_drop.value,
                snapshot.max_trades.value,
                snapshot.spread_spike.value,
            ],
        )
        await self._db.commit()

    async def load_breaker_state(self) -> CircuitBreakerSnapshot:
        """Load circuit breaker state from SQLite."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM circuit_breaker_state WHERE id=1"
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return CircuitBreakerSnapshot()
            cols = [d[0] for d in cursor.description]
        data = dict(zip(cols, row))
        # Remove non-model fields
        data.pop("id", None)
        data.pop("updated_at", None)
        return CircuitBreakerSnapshot(**data)

    async def save_position(self, pos: PositionRecord) -> None:
        """Upsert a position record."""
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO positions
            (ticket, symbol, type, volume, open_price, sl, tp, magic, open_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                pos.ticket,
                pos.symbol,
                pos.type,
                pos.volume,
                pos.open_price,
                pos.sl,
                pos.tp,
                pos.magic,
                pos.open_time,
            ],
        )
        await self._db.commit()

    async def remove_position(self, ticket: int) -> None:
        """Delete a position record."""
        assert self._db is not None
        await self._db.execute(
            "DELETE FROM positions WHERE ticket=?", [ticket]
        )
        await self._db.commit()

    async def get_positions(self) -> list[PositionRecord]:
        """Return all tracked positions."""
        assert self._db is not None
        async with self._db.execute("SELECT * FROM positions") as cursor:
            rows = await cursor.fetchall()
            cols = [d[0] for d in cursor.description]
        result = []
        for row in rows:
            data = dict(zip(cols, row))
            data.pop("updated_at", None)
            result.append(PositionRecord(**data))
        return result

    async def save_trade(self, entry: TradeJournalEntry) -> None:
        """Insert a trade journal entry."""
        assert self._db is not None
        await self._db.execute(
            """
            INSERT INTO trade_journal
            (ticket, symbol, action, volume, open_price, close_price, sl, tp,
             pnl, slippage, spread_at_entry, open_time, close_time,
             hold_duration_seconds, magic, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                entry.ticket,
                entry.symbol,
                entry.action,
                entry.volume,
                entry.open_price,
                entry.close_price,
                entry.sl,
                entry.tp,
                entry.pnl,
                entry.slippage,
                entry.spread_at_entry,
                entry.open_time,
                entry.close_time,
                entry.hold_duration_seconds,
                entry.magic,
                entry.comment,
            ],
        )
        await self._db.commit()

    async def save_account_snapshot(
        self,
        equity: float,
        balance: float,
        margin: float,
        free_margin: float,
        margin_level: float,
    ) -> None:
        """Insert an account snapshot."""
        assert self._db is not None
        await self._db.execute(
            """
            INSERT INTO account_snapshots
            (equity, balance, margin, free_margin, margin_level)
            VALUES (?, ?, ?, ?, ?)
            """,
            [equity, balance, margin, free_margin, margin_level],
        )
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
