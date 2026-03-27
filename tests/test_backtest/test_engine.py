"""Tests for BacktestDataFeed, BacktestExecutor, and result types.

Tests validate:
- BacktestDataFeed implements DataFeedProtocol
- BacktestDataFeed.advance_bar() loads bars and produces correct shapes
- Tick synthesis from M1 bars per D-02
- Multi-timeframe bar resampling with no lookahead
- BacktestDataFeed.check_tick_freshness always True
- BacktestExecutor fill prices include spread + slippage
- BacktestExecutor SL/TP checking against bar high/low
- TradeRecord and BacktestResult dataclass fields
"""

from __future__ import annotations

import asyncio

import numpy as np
import pandas as pd
import pytest

from fxsoqqabot.backtest.clock import BacktestClock
from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.backtest.data_feed import BacktestDataFeed
from fxsoqqabot.backtest.executor import BacktestExecutor
from fxsoqqabot.backtest.results import BacktestResult, TradeRecord
from fxsoqqabot.data.protocol import DataFeedProtocol


# -- Fixtures -----------------------------------------------------------------


def _make_m1_bars(n: int = 50, base_price: float = 2000.0) -> pd.DataFrame:
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
    return _make_m1_bars(50)


@pytest.fixture
def clock() -> BacktestClock:
    return BacktestClock()


@pytest.fixture
def config() -> BacktestConfig:
    return BacktestConfig()


@pytest.fixture
def feed(bars_df: pd.DataFrame, config: BacktestConfig, clock: BacktestClock) -> BacktestDataFeed:
    return BacktestDataFeed(bars_df, config, clock)


@pytest.fixture
def executor(config: BacktestConfig, clock: BacktestClock) -> BacktestExecutor:
    return BacktestExecutor(config, clock)


# -- Test 1: DataFeedProtocol conformance -------------------------------------


def test_backtest_data_feed_isinstance_protocol(feed: BacktestDataFeed) -> None:
    """BacktestDataFeed must satisfy DataFeedProtocol via structural typing."""
    assert isinstance(feed, DataFeedProtocol)


# -- Test 2: advance_bar loads bar and get_tick/bar_arrays return correct shapes


def test_advance_bar_and_shapes(
    feed: BacktestDataFeed, clock: BacktestClock, bars_df: pd.DataFrame
) -> None:
    """advance_bar loads bar; get_tick_arrays/get_bar_arrays return correct keys."""
    # Advance to bar 20 (enough history for synthesis)
    for i in range(21):
        bar = feed.advance_bar(i)
        clock.advance(bar["time"] * 1000)

    # Check bar dict keys
    assert "time" in bar
    assert "open" in bar
    assert "high" in bar
    assert "low" in bar
    assert "close" in bar
    assert "volume" in bar

    # Check tick_arrays
    tick_arrays = asyncio.get_event_loop().run_until_complete(
        feed.get_tick_arrays("XAUUSD")
    )
    expected_tick_keys = {"time_msc", "bid", "ask", "last", "spread", "volume_real"}
    assert set(tick_arrays.keys()) == expected_tick_keys

    # Check bar_arrays
    bar_arrays = asyncio.get_event_loop().run_until_complete(
        feed.get_bar_arrays("XAUUSD")
    )
    expected_bar_tfs = {"M1", "M5", "M15", "H1", "H4"}
    assert set(bar_arrays.keys()) == expected_bar_tfs
    for tf in expected_bar_tfs:
        inner = bar_arrays[tf]
        expected_inner_keys = {"time", "open", "high", "low", "close", "tick_volume"}
        assert set(inner.keys()) == expected_inner_keys


# -- Test 3: Tick synthesis from M1 bars per D-02 ----------------------------


def test_tick_synthesis_from_m1(
    feed: BacktestDataFeed, clock: BacktestClock, bars_df: pd.DataFrame
) -> None:
    """Synthesized ticks: bid=close, ask=close+spread, last=close, time_msc=time*1000."""
    # Advance to bar 10
    for i in range(11):
        bar = feed.advance_bar(i)
        clock.advance(bar["time"] * 1000)

    tick_arrays = asyncio.get_event_loop().run_until_complete(
        feed.get_tick_arrays("XAUUSD")
    )

    # Should have some ticks
    assert tick_arrays["bid"].size > 0

    # For synthesized ticks, bid = close of the bar
    # last should equal bid (close)
    np.testing.assert_array_equal(tick_arrays["last"], tick_arrays["bid"])

    # ask should be bid + spread
    np.testing.assert_array_almost_equal(
        tick_arrays["ask"], tick_arrays["bid"] + tick_arrays["spread"]
    )

    # time_msc should be time * 1000 (integer milliseconds from bar time)
    # Each tick's time_msc corresponds to a bar time * 1000
    assert tick_arrays["time_msc"].dtype == np.int64

    # volume_real should be positive
    assert np.all(tick_arrays["volume_real"] > 0)


