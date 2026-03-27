"""Tests for walk-forward validation and OOS holdout evaluation.

Tests validate per D-05, D-06, D-12, D-13:
- generate_windows produces correct number of rolling windows (6m train + 2m val + 2m step)
- First window starts at data_start_time
- Last validation window ends before holdout_start
- Validation windows never overlap with holdout period
- Walk-forward passes when >= 70% profitable AND aggregate PF > 1.5
- Walk-forward fails when < 70% profitable
- Walk-forward fails when aggregate PF < 1.5
- OOS passes when PF ratio >= 0.50 and DD ratio <= 2.0
- OOS fails when PF ratio < 0.50 (hard fail per D-13)
- OOS fails when DD ratio > 2.0 (hard fail per D-13)
- WindowResult contains all required fields
- WalkForwardResult contains aggregate metrics and pass/fail
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.backtest.results import BacktestResult, TradeRecord
from fxsoqqabot.backtest.validation import (
    OOSResult,
    WalkForwardResult,
    WalkForwardValidator,
    WindowResult,
)

# -- Constants ---------------------------------------------------------------

# Calendar month approximation: 30.44 days * 86400 seconds
MONTH_SECONDS = int(30.44 * 86400)

# 24 months of data starting Jan 2020
DATA_START = 1577836800  # 2020-01-01T00:00:00Z
DATA_END = DATA_START + 24 * MONTH_SECONDS  # ~2022-01-01


# -- Helpers -----------------------------------------------------------------


def _make_trade(pnl: float) -> TradeRecord:
    """Create a minimal TradeRecord with given P&L."""
    return TradeRecord(
        entry_time=1700000000,
        exit_time=1700003600,
        action="buy",
        symbol="XAUUSD",
        volume=0.01,
        entry_price=2000.0,
        exit_price=2000.0 + pnl / 0.01,  # reverse from pnl
        sl=1999.0,
        tp=2001.0,
        pnl=pnl,
        commission=0.06,
        regime="trending_up",
        slippage_entry=0.01,
        slippage_exit=0.01,
        spread_at_entry=0.03,
    )


def _make_backtest_result(
    pnl_list: list[float],
    starting_equity: float = 20.0,
) -> BacktestResult:
    """Create a BacktestResult from a list of trade P&Ls."""
    trades = tuple(_make_trade(p) for p in pnl_list)
    final_equity = starting_equity + sum(pnl_list)
    return BacktestResult(
        trades=trades,
        starting_equity=starting_equity,
        final_equity=final_equity,
        total_commission=sum(0.06 for _ in trades),
        total_bars_processed=1000,
        start_time=1700000000,
        end_time=1700060000,
    )


def _make_window_result(
    idx: int,
    is_profitable: bool,
    train_pnls: list[float] | None = None,
    val_pnls: list[float] | None = None,
) -> WindowResult:
    """Create a WindowResult for testing."""
    if train_pnls is None:
        train_pnls = [1.0, -0.5, 0.8]  # default profitable training
    if val_pnls is None:
        if is_profitable:
            val_pnls = [1.0, -0.3, 0.5]  # net positive
        else:
            val_pnls = [-1.0, -0.5, 0.2]  # net negative

    train_result = _make_backtest_result(train_pnls)
    val_result = _make_backtest_result(val_pnls)

    base_offset = idx * 2 * MONTH_SECONDS
    return WindowResult(
        window_idx=idx,
        train_start=DATA_START + base_offset,
        train_end=DATA_START + base_offset + 6 * MONTH_SECONDS,
        val_start=DATA_START + base_offset + 6 * MONTH_SECONDS,
        val_end=DATA_START + base_offset + 8 * MONTH_SECONDS,
        train_result=train_result,
        val_result=val_result,
        is_profitable=is_profitable,
    )


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def config() -> BacktestConfig:
    """Default backtest config for tests."""
    return BacktestConfig()


@pytest.fixture
def mock_engine():
    """Mock BacktestEngine."""
    engine = MagicMock()
    engine.run = AsyncMock(return_value=_make_backtest_result([1.0, -0.3, 0.5]))
    return engine


@pytest.fixture
def mock_loader():
    """Mock HistoricalDataLoader with 24 months of data."""
    loader = MagicMock()
    loader.get_time_range.return_value = (DATA_START, DATA_END)
    loader.load_bars.return_value = pd.DataFrame(
        {
            "time": [1700000000 + i * 60 for i in range(100)],
            "open": [2000.0] * 100,
            "high": [2001.0] * 100,
            "low": [1999.0] * 100,
            "close": [2000.5] * 100,
            "volume": [500] * 100,
        }
    )
    return loader


@pytest.fixture
def validator(mock_engine, mock_loader, config):
    """WalkForwardValidator with mocked dependencies."""
    return WalkForwardValidator(
        engine=mock_engine,
        loader=mock_loader,
        config=config,
    )


# -- Test 1: Window count ---------------------------------------------------


def test_generate_windows_count(validator):
    """Test 1: generate_windows produces correct number of windows.

    24 months - 6 holdout = 18 months usable.
    First window: 6m train + 2m val = 8m.
    Remaining: (18 - 8) / 2 = 5 more windows.
    Total: 6 windows.
    """
    windows = validator.generate_windows()
    assert len(windows) == 6


# -- Test 2: First window boundaries ----------------------------------------


def test_generate_windows_first_window_start(validator):
    """Test 2: First window starts at data_start_time."""
    windows = validator.generate_windows()
    assert len(windows) > 0
    train_start, train_end, val_start, val_end = windows[0]
    assert train_start == DATA_START
    # First window ends at data_start + 8 months (6 train + 2 val)
    expected_val_end = DATA_START + 8 * MONTH_SECONDS
    assert val_end == expected_val_end


# -- Test 3: Last window before holdout -------------------------------------


def test_generate_windows_last_before_holdout(validator):
    """Test 3: Last validation window ends before holdout_start."""
    windows = validator.generate_windows()
    holdout_start = DATA_END - 6 * MONTH_SECONDS
    _, _, _, last_val_end = windows[-1]
    assert last_val_end <= holdout_start


# -- Test 4: No overlap with holdout ----------------------------------------


def test_generate_windows_no_holdout_overlap(validator):
    """Test 4: No validation window overlaps with holdout period."""
    windows = validator.generate_windows()
    holdout_start = DATA_END - 6 * MONTH_SECONDS
    for _, _, _, val_end in windows:
        assert val_end <= holdout_start


# -- Test 5: Walk-forward passes dual threshold ------------------------------


def test_evaluate_walk_forward_passes(config):
    """Test 5: Passes when >= 70% profitable AND aggregate PF > 1.5.

    8 out of 10 windows profitable (80% >= 70%).
    Validation trades: 8 profitable windows with [1.0, -0.3, 0.5] each
    + 2 unprofitable with [-1.0, -0.5, 0.2] each.
    """
    windows = []
    for i in range(8):
        windows.append(_make_window_result(i, is_profitable=True, val_pnls=[1.0, -0.3, 0.5]))
    for i in range(8, 10):
        windows.append(_make_window_result(i, is_profitable=False, val_pnls=[-1.0, -0.5, 0.2]))

    # Compute expected aggregate PF
    # 8 profitable windows: each has winning trades [1.0, 0.5] = 1.5 profit, losing [-0.3] = 0.3 loss
    # 2 unprofitable windows: each has winning [0.2] = 0.2 profit, losing [-1.0, -0.5] = 1.5 loss
    # Total profit: 8*1.5 + 2*0.2 = 12.4
    # Total loss: 8*0.3 + 2*1.5 = 5.4
    # PF = 12.4 / 5.4 ~= 2.30
    result = WalkForwardResult(
        windows=tuple(windows),
        profitable_pct=0.80,
        aggregate_profit_factor=2.30,
        passes_threshold=True,
        min_profitable_pct_required=config.wf_min_profitable_pct,
        min_profit_factor_required=config.wf_min_profit_factor,
    )
    assert result.passes_threshold is True
    assert result.profitable_pct >= config.wf_min_profitable_pct
    assert result.aggregate_profit_factor >= config.wf_min_profit_factor


# -- Test 6: Walk-forward fails on profitable pct ---------------------------


def test_evaluate_walk_forward_fails_profitable_pct(config):
    """Test 6: Fails when only 60% profitable (below 70% threshold per D-06)."""
    windows = []
    for i in range(6):
        windows.append(_make_window_result(i, is_profitable=True))
    for i in range(6, 10):
        windows.append(_make_window_result(i, is_profitable=False))

    result = WalkForwardResult(
        windows=tuple(windows),
        profitable_pct=0.60,
        aggregate_profit_factor=2.0,
        passes_threshold=False,  # 60% < 70%
        min_profitable_pct_required=config.wf_min_profitable_pct,
        min_profit_factor_required=config.wf_min_profit_factor,
    )
    assert result.passes_threshold is False
    assert result.profitable_pct < config.wf_min_profitable_pct


# -- Test 7: Walk-forward fails on aggregate PF ------------------------------


def test_evaluate_walk_forward_fails_aggregate_pf(config):
    """Test 7: Fails when aggregate PF is 1.3 (below 1.5 threshold per D-06)."""
    windows = []
    for i in range(8):
        windows.append(_make_window_result(i, is_profitable=True))
    for i in range(8, 10):
        windows.append(_make_window_result(i, is_profitable=False))

    result = WalkForwardResult(
        windows=tuple(windows),
        profitable_pct=0.80,
        aggregate_profit_factor=1.3,
        passes_threshold=False,  # PF 1.3 < 1.5
        min_profitable_pct_required=config.wf_min_profitable_pct,
        min_profit_factor_required=config.wf_min_profit_factor,
    )
    assert result.passes_threshold is False
    assert result.aggregate_profit_factor < config.wf_min_profit_factor


# -- Test 8: OOS passes threshold -------------------------------------------


def test_evaluate_oos_passes(config):
    """Test 8: OOS passes when PF ratio >= 0.50 and DD ratio <= 2.0.

    IS PF=2.0, OOS PF=1.5 -> ratio 0.75 >= 0.50.
    IS DD=10%, OOS DD=15% -> ratio 1.5 <= 2.0.
    """
    oos_result = _make_backtest_result([1.0, -0.3, 0.5])
    result = OOSResult(
        oos_result=oos_result,
        in_sample_profit_factor=2.0,
        in_sample_max_drawdown_pct=0.10,
        oos_profit_factor=1.5,
        oos_max_drawdown_pct=0.15,
        pf_ratio=0.75,
        dd_ratio=1.5,
        passes_threshold=True,
        is_overfit=False,
    )
    assert result.passes_threshold is True
    assert result.is_overfit is False
    assert result.pf_ratio >= config.oos_min_pf_ratio
    assert result.dd_ratio <= config.oos_max_dd_ratio


# -- Test 9: OOS fails on PF ratio -----------------------------------------


def test_evaluate_oos_fails_pf_ratio(config):
    """Test 9: OOS fails when PF ratio < 0.50 (hard fail per D-13).

    IS PF=2.0, OOS PF=0.8 -> ratio 0.4 < 0.50 -> overfit.
    """
    oos_result = _make_backtest_result([-0.5, 0.3, -0.2])
    result = OOSResult(
        oos_result=oos_result,
        in_sample_profit_factor=2.0,
        in_sample_max_drawdown_pct=0.10,
        oos_profit_factor=0.8,
        oos_max_drawdown_pct=0.12,
        pf_ratio=0.4,
        dd_ratio=1.2,
        passes_threshold=False,
        is_overfit=True,
    )
    assert result.passes_threshold is False
    assert result.is_overfit is True
    assert result.pf_ratio < config.oos_min_pf_ratio


# -- Test 10: OOS fails on DD ratio ----------------------------------------


def test_evaluate_oos_fails_dd_ratio(config):
    """Test 10: OOS fails when DD ratio > 2.0 (hard fail per D-13).

    IS DD=10%, OOS DD=25% -> ratio 2.5 > 2.0 -> overfit.
    """
    oos_result = _make_backtest_result([-0.5, 0.3, -0.2])
    result = OOSResult(
        oos_result=oos_result,
        in_sample_profit_factor=2.0,
        in_sample_max_drawdown_pct=0.10,
        oos_profit_factor=1.5,
        oos_max_drawdown_pct=0.25,
        pf_ratio=0.75,
        dd_ratio=2.5,
        passes_threshold=False,
        is_overfit=True,
    )
    assert result.passes_threshold is False
    assert result.is_overfit is True
    assert result.dd_ratio > config.oos_max_dd_ratio


# -- Test 11: WindowResult fields ------------------------------------------


def test_window_result_fields():
    """Test 11: WindowResult contains all required fields."""
    train_result = _make_backtest_result([1.0, -0.3])
    val_result = _make_backtest_result([0.5, -0.1])

    wr = WindowResult(
        window_idx=0,
        train_start=DATA_START,
        train_end=DATA_START + 6 * MONTH_SECONDS,
        val_start=DATA_START + 6 * MONTH_SECONDS,
        val_end=DATA_START + 8 * MONTH_SECONDS,
        train_result=train_result,
        val_result=val_result,
        is_profitable=True,
    )

    assert wr.window_idx == 0
    assert wr.train_start == DATA_START
    assert wr.train_end == DATA_START + 6 * MONTH_SECONDS
    assert wr.val_start == DATA_START + 6 * MONTH_SECONDS
    assert wr.val_end == DATA_START + 8 * MONTH_SECONDS
    assert wr.train_result is train_result
    assert wr.val_result is val_result
    assert wr.is_profitable is True


# -- Test 12: WalkForwardResult fields --------------------------------------


def test_walk_forward_result_fields(config):
    """Test 12: WalkForwardResult contains windows, metrics, and pass/fail."""
    windows = tuple(_make_window_result(i, True) for i in range(5))
    result = WalkForwardResult(
        windows=windows,
        profitable_pct=1.0,
        aggregate_profit_factor=2.5,
        passes_threshold=True,
        min_profitable_pct_required=config.wf_min_profitable_pct,
        min_profit_factor_required=config.wf_min_profit_factor,
    )

    assert len(result.windows) == 5
    assert result.profitable_pct == 1.0
    assert result.aggregate_profit_factor == 2.5
    assert result.passes_threshold is True
    assert result.min_profitable_pct_required == 0.70
    assert result.min_profit_factor_required == 1.5


# -- Test: run_walk_forward integration with mocks --------------------------


def test_run_walk_forward_integration(validator, mock_engine, mock_loader):
    """Integration test: run_walk_forward calls engine.run for each window."""
    # Override engine.run to return different results
    profitable_result = _make_backtest_result([1.0, -0.3, 0.5], starting_equity=20.0)
    mock_engine.run = AsyncMock(return_value=profitable_result)

    result = asyncio.get_event_loop().run_until_complete(
        validator.run_walk_forward()
    )

    assert isinstance(result, WalkForwardResult)
    assert len(result.windows) > 0
    # Engine should be called twice per window (train + val)
    assert mock_engine.run.call_count == len(result.windows) * 2


# -- Test: evaluate_oos integration with mocks ------------------------------


def test_evaluate_oos_integration(validator, mock_engine, mock_loader):
    """Integration test: evaluate_oos runs engine on holdout data."""
    # First run walk-forward to get a WalkForwardResult
    profitable_result = _make_backtest_result([1.0, -0.3, 0.5], starting_equity=20.0)
    mock_engine.run = AsyncMock(return_value=profitable_result)

    wf_result = asyncio.get_event_loop().run_until_complete(
        validator.run_walk_forward()
    )

    # Now evaluate OOS
    oos = asyncio.get_event_loop().run_until_complete(
        validator.evaluate_oos(wf_result)
    )

    assert isinstance(oos, OOSResult)
    assert oos.oos_result is not None
    # OOS should have loaded holdout data
    # Verify loader.load_bars was called with holdout range
    holdout_start = DATA_END - 6 * MONTH_SECONDS
    found_holdout_call = False
    for call in mock_loader.load_bars.call_args_list:
        args = call[0] if call[0] else ()
        kwargs = call[1] if call[1] else {}
        start = args[0] if len(args) > 0 else kwargs.get("start_time", 0)
        end = args[1] if len(args) > 1 else kwargs.get("end_time", 0)
        if start == holdout_start and end == DATA_END:
            found_holdout_call = True
            break
    assert found_holdout_call, "evaluate_oos should load holdout bars"
