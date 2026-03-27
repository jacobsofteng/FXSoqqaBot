"""Async wrapper around the blocking MetaTrader5 package.

CRITICAL: Uses ThreadPoolExecutor(max_workers=1) to serialize all MT5 calls.
The MT5 package uses global internal state and is NOT thread-safe (Pitfall 2).
All calls are routed through a single-thread executor via run_in_executor.

Connection lifecycle:
- connect() initializes MT5 with credentials from ExecutionConfig
- ensure_connected() checks terminal_info and reconnects if needed
- reconnect_loop() retries indefinitely with exponential backoff per D-06
- shutdown() cleans up MT5 and executor resources
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import MetaTrader5 as mt5
import structlog

from fxsoqqabot.config.models import ExecutionConfig

# Alias asyncio.sleep so tests can mock it for backoff verification
asyncio_sleep = asyncio.sleep

logger = structlog.get_logger()


class MT5Bridge:
    """Async wrapper around the blocking MetaTrader5 package.

    CRITICAL: Uses ThreadPoolExecutor(max_workers=1) to serialize all MT5 calls.
    The MT5 package uses global internal state and is NOT thread-safe (Pitfall 2).
    """

    def __init__(self, config: ExecutionConfig) -> None:
        self._config = config
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5")
        self._connected = False
        self._logger = structlog.get_logger().bind(component="mt5_bridge")

    # -- Properties ----------------------------------------------------------

    @property
    def connected(self) -> bool:
        """Whether the bridge believes it is connected to MT5."""
        return self._connected

    @property
    def config(self) -> ExecutionConfig:
        """The execution configuration this bridge was created with."""
        return self._config

    # -- Internal executor wrapper -------------------------------------------

    async def _run_mt5(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking MT5 function in the dedicated single-thread executor.

        All MT5 API calls must go through this method to ensure serialized
        access (Pitfall 2) and non-blocking async behavior (Pitfall 3).
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, lambda: func(*args, **kwargs)
        )

    # -- Connection lifecycle ------------------------------------------------

    async def connect(self) -> bool:
        """Initialize MT5 connection.

        Builds kwargs from ExecutionConfig, only passing non-None values.
        Returns True on success, False on failure (logs error via Pitfall 1).
        """
        kwargs: dict[str, Any] = {}
        if self._config.mt5_path is not None:
            kwargs["path"] = self._config.mt5_path
        if self._config.mt5_login is not None:
            kwargs["login"] = self._config.mt5_login
        if self._config.mt5_password is not None:
            kwargs["password"] = self._config.mt5_password
        if self._config.mt5_server is not None:
            kwargs["server"] = self._config.mt5_server

        result = await self._run_mt5(mt5.initialize, **kwargs)
        if not result:
            error = await self._run_mt5(mt5.last_error)
            self._logger.error(
                "mt5_init_failed",
                error_code=error[0],
                error_msg=error[1],
            )
            return False

        # Verify terminal is actually connected
        info = await self._run_mt5(mt5.terminal_info)
        if info is None or not info.connected:
            self._logger.error("mt5_terminal_not_connected")
            return False

        self._connected = True
        self._logger.info("mt5_connected")
        return True

    async def ensure_connected(self) -> bool:
        """Check MT5 connection health, reconnect if needed.

        Uses terminal_info() to check connection state.
        If disconnected, attempts a single reconnection via connect().
        """
        info = await self._run_mt5(mt5.terminal_info)
        if info is None or not info.connected:
            self._logger.warning("mt5_connection_lost", reconnecting=True)
            self._connected = False
            return await self.connect()
        return True

    async def reconnect_loop(self, max_retries: int = 0) -> bool:
        """Retry connection with exponential backoff per D-06.

        Args:
            max_retries: Maximum number of retries. 0 means infinite retries.

        Returns:
            True when connection is re-established, False if max_retries exhausted.
        """
        delay = 1.0
        max_delay = 60.0
        attempts = 0

        while max_retries == 0 or attempts < max_retries:
            attempts += 1
            self._logger.info(
                "mt5_reconnect_attempt",
                attempt=attempts,
                delay=delay,
            )
            if await self.connect():
                self._logger.info("mt5_reconnected", attempts=attempts)
                return True
            await asyncio_sleep(delay)
            delay = min(delay * 2, max_delay)

        self._logger.error(
            "mt5_reconnect_exhausted",
            max_retries=max_retries,
        )
        return False

    # -- Data retrieval methods ----------------------------------------------

    async def get_ticks(
        self,
        symbol: str,
        date_from: datetime,
        count: int,
        flags: int = mt5.COPY_TICKS_ALL,
    ) -> Any:
        """Fetch tick data from MT5.

        Returns numpy structured array or None on failure.
        """
        return await self._run_mt5(
            mt5.copy_ticks_from, symbol, date_from, count, flags
        )

    async def get_rates(
        self,
        symbol: str,
        timeframe: int,
        date_from: datetime,
        count: int,
    ) -> Any:
        """Fetch bar (candlestick) data from MT5.

        Returns numpy structured array or None on failure.
        """
        return await self._run_mt5(
            mt5.copy_rates_from, symbol, timeframe, date_from, count
        )

    async def get_dom(self, symbol: str) -> Any:
        """Fetch Depth of Market (order book) data.

        Calls market_book_add() then market_book_get().
        Returns list of BookInfo or None if DOM unavailable.
        """
        await self._run_mt5(mt5.market_book_add, symbol)
        return await self._run_mt5(mt5.market_book_get, symbol)

    async def get_symbol_info(self, symbol: str) -> Any:
        """Fetch symbol information (contract specs, trading limits).

        Returns SymbolInfo or None.
        """
        return await self._run_mt5(mt5.symbol_info, symbol)

    async def get_symbol_tick(self, symbol: str) -> Any:
        """Fetch the latest tick for a symbol.

        Returns Tick or None.
        """
        return await self._run_mt5(mt5.symbol_info_tick, symbol)

    async def get_positions(self, symbol: str | None = None) -> Any:
        """Fetch open positions, optionally filtered by symbol.

        Returns tuple of TradePosition or None.
        """
        if symbol is not None:
            return await self._run_mt5(mt5.positions_get, symbol=symbol)
        return await self._run_mt5(mt5.positions_get)

    async def get_account_info(self) -> Any:
        """Fetch current account information (balance, equity, margin).

        Returns AccountInfo or None.
        """
        return await self._run_mt5(mt5.account_info)

    async def terminal_info(self) -> Any:
        """Fetch MT5 terminal information.

        Returns TerminalInfo or None if not connected.
        """
        return await self._run_mt5(mt5.terminal_info)

    # -- Order methods -------------------------------------------------------

    async def order_check(self, request: dict[str, Any]) -> Any:
        """Pre-validate an order request.

        Returns OrderCheckResult or None.
        """
        return await self._run_mt5(mt5.order_check, request)

    async def order_send(self, request: dict[str, Any]) -> Any:
        """Send an order to MT5.

        Note: Does NOT pre-validate here -- that's the caller's job in orders.py.
        Returns OrderSendResult or None.
        """
        return await self._run_mt5(mt5.order_send, request)

    async def last_error(self) -> tuple[int, str]:
        """Get the last MT5 error code and message.

        Returns (error_code, error_message) tuple.
        """
        return await self._run_mt5(mt5.last_error)

    # -- Cleanup -------------------------------------------------------------

    async def shutdown(self) -> None:
        """Clean shutdown: close MT5 connection and executor.

        Call this before application exit.
        """
        try:
            await self._run_mt5(mt5.shutdown)
        except Exception:
            self._logger.warning("mt5_shutdown_error", exc_info=True)
        self._executor.shutdown(wait=False)
        self._connected = False
        self._logger.info("mt5_bridge_shutdown")
