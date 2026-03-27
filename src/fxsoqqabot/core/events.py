"""Event types for the FXSoqqaBot event-driven architecture.

All event types are frozen dataclasses with __slots__ for memory
efficiency and immutability guarantees. These are the canonical
data structures passed between modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class EventType(str, Enum):
    """Enumeration of all event types in the system."""

    # Market data events
    TICK = "tick"
    BAR = "bar"
    DOM = "dom"

    # Execution events
    FILL = "fill"
    ORDER_REJECTED = "order_rejected"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"

    # System events
    CIRCUIT_BREAKER_TRIPPED = "circuit_breaker_tripped"
    KILL_SWITCH_ACTIVATED = "kill_switch_activated"
    CONNECTION_LOST = "connection_lost"
    CONNECTION_RESTORED = "connection_restored"

    # Learning events
    MUTATION = "mutation"
    RULE_RETIRED = "rule_retired"
    VARIANT_PROMOTED = "variant_promoted"


@dataclass(frozen=True, slots=True)
class TickEvent:
    """A single tick from the MT5 data feed.

    Fields match the MT5 MqlTick structure with computed spread.
    """

    symbol: str
    time_msc: int  # Millisecond timestamp from MT5
    bid: float
    ask: float
    last: float
    volume: int
    flags: int
    volume_real: float
    spread: float  # Computed: ask - bid


@dataclass(frozen=True, slots=True)
class BarEvent:
    """A completed bar (candlestick) from MT5.

    Fields match the MT5 MqlRates structure.
    """

    symbol: str
    timeframe: str  # "M1", "M5", "M15", "H1", "H4"
    time: int  # Unix timestamp
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread: int
    real_volume: int


@dataclass(frozen=True, slots=True)
class DOMEntry:
    """A single entry in the Depth of Market (order book).

    Fields match the MT5 MqlBookInfo structure.
    """

    type: int  # 1=sell, 2=buy (from MT5 BookInfo)
    price: float
    volume: int
    volume_dbl: float


@dataclass(frozen=True, slots=True)
class DOMSnapshot:
    """A point-in-time snapshot of the Depth of Market.

    Uses a tuple for entries to maintain immutability.
    Empty entries tuple represents graceful degradation when
    DOM data is unavailable (DATA-02).
    """

    symbol: str
    time_msc: int
    entries: tuple[DOMEntry, ...]  # Immutable tuple of DOM entries


@dataclass(frozen=True, slots=True)
class FillEvent:
    """A trade fill (order execution confirmation).

    is_paper distinguishes paper trading fills from live fills (D-01).
    """

    ticket: int
    symbol: str
    action: str  # "buy" or "sell"
    volume: float
    fill_price: float
    requested_price: float
    slippage: float
    sl: float
    tp: float | None
    magic: int
    is_paper: bool  # Per D-01: distinguishes paper vs live fills
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
