"""End-to-end integration tests for signal pipeline wired into TradingEngine.

Tests:
- TradingEngine creates signal modules during _initialize_components
- _signal_loop processes signals and produces FusionResult
- Weight persistence round-trip via StateManager
- Module failure isolation (error in one doesn't crash loop)
- Signal loop runs at bar_refresh_interval
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from fxsoqqabot.config.models import BotSettings
from fxsoqqabot.core.engine import TradingEngine
from fxsoqqabot.core.state import StateManager
from fxsoqqabot.signals.base import RegimeState, SignalOutput
from fxsoqqabot.signals.fusion.core import FusionCore
from fxsoqqabot.signals.fusion.weights import AdaptiveWeightTracker


@pytest.fixture
def settings() -> BotSettings:
    """Create minimal BotSettings for testing."""
    return BotSettings(
        execution={"mode": "paper", "symbol": "XAUUSD"},
        data={
            "storage_path": ":memory:",
            "tick_buffer_size": 100,
            "bar_refresh_interval_seconds": 1,
        },
    )


@pytest.fixture
def engine(settings: BotSettings) -> TradingEngine:
    """Create a TradingEngine instance."""
    return TradingEngine(settings)


class TestEngineSignalModuleCreation:
    """Test that TradingEngine creates signal modules during initialization."""

    def test_signal_module_slots_initialized_empty(self, engine: TradingEngine) -> None:
        """Signal module slots start empty before _initialize_components."""
        assert engine._signal_modules == []
        assert engine._fusion_core is None
        assert engine._weight_tracker is None
        assert engine._phase_behavior is None
        assert engine._trade_manager is None

    @pytest.mark.asyncio
    async def test_initialize_components_creates_signal_modules(
        self, engine: TradingEngine
    ) -> None:
        """After _initialize_components, signal modules are created."""
        # Mock out MT5Bridge to avoid real MT5 connection
        with patch("fxsoqqabot.core.engine.MT5Bridge") as MockBridge, \
             patch("fxsoqqabot.core.engine.MarketDataFeed"), \
             patch("fxsoqqabot.core.engine.TickStorage"), \
             patch("fxsoqqabot.core.engine.OrderManager"):
            MockBridge.return_value = MagicMock()

            with patch.object(StateManager, "initialize", new_callable=AsyncMock), \
                 patch.object(StateManager, "load_signal_weights", new_callable=AsyncMock) as mock_load:
                mock_load.return_value = {"accuracies": {}, "trade_count": 0}
                await engine._initialize_components()

            # Verify signal modules were created
            assert len(engine._signal_modules) == 3
            module_names = [m.name for m in engine._signal_modules]
            assert "chaos" in module_names
            assert "flow" in module_names
            assert "timing" in module_names

            # Verify fusion components
            assert engine._fusion_core is not None
            assert engine._weight_tracker is not None
            assert engine._phase_behavior is not None
            assert engine._trade_manager is not None


class TestSignalLoopProcessing:
    """Test that _signal_loop processes signals correctly."""

    @pytest.mark.asyncio
    async def test_signal_loop_produces_fusion_result(
        self, engine: TradingEngine
    ) -> None:
        """Signal loop should update modules, fuse signals, and log result."""
        # Set up engine state manually
        engine._running = True
        engine._tick_buffer = MagicMock()
        engine._bar_buffers = MagicMock()
        engine._bridge = AsyncMock()
        engine._state = AsyncMock()
        engine._feed = MagicMock()

        # Mock tick buffer as_arrays
        engine._tick_buffer.as_arrays.return_value = {
            "time_msc": np.array([1000], dtype=np.int64),
            "bid": np.array([2000.0], dtype=np.float64),
            "ask": np.array([2000.5], dtype=np.float64),
            "last": np.array([2000.0], dtype=np.float64),
            "spread": np.array([0.5], dtype=np.float64),
            "volume_real": np.array([1.0], dtype=np.float64),
        }

        # Mock bar buffers
        m5_arrays = {
            "time": np.array([1, 2, 3], dtype=np.int64),
            "open": np.array([2000.0, 2001.0, 2002.0], dtype=np.float64),
            "high": np.array([2001.0, 2002.0, 2003.0], dtype=np.float64),
            "low": np.array([1999.0, 2000.0, 2001.0], dtype=np.float64),
            "close": np.array([2000.5, 2001.5, 2002.5], dtype=np.float64),
            "tick_volume": np.array([100, 200, 150], dtype=np.int64),
        }
        mock_bar_buffer = MagicMock()
        mock_bar_buffer.as_arrays.return_value = m5_arrays
        engine._bar_buffers.__getitem__ = MagicMock(return_value=mock_bar_buffer)
        engine._bar_buffers.timeframes = ["M5"]

        # Create real fusion components
        from fxsoqqabot.config.models import FusionConfig, RiskConfig
        fusion_config = FusionConfig()
        engine._fusion_core = FusionCore(fusion_config)
        engine._weight_tracker = AdaptiveWeightTracker(
            module_names=["chaos", "flow", "timing"],
            alpha=0.1,
            warmup_trades=10,
        )
        from fxsoqqabot.signals.fusion.phase_behavior import PhaseBehavior
        engine._phase_behavior = PhaseBehavior(fusion_config, RiskConfig())

        # Mock trade manager
        engine._trade_manager = AsyncMock()
        from fxsoqqabot.signals.fusion.trade_manager import TradeDecision
        engine._trade_manager.evaluate_and_execute.return_value = TradeDecision(
            action="hold",
            sl_distance=0.0,
            tp_distance=0.0,
            lot_size=0.0,
            confidence=0.3,
            regime=RegimeState.RANGING,
            reason="Below threshold",
        )

        # Mock signal modules that return predictable outputs
        mock_chaos = AsyncMock()
        mock_chaos.name = "chaos"
        mock_chaos.update.return_value = SignalOutput(
            module_name="chaos",
            direction=0.5,
            confidence=0.7,
            regime=RegimeState.TRENDING_UP,
        )

        mock_flow = AsyncMock()
        mock_flow.name = "flow"
        mock_flow.update.return_value = SignalOutput(
            module_name="flow",
            direction=0.3,
            confidence=0.6,
        )

        mock_timing = AsyncMock()
        mock_timing.name = "timing"
        mock_timing.update.return_value = SignalOutput(
            module_name="timing",
            direction=0.4,
            confidence=0.5,
        )

        engine._signal_modules = [mock_chaos, mock_flow, mock_timing]

        # Mock account info
        account = MagicMock()
        account.equity = 50.0
        engine._bridge.get_account_info.return_value = account

        # Run signal loop for one iteration then stop
        loop_count = 0

        async def stop_after_one(*args):
            nonlocal loop_count
            loop_count += 1
            if loop_count >= 1:
                engine._running = False

        with patch("fxsoqqabot.core.engine.asyncio_sleep", side_effect=stop_after_one):
            await engine._signal_loop()

        # Verify all modules were called
        mock_chaos.update.assert_called_once()
        mock_flow.update.assert_called_once()
        mock_timing.update.assert_called_once()

        # Verify trade manager was called (ATR > 0 and price > 0)
        engine._trade_manager.evaluate_and_execute.assert_called_once()
        call_kwargs = engine._trade_manager.evaluate_and_execute.call_args
        assert call_kwargs.kwargs["equity"] == 50.0
        assert call_kwargs.kwargs["current_price"] > 0


class TestModuleFailureIsolation:
    """Test that a module failure doesn't crash the signal loop."""

    @pytest.mark.asyncio
    async def test_failing_module_skipped(self, engine: TradingEngine) -> None:
        """If one module raises, the loop continues with remaining modules."""
        engine._running = True
        engine._tick_buffer = MagicMock()
        engine._bar_buffers = MagicMock()
        engine._bridge = AsyncMock()
        engine._state = AsyncMock()
        engine._feed = MagicMock()

        engine._tick_buffer.as_arrays.return_value = {
            "time_msc": np.array([1000], dtype=np.int64),
            "bid": np.array([2000.0], dtype=np.float64),
            "ask": np.array([2000.5], dtype=np.float64),
            "last": np.array([2000.0], dtype=np.float64),
            "spread": np.array([0.5], dtype=np.float64),
            "volume_real": np.array([1.0], dtype=np.float64),
        }

        mock_bar = MagicMock()
        mock_bar.as_arrays.return_value = {
            "high": np.array([2001.0, 2002.0, 2003.0], dtype=np.float64),
            "low": np.array([1999.0, 2000.0, 2001.0], dtype=np.float64),
            "close": np.array([2000.5, 2001.5, 2002.5], dtype=np.float64),
        }
        engine._bar_buffers.__getitem__ = MagicMock(return_value=mock_bar)
        engine._bar_buffers.timeframes = ["M5"]

        from fxsoqqabot.config.models import FusionConfig, RiskConfig
        fusion_config = FusionConfig()
        engine._fusion_core = FusionCore(fusion_config)
        engine._weight_tracker = AdaptiveWeightTracker(
            module_names=["chaos", "flow", "timing"],
        )
        from fxsoqqabot.signals.fusion.phase_behavior import PhaseBehavior
        engine._phase_behavior = PhaseBehavior(fusion_config, RiskConfig())
        engine._trade_manager = AsyncMock()
        from fxsoqqabot.signals.fusion.trade_manager import TradeDecision
        engine._trade_manager.evaluate_and_execute.return_value = TradeDecision(
            action="hold", sl_distance=0.0, tp_distance=0.0,
            lot_size=0.0, confidence=0.0, regime=RegimeState.RANGING,
            reason="test",
        )

        # One module raises, others succeed
        failing_module = AsyncMock()
        failing_module.name = "chaos"
        failing_module.update.side_effect = RuntimeError("computation failed")

        good_module = AsyncMock()
        good_module.name = "flow"
        good_module.update.return_value = SignalOutput(
            module_name="flow", direction=0.5, confidence=0.6,
        )

        engine._signal_modules = [failing_module, good_module]

        account = MagicMock()
        account.equity = 50.0
        engine._bridge.get_account_info.return_value = account

        loop_count = 0

        async def stop_after_one(*args):
            nonlocal loop_count
            loop_count += 1
            if loop_count >= 1:
                engine._running = False

        with patch("fxsoqqabot.core.engine.asyncio_sleep", side_effect=stop_after_one):
            # Should NOT raise
            await engine._signal_loop()

        # Failing module was called but didn't crash the loop
        failing_module.update.assert_called_once()
        good_module.update.assert_called_once()

        # Trade manager was still called with the remaining signal
        engine._trade_manager.evaluate_and_execute.assert_called_once()


