"""Tests for the async MT5 bridge wrapper.

All tests mock the MetaTrader5 module -- no live MT5 connection needed.
Tests verify:
- Single-threaded executor for MT5 safety (Pitfall 2)
- Connection lifecycle (initialize, ensure_connected, reconnect)
- Data retrieval methods wrapped in asyncio
- Order methods with pre-validation
- Exponential backoff reconnection per D-06
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from fxsoqqabot.config.models import ExecutionConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def exec_config():
    """ExecutionConfig with test values."""
    return ExecutionConfig(
        symbol="XAUUSD",
        mt5_path=r"C:\MT5\terminal64.exe",
        mt5_login=12345,
        mt5_password="secret",
        mt5_server="RoboForex-ECN",
    )


@pytest.fixture
def exec_config_minimal():
    """ExecutionConfig with no MT5 credentials (defaults)."""
    return ExecutionConfig()


# ---------------------------------------------------------------------------
# Test: __init__ creates single-threaded executor
# ---------------------------------------------------------------------------


class TestMT5BridgeInit:
    """MT5Bridge initialization tests."""

    def test_creates_single_thread_executor(self, exec_config):
        """MT5Bridge must use ThreadPoolExecutor(max_workers=1) per Pitfall 2."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        bridge = MT5Bridge(exec_config)
        assert isinstance(bridge._executor, ThreadPoolExecutor)
        assert bridge._executor._max_workers == 1

    def test_starts_disconnected(self, exec_config):
        """Bridge starts in disconnected state."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        bridge = MT5Bridge(exec_config)
        assert bridge.connected is False

    def test_exposes_config(self, exec_config):
        """Bridge exposes its config."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        bridge = MT5Bridge(exec_config)
        assert bridge.config is exec_config


# ---------------------------------------------------------------------------
# Test: connect()
# ---------------------------------------------------------------------------


class TestMT5BridgeConnect:
    """MT5Bridge.connect() tests."""

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_connect_success(self, mock_mt5, exec_config):
        """connect() calls mt5.initialize with config kwargs and returns True."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_mt5.initialize.return_value = True
        terminal_info = SimpleNamespace(connected=True, name="MT5")
        mock_mt5.terminal_info.return_value = terminal_info

        bridge = MT5Bridge(exec_config)
        result = await bridge.connect()

        assert result is True
        assert bridge.connected is True
        mock_mt5.initialize.assert_called_once()
        call_kwargs = mock_mt5.initialize.call_args
        assert call_kwargs[1].get("path") == exec_config.mt5_path
        assert call_kwargs[1].get("login") == exec_config.mt5_login
        assert call_kwargs[1].get("password") == exec_config.mt5_password
        assert call_kwargs[1].get("server") == exec_config.mt5_server

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_connect_failure(self, mock_mt5, exec_config):
        """connect() returns False and logs error when mt5.initialize fails."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_mt5.initialize.return_value = False
        mock_mt5.last_error.return_value = (-1, "Connection failed")

        bridge = MT5Bridge(exec_config)
        result = await bridge.connect()

        assert result is False
        assert bridge.connected is False

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_connect_minimal_config(self, mock_mt5, exec_config_minimal):
        """connect() with no credentials only passes non-None kwargs."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = SimpleNamespace(connected=True)

        bridge = MT5Bridge(exec_config_minimal)
        await bridge.connect()

        call_kwargs = mock_mt5.initialize.call_args[1]
        # None values should NOT be passed to mt5.initialize
        assert "login" not in call_kwargs
        assert "password" not in call_kwargs
        assert "server" not in call_kwargs
        assert "path" not in call_kwargs


# ---------------------------------------------------------------------------
# Test: ensure_connected()
# ---------------------------------------------------------------------------


class TestMT5BridgeEnsureConnected:
    """MT5Bridge.ensure_connected() tests."""

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_ensure_connected_when_connected(self, mock_mt5, exec_config):
        """ensure_connected() returns True when terminal_info shows connected."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_mt5.terminal_info.return_value = SimpleNamespace(connected=True)

        bridge = MT5Bridge(exec_config)
        bridge._connected = True
        result = await bridge.ensure_connected()

        assert result is True

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_ensure_connected_reconnects_when_none(self, mock_mt5, exec_config):
        """ensure_connected() calls connect() when terminal_info returns None."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_mt5.terminal_info.return_value = None
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.side_effect = [None, SimpleNamespace(connected=True)]

        bridge = MT5Bridge(exec_config)
        bridge._connected = True
        result = await bridge.ensure_connected()

        # Should have attempted reconnection
        mock_mt5.initialize.assert_called_once()

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_ensure_connected_reconnects_when_disconnected(self, mock_mt5, exec_config):
        """ensure_connected() calls connect() when terminal_info.connected is False."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        disconnected_info = SimpleNamespace(connected=False)
        connected_info = SimpleNamespace(connected=True)
        mock_mt5.terminal_info.side_effect = [disconnected_info, connected_info]
        mock_mt5.initialize.return_value = True

        bridge = MT5Bridge(exec_config)
        bridge._connected = True
        result = await bridge.ensure_connected()

        mock_mt5.initialize.assert_called_once()


