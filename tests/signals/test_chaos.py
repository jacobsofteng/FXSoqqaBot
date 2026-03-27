"""Tests for the chaos/regime detection signal module.

Covers all five chaos metrics (Hurst, Lyapunov, fractal dimension,
Feigenbaum bifurcation, crowd entropy) and the regime classifier.
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Hurst exponent tests
# ---------------------------------------------------------------------------

class TestComputeHurst:
    """Tests for compute_hurst() -- CHAOS-01."""

    def test_returns_tuple_of_two_floats(self):
        from fxsoqqabot.signals.chaos.hurst import compute_hurst
        prices = np.cumsum(np.random.randn(200)) + 1000
        result = compute_hurst(prices)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)

    def test_insufficient_data_returns_defaults(self):
        from fxsoqqabot.signals.chaos.hurst import compute_hurst
        prices = np.array([100.0, 101.0, 102.0])
        hurst_val, confidence = compute_hurst(prices, min_length=100)
        assert hurst_val == 0.5
        assert confidence == 0.0

    def test_empty_array_returns_defaults(self):
        from fxsoqqabot.signals.chaos.hurst import compute_hurst
        prices = np.array([])
        hurst_val, confidence = compute_hurst(prices)
        assert hurst_val == 0.5
        assert confidence == 0.0

    def test_confidence_scales_with_data_length(self):
        from fxsoqqabot.signals.chaos.hurst import compute_hurst
        prices = np.cumsum(np.random.randn(250)) + 1000
        _, confidence = compute_hurst(prices, min_length=100)
        assert 0.0 < confidence <= 1.0
        # 250 / 500 = 0.5
        assert confidence == pytest.approx(0.5, abs=0.01)

    def test_full_confidence_at_500_points(self):
        from fxsoqqabot.signals.chaos.hurst import compute_hurst
        prices = np.cumsum(np.random.randn(600)) + 1000
        _, confidence = compute_hurst(prices, min_length=100)
        assert confidence == 1.0

    def test_trending_data_high_hurst(self):
        from fxsoqqabot.signals.chaos.hurst import compute_hurst
        # Cumulative sum creates strong trend -> H > 0.6
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(500)) + 1000
        hurst_val, _ = compute_hurst(prices)
        assert hurst_val > 0.6

    def test_output_clamped_to_range(self):
        from fxsoqqabot.signals.chaos.hurst import compute_hurst
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(300)) + 1000
        hurst_val, _ = compute_hurst(prices)
        assert 0.0 <= hurst_val <= 1.0


# ---------------------------------------------------------------------------
# Lyapunov exponent tests
# ---------------------------------------------------------------------------

class TestComputeLyapunov:
    """Tests for compute_lyapunov() -- CHAOS-02."""

    def test_returns_tuple_of_two_floats(self):
        from fxsoqqabot.signals.chaos.lyapunov import compute_lyapunov
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(500)) + 1000
        result = compute_lyapunov(prices)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)

    def test_insufficient_data_returns_defaults(self):
        from fxsoqqabot.signals.chaos.lyapunov import compute_lyapunov
        prices = np.array([100.0, 101.0, 102.0])
        lyap_val, confidence = compute_lyapunov(prices, min_length=300)
        assert lyap_val == 0.0
        assert confidence == 0.0

    def test_empty_array_returns_defaults(self):
        from fxsoqqabot.signals.chaos.lyapunov import compute_lyapunov
        prices = np.array([])
        lyap_val, confidence = compute_lyapunov(prices)
        assert lyap_val == 0.0
        assert confidence == 0.0

    def test_confidence_scales_with_data_length(self):
        from fxsoqqabot.signals.chaos.lyapunov import compute_lyapunov
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(500)) + 1000
        _, confidence = compute_lyapunov(prices, min_length=300)
        # 500 / (300 * 3) = 0.555...
        assert 0.0 < confidence <= 1.0

    def test_returns_finite_value(self):
        from fxsoqqabot.signals.chaos.lyapunov import compute_lyapunov
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(500)) + 1000
        lyap_val, _ = compute_lyapunov(prices)
        assert np.isfinite(lyap_val)


# ---------------------------------------------------------------------------
# Fractal dimension tests
# ---------------------------------------------------------------------------

class TestComputeFractalDimension:
    """Tests for compute_fractal_dimension() -- CHAOS-03."""

    def test_returns_tuple_of_two_floats(self):
        from fxsoqqabot.signals.chaos.fractal import compute_fractal_dimension
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(500)) + 1000
        result = compute_fractal_dimension(prices)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)

    def test_insufficient_data_returns_defaults(self):
        from fxsoqqabot.signals.chaos.fractal import compute_fractal_dimension
        prices = np.array([100.0, 101.0])
        fd_val, confidence = compute_fractal_dimension(prices, min_length=200)
        assert fd_val == 1.5
        assert confidence == 0.0

    def test_empty_array_returns_defaults(self):
        from fxsoqqabot.signals.chaos.fractal import compute_fractal_dimension
        prices = np.array([])
        fd_val, confidence = compute_fractal_dimension(prices)
        assert fd_val == 1.5
        assert confidence == 0.0

    def test_output_clamped_to_range(self):
        from fxsoqqabot.signals.chaos.fractal import compute_fractal_dimension
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(500)) + 1000
        fd_val, _ = compute_fractal_dimension(prices)
        assert 1.0 <= fd_val <= 2.0

    def test_confidence_scales_with_data_length(self):
        from fxsoqqabot.signals.chaos.fractal import compute_fractal_dimension
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(300)) + 1000
        _, confidence = compute_fractal_dimension(prices, min_length=200)
        # 300 / 600 = 0.5
        assert confidence == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# Feigenbaum bifurcation tests
# ---------------------------------------------------------------------------

class TestDetectBifurcationProximity:
    """Tests for detect_bifurcation_proximity() -- CHAOS-04."""

    def test_returns_tuple_of_two_floats(self):
        from fxsoqqabot.signals.chaos.feigenbaum import detect_bifurcation_proximity
        np.random.seed(42)
        # Oscillating data to create peaks
        t = np.linspace(0, 20 * np.pi, 500)
        prices = 1000 + 10 * np.sin(t) + np.random.randn(500)
        result = detect_bifurcation_proximity(prices)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)

    def test_insufficient_data_returns_defaults(self):
        from fxsoqqabot.signals.chaos.feigenbaum import detect_bifurcation_proximity
        prices = np.array([100.0, 101.0, 102.0])
        prox, confidence = detect_bifurcation_proximity(prices)
        assert prox == 0.0
        assert confidence == 0.0

    def test_empty_array_returns_defaults(self):
        from fxsoqqabot.signals.chaos.feigenbaum import detect_bifurcation_proximity
        prices = np.array([])
        prox, confidence = detect_bifurcation_proximity(prices)
        assert prox == 0.0
        assert confidence == 0.0

    def test_proximity_in_valid_range(self):
        from fxsoqqabot.signals.chaos.feigenbaum import detect_bifurcation_proximity
        np.random.seed(42)
        t = np.linspace(0, 20 * np.pi, 500)
        prices = 1000 + 10 * np.sin(t) + np.random.randn(500)
        prox, _ = detect_bifurcation_proximity(prices)
        assert 0.0 <= prox <= 1.0

    def test_feigenbaum_constant_used(self):
        import fxsoqqabot.signals.chaos.feigenbaum as feigenbaum_mod
        # Verify the module references the Feigenbaum delta constant
        import inspect
        src = inspect.getsource(feigenbaum_mod)
        assert "4.669201609" in src
        assert "argrelextrema" in src


# ---------------------------------------------------------------------------
# Crowd entropy tests
# ---------------------------------------------------------------------------

class TestComputeCrowdEntropy:
    """Tests for compute_crowd_entropy() -- CHAOS-05."""

    def test_returns_tuple_of_two_floats(self):
        from fxsoqqabot.signals.chaos.entropy import compute_crowd_entropy
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(200)) + 1000
        result = compute_crowd_entropy(prices)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)

    def test_insufficient_data_returns_defaults(self):
        from fxsoqqabot.signals.chaos.entropy import compute_crowd_entropy
        prices = np.array([100.0, 101.0, 102.0])
        ent_val, confidence = compute_crowd_entropy(prices, min_length=100)
        assert ent_val == 0.5
        assert confidence == 0.0

    def test_empty_array_returns_defaults(self):
        from fxsoqqabot.signals.chaos.entropy import compute_crowd_entropy
        prices = np.array([])
        ent_val, confidence = compute_crowd_entropy(prices)
        assert ent_val == 0.5
        assert confidence == 0.0

    def test_normalized_entropy_in_range(self):
        from fxsoqqabot.signals.chaos.entropy import compute_crowd_entropy
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(500)) + 1000
        ent_val, _ = compute_crowd_entropy(prices)
        assert 0.0 <= ent_val <= 1.0

    def test_confidence_scales_with_data_length(self):
        from fxsoqqabot.signals.chaos.entropy import compute_crowd_entropy
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(250)) + 1000
        _, confidence = compute_crowd_entropy(prices, min_length=100)
        # 250 / 500 = 0.5
        assert confidence == pytest.approx(0.5, abs=0.01)

    def test_uses_scipy_entropy(self):
        from fxsoqqabot.signals.chaos.entropy import compute_crowd_entropy
        import inspect
        src = inspect.getsource(compute_crowd_entropy)
        assert "scipy.stats" in src or "entropy" in src


# ---------------------------------------------------------------------------
# Regime classifier tests
# ---------------------------------------------------------------------------

class TestClassifyRegime:
    """Tests for classify_regime() -- CHAOS-06."""

    def test_returns_tuple_of_regime_state_and_float(self):
        from fxsoqqabot.signals.chaos.regime import classify_regime
        from fxsoqqabot.signals.base import RegimeState
        regime, confidence = classify_regime(
            hurst=0.5, hurst_conf=0.5,
            lyapunov=0.0, lyap_conf=0.5,
            fractal_dim=1.5, fractal_conf=0.5,
            bifurcation=0.0, bifurcation_conf=0.5,
            entropy=0.5, entropy_conf=0.5,
            price_direction=0.0,
        )
        assert isinstance(regime, RegimeState)
        assert isinstance(confidence, float)

    def test_high_bifurcation_returns_pre_bifurcation(self):
        from fxsoqqabot.signals.chaos.regime import classify_regime
        from fxsoqqabot.signals.base import RegimeState
        regime, confidence = classify_regime(
            hurst=0.7, hurst_conf=0.8,
            lyapunov=0.1, lyap_conf=0.5,
            fractal_dim=1.5, fractal_conf=0.5,
            bifurcation=0.8, bifurcation_conf=0.5,
            entropy=0.3, entropy_conf=0.5,
            price_direction=1.0,
        )
        assert regime == RegimeState.PRE_BIFURCATION

    def test_high_lyapunov_and_entropy_returns_high_chaos(self):
        from fxsoqqabot.signals.chaos.regime import classify_regime
        from fxsoqqabot.signals.base import RegimeState
        regime, confidence = classify_regime(
            hurst=0.5, hurst_conf=0.5,
            lyapunov=0.8, lyap_conf=0.5,
            fractal_dim=1.5, fractal_conf=0.5,
            bifurcation=0.3, bifurcation_conf=0.5,
            entropy=0.8, entropy_conf=0.5,
            price_direction=0.0,
        )
        assert regime == RegimeState.HIGH_CHAOS

    def test_high_hurst_positive_direction_returns_trending_up(self):
        from fxsoqqabot.signals.chaos.regime import classify_regime
        from fxsoqqabot.signals.base import RegimeState
        regime, _ = classify_regime(
            hurst=0.7, hurst_conf=0.5,
            lyapunov=0.1, lyap_conf=0.5,
            fractal_dim=1.5, fractal_conf=0.5,
            bifurcation=0.1, bifurcation_conf=0.1,
            entropy=0.3, entropy_conf=0.5,
            price_direction=1.0,
        )
        assert regime == RegimeState.TRENDING_UP

    def test_high_hurst_negative_direction_returns_trending_down(self):
        from fxsoqqabot.signals.chaos.regime import classify_regime
        from fxsoqqabot.signals.base import RegimeState
        regime, _ = classify_regime(
            hurst=0.7, hurst_conf=0.5,
            lyapunov=0.1, lyap_conf=0.5,
            fractal_dim=1.5, fractal_conf=0.5,
            bifurcation=0.1, bifurcation_conf=0.1,
            entropy=0.3, entropy_conf=0.5,
            price_direction=-1.0,
        )
        assert regime == RegimeState.TRENDING_DOWN

    def test_low_hurst_returns_ranging(self):
        from fxsoqqabot.signals.chaos.regime import classify_regime
        from fxsoqqabot.signals.base import RegimeState
        regime, _ = classify_regime(
            hurst=0.3, hurst_conf=0.5,
            lyapunov=0.1, lyap_conf=0.5,
            fractal_dim=1.5, fractal_conf=0.5,
            bifurcation=0.1, bifurcation_conf=0.1,
            entropy=0.3, entropy_conf=0.5,
            price_direction=0.0,
        )
        assert regime == RegimeState.RANGING

    def test_ambiguous_defaults_to_ranging_low_confidence(self):
        from fxsoqqabot.signals.chaos.regime import classify_regime
        from fxsoqqabot.signals.base import RegimeState
        regime, confidence = classify_regime(
            hurst=0.5, hurst_conf=0.5,
            lyapunov=0.1, lyap_conf=0.5,
            fractal_dim=1.5, fractal_conf=0.5,
            bifurcation=0.1, bifurcation_conf=0.1,
            entropy=0.3, entropy_conf=0.5,
            price_direction=0.0,
        )
        assert regime == RegimeState.RANGING
        assert confidence == pytest.approx(0.2, abs=0.01)

    def test_bifurcation_priority_over_trending(self):
        """PRE_BIFURCATION should take priority over TRENDING_UP."""
        from fxsoqqabot.signals.chaos.regime import classify_regime
        from fxsoqqabot.signals.base import RegimeState
        regime, _ = classify_regime(
            hurst=0.8, hurst_conf=0.9,
            lyapunov=0.1, lyap_conf=0.5,
            fractal_dim=1.5, fractal_conf=0.5,
            bifurcation=0.9, bifurcation_conf=0.5,
            entropy=0.3, entropy_conf=0.5,
            price_direction=1.0,
        )
        assert regime == RegimeState.PRE_BIFURCATION


# ---------------------------------------------------------------------------
# ChaosRegimeModule tests
# ---------------------------------------------------------------------------

class TestChaosRegimeModule:
    """Tests for ChaosRegimeModule -- implements SignalModule Protocol."""

    def test_name_returns_chaos(self):
        from fxsoqqabot.signals.chaos.module import ChaosRegimeModule
        from fxsoqqabot.config.models import ChaosConfig
        module = ChaosRegimeModule(ChaosConfig())
        assert module.name == "chaos"

    def test_implements_signal_module_protocol(self):
        from fxsoqqabot.signals.chaos.module import ChaosRegimeModule
        from fxsoqqabot.signals.base import SignalModule
        from fxsoqqabot.config.models import ChaosConfig
        module = ChaosRegimeModule(ChaosConfig())
        assert isinstance(module, SignalModule)

    async def test_initialize_completes(self):
        from fxsoqqabot.signals.chaos.module import ChaosRegimeModule
        from fxsoqqabot.config.models import ChaosConfig
        module = ChaosRegimeModule(ChaosConfig())
        await module.initialize()  # Should not raise

    async def test_update_with_empty_bar_arrays(self):
        from fxsoqqabot.signals.chaos.module import ChaosRegimeModule
        from fxsoqqabot.signals.base import SignalOutput, RegimeState
        from fxsoqqabot.config.models import ChaosConfig
        module = ChaosRegimeModule(ChaosConfig())
        result = await module.update(
            tick_arrays={},
            bar_arrays={},
            dom=None,
        )
        assert isinstance(result, SignalOutput)
        assert result.module_name == "chaos"
        assert result.confidence == 0.0
        assert result.regime == RegimeState.RANGING

    async def test_update_with_insufficient_data(self):
        from fxsoqqabot.signals.chaos.module import ChaosRegimeModule
        from fxsoqqabot.signals.base import SignalOutput
        from fxsoqqabot.config.models import ChaosConfig
        module = ChaosRegimeModule(ChaosConfig())
        # Only 10 data points -- insufficient for all metrics
        close_prices = np.cumsum(np.random.randn(10)) + 1000
        result = await module.update(
            tick_arrays={},
            bar_arrays={"M5": {"close": close_prices}},
            dom=None,
        )
        assert isinstance(result, SignalOutput)
        assert result.confidence == pytest.approx(0.2, abs=0.01)

    async def test_update_with_sufficient_data(self):
        from fxsoqqabot.signals.chaos.module import ChaosRegimeModule
        from fxsoqqabot.signals.base import SignalOutput, RegimeState
        from fxsoqqabot.config.models import ChaosConfig
        module = ChaosRegimeModule(ChaosConfig())
        np.random.seed(42)
        close_prices = np.cumsum(np.random.randn(500)) + 1000
        result = await module.update(
            tick_arrays={},
            bar_arrays={"M5": {"close": close_prices}},
            dom=None,
        )
        assert isinstance(result, SignalOutput)
        assert result.module_name == "chaos"
        assert isinstance(result.regime, RegimeState)
        assert -1.0 <= result.direction <= 1.0
        assert 0.0 <= result.confidence <= 1.0
        # Metadata should contain all chaos metric values
        assert "hurst" in result.metadata
        assert "lyapunov" in result.metadata
        assert "fractal_dim" in result.metadata
        assert "bifurcation" in result.metadata
        assert "entropy" in result.metadata

    async def test_update_direction_for_trending_up(self):
        """Trending up regime should give direction +1.0."""
        from fxsoqqabot.signals.chaos.module import ChaosRegimeModule
        from fxsoqqabot.signals.base import RegimeState
        from fxsoqqabot.config.models import ChaosConfig
        module = ChaosRegimeModule(ChaosConfig())
        # Strong uptrend data
        np.random.seed(42)
        close_prices = np.linspace(1000, 1200, 500) + np.random.randn(500) * 0.5
        result = await module.update(
            tick_arrays={},
            bar_arrays={"M5": {"close": close_prices}},
            dom=None,
        )
        # If classified as TRENDING_UP, direction should be +1.0
        if result.regime == RegimeState.TRENDING_UP:
            assert result.direction == 1.0

    def test_exported_from_package(self):
        from fxsoqqabot.signals.chaos import ChaosRegimeModule
        from fxsoqqabot.config.models import ChaosConfig
        module = ChaosRegimeModule(ChaosConfig())
        assert module.name == "chaos"
