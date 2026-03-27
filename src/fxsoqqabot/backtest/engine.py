"""BacktestEngine: synchronous replay engine using the exact same signal pipeline as live trading.

Per TEST-07: uses ChaosRegimeModule, OrderFlowModule, QuantumTimingModule,
FusionCore, PhaseBehavior, AdaptiveWeightTracker -- the same classes as TradingEngine.
Per Research Pattern 3: synchronous bar-by-bar replay (no async polling loops).
Per Pitfall 6: FIXED parameters across all walk-forward windows (no per-window optimization).

The engine replays M1 bars through the signal pipeline, collecting trade results.
No separate backtest code paths for signal analysis -- 100% shared analysis code.
"""

from __future__ import annotations

import pandas as pd
import structlog

from fxsoqqabot.backtest.clock import BacktestClock
from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.backtest.data_feed import BacktestDataFeed
from fxsoqqabot.backtest.executor import BacktestExecutor
from fxsoqqabot.backtest.results import BacktestResult
from fxsoqqabot.config.models import BotSettings
from fxsoqqabot.risk.sizing import PositionSizer
from fxsoqqabot.signals.base import RegimeState, SignalOutput
from fxsoqqabot.signals.chaos.module import ChaosRegimeModule
from fxsoqqabot.signals.flow.module import OrderFlowModule
from fxsoqqabot.signals.fusion.core import FusionCore
from fxsoqqabot.signals.fusion.phase_behavior import PhaseBehavior
from fxsoqqabot.signals.fusion.weights import AdaptiveWeightTracker
from fxsoqqabot.signals.timing.module import QuantumTimingModule
from fxsoqqabot.signals.timing.phase_transition import compute_atr


