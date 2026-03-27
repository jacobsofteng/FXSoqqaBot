"""Walk-forward validation and out-of-sample holdout evaluation.

Per D-05: Rolling windows with 6-month train + 2-month validation, stepping by 2 months.
Per D-06: Dual threshold -- >= 70% of windows profitable AND aggregate profit factor > 1.5.
Per D-12: Most recent 6 months reserved as untouched out-of-sample holdout.
Per D-13: OOS hard fail when PF ratio < 50% of in-sample or max DD > 2x in-sample.
Per Pitfall 6: FIXED parameters across ALL windows (no per-window optimization).

The walk-forward coordinator drives the BacktestEngine across rolling windows
and evaluates pass/fail criteria. The OOS evaluator compares holdout performance
to in-sample metrics for overfitting detection.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.backtest.engine import BacktestEngine
from fxsoqqabot.backtest.historical import HistoricalDataLoader
from fxsoqqabot.backtest.results import BacktestResult

# Calendar month approximation: 30.44 days * 86400 seconds
MONTH_SECONDS = int(30.44 * 86400)


@dataclass(frozen=True, slots=True)
class WindowResult:
    """Result of one walk-forward window (train + validation)."""

    window_idx: int
    train_start: int  # Unix timestamp seconds
    train_end: int
    val_start: int
    val_end: int
    train_result: BacktestResult
    val_result: BacktestResult
    is_profitable: bool  # val_result.final_equity > val_result.starting_equity


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """Aggregate walk-forward validation result per D-06."""

    windows: tuple[WindowResult, ...]
    profitable_pct: float  # Fraction of validation windows that are profitable
    aggregate_profit_factor: float  # PF across all validation trades combined
    passes_threshold: bool  # Both D-06 criteria met
    min_profitable_pct_required: float  # D-06 criterion 1 (0.70)
    min_profit_factor_required: float  # D-06 criterion 2 (1.5)


@dataclass(frozen=True, slots=True)
class OOSResult:
    """Out-of-sample holdout evaluation result per D-12/D-13."""

    oos_result: BacktestResult
    in_sample_profit_factor: float  # Aggregate IS PF for comparison
    in_sample_max_drawdown_pct: float  # Aggregate IS max DD for comparison
    oos_profit_factor: float
    oos_max_drawdown_pct: float
    pf_ratio: float  # oos_pf / is_pf
    dd_ratio: float  # oos_dd / is_dd
    passes_threshold: bool  # Per D-13: pf_ratio >= 0.50 AND dd_ratio <= 2.0
    is_overfit: bool  # Inverse of passes_threshold


class WalkForwardValidator:
    """Walk-forward validation coordinator per D-05, D-06, D-12, D-13.

    Generates rolling windows: 6 months train, 2 months validation, rolling by 2 months.
    Reserves most recent 6 months as OOS holdout per D-12.
    """

    def __init__(
        self,
        engine: BacktestEngine,
        loader: HistoricalDataLoader,
        config: BacktestConfig,
    ) -> None:
        self._engine = engine
        self._loader = loader
        self._config = config
        self._logger = structlog.get_logger().bind(component="walk_forward")

    def generate_windows(self) -> list[tuple[int, int, int, int]]:
        """Generate walk-forward window boundaries per D-05.

        Returns list of (train_start, train_end, val_start, val_end) timestamps.

        Window generation:
        1. Get full data time range from loader.get_time_range()
        2. Compute holdout_start = max_time - (holdout_months * MONTH_SECONDS)
        3. First window: train_start = data_start, train_end = data_start + train_months
        4. val_start = train_end, val_end = val_start + val_months
        5. Roll forward by step_months each iteration
        6. Stop when val_end would exceed holdout_start

        Uses calendar month approximation: 1 month = 30.44 days * 86400 seconds.
        """
        data_start, data_end = self._loader.get_time_range()
        holdout_start = data_end - self._config.holdout_months * MONTH_SECONDS

        train_months_sec = self._config.wf_train_months * MONTH_SECONDS
        val_months_sec = self._config.wf_validation_months * MONTH_SECONDS
        step_sec = self._config.wf_step_months * MONTH_SECONDS

        windows: list[tuple[int, int, int, int]] = []
        train_start = data_start

        while True:
            train_end = train_start + train_months_sec
            val_start = train_end
            val_end = val_start + val_months_sec

            # Stop if validation window would exceed or overlap holdout
            if val_end > holdout_start:
                break

            windows.append((train_start, train_end, val_start, val_end))

            # Roll forward by step_months
            train_start += step_sec

        self._logger.info(
            "windows_generated",
            count=len(windows),
            holdout_start=holdout_start,
            data_range=(data_start, data_end),
        )

        return windows

    async def run_walk_forward(self) -> WalkForwardResult:
        """Execute walk-forward validation across all windows.

        For each window:
        1. Load training bars via loader.load_bars(train_start, train_end)
        2. Run engine on training data (for metrics -- per Pitfall 6, NO parameter optimization)
        3. Load validation bars via loader.load_bars(val_start, val_end)
        4. Run engine on validation data with SAME fixed parameters
        5. Record WindowResult

        Per Pitfall 6: use FIXED parameters across ALL windows.
        The purpose is to validate the strategy generalizes, not to optimize per window.
        """
        windows_spec = self.generate_windows()
        window_results: list[WindowResult] = []

        for idx, (train_start, train_end, val_start, val_end) in enumerate(windows_spec):
            self._logger.info(
                "window_start",
                window=idx,
                train_range=(train_start, train_end),
                val_range=(val_start, val_end),
            )

            # Load and run training period
            train_bars = self._loader.load_bars(train_start, train_end)
            train_result = await self._engine.run(
                train_bars, run_id=f"wf_train_{idx}"
            )

            # Load and run validation period (SAME parameters -- no optimization)
            val_bars = self._loader.load_bars(val_start, val_end)
            val_result = await self._engine.run(
                val_bars, run_id=f"wf_val_{idx}"
            )

            is_profitable = val_result.final_equity > val_result.starting_equity

            window_results.append(
                WindowResult(
                    window_idx=idx,
                    train_start=train_start,
                    train_end=train_end,
                    val_start=val_start,
                    val_end=val_end,
                    train_result=train_result,
                    val_result=val_result,
                    is_profitable=is_profitable,
                )
            )

            self._logger.info(
                "window_complete",
                window=idx,
                val_pf=val_result.profit_factor,
                val_equity=val_result.final_equity,
                is_profitable=is_profitable,
            )

        # Compute aggregate metrics
        profitable_count = sum(1 for w in window_results if w.is_profitable)
        profitable_pct = profitable_count / len(window_results) if window_results else 0.0

        aggregate_pf = self._compute_aggregate_validation_pf(window_results)

        passes = (
            profitable_pct >= self._config.wf_min_profitable_pct
            and aggregate_pf >= self._config.wf_min_profit_factor
        )

        result = WalkForwardResult(
            windows=tuple(window_results),
            profitable_pct=profitable_pct,
            aggregate_profit_factor=aggregate_pf,
            passes_threshold=passes,
            min_profitable_pct_required=self._config.wf_min_profitable_pct,
            min_profit_factor_required=self._config.wf_min_profit_factor,
        )

        self._logger.info(
            "walk_forward_complete",
            windows=len(window_results),
            profitable_pct=profitable_pct,
            aggregate_pf=aggregate_pf,
            passes=passes,
        )

        return result

    async def evaluate_oos(self, wf_result: WalkForwardResult) -> OOSResult:
        """Run out-of-sample holdout evaluation per D-12/D-13.

        1. Compute holdout_start = max_time - holdout_months
        2. Load holdout bars via loader.load_bars(holdout_start, max_time)
        3. Run engine on holdout data
        4. Compare OOS metrics to aggregate in-sample metrics from walk-forward
        5. Apply D-13 hard fail criteria:
           - oos_pf / is_pf >= 0.50 (OOS profit factor at least 50% of IS)
           - oos_dd / is_dd <= 2.0 (OOS max drawdown at most 2x IS)
        """
        _, data_end = self._loader.get_time_range()
        holdout_start = data_end - self._config.holdout_months * MONTH_SECONDS

        self._logger.info(
            "oos_start",
            holdout_start=holdout_start,
            holdout_end=data_end,
        )

        # Load and run holdout period
        holdout_bars = self._loader.load_bars(holdout_start, data_end)
        oos_backtest = await self._engine.run(holdout_bars, run_id="oos_holdout")

        # Get aggregate in-sample metrics from walk-forward windows
        is_pf, is_max_dd = self._aggregate_in_sample_metrics(wf_result)

        oos_pf = oos_backtest.profit_factor
        oos_dd = oos_backtest.max_drawdown_pct

        # Compute ratios (handle division by zero)
        pf_ratio = oos_pf / is_pf if is_pf > 0 else 0.0
        dd_ratio = oos_dd / is_max_dd if is_max_dd > 0 else 0.0

        # D-13 hard fail criteria
        passes = (
            pf_ratio >= self._config.oos_min_pf_ratio
            and dd_ratio <= self._config.oos_max_dd_ratio
        )

        result = OOSResult(
            oos_result=oos_backtest,
            in_sample_profit_factor=is_pf,
            in_sample_max_drawdown_pct=is_max_dd,
            oos_profit_factor=oos_pf,
            oos_max_drawdown_pct=oos_dd,
            pf_ratio=pf_ratio,
            dd_ratio=dd_ratio,
            passes_threshold=passes,
            is_overfit=not passes,
        )

        self._logger.info(
            "oos_complete",
            oos_pf=oos_pf,
            oos_dd=oos_dd,
            pf_ratio=pf_ratio,
            dd_ratio=dd_ratio,
            passes=passes,
            is_overfit=not passes,
        )

        return result

    def _aggregate_in_sample_metrics(
        self, wf_result: WalkForwardResult
    ) -> tuple[float, float]:
        """Compute aggregate IS profit factor and max drawdown from all training windows.

        Profit factor: sum of all winning trade PnLs / abs(sum of all losing trade PnLs).
        Max drawdown: worst drawdown across any single training window.
        Returns (aggregate_pf, worst_max_dd).
        """
        total_profit = 0.0
        total_loss = 0.0
        worst_dd = 0.0

        for window in wf_result.windows:
            # Aggregate trades from training results for in-sample PF
            for trade in window.train_result.trades:
                if trade.pnl > 0:
                    total_profit += trade.pnl
                elif trade.pnl < 0:
                    total_loss += abs(trade.pnl)

            # Track worst drawdown across training windows
            dd = window.train_result.max_drawdown_pct
            if dd > worst_dd:
                worst_dd = dd

        aggregate_pf = total_profit / total_loss if total_loss > 0 else (
            float("inf") if total_profit > 0 else 0.0
        )

        return aggregate_pf, worst_dd

    @staticmethod
    def _compute_aggregate_validation_pf(
        windows: list[WindowResult],
    ) -> float:
        """Compute aggregate profit factor across all validation trades.

        Combines all validation trade PnLs across all windows into a single PF.
        """
        total_profit = 0.0
        total_loss = 0.0

        for window in windows:
            for trade in window.val_result.trades:
                if trade.pnl > 0:
                    total_profit += trade.pnl
                elif trade.pnl < 0:
                    total_loss += abs(trade.pnl)

        if total_loss == 0:
            return float("inf") if total_profit > 0 else 0.0
        return total_profit / total_loss
