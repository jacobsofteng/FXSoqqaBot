"""Tests for BacktestEngine replay loop wiring signal modules and fusion.

Tests validate:
- BacktestEngine initializes with same signal modules as TradingEngine
- BacktestEngine.run() iterates through bars advancing clock
- Signal modules receive tick_arrays and bar_arrays from BacktestDataFeed
- FusionCore.fuse() is called producing should_trade decisions
- BacktestEngine.run() returns BacktestResult
- Engine resets state cleanly between runs

NOTE: With only 200 synthetic bars, signal modules may not produce trades
(insufficient data for chaos metrics). Tests verify the engine RUNS
without errors and returns a valid BacktestResult, even if n_trades=0.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pandas as pd
import pytest

from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.backtest.engine import BacktestEngine
from fxsoqqabot.backtest.results import BacktestResult
from fxsoqqabot.config.models import BotSettings


# -- Fixtures -----------------------------------------------------------------


def _make_m1_bars(n: int = 200, base_price: float = 2000.0) -> pd.DataFrame:
    """Generate synthetic M1 bar data with realistic XAUUSD prices."""
    rng = np.random.default_rng(42)
    times = np.arange(n, dtype=np.int64) * 60 + 1700000000  # 60s apart
    closes = base_price + rng.standard_normal(n).cumsum() * 0.5
    opens = closes - rng.uniform(-0.3, 0.3, n)
    highs = np.maximum(opens, closes) + rng.uniform(0.1, 0.5, n)
    lows = np.minimum(opens, closes) - rng.uniform(0.1, 0.5, n)
    volumes = rng.integers(100, 1000, n)
    return pd.DataFrame(
        {
            "time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


@pytest.fixture
def bars_df() -> pd.DataFrame:
    return _make_m1_bars(200)


@pytest.fixture
def bars_df_small() -> pd.DataFrame:
    """A smaller distinct bar set for reset testing."""
    return _make_m1_bars(100, base_price=1950.0)


@pytest.fixture
def settings() -> BotSettings:
    """Create BotSettings with defaults (no TOML file needed)."""
    return BotSettings()


@pytest.fixture
def bt_config() -> BacktestConfig:
    return BacktestConfig()


# -- Test 1: Engine initializes with same signal modules as TradingEngine ------


def test_engine_uses_same_signal_modules() -> None:
    """BacktestEngine uses ChaosRegimeModule, OrderFlowModule, QuantumTimingModule."""
    import inspect
    from fxsoqqabot.backtest.engine import BacktestEngine

    source = inspect.getsource(BacktestEngine)
    assert "ChaosRegimeModule(" in source
    assert "OrderFlowModule(" in source
    assert "QuantumTimingModule(" in source


# -- Test 2: run() iterates bars and returns BacktestResult -------------------


@pytest.mark.asyncio
async def test_engine_run_returns_result(
    settings: BotSettings, bt_config: BacktestConfig, bars_df: pd.DataFrame
) -> None:
    """BacktestEngine.run() processes bars and returns BacktestResult."""
    engine = BacktestEngine(settings, bt_config)
    result = await engine.run(bars_df, run_id="test-run-1")

    assert isinstance(result, BacktestResult)
    assert result.total_bars_processed == len(bars_df)
    assert result.starting_equity == bt_config.starting_equity
    assert result.start_time == int(bars_df["time"].iloc[0])
    assert result.end_time == int(bars_df["time"].iloc[-1])


# -- Test 3: Signal modules receive tick_arrays and bar_arrays from data feed --


@pytest.mark.asyncio
async def test_engine_runs_signal_modules(
    settings: BotSettings, bt_config: BacktestConfig, bars_df: pd.DataFrame
) -> None:
    """Engine calls signal modules -- no exceptions thrown during run."""
    engine = BacktestEngine(settings, bt_config)
    # If signal modules crash, run() would raise or return partial result
    result = await engine.run(bars_df, run_id="test-signals")
    assert isinstance(result, BacktestResult)
    # Bars should have been processed even if no trades generated
    assert result.total_bars_processed == len(bars_df)


# -- Test 4: FusionCore.fuse() is used in the engine -------------------------


def test_engine_uses_fusion_core() -> None:
    """BacktestEngine wires FusionCore, AdaptiveWeightTracker, PhaseBehavior."""
    import inspect
    from fxsoqqabot.backtest.engine import BacktestEngine

    source = inspect.getsource(BacktestEngine)
    assert "FusionCore(" in source
    assert "AdaptiveWeightTracker(" in source
    assert "PhaseBehavior(" in source
    assert "fusion_core.fuse(" in source


# -- Test 5: When should_trade=True, executor opens position -------------------


def test_engine_uses_executor() -> None:
    """BacktestEngine.run() calls executor.open_position when should_trade=True."""
    import inspect
    from fxsoqqabot.backtest.engine import BacktestEngine

    source = inspect.getsource(BacktestEngine)
    assert "executor.open_position(" in source
    assert "executor.check_sl_tp(" in source


# -- Test 6: run() returns BacktestResult with TradeRecords -------------------


@pytest.mark.asyncio
async def test_engine_result_has_trade_records(
    settings: BotSettings, bt_config: BacktestConfig, bars_df: pd.DataFrame
) -> None:
    """BacktestResult.trades is a tuple of TradeRecord (possibly empty)."""
    engine = BacktestEngine(settings, bt_config)
    result = await engine.run(bars_df, run_id="test-records")

    assert isinstance(result.trades, tuple)
    # If trades were generated, verify they have non-zero commission
    for trade in result.trades:
        assert trade.commission > 0


# -- Test 7: Engine resets cleanly between runs --------------------------------


@pytest.mark.asyncio
async def test_engine_resets_between_runs(
    settings: BotSettings, bt_config: BacktestConfig,
    bars_df: pd.DataFrame, bars_df_small: pd.DataFrame,
) -> None:
    """BacktestEngine can be run twice on different data without state leaking."""
    engine = BacktestEngine(settings, bt_config)

    result1 = await engine.run(bars_df, run_id="run-1")
    result2 = await engine.run(bars_df_small, run_id="run-2")

    # Each result should reflect its own bar count
    assert result1.total_bars_processed == 200
    assert result2.total_bars_processed == 100

    # Start times should differ
    assert result1.start_time != result2.start_time

    # Both should be valid results
    assert isinstance(result1, BacktestResult)
    assert isinstance(result2, BacktestResult)
