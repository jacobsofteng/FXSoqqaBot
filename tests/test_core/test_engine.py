"""Tests for TradingEngine: component initialization, crash recovery, lifecycle."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fxsoqqabot.config.models import BotSettings
from fxsoqqabot.core.engine import TradingEngine


@pytest.fixture
def settings() -> BotSettings:
    """Create BotSettings with all defaults for testing."""
    return BotSettings()


@pytest.fixture
def engine(settings: BotSettings) -> TradingEngine:
    """Create a TradingEngine instance for testing."""
    return TradingEngine(settings)


class TestTradingEngineInit:
    """Test engine construction and initial state."""

    def test_initial_state(self, engine: TradingEngine) -> None:
        """Engine starts with _running=False and all components None."""
        assert engine.is_running is False
        assert engine.kill_switch is None
        assert engine.breakers is None
        assert engine.state is None

    def test_accepts_bot_settings(self, settings: BotSettings) -> None:
        """Engine accepts BotSettings in constructor."""
        engine = TradingEngine(settings)
        assert engine._settings is settings


class TestInitializeComponents:
    """Test _initialize_components creates and wires all components."""

    @pytest.mark.asyncio
    async def test_creates_all_components(self, engine: TradingEngine) -> None:
        """_initialize_components creates all component instances."""
        # Mock StateManager.initialize and load_signal_weights to avoid actual DB
        with patch(
            "fxsoqqabot.core.engine.StateManager.initialize",
            new_callable=AsyncMock,
        ), patch(
            "fxsoqqabot.core.engine.StateManager.load_signal_weights",
            new_callable=AsyncMock,
            return_value={"accuracies": {}, "trade_count": 0},
        ):
            await engine._initialize_components()

        assert engine._bridge is not None
        assert engine._state is not None
        assert engine._feed is not None
        assert engine._tick_buffer is not None
        assert engine._bar_buffers is not None
        assert engine._storage is not None
        assert engine._order_manager is not None
        assert engine._session is not None
        assert engine._sizer is not None
        assert engine._breakers is not None
        assert engine._kill_switch is not None

        # Phase 2: signal pipeline components
        assert len(engine._signal_modules) == 3
        assert engine._fusion_core is not None
        assert engine._weight_tracker is not None
        assert engine._phase_behavior is not None
        assert engine._trade_manager is not None

    @pytest.mark.asyncio
    async def test_paper_mode_creates_paper_executor(
        self, engine: TradingEngine
    ) -> None:
        """In paper mode, PaperExecutor is created."""
        engine._settings.execution.mode = "paper"
        with patch(
            "fxsoqqabot.core.engine.StateManager.initialize",
            new_callable=AsyncMock,
        ), patch(
            "fxsoqqabot.core.engine.StateManager.load_signal_weights",
            new_callable=AsyncMock,
            return_value={"accuracies": {}, "trade_count": 0},
        ):
            await engine._initialize_components()

        assert engine._paper_executor is not None

    @pytest.mark.asyncio
    async def test_live_mode_no_paper_executor(
        self, engine: TradingEngine
    ) -> None:
        """In live mode, PaperExecutor is NOT created."""
        engine._settings.execution.mode = "live"
        with patch(
            "fxsoqqabot.core.engine.StateManager.initialize",
            new_callable=AsyncMock,
        ), patch(
            "fxsoqqabot.core.engine.StateManager.load_signal_weights",
            new_callable=AsyncMock,
            return_value={"accuracies": {}, "trade_count": 0},
        ):
            await engine._initialize_components()

        assert engine._paper_executor is None


class TestCrashRecovery:
    """Test _crash_recovery per D-05, D-07, D-10."""

    @pytest.mark.asyncio
    async def test_loads_breaker_state_per_d07(
        self, engine: TradingEngine
    ) -> None:
        """Crash recovery loads circuit breaker state from SQLite per D-07."""
        engine._breakers = MagicMock()
        engine._breakers.load_state = AsyncMock()
        engine._breakers.check_session_reset = AsyncMock()
        engine._breakers.set_daily_starting_equity = MagicMock()

        engine._bridge = MagicMock()
        engine._bridge.get_positions = AsyncMock(return_value=None)
        engine._bridge.get_account_info = AsyncMock(
            return_value=SimpleNamespace(equity=20.0)
        )

        engine._order_manager = MagicMock()

        await engine._crash_recovery()

        engine._breakers.load_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_closes_open_positions_per_d05(
        self, engine: TradingEngine
    ) -> None:
        """Crash recovery closes all open positions when found per D-05/EXEC-04."""
        engine._breakers = MagicMock()
        engine._breakers.load_state = AsyncMock()
        engine._breakers.check_session_reset = AsyncMock()
        engine._breakers.set_daily_starting_equity = MagicMock()

        # Simulate open positions
        fake_positions = [
            SimpleNamespace(ticket=1, symbol="XAUUSD", volume=0.01, type=0),
            SimpleNamespace(ticket=2, symbol="XAUUSD", volume=0.01, type=1),
        ]
        engine._bridge = MagicMock()
        engine._bridge.get_positions = AsyncMock(return_value=fake_positions)
        engine._bridge.get_account_info = AsyncMock(
            return_value=SimpleNamespace(equity=20.0)
        )

        engine._order_manager = MagicMock()
        engine._order_manager.close_all_positions = AsyncMock(return_value=[])

        await engine._crash_recovery()

        engine._order_manager.close_all_positions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_close_when_no_positions(
        self, engine: TradingEngine
    ) -> None:
        """Crash recovery does not call close_all when no positions exist."""
        engine._breakers = MagicMock()
        engine._breakers.load_state = AsyncMock()
        engine._breakers.check_session_reset = AsyncMock()
        engine._breakers.set_daily_starting_equity = MagicMock()

        engine._bridge = MagicMock()
        engine._bridge.get_positions = AsyncMock(return_value=None)
        engine._bridge.get_account_info = AsyncMock(
            return_value=SimpleNamespace(equity=20.0)
        )

        engine._order_manager = MagicMock()
        engine._order_manager.close_all_positions = AsyncMock()

        await engine._crash_recovery()

        engine._order_manager.close_all_positions.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_checks_session_reset_per_d10(
        self, engine: TradingEngine
    ) -> None:
        """Crash recovery checks session boundary reset per D-10."""
        engine._breakers = MagicMock()
        engine._breakers.load_state = AsyncMock()
        engine._breakers.check_session_reset = AsyncMock()
        engine._breakers.set_daily_starting_equity = MagicMock()

        engine._bridge = MagicMock()
        engine._bridge.get_positions = AsyncMock(return_value=None)
        engine._bridge.get_account_info = AsyncMock(
            return_value=SimpleNamespace(equity=20.0)
        )

        engine._order_manager = MagicMock()

        await engine._crash_recovery()

        engine._breakers.check_session_reset.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sets_daily_starting_equity(
        self, engine: TradingEngine
    ) -> None:
        """Crash recovery sets daily starting equity from account info."""
        engine._breakers = MagicMock()
        engine._breakers.load_state = AsyncMock()
        engine._breakers.check_session_reset = AsyncMock()
        engine._breakers.set_daily_starting_equity = MagicMock()

        engine._bridge = MagicMock()
        engine._bridge.get_positions = AsyncMock(return_value=None)
        engine._bridge.get_account_info = AsyncMock(
            return_value=SimpleNamespace(equity=42.0)
        )

        engine._order_manager = MagicMock()

        await engine._crash_recovery()

        engine._breakers.set_daily_starting_equity.assert_called_once_with(42.0)


class TestStopLifecycle:
    """Test engine stop() calls shutdown on all components."""

    @pytest.mark.asyncio
    async def test_stop_calls_bridge_shutdown(
        self, engine: TradingEngine
    ) -> None:
        """stop() shuts down the MT5 bridge."""
        engine._bridge = MagicMock()
        engine._bridge.shutdown = AsyncMock()
        engine._state = MagicMock()
        engine._state.close = AsyncMock()
        engine._storage = MagicMock()
        engine._storage.flush_to_parquet = MagicMock()
        engine._storage.close = MagicMock()

        await engine.stop()

        engine._bridge.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_calls_state_close(
        self, engine: TradingEngine
    ) -> None:
        """stop() closes the state DB."""
        engine._bridge = MagicMock()
        engine._bridge.shutdown = AsyncMock()
        engine._state = MagicMock()
        engine._state.close = AsyncMock()
        engine._storage = MagicMock()
        engine._storage.flush_to_parquet = MagicMock()
        engine._storage.close = MagicMock()

        await engine.stop()

        engine._state.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_flushes_and_closes_storage(
        self, engine: TradingEngine
    ) -> None:
        """stop() flushes storage to parquet and closes it."""
        engine._bridge = MagicMock()
        engine._bridge.shutdown = AsyncMock()
        engine._state = MagicMock()
        engine._state.close = AsyncMock()
        engine._storage = MagicMock()
        engine._storage.flush_to_parquet = MagicMock()
        engine._storage.close = MagicMock()

        await engine.stop()

        engine._storage.flush_to_parquet.assert_called_once()
        engine._storage.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(
        self, engine: TradingEngine
    ) -> None:
        """stop() sets _running to False."""
        engine._running = True
        engine._bridge = None
        engine._state = None
        engine._storage = None

        await engine.stop()

        assert engine.is_running is False


class TestConnectMT5:
    """Test _connect_mt5 with retry behavior."""

    @pytest.mark.asyncio
    async def test_successful_first_connect(
        self, engine: TradingEngine
    ) -> None:
        """Direct connection succeeds on first try."""
        engine._bridge = MagicMock()
        engine._bridge.connect = AsyncMock(return_value=True)

        result = await engine._connect_mt5()

        assert result is True
        engine._bridge.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_to_reconnect_loop(
        self, engine: TradingEngine
    ) -> None:
        """Falls back to reconnect_loop when initial connect fails."""
        engine._bridge = MagicMock()
        engine._bridge.connect = AsyncMock(return_value=False)
        engine._bridge.reconnect_loop = AsyncMock(return_value=True)

        result = await engine._connect_mt5()

        assert result is True
        engine._bridge.reconnect_loop.assert_awaited_once_with(max_retries=5)
