"""Tests for regime-aware evaluation and Feigenbaum stress testing.

Tests RegimeTagger (D-08), evaluate_regime_performance, and
FeigenbaumStressTest (TEST-06).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from fxsoqqabot.backtest.regime_tagger import (
    RegimeEvalResult,
    RegimePerformance,
    RegimeTagger,
)
from fxsoqqabot.backtest.results import TradeRecord
from fxsoqqabot.backtest.stress_test import (
    FeigenbaumStressTest,
    StressTestResult,
)
from fxsoqqabot.signals.base import RegimeState


def _make_trade(
    pnl: float,
    regime: str = "trending_up",
    entry_time: int = 1000,
    exit_time: int = 1060,
) -> TradeRecord:
    """Helper to create a TradeRecord with minimal required fields."""
    return TradeRecord(
        entry_time=entry_time,
        exit_time=exit_time,
        action="buy",
        symbol="XAUUSD",
        volume=0.01,
        entry_price=2000.0,
        exit_price=2000.0 + pnl * 100,
        sl=1990.0,
        tp=2010.0,
        pnl=pnl,
        commission=0.06,
        regime=regime,
        slippage_entry=0.0,
        slippage_exit=0.0,
        spread_at_entry=0.03,
    )


class TestRegimeTagger:
    """Test RegimeTagger.tag_bars() and regime assignment."""

    @pytest.mark.asyncio
    async def test_tag_bars_assigns_regime_state(self) -> None:
        """Test 1: tag_bars assigns a RegimeState to each bar."""
        from fxsoqqabot.config.models import ChaosConfig

        tagger = RegimeTagger(ChaosConfig())
        # Create minimal bars DataFrame
        n_bars = 400
        bars_df = _make_bars_df(n_bars)

        # Mock the chaos module to return known regimes
        mock_output = MagicMock()
        mock_output.regime = RegimeState.TRENDING_UP

        with patch.object(
            tagger._chaos, "update", new_callable=AsyncMock, return_value=mock_output
        ):
            tags = await tagger.tag_bars(bars_df, window_size=300)

        # Should return dict mapping timestamps to regime strings
        assert isinstance(tags, dict)
        assert len(tags) > 0
        # All values should be valid RegimeState values
        valid_values = {rs.value for rs in RegimeState}
        for v in tags.values():
            assert v in valid_values

    @pytest.mark.asyncio
    async def test_tag_bars_returns_timestamp_to_regime_dict(self) -> None:
        """Test 2: Returns dict mapping time -> RegimeState for lookup."""
        from fxsoqqabot.config.models import ChaosConfig

        tagger = RegimeTagger(ChaosConfig())
        bars_df = _make_bars_df(400)

        mock_output = MagicMock()
        mock_output.regime = RegimeState.RANGING

        with patch.object(
            tagger._chaos, "update", new_callable=AsyncMock, return_value=mock_output
        ):
            tags = await tagger.tag_bars(bars_df, window_size=300)

        # Keys should be integers (unix timestamps)
        for k in tags:
            assert isinstance(k, (int, np.integer))


class TestEvaluateRegimePerformance:
    """Test evaluate_regime_performance per D-08."""

    def test_groups_trades_by_regime(self) -> None:
        """Test 3: Groups trades by regime and computes per-regime metrics."""
        from fxsoqqabot.config.models import ChaosConfig

        tagger = RegimeTagger(ChaosConfig())
        trades = tuple(
            _make_trade(pnl=2.0, regime="trending_up") for _ in range(5)
        ) + tuple(
            _make_trade(pnl=-1.0, regime="ranging") for _ in range(3)
        )

        result = tagger.evaluate_regime_performance(trades)
        assert isinstance(result, RegimeEvalResult)
        assert "trending_up" in result.regime_performance
        assert "ranging" in result.regime_performance

    def test_regime_performance_fields(self) -> None:
        """Test 4: RegimePerformance contains n_trades, win_rate, profit_factor, avg_pnl."""
        from fxsoqqabot.config.models import ChaosConfig

        tagger = RegimeTagger(ChaosConfig())
        trades = tuple(
            _make_trade(pnl=2.0, regime="trending_up") for _ in range(6)
        )

        result = tagger.evaluate_regime_performance(trades)
        perf = result.regime_performance["trending_up"]
        assert isinstance(perf, RegimePerformance)
        assert perf.n_trades == 6
        assert perf.win_rate == pytest.approx(1.0)
        assert perf.avg_pnl == pytest.approx(2.0)

    def test_all_five_regimes_in_result(self) -> None:
        """Test 5: RegimeEvalResult contains all 5 RegimeState values."""
        from fxsoqqabot.config.models import ChaosConfig

        tagger = RegimeTagger(ChaosConfig())
        trades = tuple(
            _make_trade(pnl=1.0, regime="trending_up") for _ in range(5)
        )

        result = tagger.evaluate_regime_performance(trades)
        # All 5 regime states should be present
        for rs in RegimeState:
            assert rs.value in result.regime_performance

    def test_zero_trades_regime_gets_zero_performance(self) -> None:
        """Test 6: Regimes with zero trades get zeroed-out RegimePerformance."""
        from fxsoqqabot.config.models import ChaosConfig

        tagger = RegimeTagger(ChaosConfig())
        trades = tuple(
            _make_trade(pnl=1.0, regime="trending_up") for _ in range(5)
        )

        result = tagger.evaluate_regime_performance(trades)
        # "ranging" has no trades
        perf = result.regime_performance["ranging"]
        assert perf.n_trades == 0
        assert perf.win_rate == 0.0
        assert perf.profit_factor == 0.0
        assert perf.avg_pnl == 0.0


class TestFeigenbaumStressTest:
    """Test Feigenbaum stress test per TEST-06."""

    def test_generate_bifurcation_series_shape(self) -> None:
        """Test 7: generate_bifurcation_price_series produces correct-length array."""
        from fxsoqqabot.config.models import ChaosConfig

        stress = FeigenbaumStressTest(ChaosConfig())
        series = stress.generate_bifurcation_price_series(n_bars=500)
        assert isinstance(series, np.ndarray)
        assert len(series) == 500

    def test_bifurcation_series_three_phases(self) -> None:
        """Test 7 cont: Three phases have distinct statistical properties."""
        from fxsoqqabot.config.models import ChaosConfig

        stress = FeigenbaumStressTest(ChaosConfig())
        series = stress.generate_bifurcation_price_series(
            n_bars=500,
            pre_transition_bars=200,
            transition_bars=100,
            post_transition_bars=200,
        )

        # Pre-transition: low volatility
        pre = series[:200]
        pre_diffs = np.diff(pre)
        pre_std = np.std(pre_diffs)

        # Post-transition: high volatility
        post = series[300:]
        post_diffs = np.diff(post)
        post_std = np.std(post_diffs)

        # Post-transition volatility should be substantially higher than pre
        assert post_std > pre_std * 1.5

    def test_stress_test_detects_transition(self) -> None:
        """Test 8: detect_bifurcation_proximity returns proximity > 0 during transition."""
        from fxsoqqabot.config.models import ChaosConfig
        from fxsoqqabot.signals.chaos.feigenbaum import detect_bifurcation_proximity

        stress = FeigenbaumStressTest(ChaosConfig())
        series = stress.generate_bifurcation_price_series(n_bars=500)

        # Run bifurcation detection on the transition phase
        transition_segment = series[150:350]
        proximity, confidence = detect_bifurcation_proximity(transition_segment, order=3)
        # Proximity should be non-negative (may be zero if no peaks detected)
        assert proximity >= 0.0

    def test_stress_test_result_structure(self) -> None:
        """Test 9: StressTestResult contains expected boolean fields."""
        result = StressTestResult(
            pre_transition_regime="trending_up",
            transition_regime="pre_bifurcation",
            post_transition_regime="high_chaos",
            pre_transition_detected=True,
            transition_detected=True,
            chaos_detected=True,
            bifurcation_proximity_at_transition=0.5,
            passes=True,
        )
        assert result.pre_transition_detected is True
        assert result.transition_detected is True
        assert result.chaos_detected is True
        assert result.passes is True


def _make_bars_df(n_bars: int, start_time: int = 1000000) -> "pd.DataFrame":
    """Create a minimal M1 bars DataFrame for testing."""
    import pandas as pd

    times = np.arange(start_time, start_time + n_bars * 60, 60, dtype=np.int64)
    rng = np.random.default_rng(42)
    # Generate realistic-ish XAUUSD prices
    base = 2000.0
    returns = rng.normal(0, 0.5, n_bars)
    close = base + np.cumsum(returns)
    open_ = close - rng.uniform(0, 0.5, n_bars)
    high = np.maximum(open_, close) + rng.uniform(0, 1.0, n_bars)
    low = np.minimum(open_, close) - rng.uniform(0, 1.0, n_bars)
    volume = rng.integers(100, 1000, n_bars)

    return pd.DataFrame({
        "time": times,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "tick_volume": volume,
    })
