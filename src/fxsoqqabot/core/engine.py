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
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from fxsoqqabot.config.models import BotSettings
from fxsoqqabot.core.state import StateManager
from fxsoqqabot.core.state_snapshot import TradingEngineState

if TYPE_CHECKING:
    from fxsoqqabot.dashboard.tui.app import FXSoqqaBotTUI
    from fxsoqqabot.dashboard.web.server import DashboardServer
    from fxsoqqabot.learning.loop import LearningLoopManager
    from fxsoqqabot.learning.trade_logger import TradeContextLogger
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

        # Phase 4: Dashboard and learning slots
        self._engine_state = TradingEngineState()
        self._trade_logger: TradeContextLogger | None = None
        self._learning_loop: LearningLoopManager | None = None
        self._web_server: DashboardServer | None = None
        self._tui_enabled: bool = settings.tui.enabled
        self._web_enabled: bool = settings.web.enabled
        self._learning_enabled: bool = settings.learning.enabled

        # Track last signals and fusion result for state updates
        self._last_signals: list[SignalOutput] | None = None
        self._last_fusion_result: Any = None

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

    @property
    def engine_state(self) -> TradingEngineState:
        """Shared TradingEngineState for dashboard consumption."""
        return self._engine_state

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

        # Phase 4: Trade context logger
        from fxsoqqabot.learning.trade_logger import TradeContextLogger

        self._trade_logger = TradeContextLogger(self._storage._db)

        # Phase 4: Learning loop
        if self._learning_enabled:
            from fxsoqqabot.learning.loop import LearningLoopManager

            self._learning_loop = LearningLoopManager(
                config=self._settings.learning,
                trade_logger=self._trade_logger,
                equity=self._settings.risk.aggressive_max,
            )

            # Wire walk-forward validation gate (LEARN-06)
            try:
                validator_cb = self._create_walk_forward_validator()
                self._learning_loop.set_walk_forward_validator(validator_cb)
            except Exception:
                self._logger.warning(
                    "walk_forward_validator_setup_failed", exc_info=True
                )
                # Learning loop will operate without WF gate (statistical-only mode)

        # Phase 4: Web dashboard server
        if self._web_enabled:
            from fxsoqqabot.dashboard.web.server import DashboardServer

            self._web_server = DashboardServer(
                config=self._settings.web,
                state=self._engine_state,
                trade_logger=self._trade_logger,
                kill_callback=self._handle_kill,
                pause_callback=self._handle_pause,
            )

        self._logger.info(
            "components_initialized",
            mode=exec_config.mode,
            symbol=exec_config.symbol,
            signal_modules=[m.name for m in self._signal_modules],
            tui_enabled=self._tui_enabled,
            web_enabled=self._web_enabled,
            learning_enabled=self._learning_enabled,
        )

    def _create_walk_forward_validator(self) -> Callable[[dict[str, float]], bool]:
        """Create a walk-forward validation callback for LEARN-06.

        Returns a closure that runs WalkForwardValidator.run_walk_forward()
        synchronously (via a new event loop) and returns passes_threshold.
        On ANY error, returns False (fail-safe: reject promotion rather than
        allow through per existing decision).

        The params dict is received but not applied to settings in this
        implementation -- the walk-forward validates the CURRENT strategy
        parameters, acting as a baseline gate. Applying per-variant params
        is a future enhancement.
        """
        from fxsoqqabot.backtest.config import BacktestConfig

        bt_config = BacktestConfig()
        settings = self._settings

        def _run_async_in_thread(coro: Any) -> Any:
            """Run an async coroutine in a new thread with its own event loop.

            Required because _check_promotions runs in the main async context
            where an event loop is already running -- asyncio.run() and
            loop.run_until_complete() would raise RuntimeError.
            """
            import concurrent.futures

            result_holder: list = []
            exc_holder: list = []

            def _target() -> None:
                loop = asyncio.new_event_loop()
                try:
                    result_holder.append(loop.run_until_complete(coro))
                except Exception as e:
                    exc_holder.append(e)
                finally:
                    loop.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_target)
                future.result()  # Block until done, propagate thread errors

            if exc_holder:
                raise exc_holder[0]
            return result_holder[0]

        def _validate(params: dict[str, float]) -> bool:
            from fxsoqqabot.backtest.engine import BacktestEngine as BtEngine
            from fxsoqqabot.backtest.historical import HistoricalDataLoader
            from fxsoqqabot.backtest.validation import WalkForwardValidator

            try:
                self._logger.debug(
                    "walk_forward_validate_called",
                    params_received=list(params.keys()),
                )
                loader = HistoricalDataLoader(bt_config)
                engine = BtEngine(settings, bt_config)
                validator = WalkForwardValidator(engine, loader, bt_config)

                result = _run_async_in_thread(validator.run_walk_forward())

                return result.passes_threshold
            except Exception:
                self._logger.error(
                    "walk_forward_validate_error", exc_info=True
                )
                return False  # Fail-safe: reject promotion on error

        return _validate

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
                        await self._handle_paper_close(triggered, latest)

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

                # Store for state update
                self._last_signals = signals

                # Get adaptive weights
                weights = self._weight_tracker.get_weights()

                # Get equity for phase-aware threshold
                account_info = await self._bridge.get_account_info()
                equity = account_info.equity if account_info else 20.0

                # Get confidence threshold for current equity
                threshold = self._phase_behavior.get_confidence_threshold(equity)

                # Fuse signals
                fusion_result = self._fusion_core.fuse(signals, weights, threshold)
                self._last_fusion_result = fusion_result

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
                    decision, fill = await self._trade_manager.evaluate_and_execute(
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

                        # Phase 4: Log trade open context
                        if self._trade_logger and fill is not None:
                            try:
                                self._trade_logger.log_trade_open(
                                    decision=decision,
                                    fill=fill,
                                    signals=signals,
                                    fusion_result=fusion_result,
                                    weights=weights,
                                    equity=equity,
                                    atr=current_atr,
                                )
                            except Exception:
                                self._logger.error(
                                    "trade_log_open_error", exc_info=True
                                )

                # Phase 4: Update shared engine state for dashboards
                self._update_engine_state()

            except Exception:
                self._logger.error("signal_loop_error", exc_info=True)

            await asyncio_sleep(interval_s)

    # -- Phase 4: Paper close pipeline ----------------------------------------

    async def _handle_paper_close(self, triggered: list[int], latest_tick: Any) -> None:
        """Close triggered paper positions and log/learn from them.

        For each triggered ticket:
        1. Capture position state before close (for hold duration)
        2. Call simulate_close to close and compute PnL
        3. Log the close to DuckDB via trade_logger
        4. Notify the learning loop
        5. Clear trade_manager position state

        Args:
            triggered: List of triggered ticket IDs from check_sl_tp.
            latest_tick: Current tick with bid/ask attributes.
        """
        assert self._paper_executor is not None

        # Capture positions before closing (simulate_close removes them)
        positions_before = {
            t: self._paper_executor._positions[t]
            for t in triggered
            if t in self._paper_executor._positions
        }

        for ticket in triggered:
            pos = positions_before.get(ticket)
            if pos is None:
                continue

            # Build close request matching simulate_close signature
            close_request = {
                "position": ticket,
                "symbol": pos.symbol,
                "price": latest_tick.bid if pos.action == "buy" else latest_tick.ask,
                "volume": pos.volume,
            }

            close_fill = self._paper_executor.simulate_close(close_request, latest_tick)

            if close_fill is not None:
                # PnL from the paper executor's close
                contract_size = 100.0
                if pos.action == "buy":
                    pnl = (close_fill.fill_price - pos.open_price) * pos.volume * contract_size
                else:
                    pnl = (pos.open_price - close_fill.fill_price) * pos.volume * contract_size

                # Hold duration
                hold_duration = (datetime.now(UTC) - pos.open_time).total_seconds()

                # Current regime for exit_regime
                exit_regime = "unknown"
                if self._last_signals:
                    chaos_sig = next(
                        (s for s in self._last_signals if s.module_name == "chaos"),
                        None,
                    )
                    if chaos_sig and chaos_sig.regime:
                        exit_regime = chaos_sig.regime.value

                # Log trade close
                if self._trade_logger:
                    try:
                        self._trade_logger.log_trade_close(
                            ticket=ticket,
                            exit_price=close_fill.fill_price,
                            pnl=pnl,
                            hold_duration_seconds=hold_duration,
                            exit_regime=exit_regime,
                        )
                    except Exception:
                        self._logger.error("trade_log_close_error", exc_info=True)

                # Notify learning loop
                if self._learning_loop and self._learning_enabled:
                    try:
                        await self._learning_loop.on_trade_closed({
                            "pnl": pnl,
                            "equity": self._paper_executor.balance,
                            "ticket": ticket,
                            "exit_price": close_fill.fill_price,
                            "exit_regime": exit_regime,
                        })
                    except Exception:
                        self._logger.error("learning_loop_trade_closed_error", exc_info=True)

                # Clear trade manager position state
                if self._trade_manager:
                    self._trade_manager.record_position_closed(ticket)

                self._logger.info(
                    "paper_trade_closed",
                    ticket=ticket,
                    pnl=pnl,
                    exit_price=close_fill.fill_price,
                    hold_duration=hold_duration,
                )

    # -- Phase 4: State update and callbacks -----------------------------------

    def _update_engine_state(self) -> None:
        """Atomically update shared state snapshot for dashboard consumption.

        Called after each signal cycle in _signal_loop(). Updates all fields
        that TUI and web dashboard read.
        """
        s = self._engine_state

        # Regime from last signals
        if self._last_signals:
            chaos_signal = next(
                (sig for sig in self._last_signals if sig.module_name == "chaos"),
                None,
            )
            if chaos_signal and chaos_signal.regime:
                s.regime = chaos_signal.regime
                s.regime_confidence = chaos_signal.confidence

        # Signal confidences/directions
        s.signal_confidences = {
            sig.module_name: sig.confidence
            for sig in (self._last_signals or [])
        }
        s.signal_directions = {
            sig.module_name: sig.direction
            for sig in (self._last_signals or [])
        }

        # Fusion score
        if self._last_fusion_result is not None:
            s.fusion_score = self._last_fusion_result.composite_score

        # Price and spread from latest tick
        if self._tick_buffer and len(self._tick_buffer) > 0:
            arrays = self._tick_buffer.as_arrays()
            if arrays["bid"].size > 0:
                s.current_price = float(arrays["bid"][-1])
            if arrays["spread"].size > 0:
                s.spread = float(arrays["spread"][-1])

        # Equity
        s.equity = getattr(self, "_current_equity", 0.0)

        # Breaker status
        if self._breakers:
            try:
                snapshot = self._breakers.get_snapshot()
                s.breaker_status = {
                    "daily_drawdown": (
                        snapshot.daily_drawdown_state.value
                        if hasattr(snapshot, "daily_drawdown_state")
                        else "unknown"
                    )
                }
            except Exception:
                pass

        # Connection status
        s.is_connected = getattr(self, "_connected", False)

        # Kill switch
        if self._kill_switch:
            s.is_killed = getattr(self._kill_switch, "is_killed", False)

        # Order flow from last flow signal
        if self._last_signals:
            flow_sig = next(
                (sig for sig in self._last_signals if sig.module_name == "flow"),
                None,
            )
            if flow_sig and flow_sig.metadata:
                s.volume_delta = flow_sig.metadata.get("volume_delta", 0.0)
                s.bid_pressure = flow_sig.metadata.get("bid_pressure", 0.0)
                s.ask_pressure = flow_sig.metadata.get("ask_pressure", 0.0)

        # Recent trades from trade_logger
        if self._trade_logger:
            try:
                s.recent_trades = self._trade_logger.get_recent_trades(20)
            except Exception:
                pass

        # Learning mutations
        if self._learning_loop:
            try:
                status = self._learning_loop.get_learning_status()
                s.recent_mutations = status.get("recent_mutations", [])
            except Exception:
                pass

    async def _handle_kill(self) -> None:
        """Handle kill switch activation from dashboard callback."""
        if self._kill_switch:
            await self._kill_switch.activate(self._order_manager)

    async def _handle_pause(self) -> None:
        """Toggle pause state from dashboard callback."""
        self._engine_state.is_paused = not self._engine_state.is_paused

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

        # Build task list
        tasks = [
            self._tick_loop(),
            self._bar_loop(),
            self._health_loop(),
            self._signal_loop(),  # Phase 2 signal pipeline
        ]

        # Phase 4: Web dashboard as parallel async task
        if self._web_enabled and self._web_server:
            tasks.append(self._web_server.start())

        try:
            await asyncio.gather(*tasks)
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

        # Phase 4: Stop web dashboard server
        if self._web_server is not None:
            try:
                await self._web_server.stop()
            except Exception:
                self._logger.error("web_server_stop_error", exc_info=True)

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
