"""Multi-tier circuit breaker system per D-08, RISK-04, RISK-07.

Five automatic breakers:
1. Daily drawdown -- halt when daily loss > configurable % (default 5%)
2. Consecutive loss streak -- halt after N consecutive losses (default 5)
3. Rapid equity drop -- halt if equity drops X% in Y minutes
4. Max daily trade count -- halt after N trades per day (default 20)
5. Spread spike -- halt when spread > 5x average for 30+ seconds

Plus weekly and total drawdown per RISK-07.

Auto-resets at session boundary per D-10.
Kill switch handled separately (requires manual reset).
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

import structlog

from fxsoqqabot.config.models import RiskConfig
from fxsoqqabot.core.state import (
    BreakerState,
    CircuitBreakerSnapshot,
    StateManager,
)
from fxsoqqabot.risk.session import SessionFilter


class CircuitBreakerManager:
    """Multi-tier circuit breaker system per D-08, RISK-04, RISK-07.

    Five automatic breakers plus weekly/total drawdown per RISK-07.
    Auto-resets at session boundary per D-10.
    Kill switch handled separately (requires manual reset).
    """

    def __init__(
        self,
        config: RiskConfig,
        state: StateManager,
        session: SessionFilter,
    ) -> None:
        self._config = config
        self._state = state
        self._session = session
        self._snapshot = CircuitBreakerSnapshot()
        self._logger = structlog.get_logger().bind(component="circuit_breakers")
        # Spread spike tracking: (timestamp, spread)
        self._spread_history: deque[tuple[float, float]] = deque(maxlen=1000)
        # Equity tracking for rapid drop: (timestamp, equity)
        self._equity_history: deque[tuple[float, float]] = deque(maxlen=1000)

    async def load_state(self) -> None:
        """Load persisted state on startup per D-07."""
        self._snapshot = await self._state.load_breaker_state()

    async def _persist(self) -> None:
        """Save current state to SQLite."""
        await self._state.save_breaker_state(self._snapshot)

    async def check_session_reset(self, now: datetime | None = None) -> None:
        """Auto-reset daily breakers at session boundary per D-10.

        Kill switch is NOT auto-reset.
        """
        current_date = self._session.get_session_date(now)
        current_week = self._session.get_week_start_date(now)

        if self._snapshot.session_date != current_date:
            self._logger.info(
                "session_reset",
                old_date=self._snapshot.session_date,
                new_date=current_date,
            )
            self._snapshot.daily_pnl = 0.0
            self._snapshot.consecutive_losses = 0
            self._snapshot.daily_trade_count = 0
            self._snapshot.session_date = current_date
            self._snapshot.daily_drawdown = BreakerState.ACTIVE
            self._snapshot.loss_streak = BreakerState.ACTIVE
            self._snapshot.rapid_equity_drop = BreakerState.ACTIVE
            self._snapshot.max_trades = BreakerState.ACTIVE
            self._snapshot.spread_spike = BreakerState.ACTIVE
            # Note: kill_switch NOT reset here per D-10

        if self._snapshot.week_start_date != current_week:
            self._snapshot.weekly_pnl = 0.0
            self._snapshot.week_start_date = current_week

        await self._persist()

    def is_trading_allowed(self) -> bool:
        """Return True only if ALL breakers are ACTIVE.

        Returns False if any breaker is TRIPPED or kill_switch is KILLED.
        """
        if self._snapshot.kill_switch != BreakerState.ACTIVE:
            return False
        for breaker in [
            self._snapshot.daily_drawdown,
            self._snapshot.loss_streak,
            self._snapshot.rapid_equity_drop,
            self._snapshot.max_trades,
            self._snapshot.spread_spike,
        ]:
            if breaker != BreakerState.ACTIVE:
                return False
        return True

    def get_tripped_breakers(self) -> list[str]:
        """Return names of all currently tripped breakers."""
        tripped = []
        for name in [
            "kill_switch",
            "daily_drawdown",
            "loss_streak",
            "rapid_equity_drop",
            "max_trades",
            "spread_spike",
        ]:
            state = getattr(self._snapshot, name)
            if state != BreakerState.ACTIVE:
                tripped.append(name)
        return tripped

    async def record_trade_outcome(self, pnl: float, equity: float) -> None:
        """Update state after a trade completes. Checks all breakers."""
        self._snapshot.daily_pnl += pnl
        self._snapshot.daily_trade_count += 1

        if pnl < 0:
            self._snapshot.consecutive_losses += 1
        else:
            self._snapshot.consecutive_losses = 0

        # Update equity high water mark
        if equity > self._snapshot.equity_high_water_mark:
            self._snapshot.equity_high_water_mark = equity

        self._snapshot.weekly_pnl += pnl
        self._snapshot.last_equity = equity
        self._snapshot.last_equity_time = datetime.now(timezone.utc).isoformat()

        # Check daily drawdown (RISK-04)
        if self._snapshot.daily_starting_equity > 0:
            daily_dd = (
                abs(self._snapshot.daily_pnl)
                / self._snapshot.daily_starting_equity
            )
            if (
                self._snapshot.daily_pnl < 0
                and daily_dd >= self._config.daily_drawdown_pct
            ):
                self._snapshot.daily_drawdown = BreakerState.TRIPPED
                self._logger.warning(
                    "daily_drawdown_tripped",
                    daily_dd=daily_dd,
                    pnl=self._snapshot.daily_pnl,
                )

        # Check consecutive losses (D-08)
        if (
            self._snapshot.consecutive_losses
            >= self._config.max_consecutive_losses
        ):
            self._snapshot.loss_streak = BreakerState.TRIPPED
            self._logger.warning(
                "loss_streak_tripped",
                consecutive=self._snapshot.consecutive_losses,
            )

        # Check max daily trades (D-08)
        if self._snapshot.daily_trade_count >= self._config.max_daily_trades:
            self._snapshot.max_trades = BreakerState.TRIPPED
            self._logger.warning(
                "max_trades_tripped",
                count=self._snapshot.daily_trade_count,
            )

        # Check total max drawdown (RISK-07)
        if self._snapshot.equity_high_water_mark > 0:
            total_dd = 1.0 - (equity / self._snapshot.equity_high_water_mark)
            if total_dd >= self._config.max_total_drawdown_pct:
                self._snapshot.daily_drawdown = BreakerState.TRIPPED
                self._logger.warning(
                    "total_drawdown_tripped", total_dd=total_dd
                )

        await self._persist()

    async def check_equity(self, equity: float) -> None:
        """Check rapid equity drop per D-08.

        Called on each tick/equity update, not just on trade completion.
        """
        now = datetime.now(timezone.utc).timestamp()
        self._equity_history.append((now, equity))

        # Check if equity dropped > rapid_equity_drop_pct within window
        window_start = now - (
            self._config.rapid_equity_drop_window_minutes * 60
        )
        old_equities = [
            e for t, e in self._equity_history if t <= window_start
        ]
        if old_equities:
            max_old_equity = max(old_equities)
            if max_old_equity > 0:
                drop_pct = (max_old_equity - equity) / max_old_equity
                if drop_pct >= self._config.rapid_equity_drop_pct:
                    self._snapshot.rapid_equity_drop = BreakerState.TRIPPED
                    self._logger.warning(
                        "rapid_equity_drop_tripped", drop_pct=drop_pct
                    )
                    await self._persist()

    async def check_spread(self, spread: float, avg_spread: float) -> None:
        """Check spread spike per D-08.

        Trips when spread > 5x average for 30+ seconds.
        """
        now = datetime.now(timezone.utc).timestamp()
        threshold = avg_spread * self._config.spread_spike_multiplier

        if spread > threshold:
            self._spread_history.append((now, spread))
            # Check if spike sustained for duration
            if len(self._spread_history) > 0:
                first_spike = self._spread_history[0][0]
                if (
                    now - first_spike
                ) >= self._config.spread_spike_duration_seconds:
                    self._snapshot.spread_spike = BreakerState.TRIPPED
                    self._logger.warning(
                        "spread_spike_tripped",
                        spread=spread,
                        avg=avg_spread,
                        duration=now - first_spike,
                    )
                    await self._persist()
        else:
            self._spread_history.clear()

    def set_daily_starting_equity(self, equity: float) -> None:
        """Set starting equity for the day. Called at session start."""
        self._snapshot.daily_starting_equity = equity
        if equity > self._snapshot.equity_high_water_mark:
            self._snapshot.equity_high_water_mark = equity

    @property
    def snapshot(self) -> CircuitBreakerSnapshot:
        """Return current circuit breaker snapshot."""
        return self._snapshot

    @property
    def is_killed(self) -> bool:
        """Synchronous check if kill switch is active."""
        return self._snapshot.kill_switch == BreakerState.KILLED

    def get_breaker_status(self) -> dict[str, str]:
        """Return all breaker states as a dict for dashboard display."""
        return {
            "kill_switch": self._snapshot.kill_switch.value,
            "daily_drawdown": self._snapshot.daily_drawdown.value,
            "loss_streak": self._snapshot.loss_streak.value,
            "rapid_equity_drop": self._snapshot.rapid_equity_drop.value,
            "max_trades": self._snapshot.max_trades.value,
            "spread_spike": self._snapshot.spread_spike.value,
        }
