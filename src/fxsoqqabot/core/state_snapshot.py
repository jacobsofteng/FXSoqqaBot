"""Shared state snapshot for dashboard consumption.

Defines the TradingEngineState dataclass that is updated atomically
by the TradingEngine and read by TUI and web dashboards. Not frozen
because the engine writes and dashboards read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fxsoqqabot.signals.base import RegimeState


@dataclass
class TradingEngineState:
    """Shared state snapshot for dashboard consumption.

    Updated atomically by TradingEngine. Read by TUI and web dashboard.
    Not frozen -- engine writes, dashboards read.
    """

    regime: RegimeState = RegimeState.RANGING
    regime_confidence: float = 0.0
    signal_confidences: dict[str, float] = field(default_factory=dict)
    signal_directions: dict[str, float] = field(default_factory=dict)
    fusion_score: float = 0.0
    open_position: dict | None = None
    current_price: float = 0.0
    spread: float = 0.0
    equity: float = 0.0
    daily_pnl: float = 0.0
    breaker_status: dict[str, str] = field(default_factory=dict)
    recent_trades: list[dict] = field(default_factory=list)
    recent_mutations: list[dict] = field(default_factory=list)
    volume_delta: float = 0.0
    bid_pressure: float = 0.0
    ask_pressure: float = 0.0
    daily_trade_count: int = 0
    daily_win_rate: float = 0.0
    equity_history: list[float] = field(default_factory=list)
    is_connected: bool = False
    is_paused: bool = False
    is_killed: bool = False

    def to_dict(self) -> dict:
        """Serialize for WebSocket JSON transmission."""
        return {
            "regime": self.regime.value,
            "regime_confidence": self.regime_confidence,
            "signal_confidences": self.signal_confidences,
            "signal_directions": self.signal_directions,
            "fusion_score": self.fusion_score,
            "open_position": self.open_position,
            "current_price": self.current_price,
            "spread": self.spread,
            "equity": self.equity,
            "daily_pnl": self.daily_pnl,
            "breaker_status": self.breaker_status,
            "recent_trades": self.recent_trades,
            "recent_mutations": self.recent_mutations,
            "volume_delta": self.volume_delta,
            "bid_pressure": self.bid_pressure,
            "ask_pressure": self.ask_pressure,
            "daily_trade_count": self.daily_trade_count,
            "daily_win_rate": self.daily_win_rate,
            "is_connected": self.is_connected,
            "is_paused": self.is_paused,
            "is_killed": self.is_killed,
        }
