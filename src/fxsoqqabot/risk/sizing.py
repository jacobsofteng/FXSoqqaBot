"""Position sizing engine with three-phase capital model per D-03.

XAUUSD specifics (from Research Pattern 2):
- Contract size: 100 oz per lot
- 0.01 lot = 1 oz
- Each $1 move in gold price = $1 per 0.01 lot
- With 1:500 leverage: margin for 0.01 lot at $2000 gold = $0.40

Key rule per D-04: If minimum lot (0.01) risk exceeds the phase limit,
the trade is SKIPPED, not forced through.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from fxsoqqabot.config.models import RiskConfig


@dataclass(frozen=True)
class SizingResult:
    """Result of position sizing calculation."""

    lot_size: float
    risk_amount: float  # Dollar amount at risk
    risk_pct: float  # Actual risk as percentage of equity
    capital_phase: str  # "aggressive", "selective", or "conservative"
    sl_distance: float  # SL distance in price units
    can_trade: bool  # False if risk exceeds limit per D-04
    skip_reason: str | None  # Reason for skipping (None if can_trade)


@dataclass(frozen=True)
class SymbolSpecs:
    """Broker symbol specifications queried at runtime.

    Avoids hardcoding per anti-pattern guidance.
    """

    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    trade_contract_size: float = 100.0  # 100 oz per lot for XAUUSD
    point: float = 0.01
    digits: int = 2


class PositionSizer:
    """Position sizing engine implementing three-phase capital model per D-03.

    Formula: lot_size = risk_amount / (sl_distance * contract_size)
    Where risk_amount = equity * risk_pct_for_phase

    Key rule per D-04: If minimum lot (0.01) risk exceeds the phase limit,
    the trade is SKIPPED, not forced through.
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._logger = structlog.get_logger().bind(component="position_sizer")

    def get_capital_phase(self, equity: float) -> str:
        """Determine current capital phase from equity per D-03.

        Args:
            equity: Current account equity in USD.

        Returns:
            Phase name: "aggressive", "selective", or "conservative".
        """
        if equity < self._config.aggressive_max:
            return "aggressive"
        elif equity < self._config.selective_max:
            return "selective"
        else:
            return "conservative"

    def calculate_lot_size(
        self,
        equity: float,
        sl_distance: float,
        specs: SymbolSpecs | None = None,
    ) -> SizingResult:
        """Calculate lot size respecting risk budget and broker constraints.

        Returns SizingResult with can_trade=False if min lot exceeds risk
        limit per D-04.

        Args:
            equity: Current account equity in USD.
            sl_distance: Stop-loss distance in price units (e.g., $3.00).
            specs: Broker symbol specifications. Defaults to XAUUSD specs.

        Returns:
            SizingResult with lot size, risk info, and trade eligibility.
        """
        if specs is None:
            specs = SymbolSpecs()  # XAUUSD defaults

        phase = self.get_capital_phase(equity)
        risk_pct = self._config.get_risk_pct(equity)
        risk_amount = equity * risk_pct

        if sl_distance <= 0:
            return SizingResult(
                lot_size=0,
                risk_amount=0,
                risk_pct=0,
                capital_phase=phase,
                sl_distance=sl_distance,
                can_trade=False,
                skip_reason="SL distance must be positive",
            )

        # Calculate ideal lot size
        lot_size = risk_amount / (sl_distance * specs.trade_contract_size)

        # Round down to volume_step
        lot_size = int(lot_size / specs.volume_step) * specs.volume_step
        lot_size = round(lot_size, 8)  # Avoid floating point artifacts

        # Apply min/max clamps
        lot_size = max(specs.volume_min, lot_size)
        lot_size = min(specs.volume_max, lot_size)

        # CRITICAL per D-04: Check if actual risk at this lot size exceeds limit
        actual_risk = lot_size * sl_distance * specs.trade_contract_size
        actual_risk_pct = actual_risk / equity if equity > 0 else float("inf")

        if actual_risk_pct > risk_pct:
            # Min lot exceeds risk budget -- skip trade
            self._logger.warning(
                "trade_skipped_risk_exceeds_limit",
                equity=equity,
                phase=phase,
                risk_pct=risk_pct,
                lot_size=lot_size,
                actual_risk=actual_risk,
                actual_risk_pct=actual_risk_pct,
                sl_distance=sl_distance,
            )
            return SizingResult(
                lot_size=lot_size,
                risk_amount=actual_risk,
                risk_pct=actual_risk_pct,
                capital_phase=phase,
                sl_distance=sl_distance,
                can_trade=False,
                skip_reason=(
                    f"Actual risk {actual_risk_pct:.1%} exceeds "
                    f"{phase} limit {risk_pct:.1%}"
                ),
            )

        self._logger.info(
            "position_sized",
            equity=equity,
            phase=phase,
            lot_size=lot_size,
            risk_amount=actual_risk,
            actual_risk_pct=actual_risk_pct,
        )

        return SizingResult(
            lot_size=lot_size,
            risk_amount=actual_risk,
            risk_pct=actual_risk_pct,
            capital_phase=phase,
            sl_distance=sl_distance,
            can_trade=True,
            skip_reason=None,
        )
