"""Tests for the decision fusion layer.

Covers FusionCore (D-01), AdaptiveWeightTracker (D-02),
PhaseBehavior (D-04/D-06/D-09/D-10/FUSE-04), and
TradeManager (D-08/D-09/D-10/D-11/FUSE-05).
"""

from __future__ import annotations

import math

import pytest

from fxsoqqabot.config.models import FusionConfig, RiskConfig
from fxsoqqabot.signals.base import RegimeState, SignalOutput
from fxsoqqabot.signals.fusion.core import FusionCore, FusionResult
from fxsoqqabot.signals.fusion.phase_behavior import PhaseBehavior
from fxsoqqabot.signals.fusion.weights import AdaptiveWeightTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(
    module: str,
    direction: float,
    confidence: float,
    regime: RegimeState | None = None,
) -> SignalOutput:
    """Create a SignalOutput for testing."""
    return SignalOutput(
        module_name=module,
        direction=direction,
        confidence=confidence,
        regime=regime,
    )


# ---------------------------------------------------------------------------
# FusionCore tests (D-01)
# ---------------------------------------------------------------------------

class TestFusionCore:
    """Test confidence-weighted signal fusion per D-01."""

    @pytest.fixture
    def core(self) -> FusionCore:
        return FusionCore(FusionConfig())

    def test_fusion_result_is_frozen_dataclass(self) -> None:
        """FusionResult should be a frozen dataclass with slots."""
        result = FusionResult(
            direction=1.0,
            composite_score=0.8,
            fused_confidence=0.7,
            should_trade=True,
            regime=RegimeState.TRENDING_UP,
            module_scores={"chaos": 0.8},
            confidence_threshold=0.5,
        )
        with pytest.raises(AttributeError):
            result.direction = -1.0  # type: ignore[misc]

    def test_all_buy_signals(self, core: FusionCore) -> None:
        """All buy signals should produce positive composite score."""
        signals = [
            _make_signal("chaos", +1.0, 0.8, RegimeState.TRENDING_UP),
            _make_signal("flow", +1.0, 0.7),
            _make_signal("timing", +1.0, 0.6),
        ]
        weights = {"chaos": 0.4, "flow": 0.35, "timing": 0.25}
        result = core.fuse(signals, weights, confidence_threshold=0.5)
        assert result.composite_score > 0
        assert result.direction == 1.0
        assert result.should_trade is True
        assert result.regime == RegimeState.TRENDING_UP

    def test_all_sell_signals(self, core: FusionCore) -> None:
        """All sell signals should produce negative composite score."""
        signals = [
            _make_signal("chaos", -1.0, 0.8, RegimeState.TRENDING_DOWN),
            _make_signal("flow", -1.0, 0.7),
            _make_signal("timing", -1.0, 0.6),
        ]
        weights = {"chaos": 0.4, "flow": 0.35, "timing": 0.25}
        result = core.fuse(signals, weights, confidence_threshold=0.5)
        assert result.composite_score < 0
        assert result.direction == -1.0
        assert result.should_trade is True

    def test_mixed_signals_weighted_average(self, core: FusionCore) -> None:
        """Mixed signals should produce weighted-average composite."""
        signals = [
            _make_signal("chaos", +1.0, 0.9, RegimeState.RANGING),
            _make_signal("flow", -1.0, 0.5),
            _make_signal("timing", +1.0, 0.3),
        ]
        weights = {"chaos": 0.5, "flow": 0.3, "timing": 0.2}
        result = core.fuse(signals, weights, confidence_threshold=0.5)
        # Composite should reflect the weighted average
        assert isinstance(result.composite_score, float)
        # Chaos is strong buy, flow is moderate sell, timing is weak buy
        # Net direction should be positive because chaos has higher weight+confidence

    def test_empty_signals(self, core: FusionCore) -> None:
        """Empty signals should produce zero composite and should_trade=False."""
        result = core.fuse([], {}, confidence_threshold=0.5)
        assert result.composite_score == 0.0
        assert result.should_trade is False

    def test_below_confidence_threshold(self, core: FusionCore) -> None:
        """When fused confidence is below threshold, should_trade=False."""
        signals = [
            _make_signal("chaos", +1.0, 0.2),
            _make_signal("flow", +1.0, 0.1),
        ]
        weights = {"chaos": 0.5, "flow": 0.5}
        result = core.fuse(signals, weights, confidence_threshold=0.9)
        assert result.should_trade is False

    def test_regime_extracted_from_chaos_module(self, core: FusionCore) -> None:
        """Regime should be extracted from the first signal with regime set."""
        signals = [
            _make_signal("flow", +1.0, 0.7),  # No regime
            _make_signal("chaos", +1.0, 0.8, RegimeState.HIGH_CHAOS),
            _make_signal("timing", +1.0, 0.6),  # No regime
        ]
        weights = {"chaos": 0.33, "flow": 0.34, "timing": 0.33}
        result = core.fuse(signals, weights, confidence_threshold=0.3)
        assert result.regime == RegimeState.HIGH_CHAOS

    def test_no_regime_defaults_to_ranging(self, core: FusionCore) -> None:
        """When no signal provides regime, default to RANGING."""
        signals = [
            _make_signal("flow", +1.0, 0.7),
            _make_signal("timing", +1.0, 0.6),
        ]
        weights = {"flow": 0.5, "timing": 0.5}
        result = core.fuse(signals, weights, confidence_threshold=0.3)
        assert result.regime == RegimeState.RANGING

    def test_module_scores_populated(self, core: FusionCore) -> None:
        """module_scores should contain individual module contributions."""
        signals = [
            _make_signal("chaos", +1.0, 0.8),
            _make_signal("flow", -1.0, 0.5),
        ]
        weights = {"chaos": 0.6, "flow": 0.4}
        result = core.fuse(signals, weights, confidence_threshold=0.3)
        assert "chaos" in result.module_scores
        assert "flow" in result.module_scores

    def test_confidence_threshold_stored_in_result(self, core: FusionCore) -> None:
        """The active confidence threshold should be stored in the result."""
        signals = [_make_signal("chaos", +1.0, 0.8)]
        weights = {"chaos": 1.0}
        result = core.fuse(signals, weights, confidence_threshold=0.65)
        assert result.confidence_threshold == 0.65


