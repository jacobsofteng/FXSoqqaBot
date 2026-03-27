"""Tests for DataFeedProtocol, Clock Protocol, and BacktestConfig models.

TDD RED phase: These tests define the expected behavior for the protocol
abstraction layer that decouples signal modules from data sources.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from fxsoqqabot.data.protocol import DataFeedProtocol
from fxsoqqabot.backtest.clock import BacktestClock, Clock, WallClock
from fxsoqqabot.backtest.config import BacktestConfig, SlippageModel, SpreadModel


# ---------- DataFeedProtocol Tests ----------


class TestDataFeedProtocol:
    """Test 1: DataFeedProtocol is runtime_checkable and defines required methods."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """DataFeedProtocol should be usable with isinstance()."""

        class FakeDataFeed:
            async def get_tick_arrays(self, symbol: str) -> dict[str, np.ndarray]:
                return {}

            async def get_bar_arrays(
                self, symbol: str
            ) -> dict[str, dict[str, np.ndarray]]:
                return {}

            async def get_dom(self, symbol: str) -> None:
                return None

            def check_tick_freshness(self, max_age_seconds: float = 10.0) -> bool:
                return True

        feed = FakeDataFeed()
        assert isinstance(feed, DataFeedProtocol)

    def test_non_conforming_class_fails_isinstance(self) -> None:
        """A class missing required methods should not satisfy the protocol."""

        class BadFeed:
            pass

        assert not isinstance(BadFeed(), DataFeedProtocol)


# ---------- Clock Protocol Tests ----------


class TestBacktestClock:
    """Tests 2-3: BacktestClock provides deterministic time control."""

    def test_initial_time_is_zero(self) -> None:
        """Test 2: BacktestClock.now_msc() returns 0 initially."""
        clock = BacktestClock()
        assert clock.now_msc() == 0

    def test_advance_sets_time(self) -> None:
        """Test 2: now_msc() returns advanced value after advance() call."""
        clock = BacktestClock()
        clock.advance(12345)
        assert clock.now_msc() == 12345

    def test_now_returns_correct_datetime(self) -> None:
        """Test 3: now() returns correct datetime matching advanced timestamp."""
        clock = BacktestClock()
        # 2024-01-15 12:30:00 UTC in milliseconds
        ts_msc = int(datetime(2024, 1, 15, 12, 30, 0, tzinfo=UTC).timestamp() * 1000)
        clock.advance(ts_msc)
        dt = clock.now()
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 12
        assert dt.minute == 30
        assert dt.tzinfo is not None  # Must be timezone-aware

    def test_clock_implements_protocol(self) -> None:
        """BacktestClock satisfies the Clock protocol."""
        clock = BacktestClock()
        assert isinstance(clock, Clock)


class TestWallClock:
    """Test 4: WallClock returns real time."""

    def test_now_msc_is_near_current_time(self) -> None:
        """Test 4: WallClock.now_msc() returns value within 1000ms of real time."""
        clock = WallClock()
        real_msc = int(datetime.now(UTC).timestamp() * 1000)
        clock_msc = clock.now_msc()
        assert abs(clock_msc - real_msc) < 1000

    def test_now_returns_timezone_aware_datetime(self) -> None:
        """WallClock.now() returns a timezone-aware datetime."""
        clock = WallClock()
        dt = clock.now()
        assert dt.tzinfo is not None

    def test_wall_clock_implements_protocol(self) -> None:
        """WallClock satisfies the Clock protocol."""
        clock = WallClock()
        assert isinstance(clock, Clock)


# ---------- BacktestConfig Tests ----------


class TestBacktestConfig:
    """Tests 5-7: BacktestConfig validates parameters via Pydantic."""

    def test_default_config_is_valid(self) -> None:
        """Default BacktestConfig should be valid."""
        config = BacktestConfig()
        assert config.symbol == "XAUUSD"
        assert config.n_monte_carlo == 10000
        assert config.holdout_months == 6

    def test_spread_model_london_ny_overlap_pips_is_tuple(self) -> None:
        """Test 5: london_ny_overlap_pips must be a tuple of two floats."""
        config = BacktestConfig()
        assert isinstance(config.spread_model.london_ny_overlap_pips, tuple)
        assert len(config.spread_model.london_ny_overlap_pips) == 2

    def test_n_monte_carlo_minimum(self) -> None:
        """Test 6: n_monte_carlo must be >= 1000."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            BacktestConfig(n_monte_carlo=999)

    def test_holdout_months_minimum(self) -> None:
        """Test 7: holdout_months must be >= 1."""
        with pytest.raises(Exception):
            BacktestConfig(holdout_months=0)

    def test_wf_train_months_minimum(self) -> None:
        """wf_train_months must be >= 1."""
        with pytest.raises(Exception):
            BacktestConfig(wf_train_months=0)

    def test_commission_non_negative(self) -> None:
        """commission_per_lot_round_trip must be >= 0."""
        with pytest.raises(Exception):
            BacktestConfig(commission_per_lot_round_trip=-1.0)


