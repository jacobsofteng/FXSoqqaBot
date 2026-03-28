"""Tests for dashboard live state wiring -- all 4 Phase 6 success criteria.

SC1: Equity and connection assignment from MT5 account info
SC2: is_killed reads a boolean, not a coroutine
SC3: equity_history/module_weights/breaker_status populated, to_dict/web endpoint
SC4: Pause guards skip loop bodies
Plus: _handle_kill calls activate() with no args
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import asyncio
import pytest

from fxsoqqabot.config.models import BotSettings
from fxsoqqabot.core.engine import TradingEngine
from fxsoqqabot.core.state import BreakerState, CircuitBreakerSnapshot
from fxsoqqabot.core.state_snapshot import TradingEngineState
from fxsoqqabot.risk.circuit_breakers import CircuitBreakerManager


@pytest.fixture
def settings() -> BotSettings:
    """Create BotSettings with all defaults for testing."""
    return BotSettings()


@pytest.fixture
def engine(settings: BotSettings) -> TradingEngine:
    """Create a TradingEngine instance for testing."""
    return TradingEngine(settings)


# ---------------------------------------------------------------------------
# SC1: Equity and Connection Assignment
# ---------------------------------------------------------------------------


class TestSC1EquityAndConnection:
    """Test equity from MT5 account info and connection status from bridge."""

    def test_init_has_current_equity_and_connected(
        self, engine: TradingEngine
    ) -> None:
        """Engine starts with _current_equity=0.0 and _connected=False."""
        assert engine._current_equity == 0.0
        assert engine._connected is False

    def test_update_engine_state_reads_current_equity(
        self, engine: TradingEngine
    ) -> None:
        """_update_engine_state reads _current_equity into state.equity."""
        engine._current_equity = 42.50
        engine._tick_buffer = MagicMock(
            spec=["__len__"], __len__=lambda s: 0
        )
        engine._update_engine_state()
        assert engine._engine_state.equity == 42.50

    def test_update_engine_state_reads_connected(
        self, engine: TradingEngine
    ) -> None:
        """_update_engine_state reads _connected into state.is_connected."""
        engine._connected = True
        engine._tick_buffer = MagicMock(
            spec=["__len__"], __len__=lambda s: 0
        )
        engine._update_engine_state()
        assert engine._engine_state.is_connected is True

    @pytest.mark.asyncio
    async def test_health_loop_sets_current_equity_and_connected(
        self, engine: TradingEngine
    ) -> None:
        """_health_loop assigns _current_equity and _connected from MT5."""
        # Mock bridge
        engine._bridge = MagicMock()
        engine._bridge.get_account_info = AsyncMock(
            return_value=SimpleNamespace(
                equity=99.50,
                balance=100.0,
                margin=10.0,
                margin_free=90.0,
            )
        )
        type(engine._bridge).connected = PropertyMock(return_value=True)

        # Mock breakers
        engine._breakers = MagicMock()
        engine._breakers.check_session_reset = AsyncMock()
        engine._breakers.check_equity = AsyncMock()
        engine._breakers.get_tripped_breakers = MagicMock(return_value=[])

        # Mock state manager
        engine._state = MagicMock()
        engine._state.save_account_snapshot = AsyncMock()

        engine._running = True

        # Patch asyncio_sleep to stop after first iteration
        call_count = 0

        async def fake_sleep(secs: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                engine._running = False

        with patch("fxsoqqabot.core.engine.asyncio_sleep", side_effect=fake_sleep):
            await engine._health_loop()

        assert engine._current_equity == 99.50
        assert engine._connected is True


# ---------------------------------------------------------------------------
# SC2: is_killed Reads a Boolean
# ---------------------------------------------------------------------------


class TestSC2IsKilledBoolean:
    """Test that is_killed is a synchronous bool, not a coroutine."""

    def test_is_killed_reads_boolean_from_breakers(self) -> None:
        """CircuitBreakerManager.is_killed returns a plain bool."""
        breakers = CircuitBreakerManager(
            config=MagicMock(),
            state=MagicMock(),
            session=MagicMock(),
        )
        assert breakers.is_killed is False

        breakers._snapshot.kill_switch = BreakerState.KILLED
        assert breakers.is_killed is True

    def test_update_engine_state_uses_breakers_is_killed(
        self, engine: TradingEngine
    ) -> None:
        """_update_engine_state sets is_killed=True from breakers.is_killed."""
        engine._breakers = MagicMock()
        engine._breakers.is_killed = True
        engine._breakers.get_breaker_status = MagicMock(
            return_value={"kill_switch": "killed"}
        )
        engine._tick_buffer = MagicMock(
            spec=["__len__"], __len__=lambda s: 0
        )
        engine._update_engine_state()
        assert engine._engine_state.is_killed is True

    def test_update_engine_state_is_killed_false_when_not_killed(
        self, engine: TradingEngine
    ) -> None:
        """_update_engine_state sets is_killed=False when breakers says so."""
        engine._breakers = MagicMock()
        engine._breakers.is_killed = False
        engine._breakers.get_breaker_status = MagicMock(
            return_value={"kill_switch": "active"}
        )
        engine._tick_buffer = MagicMock(
            spec=["__len__"], __len__=lambda s: 0
        )
        engine._update_engine_state()
        assert engine._engine_state.is_killed is False


# ---------------------------------------------------------------------------
# SC3: equity_history, module_weights, breaker_status populated
# ---------------------------------------------------------------------------


class TestSC3EquityHistoryAndModuleWeights:
    """Test equity_history append/cap, module_weights, breaker_status."""

    def test_equity_history_populated_when_positive(
        self, engine: TradingEngine
    ) -> None:
        """Positive equity gets appended to equity_history."""
        engine._current_equity = 25.0
        engine._tick_buffer = MagicMock(
            spec=["__len__"], __len__=lambda s: 0
        )
        engine._update_engine_state()
        assert engine._engine_state.equity_history == [25.0]

        engine._update_engine_state()
        assert engine._engine_state.equity_history == [25.0, 25.0]

    def test_equity_history_not_populated_when_zero(
        self, engine: TradingEngine
    ) -> None:
        """Zero equity is NOT appended to equity_history."""
        engine._current_equity = 0.0
        engine._tick_buffer = MagicMock(
            spec=["__len__"], __len__=lambda s: 0
        )
        engine._update_engine_state()
        assert engine._engine_state.equity_history == []

    def test_equity_history_capped_at_1000(
        self, engine: TradingEngine
    ) -> None:
        """Equity history is trimmed to 500 when exceeding 1000."""
        engine._current_equity = 10.0
        engine._tick_buffer = MagicMock(
            spec=["__len__"], __len__=lambda s: 0
        )
        # Pre-fill with 999 entries
        engine._engine_state.equity_history = list(range(999))

        # Push to 1000 -- should not trim yet
        engine._update_engine_state()
        assert len(engine._engine_state.equity_history) == 1000

        # Push to 1001 -- should trigger trim to 500, then append = 501
        engine._update_engine_state()
        assert len(engine._engine_state.equity_history) <= 501

    def test_module_weights_populated_from_tracker(
        self, engine: TradingEngine
    ) -> None:
        """module_weights populated from AdaptiveWeightTracker.get_weights()."""
        engine._weight_tracker = MagicMock()
        engine._weight_tracker.get_weights = MagicMock(
            return_value={"chaos": 0.4, "flow": 0.35, "timing": 0.25}
        )
        engine._tick_buffer = MagicMock(
            spec=["__len__"], __len__=lambda s: 0
        )
        engine._update_engine_state()
        assert engine._engine_state.module_weights == {
            "chaos": 0.4,
            "flow": 0.35,
            "timing": 0.25,
        }

    def test_breaker_status_populated_from_get_breaker_status(
        self, engine: TradingEngine
    ) -> None:
        """breaker_status dict has 6 keys from get_breaker_status()."""
        expected = {
            "kill_switch": "active",
            "daily_drawdown": "active",
            "loss_streak": "tripped",
            "rapid_equity_drop": "active",
            "max_trades": "active",
            "spread_spike": "active",
        }
        engine._breakers = MagicMock()
        engine._breakers.get_breaker_status = MagicMock(return_value=expected)
        engine._breakers.is_killed = False
        engine._tick_buffer = MagicMock(
            spec=["__len__"], __len__=lambda s: 0
        )
        engine._update_engine_state()
        assert engine._engine_state.breaker_status["loss_streak"] == "tripped"
        assert len(engine._engine_state.breaker_status) == 6


class TestSC3ToDict:
    """Test TradingEngineState.to_dict() includes equity_history and module_weights."""

    def test_to_dict_includes_equity_history(self) -> None:
        """to_dict() includes equity_history (last 50)."""
        state = TradingEngineState()
        state.equity_history = [10.0, 20.0, 30.0]
        d = state.to_dict()
        assert d["equity_history"] == [10.0, 20.0, 30.0]

    def test_to_dict_includes_module_weights(self) -> None:
        """to_dict() includes module_weights."""
        state = TradingEngineState()
        state.module_weights = {"chaos": 0.5, "flow": 0.3, "timing": 0.2}
        d = state.to_dict()
        assert d["module_weights"] == {"chaos": 0.5, "flow": 0.3, "timing": 0.2}


class TestSC3WebEndpoint:
    """Test /api/module-weights returns real data from state."""

    @pytest.mark.asyncio
    async def test_module_weights_endpoint_returns_state_weights(self) -> None:
        """/api/module-weights returns state.module_weights when populated."""
        from httpx import ASGITransport, AsyncClient

        from fxsoqqabot.dashboard.web.server import DashboardServer

        state = TradingEngineState()
        state.module_weights = {"chaos": 0.33}

        server = DashboardServer(
            config=MagicMock(api_key="test", host="127.0.0.1", port=8080),
            state=state,
        )
        transport = ASGITransport(app=server.get_app())
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            resp = await client.get("/api/module-weights")

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == [{"chaos": 0.33}]


# ---------------------------------------------------------------------------
# SC4: Pause Guards in All Three Loops
# ---------------------------------------------------------------------------


class TestSC4PauseGuards:
    """Test that paused state causes all three loops to skip their body."""

    @pytest.mark.asyncio
    async def test_tick_loop_skips_when_paused(
        self, engine: TradingEngine
    ) -> None:
        """_tick_loop skips body when is_paused is True."""
        engine._bridge = MagicMock(
            ensure_connected=AsyncMock(return_value=True)
        )
        engine._feed = MagicMock(
            fetch_ticks=AsyncMock(return_value=[])
        )
        engine._tick_buffer = MagicMock(__len__=lambda s: 0)
        engine._storage = MagicMock()
        engine._breakers = MagicMock()
        engine._paper_executor = None

        engine._running = True
        engine._engine_state.is_paused = True

        call_count = 0

        async def fake_sleep(secs: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                engine._running = False

        with patch("fxsoqqabot.core.engine.asyncio_sleep", side_effect=fake_sleep):
            await engine._tick_loop()

        assert engine._feed.fetch_ticks.call_count == 0

    @pytest.mark.asyncio
    async def test_bar_loop_skips_when_paused(
        self, engine: TradingEngine
    ) -> None:
        """_bar_loop skips body when is_paused is True."""
        engine._feed = MagicMock(
            fetch_multi_timeframe_bars=AsyncMock()
        )
        engine._bar_buffers = MagicMock()

        engine._running = True
        engine._engine_state.is_paused = True

        call_count = 0

        async def fake_sleep(secs: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                engine._running = False

        with patch("fxsoqqabot.core.engine.asyncio_sleep", side_effect=fake_sleep):
            await engine._bar_loop()

        assert engine._feed.fetch_multi_timeframe_bars.call_count == 0

    @pytest.mark.asyncio
    async def test_signal_loop_skips_when_paused(
        self, engine: TradingEngine
    ) -> None:
        """_signal_loop skips body when is_paused is True."""
        engine._tick_buffer = MagicMock()
        engine._bar_buffers = MagicMock()
        engine._fusion_core = MagicMock()
        engine._weight_tracker = MagicMock()
        engine._phase_behavior = MagicMock()
        engine._trade_manager = MagicMock()
        engine._bridge = MagicMock()

        engine._running = True
        engine._engine_state.is_paused = True

        call_count = 0

        async def fake_sleep(secs: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                engine._running = False

        with patch("fxsoqqabot.core.engine.asyncio_sleep", side_effect=fake_sleep):
            await engine._signal_loop()

        assert engine._tick_buffer.as_arrays.call_count == 0


# ---------------------------------------------------------------------------
# Bonus: _handle_kill signature fix
# ---------------------------------------------------------------------------


class TestHandleKillFix:
    """Test _handle_kill calls activate() with no arguments."""

    @pytest.mark.asyncio
    async def test_handle_kill_calls_activate_no_args(
        self, engine: TradingEngine
    ) -> None:
        """_handle_kill calls activate() with no positional args."""
        engine._kill_switch = MagicMock(
            activate=AsyncMock(return_value={"positions_closed": 0})
        )
        engine._breakers = MagicMock(is_killed=True)

        await engine._handle_kill()

        assert engine._kill_switch.activate.called
        args, kwargs = engine._kill_switch.activate.call_args
        assert args == ()
        assert engine._engine_state.is_killed is True
