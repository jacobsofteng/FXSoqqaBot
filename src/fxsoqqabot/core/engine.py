"""Async trading engine orchestrating all components per EXEC-01.

Ties together MT5 bridge, data feed, buffers, storage, execution,
risk management, and state persistence into a running trading bot.

Lifecycle:
- start(): initialize components, connect MT5, crash recovery, run loops
- stop(): graceful shutdown of all components
- _tick_loop(): polls ticks at configured interval, updates buffers/storage
- _bar_loop(): refreshes multi-timeframe bars at configured interval
- _health_loop(): monitors equity, session resets, and breaker state
"""

from __future__ import annotations

import asyncio
import signal
from typing import Any

import structlog

from fxsoqqabot.config.models import BotSettings
from fxsoqqabot.core.state import StateManager
from fxsoqqabot.data.buffers import BarBufferSet, TickBuffer
from fxsoqqabot.data.feed import MarketDataFeed
from fxsoqqabot.data.storage import TickStorage
from fxsoqqabot.execution.mt5_bridge import MT5Bridge
from fxsoqqabot.execution.orders import OrderManager
from fxsoqqabot.execution.paper import PaperExecutor
from fxsoqqabot.risk.circuit_breakers import CircuitBreakerManager
from fxsoqqabot.risk.kill_switch import KillSwitch
from fxsoqqabot.risk.session import SessionFilter
from fxsoqqabot.risk.sizing import PositionSizer
from fxsoqqabot.signals.base import SignalModule, SignalOutput
from fxsoqqabot.signals.chaos.module import ChaosRegimeModule
from fxsoqqabot.signals.flow.module import OrderFlowModule
from fxsoqqabot.signals.fusion.core import FusionCore
from fxsoqqabot.signals.fusion.phase_behavior import PhaseBehavior
from fxsoqqabot.signals.fusion.trade_manager import TradeManager
from fxsoqqabot.signals.fusion.weights import AdaptiveWeightTracker
from fxsoqqabot.signals.timing.module import QuantumTimingModule
from fxsoqqabot.signals.timing.phase_transition import compute_atr

# Module-level alias for testability (same pattern as mt5_bridge.py)
asyncio_sleep = asyncio.sleep

logger = structlog.get_logger()