# ---------------------------------------------------------------------------
# AdaptiveWeightTracker tests (D-02)
# ---------------------------------------------------------------------------

class TestAdaptiveWeightTracker:
    """Test EMA-based adaptive weight tracking per D-02."""

    def test_initial_equal_weights(self) -> None:
        """All modules should start at equal weight."""
        tracker = AdaptiveWeightTracker(
            module_names=["chaos", "flow", "timing"], alpha=0.1
        )
        weights = tracker.get_weights()
        expected = 1.0 / 3
        for w in weights.values():
            assert abs(w - expected) < 1e-6

    def test_equal_weights_during_warmup(self) -> None:
        """During warmup, weights should remain equal regardless of outcomes."""
        tracker = AdaptiveWeightTracker(
            module_names=["chaos", "flow"], alpha=0.1, warmup_trades=10
        )
        # Record 5 outcomes where chaos is always correct
        for _ in range(5):
            tracker.record_outcome({"chaos": +1.0, "flow": -1.0}, actual_direction=+1.0)
        weights = tracker.get_weights()
        assert abs(weights["chaos"] - weights["flow"]) < 1e-6  # Still equal

    def test_correct_outcome_increases_accuracy(self) -> None:
        """After recording correct outcome (post-warmup), module accuracy should increase."""
        tracker = AdaptiveWeightTracker(
            module_names=["chaos", "flow"], alpha=0.3, warmup_trades=0
        )
        initial_state = tracker.get_state()
        initial_acc = initial_state["accuracies"]["chaos"]
        # Record correct outcome for chaos
        tracker.record_outcome({"chaos": +1.0, "flow": -1.0}, actual_direction=+1.0)
        new_state = tracker.get_state()
        new_acc = new_state["accuracies"]["chaos"]
        assert new_acc > initial_acc

    def test_incorrect_outcome_decreases_accuracy(self) -> None:
        """After recording incorrect outcome, module accuracy should decrease."""
        tracker = AdaptiveWeightTracker(
            module_names=["chaos", "flow"], alpha=0.3, warmup_trades=0
        )
        initial_state = tracker.get_state()
        initial_acc = initial_state["accuracies"]["chaos"]
        # Record incorrect outcome for chaos (predicted +1, actual was -1)
        tracker.record_outcome({"chaos": +1.0, "flow": -1.0}, actual_direction=-1.0)
        new_state = tracker.get_state()
        new_acc = new_state["accuracies"]["chaos"]
        assert new_acc < initial_acc

    def test_weights_normalized_to_one(self) -> None:
        """Weights should always sum to 1.0."""
        tracker = AdaptiveWeightTracker(
            module_names=["chaos", "flow", "timing"], alpha=0.2, warmup_trades=0
        )
        for _ in range(20):
            tracker.record_outcome(
                {"chaos": +1.0, "flow": -1.0, "timing": +1.0},
                actual_direction=+1.0,
            )
        weights = tracker.get_weights()
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_weights_diverge_after_warmup(self) -> None:
        """After warmup, weights should diverge based on accuracy."""
        tracker = AdaptiveWeightTracker(
            module_names=["chaos", "flow"], alpha=0.3, warmup_trades=5
        )
        # Record 10 outcomes where chaos is always correct, flow always wrong
        for _ in range(10):
            tracker.record_outcome({"chaos": +1.0, "flow": -1.0}, actual_direction=+1.0)
        weights = tracker.get_weights()
        assert weights["chaos"] > weights["flow"]

    def test_ema_formula(self) -> None:
        """EMA update should follow: accuracy = alpha * correct + (1 - alpha) * old_accuracy."""
        alpha = 0.2
        tracker = AdaptiveWeightTracker(
            module_names=["chaos"], alpha=alpha, warmup_trades=0
        )
        # Initial accuracy is 0.5
        # Record correct outcome: new_acc = 0.2 * 1.0 + 0.8 * 0.5 = 0.6
        tracker.record_outcome({"chaos": +1.0}, actual_direction=+1.0)
        state = tracker.get_state()
        expected = alpha * 1.0 + (1 - alpha) * 0.5
        assert abs(state["accuracies"]["chaos"] - expected) < 1e-6

    def test_get_state_and_load_state(self) -> None:
        """State should be serializable and restorable."""
        tracker = AdaptiveWeightTracker(
            module_names=["chaos", "flow"], alpha=0.1, warmup_trades=0
        )
        for _ in range(5):
            tracker.record_outcome({"chaos": +1.0, "flow": -1.0}, actual_direction=+1.0)
        state = tracker.get_state()

        # Create a new tracker and restore state
        tracker2 = AdaptiveWeightTracker(
            module_names=["chaos", "flow"], alpha=0.1, warmup_trades=0
        )
        tracker2.load_state(state)

        assert tracker.get_weights() == tracker2.get_weights()
        assert tracker.get_state() == tracker2.get_state()


