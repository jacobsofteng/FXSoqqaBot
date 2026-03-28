"""Trade execution manager with regime-aware SL/TP per FUSE-05.

Bridges the fusion decision to actual trade execution via OrderManager.
Implements:
- ATR-based SL with chaos-aware widening (D-06, D-09)
- Dynamic risk-reward ratios per regime (D-09)
- Regime-aware trailing stops (D-10)
- Concurrent position limit with remaining-budget tracking (D-11, RISK-03)
- Adverse regime transition SL tightening (D-08)
- Position size reduction in high-chaos (D-06)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from fxsoqqabot.config.models import FusionConfig
from fxsoqqabot.core.events import FillEvent
from fxsoqqabot.signals.base import RegimeState
from fxsoqqabot.signals.fusion.core import FusionResult
from fxsoqqabot.signals.fusion.phase_behavior import PhaseBehavior

if TYPE_CHECKING:
    from fxsoqqabot.execution.orders import OrderManager
    from fxsoqqabot.risk.circuit_breakers import CircuitBreakerManager
    from fxsoqqabot.risk.sizing import PositionSizer


@dataclass(slots=True)
class OpenPosition:
    """Track an open position for concurrent position management per RISK-03.

    Attributes:
        ticket: Position ticket number from broker.
        entry_price: Fill price of the position.
        regime: Market regime at time of entry.
        risk_amount: Actual dollar risk for this position (from SizingResult).
    """

    ticket: int
    entry_price: float
    regime: RegimeState
    risk_amount: float


@dataclass(frozen=True, slots=True)
class TradeDecision:
    """Result of trade evaluation -- what the TradeManager decided.

    Frozen for immutability; follows Phase 1 frozen dataclass pattern.

    Attributes:
        action: "buy", "sell", "hold", or "tighten_sl".
        sl_distance: ATR-based, regime-adjusted stop-loss distance.
        tp_distance: SL * RR ratio take-profit distance.
        lot_size: From PositionSizer, adjusted for regime.
        confidence: From FusionResult fused confidence.
        regime: Current market regime.
        reason: Human-readable reason for the decision.
    """

    action: str
    sl_distance: float
    tp_distance: float
    lot_size: float
    confidence: float
    regime: RegimeState
    reason: str


class TradeManager:
    """Trade execution with regime-aware SL/TP, position limits, trailing stops.

    Bridges FusionResult to OrderManager for actual trade placement.
    Implements D-06 (high-chaos adjustments), D-08 (adverse regime tightening),
    D-09 (dynamic RR ratios), D-10 (trailing stops), D-11 (single position).

    Args:
        fusion_config: Fusion configuration.
        phase_behavior: Phase-aware behavior provider.
        order_manager: OrderManager for trade execution (None in testing).
        position_sizer: PositionSizer for lot calculation.
        breaker_manager: CircuitBreakerManager for safety gates (None in testing).
    """

    def __init__(
        self,
        fusion_config: FusionConfig,
        phase_behavior: PhaseBehavior,
        order_manager: OrderManager | None,
        position_sizer: PositionSizer,
        breaker_manager: CircuitBreakerManager | None,
    ) -> None:
        self._config = fusion_config
        self._phase = phase_behavior
        self._orders = order_manager
        self._sizer = position_sizer
        self._breakers = breaker_manager
        self._open_positions: list[OpenPosition] = []
        self._logger = structlog.get_logger().bind(component="trade_manager")

    def _get_remaining_risk_budget(self, equity: float) -> float:
        """Remaining risk budget after accounting for open positions per D-10/D-11.

        Total budget = equity * risk_pct. Used = sum of open position risk amounts.
        Remaining = total - used, floored at 0.

        Args:
            equity: Current account equity in USD.

        Returns:
            Remaining risk budget in dollars. 0.0 if fully consumed.
        """
        risk_pct = self._sizer._config.get_risk_pct(equity)
        total_budget = equity * risk_pct
        used = sum(p.risk_amount for p in self._open_positions)
        return max(0.0, total_budget - used)

    def compute_sl_tp(
        self,
        atr: float,
        regime: RegimeState,
        direction: float,
        current_price: float,
    ) -> tuple[float, float, float, float]:
        """Compute SL and TP prices from ATR and regime per D-09.

        SL distance = ATR * base_multiplier (widened in high-chaos per D-06).
        TP distance = SL * RR ratio per regime.

        Args:
            atr: Average True Range value.
            regime: Current market regime.
            direction: Trade direction (+1.0 buy, -1.0 sell).
            current_price: Current market price.

        Returns:
            Tuple of (sl_price, tp_price, sl_distance, tp_distance).
        """
        # Base SL distance from ATR
        sl_distance = atr * self._config.sl_atr_base_multiplier

        # Apply regime adjustments (chaos widening per D-06)
        adjustments = self._phase.get_regime_adjustments(regime)
        if "sl_widen_factor" in adjustments:
            sl_distance *= adjustments["sl_widen_factor"]

        # TP from RR ratio per D-09
        rr_ratio = self._phase.get_rr_ratio(regime)
        tp_distance = sl_distance * rr_ratio

        # Compute price levels
        if direction > 0:  # Buy
            sl_price = current_price - sl_distance
            tp_price = current_price + tp_distance
        else:  # Sell
            sl_price = current_price + sl_distance
            tp_price = current_price - tp_distance

        return sl_price, tp_price, sl_distance, tp_distance

    async def evaluate_and_execute(
        self,
        fusion_result: FusionResult,
        equity: float,
        current_price: float,
        atr: float,
    ) -> tuple[TradeDecision, FillEvent | None]:
        """Evaluate fusion result and execute trade if appropriate.

        Decision flow:
        1. Check position limit (D-11) and adverse regime transition (D-08)
        2. Check if fusion says trade
        3. Check circuit breakers
        4. Compute SL/TP
        5. Size position (with chaos reduction per D-06)
        6. Execute trade

        Args:
            fusion_result: Result from FusionCore.fuse().
            equity: Current account equity in USD.
            current_price: Current market price.
            atr: Average True Range value.

        Returns:
            Tuple of (TradeDecision, FillEvent | None). FillEvent is non-None
            only on successful order execution.
        """
        regime = fusion_result.regime

        # 1a. Check for adverse regime transition on open positions per D-08
        for pos in self._open_positions:
            if (
                pos.regime is not None
                and regime != pos.regime
                and regime in (RegimeState.HIGH_CHAOS, RegimeState.PRE_BIFURCATION)
            ):
                profit_distance = current_price - pos.entry_price
                new_sl = pos.entry_price + profit_distance * 0.5

                if self._orders:
                    try:
                        await self._orders.modify_sl(pos.ticket, new_sl)
                    except Exception:
                        self._logger.warning(
                            "modify_sl_failed", ticket=pos.ticket
                        )

                self._logger.info(
                    "adverse_regime_tighten_sl",
                    old_regime=pos.regime.value,
                    new_regime=regime.value,
                    new_sl=new_sl,
                    ticket=pos.ticket,
                )

                return TradeDecision(
                    action="tighten_sl",
                    sl_distance=abs(current_price - new_sl),
                    tp_distance=0.0,
                    lot_size=0.0,
                    confidence=fusion_result.fused_confidence,
                    regime=regime,
                    reason=f"Adverse regime transition to {regime.value} per D-08",
                ), None

        # 1b. Check position limit per D-09/RISK-03
        if len(self._open_positions) >= self._config.max_concurrent_positions:
            return TradeDecision(
                action="hold",
                sl_distance=0.0,
                tp_distance=0.0,
                lot_size=0.0,
                confidence=fusion_result.fused_confidence,
                regime=regime,
                reason=f"Position limit reached ({len(self._open_positions)}/{self._config.max_concurrent_positions})",
            ), None

        # 1c. Check remaining risk budget per D-10/D-11
        remaining_budget = self._get_remaining_risk_budget(equity)
        if remaining_budget <= 0:
            return TradeDecision(
                action="hold",
                sl_distance=0.0,
                tp_distance=0.0,
                lot_size=0.0,
                confidence=fusion_result.fused_confidence,
                regime=regime,
                reason="Risk budget fully consumed by open positions",
            ), None

        # 2. Check if fusion says trade
        if not fusion_result.should_trade:
            return TradeDecision(
                action="hold",
                sl_distance=0.0,
                tp_distance=0.0,
                lot_size=0.0,
                confidence=fusion_result.fused_confidence,
                regime=regime,
                reason="Below confidence threshold",
            ), None

        # 3. Check circuit breakers
        if self._breakers and not self._breakers.is_trading_allowed():
            tripped = self._breakers.get_tripped_breakers()
            return TradeDecision(
                action="hold",
                sl_distance=0.0,
                tp_distance=0.0,
                lot_size=0.0,
                confidence=fusion_result.fused_confidence,
                regime=regime,
                reason=f"Circuit breaker tripped: {', '.join(tripped)}",
            ), None

        # 4. Compute SL/TP per D-09
        sl_price, tp_price, sl_dist, tp_dist = self.compute_sl_tp(
            atr, regime, fusion_result.direction, current_price
        )

        # 5. Position sizing
        sizing = self._sizer.calculate_lot_size(equity, sl_dist)

        if not sizing.can_trade:
            return TradeDecision(
                action="hold",
                sl_distance=sl_dist,
                tp_distance=tp_dist,
                lot_size=0.0,
                confidence=fusion_result.fused_confidence,
                regime=regime,
                reason=sizing.skip_reason or "Sizing rejected trade",
            ), None

        # Check if this trade's risk exceeds remaining budget per D-10/D-11
        if sizing.risk_amount > remaining_budget + 0.001:  # Small epsilon for float comparison
            return TradeDecision(
                action="hold",
                sl_distance=sl_dist,
                tp_distance=tp_dist,
                lot_size=0.0,
                confidence=fusion_result.fused_confidence,
                regime=regime,
                reason=f"Trade risk ${sizing.risk_amount:.2f} exceeds remaining budget ${remaining_budget:.2f}",
            ), None

        lot_size = sizing.lot_size

        # Apply regime size reduction per D-06
        adjustments = self._phase.get_regime_adjustments(regime)
        if "size_reduction" in adjustments:
            lot_size *= 1.0 - adjustments["size_reduction"]
            lot_size = max(0.01, lot_size)  # Enforce minimum lot
            lot_size = round(lot_size, 2)  # Round to 2 decimals

        # 6. Execute trade
        action = "buy" if fusion_result.direction > 0 else "sell"
        fill: FillEvent | None = None

        if self._orders:
            try:
                fill = await self._orders.place_market_order(
                    action=action,
                    volume=lot_size,
                    sl_price=sl_price,
                    tp_price=tp_price,
                )
                if fill:
                    self._open_positions.append(
                        OpenPosition(
                            ticket=fill.ticket,
                            entry_price=fill.fill_price,
                            regime=regime,
                            risk_amount=sizing.risk_amount,
                        )
                    )
                    self._logger.info(
                        "trade_executed",
                        action=action,
                        ticket=fill.ticket,
                        fill_price=fill.fill_price,
                        lot_size=lot_size,
                        sl=sl_price,
                        tp=tp_price,
                    )
            except Exception:
                self._logger.error("trade_execution_failed", action=action)

        self._logger.info(
            "trade_decision",
            action=action,
            lot_size=lot_size,
            sl_dist=sl_dist,
            tp_dist=tp_dist,
            confidence=fusion_result.fused_confidence,
            regime=regime.value,
        )

        return TradeDecision(
            action=action,
            sl_distance=sl_dist,
            tp_distance=tp_dist,
            lot_size=lot_size,
            confidence=fusion_result.fused_confidence,
            regime=regime,
            reason="Fusion threshold exceeded",
        ), fill

    def record_position_closed(self, ticket: int) -> None:
        """Clear position state when position closes.

        Called by the engine on POSITION_CLOSED event.

        Args:
            ticket: Position ticket that was closed.
        """
        before = len(self._open_positions)
        self._open_positions = [p for p in self._open_positions if p.ticket != ticket]
        if len(self._open_positions) < before:
            self._logger.info(
                "position_closed_recorded",
                ticket=ticket,
                remaining_positions=len(self._open_positions),
            )

    def get_trailing_params(self, regime: RegimeState) -> dict[str, float] | None:
        """Get trailing stop parameters for current regime per D-10.

        Delegates to PhaseBehavior.get_trailing_stop_params().

        Args:
            regime: Current market regime.

        Returns:
            Dict with activation_atr and trail_distance_atr, or None.
        """
        return self._phase.get_trailing_stop_params(regime)
