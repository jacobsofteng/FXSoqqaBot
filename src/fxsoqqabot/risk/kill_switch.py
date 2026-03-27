"""Emergency kill switch per RISK-05, D-09.

Immediately closes all positions, cancels pending orders, halts trading.
Requires explicit manual reset per D-10 -- NOT auto-reset at session boundary.
Invocable via CLI (python -m fxsoqqabot kill) and TUI dashboard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from fxsoqqabot.core.state import BreakerState, StateManager

if TYPE_CHECKING:
    from fxsoqqabot.execution.orders import OrderManager


class KillSwitch:
    """Emergency kill switch per RISK-05, D-09.

    Immediately closes all positions, cancels pending orders, halts trading.
    Requires explicit manual reset per D-10 -- NOT auto-reset at session boundary.
    """

    def __init__(
        self,
        state: StateManager,
        order_manager: OrderManager | Any | None = None,
    ) -> None:
        self._state = state
        self._order_manager = order_manager
        self._logger = structlog.get_logger().bind(component="kill_switch")

    async def activate(self) -> dict:
        """Activate kill switch: close all positions, halt trading.

        Returns summary of actions taken.
        """
        self._logger.critical("KILL_SWITCH_ACTIVATED")

        # Close all positions per D-05/RISK-05
        closed: list = []
        if self._order_manager:
            closed = await self._order_manager.close_all_positions()

        # Set kill switch state
        snapshot = await self._state.load_breaker_state()
        snapshot.kill_switch = BreakerState.KILLED
        await self._state.save_breaker_state(snapshot)

        self._logger.info(
            "kill_switch_complete", positions_closed=len(closed)
        )
        return {"positions_closed": len(closed), "fills": closed}

    async def reset(self) -> None:
        """Explicit manual reset of kill switch per D-10.

        This is the ONLY way to clear a KILLED state.
        """
        snapshot = await self._state.load_breaker_state()
        if snapshot.kill_switch != BreakerState.KILLED:
            self._logger.warning(
                "kill_switch_not_killed_nothing_to_reset"
            )
            return
        snapshot.kill_switch = BreakerState.ACTIVE
        await self._state.save_breaker_state(snapshot)
        self._logger.info("kill_switch_reset")

    async def is_killed(self) -> bool:
        """Check if kill switch is currently active."""
        snapshot = await self._state.load_breaker_state()
        return snapshot.kill_switch == BreakerState.KILLED
