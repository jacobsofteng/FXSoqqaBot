"""Order execution layer: market order placement with risk validation.

Key safety rules:
- Server-side SL always included in initial order request (RISK-01)
- order_check always called before order_send (anti-pattern guidance)
- Filling mode determined dynamically from symbol_info (Pitfall 3)
- Paper mode routes through PaperExecutor instead of MT5 (D-01)
- Same code path for paper and live up to the execution point
- Slippage tracked as fill_price - requested_price (RISK-03)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import MetaTrader5 as mt5
import structlog

from fxsoqqabot.config.models import ExecutionConfig
from fxsoqqabot.core.events import FillEvent

if TYPE_CHECKING:
    from fxsoqqabot.execution.mt5_bridge import MT5Bridge
    from fxsoqqabot.execution.paper import PaperExecutor

# MT5 trade return codes
TRADE_RETCODE_DONE = 10009


class OrderManager:
    """Handles order placement, modification, and closure.

    Key safety rules:
    - Server-side SL always included in initial order request (RISK-01)
    - order_check always called before order_send (anti-pattern guidance)
    - Filling mode determined dynamically from symbol_info (Pitfall 3)
    - Paper mode routes through PaperExecutor instead of MT5 (D-01)
    - Same code path for paper and live up to the execution point
    """

    def __init__(
        self,
        bridge: MT5Bridge,
        config: ExecutionConfig,
        paper_executor: PaperExecutor | None = None,
    ) -> None:
        self._bridge = bridge
        self._config = config
        self._paper_executor = paper_executor
        self._logger = structlog.get_logger().bind(component="order_manager")
        self._filling_mode: int | None = None  # Cached after first query

    async def _determine_filling_mode(self, symbol: str) -> int:
        """Query broker for supported filling mode per Pitfall 3.

        Checks symbol_info.filling_mode bitmask and selects appropriate
        filling type. Caches result after first call.
        """
        if self._filling_mode is not None:
            return self._filling_mode

        info = await self._bridge.get_symbol_info(symbol)
        if info is None:
            self._logger.warning(
                "symbol_info_unavailable_using_ioc", symbol=symbol
            )
            return mt5.ORDER_FILLING_IOC

        # Check supported modes via filling_mode bitmask.
        # NOTE: MT5 uses SYMBOL_FILLING_FOK=1, SYMBOL_FILLING_IOC=2 for bitmask checks
        # but ORDER_FILLING_FOK=0, ORDER_FILLING_IOC=1 for setting in order request.
        # The filling_mode property uses SYMBOL_FILLING_* constants as bitmask values.
        if info.filling_mode & 1:  # SYMBOL_FILLING_FOK bit
            self._filling_mode = mt5.ORDER_FILLING_FOK
        elif info.filling_mode & 2:  # SYMBOL_FILLING_IOC bit
            self._filling_mode = mt5.ORDER_FILLING_IOC
        else:
            self._filling_mode = mt5.ORDER_FILLING_RETURN

        self._logger.info(
            "filling_mode_determined", mode=self._filling_mode, symbol=symbol
        )
        return self._filling_mode

    async def _validate_stops_level(
        self, symbol: str, price: float, sl_price: float
    ) -> bool:
        """Validate SL distance respects broker minimum per Pitfall 4.

        Calculates minimum distance as stops_level * point and compares
        against actual distance between price and sl_price.
        """
        info = await self._bridge.get_symbol_info(symbol)
        if info is None:
            return False

        min_distance = info.trade_stops_level * info.point
        actual_distance = abs(price - sl_price)

        if actual_distance < min_distance:
            self._logger.warning(
                "sl_too_close",
                actual_distance=actual_distance,
                min_distance=min_distance,
                stops_level=info.trade_stops_level,
            )
            return False
        return True

    async def place_market_order(
        self,
        action: str,  # "buy" or "sell"
        volume: float,  # Lot size (e.g., 0.01)
        sl_price: float,  # Server-side stop-loss price (RISK-01: always required)
        tp_price: float | None = None,
    ) -> FillEvent | None:
        """Place market order with server-side SL.

        Routes to PaperExecutor when mode=='paper' per D-01.
        Pre-validates with order_check before order_send in live mode.

        Args:
            action: "buy" or "sell"
            volume: Lot size (e.g., 0.01 for micro lot)
            sl_price: Server-side stop-loss price (RISK-01: always required)
            tp_price: Optional take-profit price

        Returns:
            FillEvent on success, None on failure.
        """
        symbol = self._config.symbol

        # Get current market price
        tick = await self._bridge.get_symbol_tick(symbol)
        if tick is None:
            self._logger.error("no_tick_data_for_order", symbol=symbol)
            return None

        price = tick.ask if action == "buy" else tick.bid
        spread = tick.ask - tick.bid
        order_type = (
            mt5.ORDER_TYPE_BUY if action == "buy" else mt5.ORDER_TYPE_SELL
        )

        # Log spread at entry per RISK-03
        self._logger.info(
            "order_spread_at_entry",
            spread=spread,
            bid=tick.bid,
            ask=tick.ask,
        )

        # Validate stops level per Pitfall 4
        if not await self._validate_stops_level(symbol, price, sl_price):
            return None

        # Determine filling mode per Pitfall 3
        filling = await self._determine_filling_mode(symbol)

        # Build request with SL in initial request per RISK-01
        request: dict = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl_price,
            "deviation": self._config.deviation,
            "magic": self._config.magic_number,
            "comment": "fxsoqqabot",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }
        if tp_price is not None:
            request["tp"] = tp_price

        # PAPER MODE: delegate to PaperExecutor per D-01
        if self._config.mode == "paper":
            if self._paper_executor is None:
                self._logger.error("paper_executor_not_configured")
                return None
            return self._paper_executor.simulate_fill(request, tick)

        # LIVE MODE: pre-validate then execute
        check = await self._bridge.order_check(request)
        if check is None:
            error = await self._bridge.last_error()
            self._logger.error("order_check_none", error=error)
            return None
        if check.retcode != 0:
            self._logger.error(
                "order_check_failed",
                retcode=check.retcode,
                comment=check.comment,
            )
            return None

        result = await self._bridge.order_send(request)
        if result is None or result.retcode != TRADE_RETCODE_DONE:
            retcode = result.retcode if result else "None"
            comment = result.comment if result else "no result"
            self._logger.error(
                "order_send_failed", retcode=retcode, comment=comment
            )
            return None

        slippage = result.price - price
        self._logger.info(
            "order_filled",
            ticket=result.order,
            fill_price=result.price,
            slippage=slippage,
            volume=result.volume,
        )

        return FillEvent(
            ticket=result.order,
            symbol=symbol,
            action=action,
            volume=result.volume,
            fill_price=result.price,
            requested_price=price,
            slippage=slippage,
            sl=sl_price,
            tp=tp_price,
            magic=self._config.magic_number,
            is_paper=False,
        )

    async def close_position(
        self,
        ticket: int,
        symbol: str,
        volume: float,
        position_type: int,
    ) -> FillEvent | None:
        """Close a specific position by sending opposite order.

        Args:
            ticket: Position ticket to close.
            symbol: Trading symbol.
            volume: Position volume to close.
            position_type: MT5 order type of the position (BUY or SELL).

        Returns:
            FillEvent on success, None on failure.
        """
        close_type = (
            mt5.ORDER_TYPE_SELL
            if position_type == mt5.ORDER_TYPE_BUY
            else mt5.ORDER_TYPE_BUY
        )
        tick = await self._bridge.get_symbol_tick(symbol)
        if tick is None:
            return None

        price = (
            tick.bid
            if position_type == mt5.ORDER_TYPE_BUY
            else tick.ask
        )
        filling = await self._determine_filling_mode(symbol)

        request: dict = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": close_type,
            "price": price,
            "deviation": self._config.deviation,
            "magic": self._config.magic_number,
            "comment": "fxsoqqabot_close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
            "position": ticket,
        }

        if self._config.mode == "paper":
            if self._paper_executor is None:
                return None
            return self._paper_executor.simulate_close(request, tick)

        result = await self._bridge.order_send(request)
        if result is None or result.retcode != TRADE_RETCODE_DONE:
            self._logger.error("close_failed", ticket=ticket)
            return None

        return FillEvent(
            ticket=ticket,
            symbol=symbol,
            action="close",
            volume=volume,
            fill_price=result.price,
            requested_price=price,
            slippage=result.price - price,
            sl=0.0,
            tp=None,
            magic=self._config.magic_number,
            is_paper=False,
        )

    async def close_all_positions(self) -> list[FillEvent]:
        """Close ALL positions per D-05. Used by kill switch and crash recovery.

        Iterates positions_get and closes each position individually.
        Returns list of FillEvents for successfully closed positions.
        """
        positions = await self._bridge.get_positions(
            symbol=self._config.symbol
        )
        if not positions:
            return []

        results = []
        for pos in positions:
            fill = await self.close_position(
                pos.ticket, pos.symbol, pos.volume, pos.type
            )
            if fill:
                results.append(fill)
        return results
