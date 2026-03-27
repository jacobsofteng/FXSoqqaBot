"""Tests for Monte Carlo trade sequence shuffling per D-07.

Verifies that run_monte_carlo:
- Shuffles trade P&L sequences n_simulations times
- Computes tail risk statistics (5th/50th/95th percentile)
- Evaluates dual threshold (5th pct positive + median positive + DD bounded)
- Handles edge cases (zero trades, single trade)
- Is reproducible with seed
"""

from __future__ import annotations

import numpy as np
import pytest

from fxsoqqabot.backtest.monte_carlo import MonteCarloResult, run_monte_carlo


class TestMonteCarloResult:
    """Test MonteCarloResult data structure."""

    def test_n_simulations_recorded(self) -> None:
        """Test 1: run_monte_carlo with 10,000 simulations records n_simulations."""
        pnls = np.array([2.0] * 10)
        result = run_monte_carlo(pnls, starting_equity=100.0, n_simulations=1000)
        assert result.n_simulations == 1000

    def test_pct_5_equity_is_5th_percentile(self) -> None:
        """Test 2: pct_5_equity is the 5th percentile of final equity distribution."""
        pnls = np.array([2.0] * 10)
        result = run_monte_carlo(pnls, starting_equity=100.0, n_simulations=1000)
        # All trades are identical (+2), so every permutation gives same final equity
        # 100 + 10*2 = 120
        assert result.pct_5_equity == pytest.approx(120.0, abs=0.01)

    def test_median_equity_is_50th_percentile(self) -> None:
        """Test 3: median_equity is the 50th percentile."""
        pnls = np.array([2.0] * 10)
        result = run_monte_carlo(pnls, starting_equity=100.0, n_simulations=1000)
        assert result.median_equity == pytest.approx(120.0, abs=0.01)

    def test_pct_95_max_dd_is_95th_percentile(self) -> None:
        """Test 4: pct_95_max_dd is the 95th percentile of max drawdown distribution."""
        pnls = np.array([2.0] * 10)
        result = run_monte_carlo(pnls, starting_equity=100.0, n_simulations=1000)
        # All trades are profitable, so max drawdown should be 0 (no decline)
        assert result.pct_95_max_dd == pytest.approx(0.0, abs=0.01)

    def test_p_value_fraction_below_starting(self) -> None:
        """Test 5: p_value is fraction of runs with final equity below starting."""
        pnls = np.array([2.0] * 10)
        result = run_monte_carlo(pnls, starting_equity=100.0, n_simulations=1000)
        # All runs end at 120, which is above starting 100
        assert result.p_value == pytest.approx(0.0, abs=0.01)


class TestDualThreshold:
    """Test D-07 dual threshold evaluation."""

    def test_profitable_trades_pass(self) -> None:
        """Test 6: With profitable trade set, passes_threshold is True."""
        pnls = np.array([2.0] * 10)
        result = run_monte_carlo(pnls, starting_equity=100.0, n_simulations=1000)
        assert result.passes_threshold is True

    def test_losing_trades_fail(self) -> None:
        """Test 7: With losing trade set, passes_threshold is False."""
        pnls = np.array([-2.0] * 10)
        result = run_monte_carlo(pnls, starting_equity=100.0, n_simulations=1000)
        assert result.passes_threshold is False

    def test_mixed_trades_p_value_bounded(self) -> None:
        """Test 8: With mixed trades, p_value is between 0 and 1."""
        pnls = np.array([3.0] * 5 + [-2.0] * 5)
        result = run_monte_carlo(pnls, starting_equity=100.0, n_simulations=1000)
        assert 0.0 <= result.p_value <= 1.0


class TestReproducibility:
    """Test seed-based reproducibility."""

    def test_same_seed_same_results(self) -> None:
        """Test 9: Reproducible results with same seed."""
        pnls = np.array([3.0, -1.0, 2.0, -0.5, 1.5, -2.0, 4.0, -1.5, 0.5, 1.0])
        result1 = run_monte_carlo(pnls, starting_equity=100.0, n_simulations=500, seed=42)
        result2 = run_monte_carlo(pnls, starting_equity=100.0, n_simulations=500, seed=42)
        assert result1.pct_5_equity == result2.pct_5_equity
        assert result1.median_equity == result2.median_equity
        assert result1.pct_95_max_dd == result2.pct_95_max_dd
        assert result1.p_value == result2.p_value
        assert result1.passes_threshold == result2.passes_threshold


class TestEdgeCases:
    """Test edge cases."""

    def test_single_trade(self) -> None:
        """Test 10: Single trade returns valid result."""
        pnls = np.array([5.0])
        result = run_monte_carlo(pnls, starting_equity=100.0, n_simulations=1000)
        assert isinstance(result, MonteCarloResult)
        assert result.n_simulations == 1000
        # Single trade: only one permutation possible
        assert result.pct_5_equity == pytest.approx(105.0, abs=0.01)
        assert result.median_equity == pytest.approx(105.0, abs=0.01)

    def test_zero_trades(self) -> None:
        """Test 11: Zero trades returns MonteCarloResult with passes_threshold=False."""
        pnls = np.array([])
        result = run_monte_carlo(pnls, starting_equity=100.0, n_simulations=1000)
        assert isinstance(result, MonteCarloResult)
        assert result.passes_threshold is False
        assert result.p_value == 1.0