# -- Test 4: Multi-timeframe bar arrays with no lookahead --------------------


def test_multi_timeframe_no_lookahead(
    feed: BacktestDataFeed, clock: BacktestClock, bars_df: pd.DataFrame
) -> None:
    """Bar arrays use only data up to current bar -- no lookahead."""
    # Advance to bar 30 (enough for some M5 and M15 bars)
    for i in range(31):
        bar = feed.advance_bar(i)
        clock.advance(bar["time"] * 1000)

    bar_arrays = asyncio.get_event_loop().run_until_complete(
        feed.get_bar_arrays("XAUUSD")
    )

    current_time = int(bars_df["time"].iloc[30])

    # M1 bars: all times should be <= current time
    m1_times = bar_arrays["M1"]["time"]
    assert m1_times.size > 0
    assert np.all(m1_times <= current_time)

    # M5 bars: all times should be <= current time
    m5_times = bar_arrays["M5"]["time"]
    if m5_times.size > 0:
        assert np.all(m5_times <= current_time)

    # M15 bars: all times should be <= current time
    m15_times = bar_arrays["M15"]["time"]
    if m15_times.size > 0:
        assert np.all(m15_times <= current_time)


# -- Test 5: check_tick_freshness always True --------------------------------


def test_check_tick_freshness_always_true(feed: BacktestDataFeed) -> None:
    """In backtest mode, tick freshness always returns True."""
    assert feed.check_tick_freshness() is True
    assert feed.check_tick_freshness(max_age_seconds=0.001) is True


# -- Test 6: BacktestExecutor fill price calculation --------------------------


def test_executor_fill_price_buy(
    executor: BacktestExecutor, clock: BacktestClock
) -> None:
    """Buy fill price = close + spread + slippage (ask + slippage)."""
    bar = {
        "time": 1700000000,
        "open": 2000.0,
        "high": 2005.0,
        "low": 1995.0,
        "close": 2001.0,
        "volume": 500,
    }
    clock.advance(bar["time"] * 1000)

    executor.open_position(
        action="buy",
        volume=0.01,
        bar=bar,
        sl_distance=3.0,
        tp_distance=9.0,
        regime="trending_up",
    )

    # Position should exist with entry_price > close (spread + slippage added)
    assert len(executor._positions) == 1
    pos = executor._positions[0]
    # Entry price should be at least close (spread and slippage are >= 0)
    assert pos.entry_price >= bar["close"]


def test_executor_fill_price_sell(
    executor: BacktestExecutor, clock: BacktestClock
) -> None:
    """Sell fill price = close - slippage (bid - slippage)."""
    bar = {
        "time": 1700000000,
        "open": 2000.0,
        "high": 2005.0,
        "low": 1995.0,
        "close": 2001.0,
        "volume": 500,
    }
    clock.advance(bar["time"] * 1000)

    executor.open_position(
        action="sell",
        volume=0.01,
        bar=bar,
        sl_distance=3.0,
        tp_distance=4.5,
        regime="ranging",
    )

    assert len(executor._positions) == 1
    pos = executor._positions[0]
    # Sell entry price should be <= close (slippage is adverse)
    assert pos.entry_price <= bar["close"]


# -- Test 7: Commission calculation ------------------------------------------


def test_executor_commission(config: BacktestConfig) -> None:
    """Commission = volume * commission_per_lot_round_trip."""
    clock = BacktestClock()
    executor = BacktestExecutor(config, clock)

    volume = 0.05
    expected = volume * config.commission_per_lot_round_trip
    actual = executor.calculate_commission(volume)
    assert actual == pytest.approx(expected)


# -- Test 8: SL/TP checking against bar high/low ----------------------------


