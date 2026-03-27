"""Tests for SQLite state persistence (StateManager) per D-07.

Validates WAL mode, table creation, circuit breaker state persistence,
position tracking, trade journal, and account snapshots.
"""

from __future__ import annotations

import pytest

from fxsoqqabot.core.state import (
    BreakerState,
    CircuitBreakerSnapshot,
    PositionRecord,
    StateManager,
    TradeJournalEntry,
)


@pytest.fixture
async def state_mgr(tmp_path):
    """Create a StateManager with a temporary database."""
    db_path = tmp_path / "test_state.db"
    mgr = StateManager(db_path=db_path)
    await mgr.initialize()
    yield mgr
    await mgr.close()


class TestStateManagerInit:
    """Test database initialization and WAL mode."""

    async def test_initialize_creates_db_with_wal_mode(self, tmp_path):
        """StateManager.initialize() creates SQLite DB with WAL mode enabled."""
        db_path = tmp_path / "wal_test.db"
        mgr = StateManager(db_path=db_path)
        await mgr.initialize()

        # Verify WAL mode is set
        async with mgr._db.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
        assert row[0] == "wal"

        await mgr.close()

    async def test_initialize_creates_all_tables(self, state_mgr):
        """initialize() creates circuit_breaker_state, positions, trade_journal, account_snapshots tables."""
        tables = []
        async with state_mgr._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cursor:
            rows = await cursor.fetchall()
        tables = [r[0] for r in rows]

        assert "circuit_breaker_state" in tables
        assert "positions" in tables
        assert "trade_journal" in tables
        assert "account_snapshots" in tables

    async def test_circuit_breaker_state_singleton(self, state_mgr):
        """circuit_breaker_state table has exactly one row after initialization (singleton pattern)."""
        async with state_mgr._db.execute(
            "SELECT COUNT(*) FROM circuit_breaker_state"
        ) as cursor:
            row = await cursor.fetchone()
        assert row[0] == 1


class TestBreakerStatePersistence:
    """Test save/load roundtrip for circuit breaker state."""

    async def test_save_and_load_breaker_state(self, state_mgr):
        """save_breaker_state(snapshot) persists all fields, load_breaker_state() returns them."""
        snapshot = CircuitBreakerSnapshot(
            daily_pnl=-5.50,
            daily_starting_equity=100.0,
            weekly_pnl=-12.30,
            equity_high_water_mark=120.0,
            consecutive_losses=3,
            daily_trade_count=7,
            last_equity=94.50,
            last_equity_time="2026-03-27T10:00:00Z",
            session_date="2026-03-27",
            week_start_date="2026-03-24",
            kill_switch=BreakerState.ACTIVE,
            daily_drawdown=BreakerState.TRIPPED,
            loss_streak=BreakerState.ACTIVE,
            rapid_equity_drop=BreakerState.ACTIVE,
            max_trades=BreakerState.ACTIVE,
            spread_spike=BreakerState.TRIPPED,
        )
        await state_mgr.save_breaker_state(snapshot)
        loaded = await state_mgr.load_breaker_state()

        assert loaded.daily_pnl == -5.50
        assert loaded.daily_starting_equity == 100.0
        assert loaded.weekly_pnl == -12.30
        assert loaded.equity_high_water_mark == 120.0
        assert loaded.consecutive_losses == 3
        assert loaded.daily_trade_count == 7
        assert loaded.last_equity == 94.50
        assert loaded.last_equity_time == "2026-03-27T10:00:00Z"
        assert loaded.session_date == "2026-03-27"
        assert loaded.week_start_date == "2026-03-24"
        assert loaded.kill_switch == BreakerState.ACTIVE
        assert loaded.daily_drawdown == BreakerState.TRIPPED
        assert loaded.loss_streak == BreakerState.ACTIVE
        assert loaded.rapid_equity_drop == BreakerState.ACTIVE
        assert loaded.max_trades == BreakerState.ACTIVE
        assert loaded.spread_spike == BreakerState.TRIPPED

    async def test_load_default_state(self, state_mgr):
        """load_breaker_state() returns defaults when no explicit save has occurred."""
        loaded = await state_mgr.load_breaker_state()
        assert loaded.daily_pnl == 0.0
        assert loaded.consecutive_losses == 0
        assert loaded.kill_switch == BreakerState.ACTIVE


