"""Regime-aware evaluation tagger per D-08.

Tags historical bars with RegimeState by running the chaos module over
sliding windows, then evaluates per-regime trading performance.

Used to answer: "Does the strategy work across all market regimes,
or only in trending/ranging conditions?"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import structlog

from fxsoqqabot.backtest.results import TradeRecord
from fxsoqqabot.signals.base import RegimeState, SignalOutput
from fxsoqqabot.signals.chaos.module import ChaosRegimeModule

if TYPE_CHECKING:
    import pandas as pd

    from fxsoqqabot.config.models import ChaosConfig


@dataclass(frozen=True, slots=True)
class RegimePerformance:
    """Performance metrics for a single regime.

    Attributes:
        regime: RegimeState value string.
        n_trades: Number of trades in this regime.
        win_rate: Fraction of winning trades (0.0 to 1.0).
        profit_factor: gross_profit / abs(gross_loss), 0.0 if no losses or no trades.
        avg_pnl: Average P&L per trade.
        total_pnl: Sum of all trade P&Ls.
        max_drawdown_pct: Maximum drawdown as fraction of peak equity for this regime's trades.
    """

    regime: str
    n_trades: int
    win_rate: float
    profit_factor: float
    avg_pnl: float
    total_pnl: float
    max_drawdown_pct: float


@dataclass(frozen=True, slots=True)
class RegimeEvalResult:
    """Regime-aware evaluation per D-08.

    Attributes:
        regime_performance: Dict keyed by RegimeState.value -> RegimePerformance.
        best_regime: RegimeState.value with highest profit_factor (among regimes with >= 5 trades).
        worst_regime: RegimeState.value with lowest profit_factor (among regimes with >= 5 trades).
        regimes_with_trades: How many of the 5 regimes had at least one trade.
    """

    regime_performance: dict[str, RegimePerformance]
    best_regime: str
    worst_regime: str
    regimes_with_trades: int


class RegimeTagger:
    """Tags historical bars with RegimeState by running the chaos module per D-08.

    Uses the same ChaosRegimeModule from Phase 2 to classify each bar's regime.
    Runs over sliding windows of bar data.
    """

    def __init__(self, config: ChaosConfig) -> None:
        self._chaos = ChaosRegimeModule(config)
        self._config = config
        self._logger = structlog.get_logger().bind(component="regime_tagger")

    async def tag_bars(
        self,
        bars_df: pd.DataFrame,
        window_size: int = 300,
    ) -> dict[int, str]:
        """Tag each bar timestamp with a RegimeState value.

        Runs the chaos module over sliding windows of the bar data. Steps
        through the DataFrame in increments of window_size // 10 for
        efficiency, then forward-fills regime tags for intermediate bars.

        Args:
            bars_df: DataFrame with columns: time, open, high, low, close, tick_volume.
                Time is unix seconds.
            window_size: Number of M1 bars in each chaos analysis window.

        Returns:
            Dict mapping unix timestamp (int) -> RegimeState.value (str).
        """
        n = len(bars_df)
        if n < window_size:
            # Not enough data for even one window -- tag all as RANGING
            tags: dict[int, str] = {}
            for t in bars_df["time"].values:
                tags[int(t)] = RegimeState.RANGING.value
            return tags

        times = bars_df["time"].values
        close = bars_df["close"].values.astype(np.float64)
        open_ = bars_df["open"].values.astype(np.float64)
        high = bars_df["high"].values.astype(np.float64)
        low = bars_df["low"].values.astype(np.float64)
        tick_volume = bars_df["tick_volume"].values.astype(np.float64)

        step = max(1, window_size // 10)
        regime_at: dict[int, str] = {}

        for end_idx in range(window_size, n + 1, step):
            start_idx = end_idx - window_size
            window_close = close[start_idx:end_idx]

            # Build bar_arrays matching the format ChaosRegimeModule expects
            # Resample M1 to M5 by grouping every 5 bars
            m5_close = _resample_to_m5(window_close)
            m5_open = _resample_to_m5(open_[start_idx:end_idx], agg="first")
            m5_high = _resample_to_m5(high[start_idx:end_idx], agg="max")
            m5_low = _resample_to_m5(low[start_idx:end_idx], agg="min")
            m5_time = _resample_to_m5(
                times[start_idx:end_idx].astype(np.float64), agg="first"
            )
            m5_vol = _resample_to_m5(tick_volume[start_idx:end_idx], agg="sum")

            bar_arrays = {
                "M5": {
                    "close": m5_close,
                    "open": m5_open,
                    "high": m5_high,
                    "low": m5_low,
                    "time": m5_time,
                    "tick_volume": m5_vol,
                },
            }

            # Build minimal tick_arrays from close prices
            tick_arrays = {
                "time_msc": (m5_time * 1000).astype(np.int64),
                "bid": m5_close,
                "ask": m5_close + 0.03,  # synthetic spread
                "last": m5_close,
                "spread": np.full_like(m5_close, 3.0),
                "volume_real": m5_vol,
            }

            try:
                signal: SignalOutput = await self._chaos.update(
                    tick_arrays, bar_arrays, None
                )
                regime_value = (
                    signal.regime.value
                    if signal.regime is not None
                    else RegimeState.RANGING.value
                )
            except Exception:
                regime_value = RegimeState.RANGING.value

            # Tag bars in this step range
            tag_start = max(start_idx, end_idx - step)
            for idx in range(tag_start, end_idx):
                if idx < n:
                    regime_at[int(times[idx])] = regime_value

        # Forward-fill any untagged early bars
        first_tagged_regime = RegimeState.RANGING.value
        for end_idx in range(window_size, n + 1, step):
            start_idx = end_idx - window_size
            if int(times[start_idx]) in regime_at:
                first_tagged_regime = regime_at[int(times[start_idx])]
                break

        for i in range(n):
            t = int(times[i])
            if t not in regime_at:
                regime_at[t] = first_tagged_regime
            else:
                # Once we hit a tagged bar, forward-fill from here
                first_tagged_regime = regime_at[t]

        return regime_at

    def evaluate_regime_performance(
        self,
        trades: tuple[TradeRecord, ...],
        regime_tags: dict[int, str] | None = None,
    ) -> RegimeEvalResult:
        """Group trades by regime and compute per-regime metrics per D-08.

        If regime_tags is provided, look up each trade's regime from its
        entry_time. Otherwise use the trade's .regime field (set during backtest).

        For each of the 5 RegimeState values:
        - Count trades, compute win_rate, profit_factor, avg_pnl, total_pnl
        - If no trades for a regime, return RegimePerformance with all zeros

        Identifies best_regime (highest profit_factor among regimes with >= 5 trades)
        and worst_regime (lowest profit_factor among regimes with >= 5 trades).

        Args:
            trades: Tuple of TradeRecord from backtest.
            regime_tags: Optional dict mapping unix timestamp -> RegimeState.value.

        Returns:
            RegimeEvalResult with per-regime performance.
        """
        # Group trades by regime
        regime_trades: dict[str, list[TradeRecord]] = {
            rs.value: [] for rs in RegimeState
        }

        for trade in trades:
            if regime_tags is not None and trade.entry_time in regime_tags:
                regime = regime_tags[trade.entry_time]
            else:
                regime = trade.regime

            if regime in regime_trades:
                regime_trades[regime].append(trade)
            else:
                # Unknown regime -- add to RANGING
                regime_trades[RegimeState.RANGING.value].append(trade)

        # Compute per-regime performance
        regime_perf: dict[str, RegimePerformance] = {}
        for regime_val, rtrades in regime_trades.items():
            regime_perf[regime_val] = _compute_regime_performance(
                regime_val, rtrades
            )

        # Find best/worst regime (among those with >= 5 trades)
        qualified = {
            k: v for k, v in regime_perf.items() if v.n_trades >= 5
        }
        if qualified:
            best = max(qualified, key=lambda k: qualified[k].profit_factor)
            worst = min(qualified, key=lambda k: qualified[k].profit_factor)
        else:
            # No regime has enough trades -- pick from all with any trades
            with_trades = {k: v for k, v in regime_perf.items() if v.n_trades > 0}
            if with_trades:
                best = max(with_trades, key=lambda k: with_trades[k].profit_factor)
                worst = min(with_trades, key=lambda k: with_trades[k].profit_factor)
            else:
                best = RegimeState.RANGING.value
                worst = RegimeState.RANGING.value

        regimes_with_trades = sum(
            1 for v in regime_perf.values() if v.n_trades > 0
        )

        return RegimeEvalResult(
            regime_performance=regime_perf,
            best_regime=best,
            worst_regime=worst,
            regimes_with_trades=regimes_with_trades,
        )


def _compute_regime_performance(
    regime: str,
    trades: list[TradeRecord],
) -> RegimePerformance:
    """Compute RegimePerformance for a list of trades in one regime."""
    if not trades:
        return RegimePerformance(
            regime=regime,
            n_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            avg_pnl=0.0,
            total_pnl=0.0,
            max_drawdown_pct=0.0,
        )

    pnls = [t.pnl for t in trades]
    n_trades = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / n_trades

    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss == 0:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss

    avg_pnl = sum(pnls) / n_trades
    total_pnl = sum(pnls)

    # Max drawdown from this regime's trade sequence
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    return RegimePerformance(
        regime=regime,
        n_trades=n_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_pnl=avg_pnl,
        total_pnl=total_pnl,
        max_drawdown_pct=max_dd,
    )


def _resample_to_m5(
    arr: np.ndarray,
    agg: str = "last",
) -> np.ndarray:
    """Resample M1 array to M5 by grouping every 5 bars.

    Uses numpy reshape for efficiency (no pandas groupby overhead).

    Args:
        arr: 1D numpy array of M1 values.
        agg: Aggregation method -- 'last', 'first', 'max', 'min', 'sum'.

    Returns:
        Resampled 1D array with length = len(arr) // 5.
    """
    n = len(arr)
    trim = n - (n % 5)
    if trim == 0:
        return arr[:1] if len(arr) > 0 else arr

    reshaped = arr[:trim].reshape(-1, 5)

    if agg == "last":
        return reshaped[:, -1]
    elif agg == "first":
        return reshaped[:, 0]
    elif agg == "max":
        return reshaped.max(axis=1)
    elif agg == "min":
        return reshaped.min(axis=1)
    elif agg == "sum":
        return reshaped.sum(axis=1)
    else:
        return reshaped[:, -1]