class TestWeightPersistence:
    """Test weight persistence round-trip via StateManager."""

    @pytest.mark.asyncio
    async def test_weight_save_and_load_roundtrip(self) -> None:
        """Weights saved to StateManager can be loaded back."""
        sm = StateManager(":memory:")
        await sm.initialize()

        # Create tracker with some state
        tracker = AdaptiveWeightTracker(
            module_names=["chaos", "flow", "timing"],
            alpha=0.1,
            warmup_trades=10,
        )

        # Record some outcomes to change weights
        for _ in range(15):
            tracker.record_outcome(
                {"chaos": 1.0, "flow": -1.0, "timing": 0.5},
                actual_direction=1.0,
            )

        # Save
        state = tracker.get_state()
        await sm.save_signal_weights(state)

        # Load
        loaded = await sm.load_signal_weights()
        assert loaded["trade_count"] == 15
        assert "chaos" in loaded["accuracies"]
        assert "flow" in loaded["accuracies"]
        assert "timing" in loaded["accuracies"]

        # Create new tracker and load state
        new_tracker = AdaptiveWeightTracker(
            module_names=["chaos", "flow", "timing"],
            alpha=0.1,
            warmup_trades=10,
        )
        loaded["alpha"] = 0.1
        loaded["warmup"] = 10
        new_tracker.load_state(loaded)

        # Weights should match
        orig_weights = tracker.get_weights()
        new_weights = new_tracker.get_weights()
        for name in orig_weights:
            assert abs(orig_weights[name] - new_weights[name]) < 1e-10

        await sm.close()