# ---------------------------------------------------------------------------
# Test: Data retrieval methods (all use _run_mt5)
# ---------------------------------------------------------------------------


class TestMT5BridgeDataRetrieval:
    """Data retrieval method tests."""

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_get_ticks(self, mock_mt5, exec_config):
        """get_ticks() wraps mt5.copy_ticks_from in executor."""
        from datetime import datetime, timezone

        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        fake_data = np.array(
            [(1000, 1.0, 2.0, 1.5, 100, 1000000, 1, 100.0)],
            dtype=[
                ("time", "i8"),
                ("bid", "f8"),
                ("ask", "f8"),
                ("last", "f8"),
                ("volume", "i8"),
                ("time_msc", "i8"),
                ("flags", "i4"),
                ("volume_real", "f8"),
            ],
        )
        mock_mt5.copy_ticks_from.return_value = fake_data

        bridge = MT5Bridge(exec_config)
        now = datetime.now(timezone.utc)
        result = await bridge.get_ticks("XAUUSD", now, 100)

        # COPY_TICKS_ALL is -1 in the real MT5 module; default arg captured at import
        mock_mt5.copy_ticks_from.assert_called_once_with("XAUUSD", now, 100, -1)
        assert result is fake_data

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_get_rates(self, mock_mt5, exec_config):
        """get_rates() wraps mt5.copy_rates_from in executor."""
        from datetime import datetime, timezone

        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        fake_data = np.array(
            [(1000, 1.0, 2.0, 0.5, 1.5, 500, 10, 0)],
            dtype=[
                ("time", "i8"),
                ("open", "f8"),
                ("high", "f8"),
                ("low", "f8"),
                ("close", "f8"),
                ("tick_volume", "i8"),
                ("spread", "i4"),
                ("real_volume", "i8"),
            ],
        )
        mock_mt5.copy_rates_from.return_value = fake_data

        bridge = MT5Bridge(exec_config)
        now = datetime.now(timezone.utc)
        result = await bridge.get_rates("XAUUSD", 1, now, 100)

        mock_mt5.copy_rates_from.assert_called_once_with("XAUUSD", 1, now, 100)
        assert result is fake_data

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_get_symbol_info(self, mock_mt5, exec_config):
        """get_symbol_info() wraps mt5.symbol_info."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_info = SimpleNamespace(name="XAUUSD", bid=2000.0, ask=2000.5)
        mock_mt5.symbol_info.return_value = mock_info

        bridge = MT5Bridge(exec_config)
        result = await bridge.get_symbol_info("XAUUSD")

        mock_mt5.symbol_info.assert_called_once_with("XAUUSD")
        assert result is mock_info

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_get_symbol_tick(self, mock_mt5, exec_config):
        """get_symbol_tick() wraps mt5.symbol_info_tick."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_tick = SimpleNamespace(bid=2000.0, ask=2000.5)
        mock_mt5.symbol_info_tick.return_value = mock_tick

        bridge = MT5Bridge(exec_config)
        result = await bridge.get_symbol_tick("XAUUSD")

        mock_mt5.symbol_info_tick.assert_called_once_with("XAUUSD")
        assert result is mock_tick

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_get_positions(self, mock_mt5, exec_config):
        """get_positions() wraps mt5.positions_get."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_positions = (SimpleNamespace(ticket=1), SimpleNamespace(ticket=2))
        mock_mt5.positions_get.return_value = mock_positions

        bridge = MT5Bridge(exec_config)
        result = await bridge.get_positions(symbol="XAUUSD")

        mock_mt5.positions_get.assert_called_once_with(symbol="XAUUSD")
        assert result is mock_positions

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_get_positions_all(self, mock_mt5, exec_config):
        """get_positions() with no symbol gets all positions."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_positions = ()
        mock_mt5.positions_get.return_value = mock_positions

        bridge = MT5Bridge(exec_config)
        result = await bridge.get_positions()

        mock_mt5.positions_get.assert_called_once_with()
        assert result == ()

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_get_dom(self, mock_mt5, exec_config):
        """get_dom() calls market_book_add then market_book_get."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_mt5.market_book_add.return_value = True
        mock_entries = [
            SimpleNamespace(type=1, price=2000.0, volume=10, volume_dbl=10.0),
            SimpleNamespace(type=2, price=1999.0, volume=5, volume_dbl=5.0),
        ]
        mock_mt5.market_book_get.return_value = tuple(mock_entries)

        bridge = MT5Bridge(exec_config)
        result = await bridge.get_dom("XAUUSD")

        mock_mt5.market_book_add.assert_called_once_with("XAUUSD")
        mock_mt5.market_book_get.assert_called_once_with("XAUUSD")
        assert result is not None
        assert len(result) == 2

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_get_account_info(self, mock_mt5, exec_config):
        """get_account_info() wraps mt5.account_info."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_account = SimpleNamespace(balance=20.0, equity=20.0, margin=0.0)
        mock_mt5.account_info.return_value = mock_account

        bridge = MT5Bridge(exec_config)
        result = await bridge.get_account_info()

        mock_mt5.account_info.assert_called_once()
        assert result is mock_account


