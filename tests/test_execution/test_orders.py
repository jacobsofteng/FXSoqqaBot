"""Tests for the OrderManager order execution layer.

Tests verify:
- Server-side SL always in initial request (RISK-01)
- order_check called BEFORE order_send (pre-validation)
- Dynamic fill mode from symbol_info (Pitfall 3)
- Slippage tracking (fill_price - requested_price) per RISK-03
- Paper mode routes to PaperExecutor instead of MT5 (D-01)
- Live mode routes to MT5 order_send
- Stops level validation (Pitfall 4)
- Spread logging at entry (RISK-03)
- Close position sends opposite order type
- close_all_positions iterates and closes all (D-05)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from fxsoqqabot.config.models import ExecutionConfig
from fxsoqqabot.core.events import FillEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# MT5 constants (replicated for test without importing mt5)
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
TRADE_ACTION_DEAL = 1
ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2
ORDER_TIME_GTC = 0
TRADE_RETCODE_DONE = 10009


@pytest.fixture
def exec_config_live():
    """ExecutionConfig in live mode."""
    return ExecutionConfig(
        symbol="XAUUSD",
        magic_number=20260327,
        deviation=20,
        mode="live",
    )


@pytest.fixture
def exec_config_paper():
    """ExecutionConfig in paper mode."""
    return ExecutionConfig(
        symbol="XAUUSD",
        magic_number=20260327,
        deviation=20,
        mode="paper",
    )


@pytest.fixture
def mock_bridge():
    """Mock MT5Bridge with common responses."""
    bridge = AsyncMock()
    # Default tick
    bridge.get_symbol_tick.return_value = SimpleNamespace(
        bid=2950.0, ask=2950.50
    )
    # Default symbol info with FOK filling, stops_level=50, point=0.01
    bridge.get_symbol_info.return_value = SimpleNamespace(
        filling_mode=1,  # FOK bit set
        trade_stops_level=50,
        point=0.01,
    )
    return bridge


@pytest.fixture
def mock_paper_executor():
    """Mock PaperExecutor."""
    executor = MagicMock()
    executor.simulate_fill.return_value = FillEvent(
        ticket=1000000,
        symbol="XAUUSD",
        action="buy",
        volume=0.01,
        fill_price=2950.52,
        requested_price=2950.50,
        slippage=0.02,
        sl=2948.0,
        tp=None,
        magic=20260327,
        is_paper=True,
    )
    executor.simulate_close.return_value = FillEvent(
        ticket=1000000,
        symbol="XAUUSD",
        action="close",
        volume=0.01,
        fill_price=2951.0,
        requested_price=2950.0,
        slippage=1.0,
        sl=2948.0,
        tp=None,
        magic=20260327,
        is_paper=True,
    )
    return executor


# ---------------------------------------------------------------------------
# Test: Request dict construction with server-side SL (RISK-01)
# ---------------------------------------------------------------------------


class TestOrderRequestConstruction:
    """Verify order request dict is built correctly."""

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_place_market_order_includes_sl_in_request(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """place_market_order includes sl field in request dict per RISK-01."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        mock_bridge.order_check.return_value = SimpleNamespace(
            retcode=0, comment="Done"
        )
        mock_bridge.order_send.return_value = SimpleNamespace(
            retcode=TRADE_RETCODE_DONE, order=123456,
            price=2950.50, volume=0.01,
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        await mgr.place_market_order("buy", 0.01, sl_price=2948.0)

        # Verify SL is in the request dict passed to order_check
        check_request = mock_bridge.order_check.call_args[0][0]
        assert "sl" in check_request
        assert check_request["sl"] == 2948.0

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_place_market_order_builds_correct_buy_request(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """Buy order builds request with TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ask price."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        mock_bridge.order_check.return_value = SimpleNamespace(retcode=0, comment="Done")
        mock_bridge.order_send.return_value = SimpleNamespace(
            retcode=TRADE_RETCODE_DONE, order=123, price=2950.50, volume=0.01,
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        await mgr.place_market_order("buy", 0.01, sl_price=2948.0)

        request = mock_bridge.order_check.call_args[0][0]
        assert request["action"] == TRADE_ACTION_DEAL
        assert request["type"] == ORDER_TYPE_BUY
        assert request["price"] == 2950.50  # ask
        assert request["symbol"] == "XAUUSD"
        assert request["volume"] == 0.01
        assert request["sl"] == 2948.0


# ---------------------------------------------------------------------------
# Test: Pre-validation flow (order_check before order_send)
# ---------------------------------------------------------------------------


class TestPreValidation:
    """order_check must be called BEFORE order_send."""

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_order_check_called_before_order_send(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """place_market_order calls order_check BEFORE order_send."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        call_order = []
        mock_bridge.order_check.side_effect = lambda r: (
            call_order.append("check") or SimpleNamespace(retcode=0, comment="Ok")
        )
        mock_bridge.order_send.side_effect = lambda r: (
            call_order.append("send") or SimpleNamespace(
                retcode=TRADE_RETCODE_DONE, order=1, price=2950.50, volume=0.01,
            )
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        await mgr.place_market_order("buy", 0.01, sl_price=2948.0)

        assert call_order == ["check", "send"]

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_returns_none_when_order_check_fails(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """place_market_order returns None when order_check retcode != 0."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        mock_bridge.order_check.return_value = SimpleNamespace(
            retcode=10013, comment="Invalid request"
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        result = await mgr.place_market_order("buy", 0.01, sl_price=2948.0)

        assert result is None
        mock_bridge.order_send.assert_not_called()

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_returns_none_when_order_check_is_none(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """place_market_order returns None when order_check returns None."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        mock_bridge.order_check.return_value = None
        mock_bridge.last_error.return_value = (-1, "Error")

        mgr = OrderManager(mock_bridge, exec_config_live)
        result = await mgr.place_market_order("buy", 0.01, sl_price=2948.0)

        assert result is None

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_returns_none_when_order_send_fails(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """place_market_order returns None when order_send retcode != TRADE_RETCODE_DONE."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        mock_bridge.order_check.return_value = SimpleNamespace(retcode=0, comment="Ok")
        mock_bridge.order_send.return_value = SimpleNamespace(
            retcode=10004, comment="Requote"
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        result = await mgr.place_market_order("buy", 0.01, sl_price=2948.0)

        assert result is None


# ---------------------------------------------------------------------------
# Test: Slippage tracking (RISK-03)
# ---------------------------------------------------------------------------


class TestSlippageTracking:
    """Slippage = fill_price - requested_price per RISK-03."""

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_fill_event_contains_slippage(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """place_market_order returns FillEvent with slippage = fill_price - requested_price."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        mock_bridge.order_check.return_value = SimpleNamespace(retcode=0, comment="Ok")
        # Filled at 2950.55 instead of requested 2950.50 (ask)
        mock_bridge.order_send.return_value = SimpleNamespace(
            retcode=TRADE_RETCODE_DONE, order=123, price=2950.55, volume=0.01,
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        fill = await mgr.place_market_order("buy", 0.01, sl_price=2948.0)

        assert fill is not None
        assert fill.slippage == pytest.approx(0.05)  # 2950.55 - 2950.50
        assert fill.fill_price == 2950.55
        assert fill.requested_price == 2950.50


# ---------------------------------------------------------------------------
# Test: Dynamic fill mode (Pitfall 3)
# ---------------------------------------------------------------------------


class TestDynamicFillMode:
    """Fill mode determined from symbol_info.filling_mode at runtime."""

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_determine_filling_mode_fok(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """_determine_filling_mode returns FOK when FOK bit set."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN

        mock_bridge.get_symbol_info.return_value = SimpleNamespace(
            filling_mode=1,  # FOK bit
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        mode = await mgr._determine_filling_mode("XAUUSD")
        assert mode == ORDER_FILLING_FOK

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_determine_filling_mode_ioc(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """_determine_filling_mode returns IOC when only IOC bit set."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN

        mock_bridge.get_symbol_info.return_value = SimpleNamespace(
            filling_mode=2,  # IOC bit only
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        mode = await mgr._determine_filling_mode("XAUUSD")
        assert mode == ORDER_FILLING_IOC

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_determine_filling_mode_return(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """_determine_filling_mode returns RETURN when neither FOK nor IOC."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN

        mock_bridge.get_symbol_info.return_value = SimpleNamespace(
            filling_mode=4,  # RETURN bit
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        mode = await mgr._determine_filling_mode("XAUUSD")
        assert mode == ORDER_FILLING_RETURN

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_determine_filling_mode_cached(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """_determine_filling_mode caches result after first call."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN

        mock_bridge.get_symbol_info.return_value = SimpleNamespace(filling_mode=1)

        mgr = OrderManager(mock_bridge, exec_config_live)
        await mgr._determine_filling_mode("XAUUSD")
        await mgr._determine_filling_mode("XAUUSD")
        # Only called once due to caching
        assert mock_bridge.get_symbol_info.call_count == 1


# ---------------------------------------------------------------------------
# Test: Stops level validation (Pitfall 4)
# ---------------------------------------------------------------------------


class TestStopsLevelValidation:
    """SL distance must respect broker minimum stops_level."""

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_validates_sl_respects_stops_level(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """place_market_order returns None when SL too close per stops_level."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        # stops_level=50 * point=0.01 = min_distance=0.50
        mock_bridge.get_symbol_info.return_value = SimpleNamespace(
            filling_mode=1, trade_stops_level=50, point=0.01,
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        # SL at 2950.40, price at 2950.50 -> distance = 0.10 < 0.50
        result = await mgr.place_market_order("buy", 0.01, sl_price=2950.40)

        assert result is None
        mock_bridge.order_check.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Paper mode routing (D-01)
# ---------------------------------------------------------------------------


class TestPaperModeRouting:
    """Paper mode routes to PaperExecutor instead of MT5."""

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_paper_mode_delegates_to_paper_executor(
        self, mock_mt5, mock_bridge, exec_config_paper, mock_paper_executor
    ):
        """When mode=='paper', place_market_order delegates to PaperExecutor."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        mgr = OrderManager(mock_bridge, exec_config_paper, mock_paper_executor)
        fill = await mgr.place_market_order("buy", 0.01, sl_price=2948.0)

        assert fill is not None
        assert fill.is_paper is True
        mock_paper_executor.simulate_fill.assert_called_once()
        # order_send should NOT be called in paper mode
        mock_bridge.order_send.assert_not_called()

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_live_mode_uses_mt5_order_send(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """When mode=='live', place_market_order uses MT5 order_send."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        mock_bridge.order_check.return_value = SimpleNamespace(retcode=0, comment="Ok")
        mock_bridge.order_send.return_value = SimpleNamespace(
            retcode=TRADE_RETCODE_DONE, order=123, price=2950.50, volume=0.01,
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        fill = await mgr.place_market_order("buy", 0.01, sl_price=2948.0)

        assert fill is not None
        assert fill.is_paper is False
        mock_bridge.order_send.assert_called_once()


# ---------------------------------------------------------------------------
# Test: Spread logging (RISK-03)
# ---------------------------------------------------------------------------


class TestSpreadLogging:
    """Spread at entry time must be logged per RISK-03."""

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_place_market_order_logs_spread(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """place_market_order logs spread at entry time per RISK-03."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        mock_bridge.order_check.return_value = SimpleNamespace(retcode=0, comment="Ok")
        mock_bridge.order_send.return_value = SimpleNamespace(
            retcode=TRADE_RETCODE_DONE, order=123, price=2950.50, volume=0.01,
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        # Test that this call doesn't error -- spread logging is internal
        fill = await mgr.place_market_order("buy", 0.01, sl_price=2948.0)
        assert fill is not None


# ---------------------------------------------------------------------------
# Test: close_position
# ---------------------------------------------------------------------------


class TestClosePosition:
    """close_position sends opposite order type."""

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_close_position_sends_opposite_type(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """close_position sends TRADE_ACTION_DEAL with opposite order type and correct volume."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        mock_bridge.order_send.return_value = SimpleNamespace(
            retcode=TRADE_RETCODE_DONE, order=123, price=2950.0, volume=0.01,
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        fill = await mgr.close_position(
            ticket=12345, symbol="XAUUSD", volume=0.01,
            position_type=ORDER_TYPE_BUY,
        )

        assert fill is not None
        request = mock_bridge.order_send.call_args[0][0]
        assert request["type"] == ORDER_TYPE_SELL  # Opposite of BUY
        assert request["volume"] == 0.01
        assert request["position"] == 12345
        assert request["action"] == TRADE_ACTION_DEAL


# ---------------------------------------------------------------------------
# Test: close_all_positions (D-05)
# ---------------------------------------------------------------------------


class TestCloseAllPositions:
    """close_all_positions iterates positions and closes each."""

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_close_all_positions(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """close_all_positions iterates positions_get and closes each one per D-05."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        mock_mt5.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        mock_mt5.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        mock_mt5.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        mock_mt5.ORDER_TIME_GTC = ORDER_TIME_GTC

        # Two open positions
        mock_bridge.get_positions.return_value = (
            SimpleNamespace(ticket=1, symbol="XAUUSD", volume=0.01, type=ORDER_TYPE_BUY),
            SimpleNamespace(ticket=2, symbol="XAUUSD", volume=0.02, type=ORDER_TYPE_SELL),
        )
        mock_bridge.order_send.return_value = SimpleNamespace(
            retcode=TRADE_RETCODE_DONE, order=999, price=2950.0, volume=0.01,
        )

        mgr = OrderManager(mock_bridge, exec_config_live)
        results = await mgr.close_all_positions()

        assert len(results) == 2
        assert mock_bridge.order_send.call_count == 2

    @patch("fxsoqqabot.execution.orders.mt5")
    async def test_close_all_positions_empty(
        self, mock_mt5, mock_bridge, exec_config_live
    ):
        """close_all_positions returns empty list when no positions open."""
        from fxsoqqabot.execution.orders import OrderManager

        mock_bridge.get_positions.return_value = None

        mgr = OrderManager(mock_bridge, exec_config_live)
        results = await mgr.close_all_positions()

        assert results == []