class TradingEngine:
    """Async engine orchestrating all components per EXEC-01.

    Constructor accepts BotSettings and initializes all component slots to None.
    Components are created in _initialize_components() and wired together.
    """

    def __init__(self, settings: BotSettings) -> None:
        self._settings = settings
        self._running = False
        self._logger = structlog.get_logger().bind(component="engine")
        self._tick_poll_count = 0

        # Component slots -- initialized in _initialize_components()
        self._bridge: MT5Bridge | None = None
        self._state: StateManager | None = None
        self._feed: MarketDataFeed | None = None
        self._tick_buffer: TickBuffer | None = None
        self._bar_buffers: BarBufferSet | None = None
        self._storage: TickStorage | None = None
        self._paper_executor: PaperExecutor | None = None
        self._order_manager: OrderManager | None = None
        self._session: SessionFilter | None = None
        self._sizer: PositionSizer | None = None
        self._breakers: CircuitBreakerManager | None = None
        self._kill_switch: KillSwitch | None = None

        # Signal pipeline slots -- initialized in _initialize_components()
        self._signal_modules: list[SignalModule] = []
        self._fusion_core: FusionCore | None = None
        self._weight_tracker: AdaptiveWeightTracker | None = None
        self._phase_behavior: PhaseBehavior | None = None
        self._trade_manager: TradeManager | None = None

    # -- Properties -----------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Whether the engine event loop is currently active."""
        return self._running

    @property
    def kill_switch(self) -> KillSwitch | None:
        """KillSwitch instance for CLI and Phase 2 access."""
        return self._kill_switch

    @property
    def breakers(self) -> CircuitBreakerManager | None:
        """CircuitBreakerManager instance for CLI and Phase 2 access."""
        return self._breakers

    @property
    def state(self) -> StateManager | None:
        """StateManager instance for external access."""
        return self._state

    # -- Component initialization ---------------------------------------------

    async def _initialize_components(self) -> None:
        """Create and wire all components from settings.

        Order matters: dependencies must be created before dependents.
        """
        exec_config = self._settings.execution
        data_config = self._settings.data
        risk_config = self._settings.risk
        session_config = self._settings.session

        # MT5 bridge
        self._bridge = MT5Bridge(exec_config)

        # State manager (SQLite)
        state_db_path = data_config.storage_path + "/state.db"
        self._state = StateManager(state_db_path)
        await self._state.initialize()

        # Data feed
        self._feed = MarketDataFeed(self._bridge, data_config)

        # Buffers
        self._tick_buffer = TickBuffer(maxlen=data_config.tick_buffer_size)
        self._bar_buffers = BarBufferSet(data_config)

        # Storage
        self._storage = TickStorage(data_config)

        # Paper executor (only in paper mode)
        if exec_config.mode == "paper":
            self._paper_executor = PaperExecutor(starting_balance=20.0)

        # Order manager
        self._order_manager = OrderManager(
            self._bridge, exec_config, self._paper_executor
        )

        # Session filter
        self._session = SessionFilter(session_config)

        # Position sizer
        self._sizer = PositionSizer(risk_config)

        # Circuit breakers (depend on state and session)
        self._breakers = CircuitBreakerManager(
            risk_config, self._state, self._session
        )

        # Kill switch (depend on state and order manager)
        self._kill_switch = KillSwitch(self._state, self._order_manager)

        # Signal modules (Phase 2)
        sig_config = self._settings.signals
        chaos_module = ChaosRegimeModule(sig_config.chaos)
        flow_module = OrderFlowModule(sig_config.flow)
        timing_module = QuantumTimingModule(sig_config.timing)
        self._signal_modules = [chaos_module, flow_module, timing_module]

        # Initialize all signal modules (Numba warm-up etc.)
        for mod in self._signal_modules:
            await mod.initialize()

        # Fusion core
        self._fusion_core = FusionCore(sig_config.fusion)

        # Adaptive weight tracker
        module_names = [m.name for m in self._signal_modules]
        self._weight_tracker = AdaptiveWeightTracker(
            module_names=module_names,
            alpha=sig_config.fusion.ema_alpha,
            warmup_trades=sig_config.fusion.weight_warmup_trades,
        )

        # Load persisted weights (Pitfall 6 prevention)
        weight_state = await self._state.load_signal_weights()
        if weight_state.get("trade_count", 0) > 0:
            # Add alpha/warmup from config for load_state compatibility
            weight_state["alpha"] = sig_config.fusion.ema_alpha
            weight_state["warmup"] = sig_config.fusion.weight_warmup_trades
            self._weight_tracker.load_state(weight_state)
            self._logger.info("signal_weights_loaded", trade_count=weight_state["trade_count"])

        # Phase behavior
        self._phase_behavior = PhaseBehavior(sig_config.fusion, self._settings.risk)

        # Trade manager
        self._trade_manager = TradeManager(
            fusion_config=sig_config.fusion,
            phase_behavior=self._phase_behavior,
            order_manager=self._order_manager,
            position_sizer=self._sizer,
            breaker_manager=self._breakers,
        )

        self._logger.info(
            "components_initialized",
            mode=exec_config.mode,
            symbol=exec_config.symbol,
            signal_modules=[m.name for m in self._signal_modules],
        )

    # -- Connection -----------------------------------------------------------

    async def _connect_mt5(self) -> bool:
        """Connect to MT5 terminal. Retries via reconnect_loop per D-06.

        Returns True on success, False if connection exhausted.
        """
        assert self._bridge is not None
        if await self._bridge.connect():
            return True
        self._logger.warning("mt5_initial_connect_failed_retrying")
        return await self._bridge.reconnect_loop(max_retries=5)

    # -- Crash recovery -------------------------------------------------------

    async def _crash_recovery(self) -> None:
        """Perform crash recovery per D-05, D-07, D-10.

        Steps:
        1. Load circuit breaker state from SQLite per D-07
        2. Check for open positions via bridge
        3. Close ALL positions if any exist per D-05/EXEC-04
        4. Check session reset per D-10
        5. Set daily starting equity from account info
        """
        assert self._breakers is not None
        assert self._bridge is not None
        assert self._order_manager is not None

        # 1. Load persisted breaker state per D-07
        await self._breakers.load_state()
        self._logger.info("breaker_state_loaded")

        # 2-3. Check and close open positions per D-05/EXEC-04
        symbol = self._settings.execution.symbol
        positions = await self._bridge.get_positions(symbol=symbol)
        if positions:
            self._logger.warning(
                "crash_recovery_open_positions_found",
                count=len(positions),
            )
            fills = await self._order_manager.close_all_positions()
            self._logger.info(
                "crash_recovery_positions_closed",
                closed=len(fills),
            )

        # 4. Check session boundary reset per D-10
        await self._breakers.check_session_reset()

        # 5. Set daily starting equity
        account_info = await self._bridge.get_account_info()
        if account_info is not None:
            self._breakers.set_daily_starting_equity(account_info.equity)
            self._logger.info(
                "daily_starting_equity_set",
                equity=account_info.equity,
            )

    # -- Main loops -----------------------------------------------------------

    async def _tick_loop(self) -> None:
        """Poll ticks at configured interval, update buffers and storage.

        Runs while self._running. Handles:
        - MT5 connection checks
        - Tick data fetching and buffer/storage updates
        - Tick freshness checks per Pitfall 7
        - Spread monitoring for circuit breaker per D-08
        - Paper position SL/TP checks
        - Periodic parquet flush
        """
        assert self._bridge is not None
        assert self._feed is not None
        assert self._tick_buffer is not None
        assert self._storage is not None

        symbol = self._settings.execution.symbol
        interval_s = self._settings.data.tick_poll_interval_ms / 1000.0

        while self._running:
            try:
                # Check MT5 connection
                if not await self._bridge.ensure_connected():
                    self._logger.warning("tick_loop_reconnecting")
                    await self._bridge.reconnect_loop(max_retries=3)

                # Fetch ticks
                ticks = await self._feed.fetch_ticks(symbol, count=100)
                if ticks:
                    self._tick_buffer.extend(ticks)
                    self._storage.store_ticks(ticks)
                    self._tick_poll_count += 1

                # Check tick freshness per Pitfall 7
                if not self._feed.check_tick_freshness():
                    self._logger.warning("tick_data_stale")

                # Check spread for circuit breaker per D-08
                if ticks and self._breakers is not None:
                    latest_tick = ticks[-1]
                    avg_spread = self._compute_avg_spread()
                    if avg_spread > 0:
                        await self._breakers.check_spread(
                            latest_tick.spread, avg_spread
                        )

                # Check paper position SL/TP
                if (
                    self._settings.execution.mode == "paper"
                    and self._paper_executor is not None
                    and ticks
                ):
                    latest = ticks[-1]
                    triggered = self._paper_executor.check_sl_tp(
                        latest.bid, latest.ask
                    )
                    if triggered:
                        self._logger.info(
                            "paper_sl_tp_triggered", tickets=triggered
                        )

                # Periodic parquet flush (every 1000 polls)
                if self._tick_poll_count % 1000 == 0 and self._tick_poll_count > 0:
                    self._storage.flush_to_parquet()

            except Exception:
                self._logger.error("tick_loop_error", exc_info=True)

            await asyncio_sleep(interval_s)

    async def _bar_loop(self) -> None:
        """Refresh multi-timeframe bars at configured interval.

        Per DATA-03: fetches all five timeframes (M1, M5, M15, H1, H4).
        """
        assert self._feed is not None
        assert self._bar_buffers is not None

        symbol = self._settings.execution.symbol
        interval_s = self._settings.data.bar_refresh_interval_seconds

        while self._running:
            try:
                bars_by_tf = await self._feed.fetch_multi_timeframe_bars(
                    symbol
                )
                for tf, bars in bars_by_tf.items():
                    self._bar_buffers.update(tf, bars)
            except Exception:
                self._logger.error("bar_loop_error", exc_info=True)

            await asyncio_sleep(interval_s)

    async def _health_loop(self) -> None:
        """Monitor equity, session resets, and breaker state.

        Runs every 10 seconds while self._running.
        """
        assert self._bridge is not None
        assert self._breakers is not None
        assert self._state is not None

        while self._running:
            try:
                # Check session boundary reset per D-10
                await self._breakers.check_session_reset()

                # Get account info and check equity
                account_info = await self._bridge.get_account_info()
                if account_info is not None:
                    await self._breakers.check_equity(account_info.equity)

                    # Save account snapshot
                    await self._state.save_account_snapshot(
                        equity=account_info.equity,
                        balance=account_info.balance,
                        margin=account_info.margin,
                        free_margin=account_info.margin_free,
                        margin_level=(
                            account_info.margin_level
                            if hasattr(account_info, "margin_level")
                            else 0.0
                        ),
                    )

                # Log tripped breakers
                tripped = self._breakers.get_tripped_breakers()
                if tripped:
                    self._logger.warning("breakers_tripped", breakers=tripped)

            except Exception:
                self._logger.error("health_loop_error", exc_info=True)

            await asyncio_sleep(10.0)

    async def _signal_loop(self) -> None:
        """Run signal analysis, fusion, and trade decisions.

        Orchestrates: update all modules -> fuse signals -> evaluate trade -> execute.
        Runs at bar refresh interval since regime detection operates on bar data.
        """
        assert self._tick_buffer is not None
        assert self._bar_buffers is not None
        assert self._fusion_core is not None
        assert self._weight_tracker is not None
        assert self._phase_behavior is not None
        assert self._trade_manager is not None
        assert self._bridge is not None

        interval_s = self._settings.data.bar_refresh_interval_seconds

        while self._running:
            try:
                # Prepare data for signal modules
                tick_arrays = self._tick_buffer.as_arrays()
                bar_arrays = {
                    tf: self._bar_buffers[tf].as_arrays()
                    for tf in self._bar_buffers.timeframes
                }

                # Get latest DOM snapshot (may be None)
                dom = None

                # Update all signal modules
                signals: list[SignalOutput] = []
                for module in self._signal_modules:
                    try:
                        signal_out = await module.update(tick_arrays, bar_arrays, dom)
                        signals.append(signal_out)
                    except Exception:
                        self._logger.error(
                            "signal_module_error",
                            module=module.name,
                            exc_info=True,
                        )
                        # Skip failed module -- fusion works with partial signals

                if not signals:
                    await asyncio_sleep(interval_s)
                    continue

                # Get adaptive weights
                weights = self._weight_tracker.get_weights()

                # Get equity for phase-aware threshold
                account_info = await self._bridge.get_account_info()
                equity = account_info.equity if account_info else 20.0

                # Get confidence threshold for current equity
                threshold = self._phase_behavior.get_confidence_threshold(equity)

                # Fuse signals
                fusion_result = self._fusion_core.fuse(signals, weights, threshold)

                # Log fusion state
                self._logger.debug(
                    "fusion_state",
                    regime=fusion_result.regime.value,
                    direction=fusion_result.direction,
                    composite=fusion_result.composite_score,
                    confidence=fusion_result.fused_confidence,
                    should_trade=fusion_result.should_trade,
                    threshold=threshold,
                    weights=weights,
                    module_scores=fusion_result.module_scores,
                )

                # Compute ATR for SL/TP
                m5_bars = bar_arrays.get("M5", {})
                current_atr = 0.0
                if "high" in m5_bars and len(m5_bars["high"]) > 0:
                    atr_array = compute_atr(
                        m5_bars["high"],
                        m5_bars["low"],
                        m5_bars["close"],
                        period=self._settings.signals.fusion.sl_atr_period,
                    )
                    current_atr = float(atr_array[-1])

                # Get current price
                current_price = 0.0
                if tick_arrays["bid"].size > 0:
                    current_price = float(tick_arrays["bid"][-1])

                # Evaluate and potentially execute trade
                if current_atr > 0 and current_price > 0:
                    decision = await self._trade_manager.evaluate_and_execute(
                        fusion_result=fusion_result,
                        equity=equity,
                        current_price=current_price,
                        atr=current_atr,
                    )

                    if decision.action in ("buy", "sell"):
                        self._logger.info(
                            "trade_executed",
                            action=decision.action,
                            lot_size=decision.lot_size,
                            sl_distance=decision.sl_distance,
                            tp_distance=decision.tp_distance,
                            regime=decision.regime.value,
                            confidence=decision.confidence,
                        )

                        # Persist weight state after trade
                        await self._state.save_signal_weights(
                            self._weight_tracker.get_state()
                        )

            except Exception:
                self._logger.error("signal_loop_error", exc_info=True)

            await asyncio_sleep(interval_s)

    # -- Helpers --------------------------------------------------------------

    def _compute_avg_spread(self) -> float:
        """Compute average spread from tick buffer for breaker comparison."""
        if self._tick_buffer is None or len(self._tick_buffer) == 0:
            return 0.0
        arrays = self._tick_buffer.as_arrays()
        spreads = arrays["spread"]
        if len(spreads) == 0:
            return 0.0
        return float(spreads.mean())

    # -- Start / Stop ---------------------------------------------------------

    async def start(self) -> None:
        """Start the trading engine.

        Steps:
        1. Initialize all components
        2. Connect to MT5 (abort if cannot connect)
        3. Run crash recovery
        4. Run concurrent loops via asyncio.gather
        """
        self._logger.info("engine_starting", mode=self._settings.execution.mode)

        # Initialize components
        await self._initialize_components()

        # Connect to MT5
        if not await self._connect_mt5():
            self._logger.error("engine_cannot_connect_mt5_aborting")
            await self.stop()
            return

        # Crash recovery
        await self._crash_recovery()

        # Start concurrent loops
        self._running = True
        self._logger.info("engine_started")

        try:
            await asyncio.gather(
                self._tick_loop(),
                self._bar_loop(),
                self._health_loop(),
                self._signal_loop(),  # Phase 2 signal pipeline
            )
        except asyncio.CancelledError:
            self._logger.info("engine_loops_cancelled")
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Graceful shutdown of all components.

        Flushes storage, closes state DB, shuts down MT5 bridge.
        """
        self._running = False
        self._logger.info("engine_stopping")

        # Flush storage to parquet
        if self._storage is not None:
            try:
                self._storage.flush_to_parquet()
                self._storage.close()
            except Exception:
                self._logger.error("storage_close_error", exc_info=True)

        # Close state DB
        if self._state is not None:
            try:
                await self._state.close()
            except Exception:
                self._logger.error("state_close_error", exc_info=True)

        # Shutdown MT5 bridge
        if self._bridge is not None:
            try:
                await self._bridge.shutdown()
            except Exception:
                self._logger.error("bridge_shutdown_error", exc_info=True)

        self._logger.info("engine_stopped")
