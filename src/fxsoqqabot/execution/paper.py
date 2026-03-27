"""Paper trading fill simulation engine per D-01.

Runs the full pipeline but simulates fills instead of executing on MT5.
Models spread, slippage, and produces realistic P&L tracking.
Same code path as live up to the execution point.

Key behaviors:
- Fills at market price (ask for buy, bid for sell) matching live behavior
- Adds random slippage within configured deviation range (70% adverse, 20% neutral, 10% favorable)
- Tracks paper positions with SL/TP for automatic closure
- Maintains virtual balance and equity for realistic paper P&L
- XAUUSD contract_size = 100 (1 lot = 100 oz gold)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from fxsoqqabot.core.events import FillEvent


@dataclass
class PaperPosition:
    """A simulated open position in paper mode."""

    ticket: int
    symbol: str
    action: str  # "buy" or "sell"
    volume: float
    open_price: float
    sl: float
    tp: float | None
    magic: int
    open_time: datetime = field(default_factory=lambda: datetime.now(UTC))

    def unrealized_pnl(self, bid: float, ask: float) -> float:
        """Calculate unrealized P&L at current prices.

        XAUUSD: 0.01 lot = 1 oz, each $1 move = $1 per 0.01 lot.
        PnL = (close_price - open_price) * volume * contract_size
        contract_size = 100 for gold.
        """
        contract_size = 100.0
        if self.action == "buy":
            return (bid - self.open_price) * self.volume * contract_size
        else:
            return (self.open_price - ask) * self.volume * contract_size


class PaperExecutor:
    """Paper trading fill simulation engine per D-01.

    Runs the full pipeline but simulates fills instead of executing on MT5.
    Models spread, slippage, and produces realistic P&L tracking.
    Same code path as live up to the execution point.
    """

    def __init__(
        self, starting_balance: float = 20.0, max_slippage_points: int = 5
    ) -> None:
        self._balance = starting_balance
        self._max_slippage_points = max_slippage_points
        self._positions: dict[int, PaperPosition] = {}
        self._next_ticket = 1000000
        self._trade_history: list[FillEvent] = []
        self._logger = structlog.get_logger().bind(component="paper_executor")

    def _gen_ticket(self) -> int:
        """Generate sequential paper ticket numbers starting from 1000000."""
        ticket = self._next_ticket
        self._next_ticket += 1
        return ticket

    def _simulate_slippage(self, price: float, point: float = 0.01) -> float:
        """Add random slippage within configured deviation range.

        Slippage distribution per D-01 realism:
        - 70% adverse (against the trader)
        - 20% neutral (no slippage)
        - 10% favorable (in trader's favor)
        """
        r = random.random()
        if r < 0.7:
            slip_points = random.randint(0, self._max_slippage_points)
        elif r < 0.9:
            slip_points = 0
        else:
            slip_points = -random.randint(0, self._max_slippage_points // 2)
        return price + slip_points * point

    def simulate_fill(self, request: dict, tick: object) -> FillEvent:
        """Simulate a market order fill per D-01.

        Args:
            request: Order request dict (same format as MT5 order_send).
            tick: Current tick with bid and ask attributes.

        Returns:
            FillEvent with is_paper=True.
        """
        ticket = self._gen_ticket()
        symbol = request["symbol"]
        is_buy = request["type"] == 0  # ORDER_TYPE_BUY = 0

        # Fill at market price (ask for buy, bid for sell) -- same as live
        base_price = tick.ask if is_buy else tick.bid  # type: ignore[union-attr]
        fill_price = self._simulate_slippage(base_price)
        slippage = fill_price - request["price"]
        action = "buy" if is_buy else "sell"

        # Create paper position
        position = PaperPosition(
            ticket=ticket,
            symbol=symbol,
            action=action,
            volume=request["volume"],
            open_price=fill_price,
            sl=request.get("sl", 0.0),
            tp=request.get("tp"),
            magic=request.get("magic", 0),
        )
        self._positions[ticket] = position

        fill = FillEvent(
            ticket=ticket,
            symbol=symbol,
            action=action,
            volume=request["volume"],
            fill_price=fill_price,
            requested_price=request["price"],
            slippage=slippage,
            sl=request.get("sl", 0.0),
            tp=request.get("tp"),
            magic=request.get("magic", 0),
            is_paper=True,
        )
        self._logger.info(
            "paper_fill",
            ticket=ticket,
            action=action,
            fill_price=fill_price,
            slippage=slippage,
            volume=request["volume"],
        )
        return fill

    def simulate_close(self, request: dict, tick: object) -> FillEvent | None:
        """Simulate closing a position.

        Args:
            request: Close request dict with 'position' field for ticket.
            tick: Current tick with bid and ask attributes.

        Returns:
            FillEvent with action='close' and is_paper=True, or None if position not found.
        """
        ticket = request.get("position")
        if ticket not in self._positions:
            self._logger.error("paper_position_not_found", ticket=ticket)
            return None

        pos = self._positions.pop(ticket)
        is_buy_close = pos.action == "buy"

        # Close price: bid for closing buy (selling), ask for closing sell (buying)
        close_price = tick.bid if is_buy_close else tick.ask  # type: ignore[union-attr]
        close_price = self._simulate_slippage(close_price)

        # Calculate realized P&L
        contract_size = 100.0
        if pos.action == "buy":
            pnl = (close_price - pos.open_price) * pos.volume * contract_size
        else:
            pnl = (pos.open_price - close_price) * pos.volume * contract_size

        self._balance += pnl

        fill = FillEvent(
            ticket=ticket,
            symbol=pos.symbol,
            action="close",
            volume=pos.volume,
            fill_price=close_price,
            requested_price=request["price"],
            slippage=close_price - request["price"],
            sl=pos.sl,
            tp=pos.tp,
            magic=pos.magic,
            is_paper=True,
        )
        self._trade_history.append(fill)
        self._logger.info(
            "paper_close",
            ticket=ticket,
            pnl=pnl,
            balance=self._balance,
        )
        return fill

    def check_sl_tp(self, bid: float, ask: float) -> list[int]:
        """Check all open paper positions for SL/TP hits.

        Returns list of tickets that were triggered.
        For buys: SL hit if bid <= sl; TP hit if bid >= tp.
        For sells: SL hit if ask >= sl; TP hit if ask <= tp.
        """
        triggered = []
        for ticket, pos in list(self._positions.items()):
            if pos.action == "buy":
                if pos.sl > 0 and bid <= pos.sl:
                    triggered.append(ticket)
                elif pos.tp is not None and bid >= pos.tp:
                    triggered.append(ticket)
            else:
                if pos.sl > 0 and ask >= pos.sl:
                    triggered.append(ticket)
                elif pos.tp is not None and ask <= pos.tp:
                    triggered.append(ticket)
        return triggered

    def get_paper_positions(self) -> list[PaperPosition]:
        """Return list of currently open paper positions."""
        return list(self._positions.values())

    @property
    def balance(self) -> float:
        """Current paper balance (starting + realized P&L)."""
        return self._balance

    def get_paper_equity(self, bid: float, ask: float) -> float:
        """Balance + unrealized P&L of all open positions."""
        unrealized = sum(
            p.unrealized_pnl(bid, ask) for p in self._positions.values()
        )
        return self._balance + unrealized

    @property
    def trade_history(self) -> list[FillEvent]:
        """List of all closed paper trade fill events."""
        return list(self._trade_history)