class TestPositionTracking:
    """Test position CRUD operations."""

    async def test_save_and_get_position(self, state_mgr):
        """save_position(pos) upserts, get_positions() returns all."""
        pos = PositionRecord(
            ticket=12345,
            symbol="XAUUSD",
            type=0,
            volume=0.01,
            open_price=2050.50,
            sl=2048.00,
            tp=2055.00,
            magic=20260327,
            open_time="2026-03-27T10:00:00Z",
        )
        await state_mgr.save_position(pos)
        positions = await state_mgr.get_positions()

        assert len(positions) == 1
        assert positions[0].ticket == 12345
        assert positions[0].symbol == "XAUUSD"
        assert positions[0].volume == 0.01
        assert positions[0].open_price == 2050.50
        assert positions[0].sl == 2048.00
        assert positions[0].tp == 2055.00

    async def test_save_position_upserts(self, state_mgr):
        """save_position with same ticket updates rather than duplicating."""
        pos1 = PositionRecord(ticket=100, symbol="XAUUSD", type=0, volume=0.01, open_price=2050.0)
        await state_mgr.save_position(pos1)

        pos2 = PositionRecord(ticket=100, symbol="XAUUSD", type=0, volume=0.02, open_price=2051.0)
        await state_mgr.save_position(pos2)

        positions = await state_mgr.get_positions()
        assert len(positions) == 1
        assert positions[0].volume == 0.02
        assert positions[0].open_price == 2051.0

    async def test_remove_position(self, state_mgr):
        """remove_position(ticket) deletes a position record."""
        pos = PositionRecord(ticket=200, symbol="XAUUSD", type=0, volume=0.01, open_price=2050.0)
        await state_mgr.save_position(pos)
        await state_mgr.remove_position(200)

        positions = await state_mgr.get_positions()
        assert len(positions) == 0

    async def test_get_positions_returns_multiple(self, state_mgr):
        """get_positions() returns all tracked positions."""
        for i in range(3):
            pos = PositionRecord(
                ticket=300 + i, symbol="XAUUSD", type=0,
                volume=0.01, open_price=2050.0 + i,
            )
            await state_mgr.save_position(pos)

        positions = await state_mgr.get_positions()
        assert len(positions) == 3


class TestTradeJournal:
    """Test trade journal persistence."""

    async def test_save_trade(self, state_mgr):
        """save_trade(journal_entry) inserts into trade_journal."""
        entry = TradeJournalEntry(
            ticket=500,
            symbol="XAUUSD",
            action="buy",
            volume=0.01,
            open_price=2050.0,
            close_price=2055.0,
            sl=2048.0,
            tp=2055.0,
            pnl=5.0,
            slippage=0.1,
            spread_at_entry=0.3,
            open_time="2026-03-27T10:00:00Z",
            close_time="2026-03-27T10:05:00Z",
            hold_duration_seconds=300.0,
            magic=20260327,
            comment="test trade",
        )
        await state_mgr.save_trade(entry)

        async with state_mgr._db.execute("SELECT COUNT(*) FROM trade_journal") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 1


class TestAccountSnapshots:
    """Test account snapshot persistence."""

    async def test_save_account_snapshot(self, state_mgr):
        """save_account_snapshot inserts into account_snapshots."""
        await state_mgr.save_account_snapshot(
            equity=100.0, balance=95.0, margin=10.0,
            free_margin=85.0, margin_level=950.0,
        )

        async with state_mgr._db.execute("SELECT COUNT(*) FROM account_snapshots") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 1


class TestCrashRecovery:
    """Test WAL mode crash recovery per Pitfall 6."""

    async def test_wal_mode_survives_reopen(self, tmp_path):
        """Database survives close/reopen (WAL mode recovery)."""
        db_path = tmp_path / "crash_test.db"

        # Write state, close without explicit cleanup
        mgr1 = StateManager(db_path=db_path)
        await mgr1.initialize()
        snapshot = CircuitBreakerSnapshot(
            daily_pnl=-3.0,
            consecutive_losses=2,
            daily_drawdown=BreakerState.TRIPPED,
        )
        await mgr1.save_breaker_state(snapshot)
        await mgr1.close()

        # Reopen and verify data survived
        mgr2 = StateManager(db_path=db_path)
        await mgr2.initialize()
        loaded = await mgr2.load_breaker_state()

        assert loaded.daily_pnl == -3.0
        assert loaded.consecutive_losses == 2
        assert loaded.daily_drawdown == BreakerState.TRIPPED
        await mgr2.close()


class TestClose:
    """Test database connection cleanup."""

    async def test_close_clears_connection(self, tmp_path):
        """close() properly closes the database connection."""
        db_path = tmp_path / "close_test.db"
        mgr = StateManager(db_path=db_path)
        await mgr.initialize()
        assert mgr._db is not None

        await mgr.close()
        assert mgr._db is None
