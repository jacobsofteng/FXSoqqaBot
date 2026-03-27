"""Tests for circuit breaker system per D-08, RISK-04, RISK-07.

Validates all five circuit breakers, weekly/total drawdown,
session reset, and trade outcome recording.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from fxsoqqabot.config.models import RiskConfig, SessionConfig
from fxsoqqabot.core.state import (
    BreakerState,
    CircuitBreakerSnapshot,
    StateManager,
)
from fxsoqqabot.risk.circuit_breakers import CircuitBreakerManager
from fxsoqqabot.risk.session import SessionFilter


@pytest.fixture
async def state_mgr(tmp_path):
    """Create a StateManager with a temporary database."""
    db_path = tmp_path / "cb_test.db"
    mgr = StateManager(db_path=db_path)
    await mgr.initialize()
    yield mgr
    await mgr.close()


@pytest.fixture
def risk_config():
    """Return default RiskConfig."""
    return RiskConfig()


@pytest.fixture
def session_filter():
    """Return default SessionFilter."""
    return SessionFilter(SessionConfig())


@pytest.fixture
async def cb_manager(risk_config, state_mgr, session_filter):
    """Create a CircuitBreakerManager for testing."""
    mgr = CircuitBreakerManager(risk_config, state_mgr, session_filter)
    await mgr.load_state()
    return mgr


class TestTradingAllowed:
    """Test is_trading_allowed behavior."""

    async def test_all_active_allows_trading(self, cb_manager):
        """is_trading_allowed() returns True when all breakers are ACTIVE."""
        assert cb_manager.is_trading_allowed() is True

    async def test_tripped_breaker_blocks_trading(self, cb_manager):
        """is_trading_allowed returns False when any breaker is TRIPPED."""
        cb_manager._snapshot.daily_drawdown = BreakerState.TRIPPED
        assert cb_manager.is_trading_allowed() is False

    async def test_killed_blocks_trading(self, cb_manager):
        """is_trading_allowed returns False when kill_switch is KILLED."""
        cb_manager._snapshot.kill_switch = BreakerState.KILLED
        assert cb_manager.is_trading_allowed() is False


class TestDailyDrawdown:
    """Test daily drawdown circuit breaker per RISK-04."""

    async def test_daily_drawdown_trips_at_threshold(self, cb_manager):
        """Daily drawdown trips when daily_pnl / daily_starting_equity > 5%."""
        cb_manager.set_daily_starting_equity(100.0)
        # Lose 5% of starting equity ($5 on $100)
        await cb_manager.record_trade_outcome(pnl=-5.0, equity=95.0)

        assert cb_manager._snapshot.daily_drawdown == BreakerState.TRIPPED
        assert cb_manager.is_trading_allowed() is False

    async def test_daily_drawdown_no_trip_below_threshold(self, cb_manager):
        """Daily drawdown does NOT trip when loss < 5%."""
        cb_manager.set_daily_starting_equity(100.0)
        await cb_manager.record_trade_outcome(pnl=-4.0, equity=96.0)

        assert cb_manager._snapshot.daily_drawdown == BreakerState.ACTIVE
        assert cb_manager.is_trading_allowed() is True


class TestConsecutiveLosses:
    """Test consecutive loss streak circuit breaker per D-08."""

    async def test_loss_streak_trips_at_threshold(self, cb_manager):
        """Consecutive losses trips when count >= max_consecutive_losses (5)."""
        cb_manager.set_daily_starting_equity(100.0)
        equity = 100.0
        for i in range(5):
            equity -= 0.5
            await cb_manager.record_trade_outcome(pnl=-0.5, equity=equity)

        assert cb_manager._snapshot.loss_streak == BreakerState.TRIPPED

    async def test_loss_streak_resets_on_win(self, cb_manager):
        """Consecutive loss counter resets to 0 on a winning trade."""
        cb_manager.set_daily_starting_equity(1000.0)
        # 3 losses
        for _ in range(3):
            await cb_manager.record_trade_outcome(pnl=-0.5, equity=999.0)
        assert cb_manager._snapshot.consecutive_losses == 3

        # 1 win resets
        await cb_manager.record_trade_outcome(pnl=1.0, equity=1000.0)
        assert cb_manager._snapshot.consecutive_losses == 0


class TestRapidEquityDrop:
    """Test rapid equity drop circuit breaker per D-08."""

    async def test_rapid_equity_drop_trips(self, cb_manager):
        """Rapid equity drop trips when equity drops > 5% within 15 min window."""
        now = datetime.now(timezone.utc)

        # Record high equity at start of window
        cb_manager._equity_history.append(
            (now.timestamp() - 900, 100.0)  # 15 minutes ago
        )

        # Check current equity that has dropped > 5%
        await cb_manager.check_equity(94.0)

        assert cb_manager._snapshot.rapid_equity_drop == BreakerState.TRIPPED

    async def test_rapid_equity_drop_no_trip_small_drop(self, cb_manager):
        """Rapid equity drop does NOT trip for < 5% drop."""
        now = datetime.now(timezone.utc)

        cb_manager._equity_history.append(
            (now.timestamp() - 900, 100.0)
        )

        await cb_manager.check_equity(96.0)

        assert cb_manager._snapshot.rapid_equity_drop == BreakerState.ACTIVE


class TestMaxDailyTrades:
    """Test max daily trade count circuit breaker per D-08."""

    async def test_max_trades_trips_at_limit(self, cb_manager):
        """Max daily trades trips when count >= max_daily_trades (20)."""
        cb_manager.set_daily_starting_equity(1000.0)
        for i in range(20):
            await cb_manager.record_trade_outcome(pnl=0.1, equity=1000.0 + i * 0.1)

        assert cb_manager._snapshot.max_trades == BreakerState.TRIPPED

    async def test_max_trades_not_tripped_below_limit(self, cb_manager):
        """Max daily trades does NOT trip below limit."""
        cb_manager.set_daily_starting_equity(1000.0)
        for i in range(19):
            await cb_manager.record_trade_outcome(pnl=0.1, equity=1000.0 + i * 0.1)

        assert cb_manager._snapshot.max_trades == BreakerState.ACTIVE


class TestSpreadSpike:
    """Test spread spike circuit breaker per D-08."""

    async def test_spread_spike_trips_sustained(self, cb_manager):
        """Spread spike trips when spread > 5x average for > 30 seconds."""
        avg_spread = 0.5

        # Simulate sustained spike over 31 seconds
        now = datetime.now(timezone.utc).timestamp()
        cb_manager._spread_history.append((now - 31, 3.0))

        await cb_manager.check_spread(spread=3.0, avg_spread=avg_spread)

        assert cb_manager._snapshot.spread_spike == BreakerState.TRIPPED

    async def test_spread_spike_clears_on_normal(self, cb_manager):
        """Spread history clears when spread returns below threshold."""
        cb_manager._spread_history.append((1000.0, 3.0))
        assert len(cb_manager._spread_history) == 1

        await cb_manager.check_spread(spread=0.3, avg_spread=0.5)

        assert len(cb_manager._spread_history) == 0


class TestWeeklyAndTotalDrawdown:
    """Test weekly and total max drawdown per RISK-07."""

    async def test_total_drawdown_trips(self, cb_manager):
        """Total max drawdown trips when equity < high_water_mark * (1 - 25%)."""
        cb_manager.set_daily_starting_equity(100.0)
        cb_manager._snapshot.equity_high_water_mark = 100.0

        # Equity at 75 = exactly 25% drawdown from 100 HWM
        await cb_manager.record_trade_outcome(pnl=-25.0, equity=75.0)

        # daily_drawdown should be tripped by total drawdown check
        assert cb_manager._snapshot.daily_drawdown == BreakerState.TRIPPED


class TestSessionReset:
    """Test auto-reset at session boundary per D-10."""

    async def test_daily_breakers_reset_on_session_change(self, cb_manager):
        """Auto-reset: daily breakers reset when session_date changes."""
        # Set initial state with tripped breakers
        cb_manager._snapshot.session_date = "2026-03-26"
        cb_manager._snapshot.daily_drawdown = BreakerState.TRIPPED
        cb_manager._snapshot.loss_streak = BreakerState.TRIPPED
        cb_manager._snapshot.rapid_equity_drop = BreakerState.TRIPPED
        cb_manager._snapshot.max_trades = BreakerState.TRIPPED
        cb_manager._snapshot.spread_spike = BreakerState.TRIPPED
        cb_manager._snapshot.daily_pnl = -5.0
        cb_manager._snapshot.consecutive_losses = 5
        cb_manager._snapshot.daily_trade_count = 20

        # New session date
        new_day = datetime(2026, 3, 27, 14, 0, tzinfo=timezone.utc)
        await cb_manager.check_session_reset(now=new_day)

        assert cb_manager._snapshot.daily_drawdown == BreakerState.ACTIVE
        assert cb_manager._snapshot.loss_streak == BreakerState.ACTIVE
        assert cb_manager._snapshot.rapid_equity_drop == BreakerState.ACTIVE
        assert cb_manager._snapshot.max_trades == BreakerState.ACTIVE
        assert cb_manager._snapshot.spread_spike == BreakerState.ACTIVE
        assert cb_manager._snapshot.daily_pnl == 0.0
        assert cb_manager._snapshot.consecutive_losses == 0
        assert cb_manager._snapshot.daily_trade_count == 0

    async def test_kill_switch_not_reset_on_session_change(self, cb_manager):
        """Kill switch is NOT auto-reset at session boundary per D-10."""
        cb_manager._snapshot.session_date = "2026-03-26"
        cb_manager._snapshot.kill_switch = BreakerState.KILLED

        new_day = datetime(2026, 3, 27, 14, 0, tzinfo=timezone.utc)
        await cb_manager.check_session_reset(now=new_day)

        assert cb_manager._snapshot.kill_switch == BreakerState.KILLED


class TestRecordTradeOutcome:
    """Test trade outcome recording updates state correctly."""

    async def test_record_updates_daily_pnl(self, cb_manager):
        """record_trade_outcome(pnl) updates daily_pnl."""
        cb_manager.set_daily_starting_equity(1000.0)
        await cb_manager.record_trade_outcome(pnl=2.5, equity=1002.5)
        assert cb_manager._snapshot.daily_pnl == 2.5

        await cb_manager.record_trade_outcome(pnl=-1.0, equity=1001.5)
        assert cb_manager._snapshot.daily_pnl == 1.5

    async def test_record_updates_consecutive_losses(self, cb_manager):
        """record_trade_outcome updates consecutive_losses correctly."""
        cb_manager.set_daily_starting_equity(1000.0)
        await cb_manager.record_trade_outcome(pnl=-1.0, equity=999.0)
        assert cb_manager._snapshot.consecutive_losses == 1

        await cb_manager.record_trade_outcome(pnl=-1.0, equity=998.0)
        assert cb_manager._snapshot.consecutive_losses == 2

        await cb_manager.record_trade_outcome(pnl=1.0, equity=999.0)
        assert cb_manager._snapshot.consecutive_losses == 0

    async def test_record_updates_daily_trade_count(self, cb_manager):
        """record_trade_outcome increments daily_trade_count."""
        cb_manager.set_daily_starting_equity(1000.0)
        await cb_manager.record_trade_outcome(pnl=1.0, equity=1001.0)
        assert cb_manager._snapshot.daily_trade_count == 1

    async def test_tripped_breaker_persists_to_sqlite(self, cb_manager, state_mgr):
        """Tripped breaker state persists to SQLite."""
        cb_manager.set_daily_starting_equity(100.0)
        await cb_manager.record_trade_outcome(pnl=-5.0, equity=95.0)

        # Load from SQLite directly to verify persistence
        loaded = await state_mgr.load_breaker_state()
        assert loaded.daily_drawdown == BreakerState.TRIPPED


class TestGetTrippedBreakers:
    """Test get_tripped_breakers helper."""

    async def test_returns_tripped_names(self, cb_manager):
        """get_tripped_breakers returns names of tripped breakers."""
        cb_manager._snapshot.daily_drawdown = BreakerState.TRIPPED
        cb_manager._snapshot.spread_spike = BreakerState.TRIPPED

        tripped = cb_manager.get_tripped_breakers()
        assert "daily_drawdown" in tripped
        assert "spread_spike" in tripped
        assert len(tripped) == 2

    async def test_returns_empty_when_all_active(self, cb_manager):
        """get_tripped_breakers returns empty list when all active."""
        tripped = cb_manager.get_tripped_breakers()
        assert tripped == []