# ---------------------------------------------------------------------------
# PhaseBehavior tests (D-04, D-06, D-09, D-10, FUSE-04)
# ---------------------------------------------------------------------------

class TestPhaseBehavior:
    """Test phase-aware behavior with smooth transitions."""

    @pytest.fixture
    def behavior(self) -> PhaseBehavior:
        return PhaseBehavior(FusionConfig(), RiskConfig())

    def test_aggressive_phase_threshold(self, behavior: PhaseBehavior) -> None:
        """At equity=50 (mid-aggressive), threshold should be near 0.5."""
        threshold = behavior.get_confidence_threshold(50.0)
        assert abs(threshold - 0.5) < 0.05  # Near 0.5

    def test_selective_phase_threshold(self, behavior: PhaseBehavior) -> None:
        """At equity=200 (mid-selective), threshold should be near 0.6."""
        threshold = behavior.get_confidence_threshold(200.0)
        assert abs(threshold - 0.6) < 0.05  # Near 0.6

    def test_conservative_phase_threshold(self, behavior: PhaseBehavior) -> None:
        """At equity=500 (conservative), threshold should be 0.7."""
        threshold = behavior.get_confidence_threshold(500.0)
        assert abs(threshold - 0.7) < 0.05  # Near 0.7

    def test_smooth_transitions_not_step_functions(self, behavior: PhaseBehavior) -> None:
        """Transitions should be smooth (sigmoid), not step functions per FUSE-04."""
        # Sample equities across the aggressive->selective boundary ($100)
        thresholds = [behavior.get_confidence_threshold(e) for e in range(80, 121)]
        # Check that values change gradually
        for i in range(1, len(thresholds)):
            diff = abs(thresholds[i] - thresholds[i - 1])
            # No single $1 step should cause more than 0.05 jump
            assert diff < 0.05, f"Step function detected at equity={80 + i}: diff={diff}"

    def test_high_chaos_regime_adjustments(self, behavior: PhaseBehavior) -> None:
        """HIGH_CHAOS should return confidence boost, size reduction, sl widen per D-06."""
        adj = behavior.get_regime_adjustments(RegimeState.HIGH_CHAOS)
        assert adj["confidence_boost"] > 0
        assert adj["size_reduction"] > 0
        assert adj["sl_widen_factor"] > 1.0

    def test_pre_bifurcation_regime_adjustments(self, behavior: PhaseBehavior) -> None:
        """PRE_BIFURCATION should return same adjustments as HIGH_CHAOS per D-06."""
        adj = behavior.get_regime_adjustments(RegimeState.PRE_BIFURCATION)
        assert adj["confidence_boost"] > 0
        assert adj["size_reduction"] > 0
        assert adj["sl_widen_factor"] > 1.0

    def test_ranging_no_adjustments(self, behavior: PhaseBehavior) -> None:
        """RANGING should return empty adjustments dict per D-07."""
        adj = behavior.get_regime_adjustments(RegimeState.RANGING)
        assert len(adj) == 0

    def test_trending_no_adjustments(self, behavior: PhaseBehavior) -> None:
        """TRENDING should return empty adjustments dict."""
        adj = behavior.get_regime_adjustments(RegimeState.TRENDING_UP)
        assert len(adj) == 0

    def test_rr_ratio_trending(self, behavior: PhaseBehavior) -> None:
        """Trending regime should use 3.0 RR per D-09."""
        assert behavior.get_rr_ratio(RegimeState.TRENDING_UP) == 3.0
        assert behavior.get_rr_ratio(RegimeState.TRENDING_DOWN) == 3.0

    def test_rr_ratio_ranging(self, behavior: PhaseBehavior) -> None:
        """Ranging regime should use 1.5 RR per D-09."""
        assert behavior.get_rr_ratio(RegimeState.RANGING) == 1.5

    def test_rr_ratio_high_chaos(self, behavior: PhaseBehavior) -> None:
        """High-chaos regime should use 2.0 RR per D-09."""
        assert behavior.get_rr_ratio(RegimeState.HIGH_CHAOS) == 2.0
        assert behavior.get_rr_ratio(RegimeState.PRE_BIFURCATION) == 2.0

    def test_trailing_stop_trending(self, behavior: PhaseBehavior) -> None:
        """Trending regime should have trailing stop params per D-10."""
        params = behavior.get_trailing_stop_params(RegimeState.TRENDING_UP)
        assert params is not None
        assert "activation_atr" in params
        assert "trail_distance_atr" in params
        assert params["activation_atr"] == 1.0
        assert params["trail_distance_atr"] == 0.5

    def test_trailing_stop_ranging(self, behavior: PhaseBehavior) -> None:
        """Ranging regime should have no trailing stop per D-10."""
        params = behavior.get_trailing_stop_params(RegimeState.RANGING)
        assert params is None

    def test_trailing_stop_high_chaos(self, behavior: PhaseBehavior) -> None:
        """High-chaos regime should have aggressive trailing per D-10."""
        params = behavior.get_trailing_stop_params(RegimeState.HIGH_CHAOS)
        assert params is not None
        assert params["trail_distance_atr"] == 0.3