def test_executor_sl_hit_buy(
    executor: BacktestExecutor, clock: BacktestClock
) -> None:
    """Buy position SL hit when bar low <= sl_price."""
    open_bar = {
        "time": 1700000000,
        "open": 2000.0,
        "high": 2005.0,
        "low": 1995.0,
        "close": 2001.0,
        "volume": 500,
    }
    clock.advance(open_bar["time"] * 1000)

    executor.open_position(
        action="buy",
        volume=0.01,
        bar=open_bar,
        sl_distance=3.0,
        tp_distance=9.0,
        regime="trending_up",
    )

    pos = executor._positions[0]

    # Next bar with low below SL
    check_bar = {
        "time": 1700000060,
        "open": 2000.0,
        "high": 2002.0,
        "low": pos.sl_price - 1.0,  # Below SL
        "close": 1999.0,
        "volume": 300,
    }
    clock.advance(check_bar["time"] * 1000)

    closed = executor.check_sl_tp(check_bar)
    assert len(closed) == 1
    assert closed[0].pnl < 0  # SL hit = loss
    assert len(executor._positions) == 0  # Position removed


def test_executor_tp_hit_buy(
    executor: BacktestExecutor, clock: BacktestClock
) -> None:
    """Buy position TP hit when bar high >= tp_price."""
    open_bar = {
        "time": 1700000000,
        "open": 2000.0,
        "high": 2005.0,
        "low": 1995.0,
        "close": 2001.0,
        "volume": 500,
    }
    clock.advance(open_bar["time"] * 1000)

    executor.open_position(
        action="buy",
        volume=0.01,
        bar=open_bar,
        sl_distance=3.0,
        tp_distance=9.0,
        regime="trending_up",
    )

    pos = executor._positions[0]

    # Next bar with high above TP
    check_bar = {
        "time": 1700000060,
        "open": 2005.0,
        "high": pos.tp_price + 1.0,  # Above TP
        "low": 2003.0,
        "close": 2008.0,
        "volume": 400,
    }
    clock.advance(check_bar["time"] * 1000)

    closed = executor.check_sl_tp(check_bar)
    assert len(closed) == 1
    assert closed[0].pnl > 0  # TP hit = profit (before commission may make net negative)
    assert len(executor._positions) == 0


# -- Test 9: TradeRecord frozen dataclass ------------------------------------


def test_trade_record_fields() -> None:
    """TradeRecord has all required fields and is frozen."""
    record = TradeRecord(
        entry_time=1700000000,
        exit_time=1700000060,
        action="buy",
        symbol="XAUUSD",
        volume=0.01,
        entry_price=2001.50,
        exit_price=2010.50,
        sl=1998.50,
        tp=2010.50,
        pnl=8.70,
        commission=0.06,
        regime="trending_up",
        slippage_entry=0.02,
        slippage_exit=0.01,
        spread_at_entry=0.03,
    )
    assert record.entry_time == 1700000000
    assert record.exit_time == 1700000060
    assert record.action == "buy"
    assert record.symbol == "XAUUSD"
    assert record.volume == 0.01
    assert record.entry_price == 2001.50
    assert record.exit_price == 2010.50
    assert record.pnl == 8.70
    assert record.commission == 0.06
    assert record.regime == "trending_up"

    # Frozen check
    with pytest.raises(AttributeError):
        record.pnl = 999.0  # type: ignore[misc]


# -- Test 10: BacktestResult fields and computed properties -------------------


def test_backtest_result_properties() -> None:
    """BacktestResult has trades list, equity, commission, and computed metrics."""
    win = TradeRecord(
        entry_time=100, exit_time=200, action="buy", symbol="XAUUSD",
        volume=0.01, entry_price=2000.0, exit_price=2010.0,
        sl=1997.0, tp=2010.0, pnl=0.94, commission=0.06,
        regime="trending_up", slippage_entry=0.0, slippage_exit=0.0,
        spread_at_entry=0.03,
    )
    loss = TradeRecord(
        entry_time=300, exit_time=400, action="sell", symbol="XAUUSD",
        volume=0.01, entry_price=2010.0, exit_price=2015.0,
        sl=2015.0, tp=2005.0, pnl=-0.56, commission=0.06,
        regime="ranging", slippage_entry=0.0, slippage_exit=0.0,
        spread_at_entry=0.03,
    )
    result = BacktestResult(
        trades=(win, loss),
        starting_equity=20.0,
        final_equity=20.38,
        total_commission=0.12,
        total_bars_processed=100,
        start_time=100,
        end_time=400,
    )

    assert result.n_trades == 2
    assert result.win_rate == pytest.approx(0.5)  # 1 win / 2 trades
    assert result.profit_factor > 0  # gross_profit / gross_loss
    assert result.max_drawdown_pct >= 0.0
    assert result.starting_equity == 20.0
    assert result.final_equity == 20.38
    assert result.total_commission == 0.12