class BacktestEngine:
    """Synchronous replay engine using the exact same signal pipeline as live trading.

    Per TEST-07: uses ChaosRegimeModule, OrderFlowModule, QuantumTimingModule,
    FusionCore, PhaseBehavior, AdaptiveWeightTracker -- the same classes as TradingEngine.
    Per Research Pattern 3: synchronous bar-by-bar replay (no async polling loops).
    Per Pitfall 6: FIXED parameters across all walk-forward windows (no per-window optimization).
    """

    def __init__(self, settings: BotSettings, backtest_config: BacktestConfig) -> None:
        self._settings = settings
        self._bt_config = backtest_config
        self._logger = structlog.get_logger().bind(component="backtest_engine")

    async def run(self, bars_df: pd.DataFrame, run_id: str = "") -> BacktestResult:
        """Replay bars through signal pipeline and collect trade results.

        Creates fresh instances of all components for each run to ensure
        clean state between walk-forward windows.

        Args:
            bars_df: M1 bar DataFrame with columns time, open, high, low, close, volume.
                     Must be sorted by time ascending.
            run_id: Identifier for this backtest run (for structured logging).

        Returns:
            BacktestResult with all trades, equity curve, and performance metrics.
        """
        log = self._logger.bind(run_id=run_id, bars=len(bars_df))
        log.info("backtest_start")

        # Initialize signal modules (same as TradingEngine._initialize_components)
        sig_config = self._settings.signals
        chaos_module = ChaosRegimeModule(sig_config.chaos)
        flow_module = OrderFlowModule(sig_config.flow)
        timing_module = QuantumTimingModule(sig_config.timing)
        signal_modules = [chaos_module, flow_module, timing_module]
        for mod in signal_modules:
            await mod.initialize()

        # Initialize fusion (same as TradingEngine)
        fusion_core = FusionCore(sig_config.fusion)
        weight_tracker = AdaptiveWeightTracker(
            module_names=[m.name for m in signal_modules],
            alpha=sig_config.fusion.ema_alpha,
            warmup_trades=sig_config.fusion.weight_warmup_trades,
        )
        # Seed initial accuracies from config (for optimizer weight evolution)
        weight_tracker._accuracies["chaos"] = sig_config.fusion.weight_chaos_seed
        weight_tracker._accuracies["flow"] = sig_config.fusion.weight_flow_seed
        weight_tracker._accuracies["timing"] = sig_config.fusion.weight_timing_seed
        phase_behavior = PhaseBehavior(sig_config.fusion, self._settings.risk)

        # Initialize data feed and executor (fresh per run for clean state)
        clock = BacktestClock()
        data_feed = BacktestDataFeed(bars_df, self._bt_config, clock)
        executor = BacktestExecutor(self._bt_config, clock)

        # Position sizing (same as live)
        sizer = PositionSizer(self._settings.risk)

        # Replay loop: iterate bar-by-bar
        for bar_idx in range(len(bars_df)):
            bar = data_feed.advance_bar(bar_idx)
            clock.advance(bar["time"] * 1000)  # Convert seconds to milliseconds

            # Check SL/TP hits on current bar
            executor.check_sl_tp(bar)

            # Get data in same format as live engine
            tick_arrays = await data_feed.get_tick_arrays(self._bt_config.symbol)
            bar_arrays = await data_feed.get_bar_arrays(self._bt_config.symbol)

            # Skip if insufficient data for signal modules
            if tick_arrays["bid"].size < 10:
                continue

            # Run signal modules (same code path as TradingEngine._signal_loop)
            signals: list[SignalOutput] = []
            for module in signal_modules:
                try:
                    signal_out = await module.update(tick_arrays, bar_arrays, None)
                    signals.append(signal_out)
                except Exception:
                    log.debug(
                        "signal_module_error",
                        module=module.name,
                        bar_idx=bar_idx,
                        exc_info=True,
                    )

            if not signals:
                continue

            # Get adaptive weights
            weights = weight_tracker.get_weights()

            # Get equity for phase-aware threshold
            equity = executor.equity

            # Get confidence threshold for current equity
            threshold = phase_behavior.get_confidence_threshold(equity)

            # Fuse signals
            fusion_result = fusion_core.fuse(signals, weights, threshold)

            # Trade evaluation (simplified vs live -- no TradeManager dependency on OrderManager)
            if (
                fusion_result.should_trade
                and len(executor._positions) < sig_config.fusion.max_concurrent_positions
            ):
                # Compute ATR for SL/TP (same logic as TradingEngine)
                m5_bars = bar_arrays.get("M5", {})
                current_atr = 0.0
                if "high" in m5_bars and len(m5_bars["high"]) > 0:
                    atr_array = compute_atr(
                        m5_bars["high"],
                        m5_bars["low"],
                        m5_bars["close"],
                        period=sig_config.fusion.sl_atr_period,
                    )
                    current_atr = float(atr_array[-1])

                if current_atr > 0:
                    # SL distance (same as live)
                    sl_multiplier = sig_config.fusion.sl_atr_base_multiplier
                    if fusion_result.regime == RegimeState.HIGH_CHAOS:
                        sl_multiplier *= sig_config.fusion.sl_chaos_widen_factor

                    sl_distance = current_atr * sl_multiplier

                    # Compute lot size via PositionSizer
                    sizing = sizer.calculate_lot_size(
                        equity=equity, sl_distance=sl_distance
                    )
                    if sizing.can_trade:
                        action = "buy" if fusion_result.direction > 0 else "sell"

                        # TP distance from regime RR
                        rr_ratio = sig_config.fusion.trending_rr_ratio  # default
                        if fusion_result.regime in (
                            RegimeState.TRENDING_UP,
                            RegimeState.TRENDING_DOWN,
                        ):
                            rr_ratio = sig_config.fusion.trending_rr_ratio
                        elif fusion_result.regime == RegimeState.RANGING:
                            rr_ratio = sig_config.fusion.ranging_rr_ratio
                        elif fusion_result.regime == RegimeState.HIGH_CHAOS:
                            rr_ratio = sig_config.fusion.high_chaos_rr_ratio

                        tp_distance = sl_distance * rr_ratio

                        executor.open_position(
                            action=action,
                            volume=sizing.lot_size,
                            bar=bar,
                            sl_distance=sl_distance,
                            tp_distance=tp_distance,
                            regime=fusion_result.regime.value,
                        )

        # Close any remaining positions at final bar
        if len(bars_df) > 0:
            final_bar = {
                "time": int(bars_df["time"].iloc[-1]),
                "open": float(bars_df["open"].iloc[-1]),
                "high": float(bars_df["high"].iloc[-1]),
                "low": float(bars_df["low"].iloc[-1]),
                "close": float(bars_df["close"].iloc[-1]),
                "volume": int(bars_df["volume"].iloc[-1]),
            }
            executor.close_all(final_bar)

        # Build result
        result = BacktestResult(
            trades=tuple(executor.closed_trades),
            starting_equity=self._bt_config.starting_equity,
            final_equity=executor.equity,
            total_commission=sum(t.commission for t in executor.closed_trades),
            total_bars_processed=len(bars_df),
            start_time=int(bars_df["time"].iloc[0]) if len(bars_df) > 0 else 0,
            end_time=int(bars_df["time"].iloc[-1]) if len(bars_df) > 0 else 0,
        )
        log.info(
            "backtest_complete",
            trades=result.n_trades,
            final_equity=result.final_equity,
            win_rate=result.win_rate,
        )
        return result
