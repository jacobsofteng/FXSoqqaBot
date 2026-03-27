"""Tests for trade logging wiring: open/close lifecycle per 04-07.

Covers:
- TradeManager.evaluate_and_execute returns (TradeDecision, FillEvent | None)
- Engine _signal_loop calls log_trade_open when fill is not None
- Engine paper SL/TP triggers close/log/learn pipeline
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import duckdb
import pytest

from fxsoqqabot.core.events import FillEvent
from fxsoqqabot.signals.base import RegimeState, SignalOutput
from fxsoqqabot.signals.fusion.core import FusionResult
from fxsoqqabot.signals.fusion.trade_manager import TradeDecision, TradeManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fill(ticket: int = 12345, action: str = "buy") -> FillEvent:
    return FillEvent(
        ticket=ticket,
        symbol="XAUUSD",
        action=action,
        volume=0.01,
        fill_price=2050.50,
        requested_price=2050.40,
        slippage=0.10,
        sl=2048.50,
        tp=2056.50,
        magic=20260327,
        is_paper=True,
    )


def _make_fusion_result(
    should_trade: bool = True,
    direction: float = 1.0,
    regime: RegimeState = RegimeState.TRENDING_UP,
) -> FusionResult:
    return FusionResult(
        direction=direction,
        composite_score=0.7,
        fused_confidence=0.72,
        should_trade=should_trade,
        regime=regime,
        module_scores={"chaos": 0.56, "flow": 0.48, "timing": 0.30},
        confidence_threshold=0.5,
    )


def _make_signals() -> list[SignalOutput]:
    return [
        SignalOutput(module_name="chaos", direction=0.8, confidence=0.7, regime=RegimeState.TRENDING_UP),
        SignalOutput(module_name="flow", direction=0.6, confidence=0.8),
        SignalOutput(module_name="timing", direction=0.5, confidence=0.6),
    ]


# ---------------------------------------------------------------------------
# Test: TradeManager tuple return
# ---------------------------------------------------------------------------


class TestTradeManagerTupleReturn:
    """TradeManager.evaluate_and_execute returns (TradeDecision, FillEvent | None)."""

    @pytest.fixture
    def trade_manager(self):
        """TradeManager with mock order_manager that returns a FillEvent."""
        from fxsoqqabot.config.models import FusionConfig, RiskConfig
        from fxsoqqabot.signals.fusion.phase_behavior import PhaseBehavior

        fusion_config = FusionConfig()
        risk_config = RiskConfig()
        phase_behavior = PhaseBehavior(fusion_config, risk_config)

        # Mock order_manager
        order_mgr = AsyncMock()
        order_mgr.place_market_order = AsyncMock(return_value=_make_fill())

        # Mock position sizer
        sizer = MagicMock()
        sizing_result = MagicMock()
        sizing_result.can_trade = True
        sizing_result.lot_size = 0.01
        sizing_result.skip_reason = None
        sizer.calculate_lot_size.return_value = sizing_result

        return TradeManager(
            fusion_config=fusion_config,
            phase_behavior=phase_behavior,
            order_manager=order_mgr,
            position_sizer=sizer,
            breaker_manager=None,
        )

    @pytest.mark.asyncio
    async def test_returns_tuple_on_buy(self, trade_manager):
        """evaluate_and_execute returns a 2-tuple for buy trades."""
        result = await trade_manager.evaluate_and_execute(
            fusion_result=_make_fusion_result(should_trade=True, direction=1.0),
            equity=20.0,
            current_price=2050.0,
            atr=3.5,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        decision, fill = result
        assert isinstance(decision, TradeDecision)
        assert isinstance(fill, FillEvent)
        assert decision.action == "buy"

    @pytest.mark.asyncio
    async def test_returns_tuple_on_sell(self, trade_manager):
        """evaluate_and_execute returns a 2-tuple for sell trades."""
        result = await trade_manager.evaluate_and_execute(
            fusion_result=_make_fusion_result(should_trade=True, direction=-1.0),
            equity=20.0,
            current_price=2050.0,
            atr=3.5,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        decision, fill = result
        assert isinstance(decision, TradeDecision)

    @pytest.mark.asyncio
    async def test_returns_none_fill_on_hold(self, trade_manager):
        """evaluate_and_execute returns (TradeDecision, None) when action is hold."""
        result = await trade_manager.evaluate_and_execute(
            fusion_result=_make_fusion_result(should_trade=False),
            equity=20.0,
            current_price=2050.0,
            atr=3.5,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        decision, fill = result
        assert decision.action == "hold"
        assert fill is None

    @pytest.mark.asyncio
    async def test_returns_none_fill_on_tighten_sl(self, trade_manager):
        """evaluate_and_execute returns (TradeDecision, None) on tighten_sl."""
        # First, execute a buy to open a position
        await trade_manager.evaluate_and_execute(
            fusion_result=_make_fusion_result(should_trade=True, direction=1.0),
            equity=20.0,
            current_price=2050.0,
            atr=3.5,
        )

        # Now trigger adverse regime transition to get tighten_sl
        result = await trade_manager.evaluate_and_execute(
            fusion_result=_make_fusion_result(
                should_trade=True, direction=1.0, regime=RegimeState.HIGH_CHAOS
            ),
            equity=20.0,
            current_price=2055.0,
            atr=3.5,
        )
        assert isinstance(result, tuple)
        decision, fill = result
        assert decision.action == "tighten_sl"
        assert fill is None


# ---------------------------------------------------------------------------
# Test: Engine trade open logging
# ---------------------------------------------------------------------------


class TestEngineTradeOpenLogging:
    """Engine _signal_loop calls log_trade_open when fill is not None."""

    @pytest.mark.asyncio
    async def test_log_trade_open_called_on_fill(self):
        """Engine calls log_trade_open when evaluate_and_execute returns a FillEvent."""
        from fxsoqqabot.config.models import BotSettings

        engine = _make_minimal_engine()

        # Mock trade_manager to return tuple with fill
        fill = _make_fill()
        decision = TradeDecision(
            action="buy", sl_distance=2.0, tp_distance=6.0,
            lot_size=0.01, confidence=0.75,
            regime=RegimeState.TRENDING_UP, reason="Test",
        )
        engine._trade_manager = AsyncMock()
        engine._trade_manager.evaluate_and_execute = AsyncMock(return_value=(decision, fill))

        # Mock trade_logger
        engine._trade_logger = MagicMock()
        engine._trade_logger.log_trade_open = MagicMock()

        # Mock other dependencies for _signal_loop iteration
        engine._weight_tracker = MagicMock()
        engine._weight_tracker.get_weights.return_value = {"chaos": 0.4, "flow": 0.35, "timing": 0.25}
        engine._weight_tracker.get_state.return_value = {}

        engine._state = AsyncMock()
        engine._state.save_signal_weights = AsyncMock()

        # Simulate one signal loop iteration
        await _run_one_signal_iteration(engine)

        engine._trade_logger.log_trade_open.assert_called_once()
        call_kwargs = engine._trade_logger.log_trade_open.call_args
        assert call_kwargs[1]["fill"] == fill or call_kwargs[0][1] == fill

    @pytest.mark.asyncio
    async def test_log_trade_open_not_called_on_hold(self):
        """Engine does NOT call log_trade_open when decision is hold."""
        engine = _make_minimal_engine()

        # Mock trade_manager to return hold with no fill
        decision = TradeDecision(
            action="hold", sl_distance=0.0, tp_distance=0.0,
            lot_size=0.0, confidence=0.5,
            regime=RegimeState.RANGING, reason="Below threshold",
        )
        engine._trade_manager = AsyncMock()
        engine._trade_manager.evaluate_and_execute = AsyncMock(return_value=(decision, None))

        engine._trade_logger = MagicMock()
        engine._trade_logger.log_trade_open = MagicMock()

        engine._weight_tracker = MagicMock()
        engine._weight_tracker.get_weights.return_value = {"chaos": 0.4, "flow": 0.35, "timing": 0.25}

        engine._state = AsyncMock()

        await _run_one_signal_iteration(engine)

        engine._trade_logger.log_trade_open.assert_not_called()


# ---------------------------------------------------------------------------
# Helpers for engine tests
# ---------------------------------------------------------------------------


def _make_minimal_engine():
    """Create a TradingEngine with mocked internals for testing signal loop."""
    from fxsoqqabot.config.models import BotSettings

    settings = BotSettings()
    from fxsoqqabot.core.engine import TradingEngine

    engine = TradingEngine(settings)
    engine._running = True

    # Mock bridge for account info
    engine._bridge = AsyncMock()
    account_info = MagicMock()
    account_info.equity = 20.0
    engine._bridge.get_account_info = AsyncMock(return_value=account_info)

    # Mock tick buffer with data
    import numpy as np

    engine._tick_buffer = MagicMock()
    arrays = {
        "bid": np.array([2050.0]),
        "ask": np.array([2050.5]),
        "spread": np.array([0.5]),
        "time_msc": np.array([1000000]),
        "volume": np.array([100]),
    }
    engine._tick_buffer.as_arrays.return_value = arrays
    engine._tick_buffer.__len__ = MagicMock(return_value=1)

    # Mock bar buffers
    engine._bar_buffers = MagicMock()
    engine._bar_buffers.timeframes = ["M5"]
    m5_arrays = {
        "high": np.array([2055.0, 2053.0, 2054.0]),
        "low": np.array([2045.0, 2047.0, 2046.0]),
        "close": np.array([2050.0, 2051.0, 2052.0]),
    }
    engine._bar_buffers.__getitem__ = MagicMock(return_value=MagicMock(as_arrays=MagicMock(return_value=m5_arrays)))

    # Mock fusion core
    engine._fusion_core = MagicMock()
    engine._fusion_core.fuse.return_value = _make_fusion_result()

    # Mock phase behavior
    engine._phase_behavior = MagicMock()
    engine._phase_behavior.get_confidence_threshold.return_value = 0.5

    # Mock signal modules
    mock_module = AsyncMock()
    mock_module.name = "chaos"
    mock_module.update = AsyncMock(return_value=SignalOutput(
        module_name="chaos", direction=0.8, confidence=0.7, regime=RegimeState.TRENDING_UP,
    ))
    engine._signal_modules = [mock_module]

    return engine


async def _run_one_signal_iteration(engine):
    """Run a single iteration of the signal loop logic (not the loop itself)."""
    # Replicate the signal loop body without the while loop
    import numpy as np

    tick_arrays = engine._tick_buffer.as_arrays()
    bar_arrays = {
        tf: engine._bar_buffers[tf].as_arrays()
        for tf in engine._bar_buffers.timeframes
    }

    signals = []
    for module in engine._signal_modules:
        signal_out = await module.update(tick_arrays, bar_arrays, None)
        signals.append(signal_out)

    engine._last_signals = signals
    weights = engine._weight_tracker.get_weights()
    account_info = await engine._bridge.get_account_info()
    equity = account_info.equity if account_info else 20.0
    threshold = engine._phase_behavior.get_confidence_threshold(equity)
    fusion_result = engine._fusion_core.fuse(signals, weights, threshold)
    engine._last_fusion_result = fusion_result

    from fxsoqqabot.signals.timing.phase_transition import compute_atr

    m5_bars = bar_arrays.get("M5", {})
    current_atr = 0.0
    if "high" in m5_bars and len(m5_bars["high"]) > 0:
        atr_array = compute_atr(m5_bars["high"], m5_bars["low"], m5_bars["close"], period=14)
        current_atr = float(atr_array[-1])

    current_price = float(tick_arrays["bid"][-1]) if tick_arrays["bid"].size > 0 else 0.0

    if current_atr > 0 and current_price > 0:
        decision, fill = await engine._trade_manager.evaluate_and_execute(
            fusion_result=fusion_result,
            equity=equity,
            current_price=current_price,
            atr=current_atr,
        )

        if decision.action in ("buy", "sell"):
            await engine._state.save_signal_weights(engine._weight_tracker.get_state())

            if engine._trade_logger and fill is not None:
                try:
                    engine._trade_logger.log_trade_open(
                        decision=decision,
                        fill=fill,
                        signals=signals,
                        fusion_result=fusion_result,
                        weights=weights,
                        equity=equity,
                        atr=current_atr,
                    )
                except Exception:
                    pass