# ---------- SpreadModel Tests ----------


class TestSpreadModel:
    """Test 8: SpreadModel.sample_spread returns session-aware spreads."""

    def test_sample_spread_london_ny_overlap(self) -> None:
        """Test 8: sample_spread returns value within expected range for hour 14."""
        model = SpreadModel()
        rng = np.random.default_rng(42)
        spread = model.sample_spread(hour_utc=14, rng=rng)
        # London-NY overlap: (2.0, 3.0) pips * 0.01 pip_to_price = 0.02 to 0.03
        assert 0.02 <= spread <= 0.03

    def test_sample_spread_asian_session(self) -> None:
        """Asian session (hour 3) should produce wider spreads."""
        model = SpreadModel()
        rng = np.random.default_rng(42)
        spread = model.sample_spread(hour_utc=3, rng=rng)
        # Asian session: (4.0, 6.0) pips * 0.01 = 0.04 to 0.06
        assert 0.04 <= spread <= 0.06

    def test_sample_spread_volatility_factor(self) -> None:
        """Volatility factor should widen spreads."""
        model = SpreadModel()
        rng1 = np.random.default_rng(42)
        rng2 = np.random.default_rng(42)
        normal = model.sample_spread(hour_utc=14, rng=rng1, volatility_factor=1.0)
        wide = model.sample_spread(hour_utc=14, rng=rng2, volatility_factor=2.0)
        assert wide > normal


# ---------- SlippageModel Tests ----------


class TestSlippageModel:
    """Test 9: SlippageModel stochastic slippage distribution."""

    def test_no_slippage_majority(self) -> None:
        """Test 9: sample_slippage returns 0.0 at least 70% of 1000 samples."""
        model = SlippageModel()
        rng = np.random.default_rng(42)
        samples = [model.sample_slippage(rng=rng) for _ in range(1000)]
        zero_count = sum(1 for s in samples if s == 0.0)
        # Default no_slip_pct=0.80 so we expect ~80% zeros, test at 70% tolerance
        assert zero_count >= 700, f"Expected >= 700 zeros, got {zero_count}"

    def test_slippage_always_non_negative(self) -> None:
        """Slippage should always be non-negative (adverse direction)."""
        model = SlippageModel()
        rng = np.random.default_rng(42)
        samples = [model.sample_slippage(rng=rng) for _ in range(1000)]
        assert all(s >= 0.0 for s in samples)

    def test_slippage_volatility_factor(self) -> None:
        """Higher volatility factor should increase average slippage."""
        model = SlippageModel()
        rng1 = np.random.default_rng(42)
        rng2 = np.random.default_rng(42)
        normal = [model.sample_slippage(rng=rng1, volatility_factor=1.0) for _ in range(1000)]
        high = [model.sample_slippage(rng=rng2, volatility_factor=2.0) for _ in range(1000)]
        # Average slippage should be higher with higher volatility
        assert np.mean(high) >= np.mean(normal)