# ---------------------------------------------------------------------------
# Test: Order methods
# ---------------------------------------------------------------------------


class TestMT5BridgeOrders:
    """Order method tests."""

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_order_send_success(self, mock_mt5, exec_config):
        """order_send() calls order_send on the MT5 module."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_result = SimpleNamespace(retcode=10009, order=123456)
        mock_mt5.order_send.return_value = mock_result

        bridge = MT5Bridge(exec_config)
        request = {"action": 1, "symbol": "XAUUSD", "volume": 0.01}
        result = await bridge.order_send(request)

        mock_mt5.order_send.assert_called_once_with(request)
        assert result is mock_result

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_order_check(self, mock_mt5, exec_config):
        """order_check() wraps mt5.order_check."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_check = SimpleNamespace(retcode=0, comment="Done")
        mock_mt5.order_check.return_value = mock_check

        bridge = MT5Bridge(exec_config)
        request = {"action": 1, "symbol": "XAUUSD", "volume": 0.01}
        result = await bridge.order_check(request)

        mock_mt5.order_check.assert_called_once_with(request)
        assert result is mock_check

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_last_error(self, mock_mt5, exec_config):
        """last_error() wraps mt5.last_error."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_mt5.last_error.return_value = (0, "No error")

        bridge = MT5Bridge(exec_config)
        result = await bridge.last_error()

        mock_mt5.last_error.assert_called_once()
        assert result == (0, "No error")


# ---------------------------------------------------------------------------
# Test: shutdown()
# ---------------------------------------------------------------------------


class TestMT5BridgeShutdown:
    """MT5Bridge.shutdown() tests."""

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_shutdown(self, mock_mt5, exec_config):
        """shutdown() calls mt5.shutdown and marks disconnected."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        bridge = MT5Bridge(exec_config)
        bridge._connected = True
        await bridge.shutdown()

        mock_mt5.shutdown.assert_called_once()
        assert bridge.connected is False


# ---------------------------------------------------------------------------
# Test: reconnect_loop() -- exponential backoff per D-06
# ---------------------------------------------------------------------------


class TestMT5BridgeReconnect:
    """Reconnection with exponential backoff tests."""

    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_reconnect_loop_success_first_try(self, mock_mt5, exec_config):
        """reconnect_loop() returns True when connect succeeds on first attempt."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = SimpleNamespace(connected=True)

        bridge = MT5Bridge(exec_config)
        result = await bridge.reconnect_loop(max_retries=5)

        assert result is True
        assert mock_mt5.initialize.call_count == 1

    @patch("fxsoqqabot.execution.mt5_bridge.asyncio_sleep")
    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_reconnect_loop_exponential_backoff(
        self, mock_mt5, mock_sleep, exec_config
    ):
        """reconnect_loop() uses exponential backoff: 1s, 2s, 4s..."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        # Fail first 3, succeed on 4th
        mock_mt5.initialize.side_effect = [False, False, False, True]
        mock_mt5.last_error.return_value = (-1, "Failed")
        mock_mt5.terminal_info.return_value = SimpleNamespace(connected=True)

        bridge = MT5Bridge(exec_config)
        result = await bridge.reconnect_loop(max_retries=5)

        assert result is True
        assert mock_mt5.initialize.call_count == 4
        # Check backoff delays: 1.0, 2.0, 4.0
        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [1.0, 2.0, 4.0]

    @patch("fxsoqqabot.execution.mt5_bridge.asyncio_sleep")
    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_reconnect_loop_max_retries_exhausted(
        self, mock_mt5, mock_sleep, exec_config
    ):
        """reconnect_loop() returns False when max_retries exhausted."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        mock_mt5.initialize.return_value = False
        mock_mt5.last_error.return_value = (-1, "Failed")

        bridge = MT5Bridge(exec_config)
        result = await bridge.reconnect_loop(max_retries=3)

        assert result is False
        assert mock_mt5.initialize.call_count == 3

    @patch("fxsoqqabot.execution.mt5_bridge.asyncio_sleep")
    @patch("fxsoqqabot.execution.mt5_bridge.mt5")
    async def test_reconnect_loop_backoff_capped_at_60s(
        self, mock_mt5, mock_sleep, exec_config
    ):
        """reconnect_loop() caps backoff delay at 60 seconds."""
        from fxsoqqabot.execution.mt5_bridge import MT5Bridge

        # Fail 8 times (1, 2, 4, 8, 16, 32, 60, 60), succeed on 9th
        side_effects = [False] * 8 + [True]
        mock_mt5.initialize.side_effect = side_effects
        mock_mt5.last_error.return_value = (-1, "Failed")
        mock_mt5.terminal_info.return_value = SimpleNamespace(connected=True)

        bridge = MT5Bridge(exec_config)
        result = await bridge.reconnect_loop(max_retries=10)

        assert result is True
        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        # Backoff: 1, 2, 4, 8, 16, 32, 60, 60 (capped at 60)
        assert sleep_calls == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]