class TestSignalLoopTiming:
    """Test that signal loop runs at bar_refresh_interval."""

    @pytest.mark.asyncio
    async def test_signal_loop_uses_bar_refresh_interval(
        self, engine: TradingEngine
    ) -> None:
        """Signal loop should sleep for bar_refresh_interval_seconds."""
        engine._running = True
        engine._tick_buffer = MagicMock()
        engine._bar_buffers = MagicMock()
        engine._bridge = AsyncMock()
        engine._state = AsyncMock()
        engine._feed = MagicMock()

        engine._tick_buffer.as_arrays.return_value = {
            "time_msc": np.array([], dtype=np.int64),
            "bid": np.array([], dtype=np.float64),
            "ask": np.array([], dtype=np.float64),
            "last": np.array([], dtype=np.float64),
            "spread": np.array([], dtype=np.float64),
            "volume_real": np.array([], dtype=np.float64),
        }

        mock_bar = MagicMock()
        mock_bar.as_arrays.return_value = {}
        engine._bar_buffers.__getitem__ = MagicMock(return_value=mock_bar)
        engine._bar_buffers.timeframes = []

        from fxsoqqabot.config.models import FusionConfig, RiskConfig
        engine._fusion_core = FusionCore(FusionConfig())
        engine._weight_tracker = AdaptiveWeightTracker(module_names=[])
        from fxsoqqabot.signals.fusion.phase_behavior import PhaseBehavior
        engine._phase_behavior = PhaseBehavior(FusionConfig(), RiskConfig())
        engine._trade_manager = AsyncMock()

        # No modules -> skip to sleep
        engine._signal_modules = []

        sleep_values = []

        async def capture_sleep(duration):
            sleep_values.append(duration)
            engine._running = False

        with patch("fxsoqqabot.core.engine.asyncio_sleep", side_effect=capture_sleep):
            await engine._signal_loop()

        expected_interval = engine._settings.data.bar_refresh_interval_seconds
        assert len(sleep_values) == 1
        assert sleep_values[0] == expected_interval


class TestAsyncioGatherInclusion:
    """Test that _signal_loop is included in asyncio.gather."""

    def test_start_method_references_signal_loop(self, engine: TradingEngine) -> None:
        """Verify that engine.start() would call _signal_loop in gather."""
        import inspect
        source = inspect.getsource(engine.start)
        assert "_signal_loop" in source
        assert "asyncio.gather" in source
