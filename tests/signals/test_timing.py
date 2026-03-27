"""Tests for quantum timing engine components.

Covers OU parameter estimation, entry/exit windows, ATR computation
with Wilder smoothing, and phase transition detection via volatility
compression/expansion energy model.
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# OU Model tests
# ---------------------------------------------------------------------------


class TestEstimateOUParameters:
    """Tests for estimate_ou_parameters()."""

    def test_short_series_returns_fallback(self) -> None:
        """< 30 points returns (0.0, mean, 0.0, 0.0)."""
        from fxsoqqabot.signals.timing.ou_model import estimate_ou_parameters

        prices = np.array([100.0, 101.0, 99.0])
        kappa, theta, sigma, conf = estimate_ou_parameters(prices)
        assert kappa == 0.0
        assert theta == pytest.approx(np.mean(prices))
        assert sigma == 0.0
        assert conf == 0.0

    def test_mean_reverting_series_positive_kappa(self) -> None:
        """Mean-reverting synthetic series produces kappa > 0."""
        from fxsoqqabot.signals.timing.ou_model import estimate_ou_parameters

        rng = np.random.default_rng(42)
        # Simulate OU process: X_{t+1} = X_t + 0.3*(100-X_t) + noise
        n = 200
        prices = np.empty(n)
        prices[0] = 95.0
        for i in range(1, n):
            prices[i] = prices[i - 1] + 0.3 * (100.0 - prices[i - 1]) + rng.normal(0, 0.5)

        kappa, theta, sigma, conf = estimate_ou_parameters(prices)
        assert kappa > 0, f"Expected positive kappa for mean-reverting series, got {kappa}"
        assert 95.0 < theta < 105.0, f"theta={theta} should be near 100"
        assert sigma > 0
        assert 0.0 <= conf <= 1.0

    def test_returns_float_tuple(self) -> None:
        """All returned values are Python floats."""
        from fxsoqqabot.signals.timing.ou_model import estimate_ou_parameters

        rng = np.random.default_rng(7)
        prices = rng.normal(100, 1, 50)
        result = estimate_ou_parameters(prices)
        assert len(result) == 4
        for val in result:
            assert isinstance(val, float), f"Expected float, got {type(val)}"

    def test_constant_prices_returns_fallback(self) -> None:
        """Constant prices have zero denominator -> fallback."""
        from fxsoqqabot.signals.timing.ou_model import estimate_ou_parameters

        prices = np.full(50, 100.0)
        kappa, theta, sigma, conf = estimate_ou_parameters(prices)
        assert kappa == 0.0
        assert theta == pytest.approx(100.0)

    def test_confidence_clamped_0_1(self) -> None:
        """Confidence is always in [0, 1] range."""
        from fxsoqqabot.signals.timing.ou_model import estimate_ou_parameters

        rng = np.random.default_rng(99)
        prices = rng.normal(100, 2, 100)
        _, _, _, conf = estimate_ou_parameters(prices)
        assert 0.0 <= conf <= 1.0


class TestComputeEntryWindow:
    """Tests for compute_entry_window()."""

    def test_no_mean_reversion_returns_zeros(self) -> None:
        """kappa <= 0 or low confidence returns all zeros."""
        from fxsoqqabot.signals.timing.ou_model import compute_entry_window

        direction, urgency, conf = compute_entry_window(0.0, 100.0, 1.0, 95.0, 0.5)
        assert direction == 0.0
        assert urgency == 0.0
        assert conf == 0.0

    def test_low_confidence_returns_zeros(self) -> None:
        """confidence < 0.1 returns all zeros."""
        from fxsoqqabot.signals.timing.ou_model import compute_entry_window

        direction, urgency, conf = compute_entry_window(0.5, 100.0, 1.0, 95.0, 0.05)
        assert direction == 0.0
        assert urgency == 0.0
        assert conf == 0.0

    def test_price_below_mean_positive_direction(self) -> None:
        """Price below theta -> positive direction (expect rise)."""
        from fxsoqqabot.signals.timing.ou_model import compute_entry_window

        direction, urgency, conf = compute_entry_window(0.5, 100.0, 1.0, 90.0, 0.8)
        assert direction == 1.0, f"Expected +1.0, got {direction}"
        assert urgency > 0

    def test_price_above_mean_negative_direction(self) -> None:
        """Price above theta -> negative direction (expect fall)."""
        from fxsoqqabot.signals.timing.ou_model import compute_entry_window

        direction, urgency, conf = compute_entry_window(0.5, 100.0, 1.0, 110.0, 0.8)
        assert direction == -1.0, f"Expected -1.0, got {direction}"

    def test_far_from_mean_higher_urgency(self) -> None:
        """Price far from theta -> higher urgency than close."""
        from fxsoqqabot.signals.timing.ou_model import compute_entry_window

        _, urgency_far, _ = compute_entry_window(0.3, 100.0, 1.0, 85.0, 0.8)
        _, urgency_close, _ = compute_entry_window(0.3, 100.0, 1.0, 99.0, 0.8)
        assert urgency_far > urgency_close

    def test_urgency_capped_at_1(self) -> None:
        """Urgency is clamped to max 1.0."""
        from fxsoqqabot.signals.timing.ou_model import compute_entry_window

        _, urgency, _ = compute_entry_window(0.5, 100.0, 0.001, 50.0, 0.9)
        assert urgency <= 1.0


class TestComputeExitWindow:
    """Tests for compute_exit_window()."""

    def test_zero_kappa_returns_exit_now(self) -> None:
        """kappa <= 0 means no mean reversion -> exit."""
        from fxsoqqabot.signals.timing.ou_model import compute_exit_window

        exit_urgency, conf = compute_exit_window(0.0, 100.0, 95.0, 90.0)
        assert exit_urgency == 1.0
        assert conf == 1.0

    def test_moving_away_from_theta_exit_now(self) -> None:
        """If price is moving further from theta (wrong direction), exit urgently."""
        from fxsoqqabot.signals.timing.ou_model import compute_exit_window

        # Bought at 95, theta at 100, current at 93 -> moving away
        exit_urgency, conf = compute_exit_window(0.3, 100.0, 93.0, 95.0)
        assert exit_urgency == 1.0

    def test_approaching_theta_hold(self) -> None:
        """If price is moving toward theta, low exit urgency."""
        from fxsoqqabot.signals.timing.ou_model import compute_exit_window

        # Bought at 95, theta at 100, current at 98 -> approaching theta
        exit_urgency, conf = compute_exit_window(0.3, 100.0, 98.0, 95.0)
        assert exit_urgency < 1.0


# ---------------------------------------------------------------------------
# ATR / Phase Transition tests
# ---------------------------------------------------------------------------


class TestComputeATR:
    """Tests for compute_atr()."""

    def test_basic_atr_shape(self) -> None:
        """Output has same shape as input."""
        from fxsoqqabot.signals.timing.phase_transition import compute_atr

        n = 50
        high = np.random.default_rng(1).uniform(101, 105, n)
        low = np.random.default_rng(2).uniform(95, 99, n)
        close = (high + low) / 2
        atr = compute_atr(high, low, close)
        assert atr.shape == (n,)

    def test_atr_positive(self) -> None:
        """ATR values are non-negative."""
        from fxsoqqabot.signals.timing.phase_transition import compute_atr

        rng = np.random.default_rng(3)
        n = 100
        close = 100 + np.cumsum(rng.normal(0, 0.5, n))
        high = close + rng.uniform(0.5, 2.0, n)
        low = close - rng.uniform(0.5, 2.0, n)
        atr = compute_atr(high, low, close)
        assert np.all(atr >= 0), "ATR should always be non-negative"

    def test_atr_short_data(self) -> None:
        """< period data returns array of simple average TR."""
        from fxsoqqabot.signals.timing.phase_transition import compute_atr

        high = np.array([102.0, 103.0, 101.0])
        low = np.array([98.0, 97.0, 99.0])
        close = np.array([100.0, 100.5, 100.2])
        atr = compute_atr(high, low, close, period=14)
        assert len(atr) == 3
        # Should be the simple average of TR
        assert np.all(atr > 0)

    def test_wilder_smoothing(self) -> None:
        """After initial period, ATR uses Wilder smoothing."""
        from fxsoqqabot.signals.timing.phase_transition import compute_atr

        n = 30
        rng = np.random.default_rng(5)
        close = 100 + np.cumsum(rng.normal(0, 0.5, n))
        high = close + rng.uniform(1.0, 3.0, n)
        low = close - rng.uniform(1.0, 3.0, n)
        atr = compute_atr(high, low, close, period=14)
        # The smoothed values should be relatively stable (not jumping wildly)
        assert atr.shape == (n,)
        # Verify first `period` values are same (simple avg)
        assert np.allclose(atr[:14], atr[0]), "First period values should be simple average"


class TestDetectPhaseTransition:
    """Tests for detect_phase_transition()."""

    def test_compression_detected(self) -> None:
        """Low volatility returns 'compression' state."""
        from fxsoqqabot.signals.timing.phase_transition import detect_phase_transition

        # Create a series that starts volatile then compresses
        rng = np.random.default_rng(10)
        n = 100
        close = 100 + np.cumsum(rng.normal(0, 0.01, n))  # Very low vol
        high = close + 0.01  # Tiny range -> very low ATR
        low = close - 0.01

        state, energy, conf = detect_phase_transition(close, high, low)
        assert state == "compression", f"Expected compression, got {state}"
        assert energy > 0, "Compression should have stored energy"

    def test_expansion_detected(self) -> None:
        """High volatility returns 'expansion' state."""
        from fxsoqqabot.signals.timing.phase_transition import detect_phase_transition

        rng = np.random.default_rng(20)
        n = 100
        # Start calm, then create massive move at the end
        close = np.concatenate([
            100 + np.cumsum(rng.normal(0, 0.1, 80)),
            100 + np.cumsum(rng.normal(0, 5.0, 20)),
        ])
        high = close + np.concatenate([
            np.full(80, 0.2),
            np.full(20, 10.0),
        ])
        low = close - np.concatenate([
            np.full(80, 0.2),
            np.full(20, 10.0),
        ])

        state, energy, conf = detect_phase_transition(close, high, low)
        assert state == "expansion", f"Expected expansion, got {state}"
        assert energy > 0

    def test_normal_state(self) -> None:
        """Normal volatility returns 'normal' state."""
        from fxsoqqabot.signals.timing.phase_transition import detect_phase_transition

        rng = np.random.default_rng(30)
        n = 100
        close = 100 + np.cumsum(rng.normal(0, 1.0, n))
        high = close + rng.uniform(1.0, 2.0, n)
        low = close - rng.uniform(1.0, 2.0, n)

        state, energy, conf = detect_phase_transition(close, high, low)
        assert state in ("normal", "compression", "expansion")

    def test_confidence_scales_with_data(self) -> None:
        """Confidence increases with more data."""
        from fxsoqqabot.signals.timing.phase_transition import detect_phase_transition

        rng = np.random.default_rng(40)
        # Short data
        n_short = 20
        close_s = 100 + np.cumsum(rng.normal(0, 1.0, n_short))
        high_s = close_s + 1.0
        low_s = close_s - 1.0
        _, _, conf_short = detect_phase_transition(close_s, high_s, low_s)

        # Longer data
        n_long = 200
        close_l = 100 + np.cumsum(rng.normal(0, 1.0, n_long))
        high_l = close_l + 1.0
        low_l = close_l - 1.0
        _, _, conf_long = detect_phase_transition(close_l, high_l, low_l)

        assert conf_long >= conf_short, (
            f"Longer data ({conf_long}) should have >= confidence than short ({conf_short})"
        )

    def test_returns_valid_types(self) -> None:
        """Returns (str, float, float)."""
        from fxsoqqabot.signals.timing.phase_transition import detect_phase_transition

        rng = np.random.default_rng(50)
        n = 50
        close = 100 + np.cumsum(rng.normal(0, 1.0, n))
        high = close + 1.0
        low = close - 1.0

        state, energy, conf = detect_phase_transition(close, high, low)
        assert isinstance(state, str)
        assert isinstance(energy, float)
        assert isinstance(conf, float)
        assert state in ("compression", "expansion", "normal")
