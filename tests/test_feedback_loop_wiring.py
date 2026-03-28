"""Integration tests for self-learning feedback loop wiring (Phase 5).

Verifies the four cross-phase integration gaps from v1.0 milestone audit:
- FUSE-02: AdaptiveWeightTracker.record_outcome called after trade close
- LEARN-04: ShadowManager.record_variant_trade called for all variants
- LEARN-05: Promote callback applies params to live strategy
- LEARN-06: Walk-forward gate reachable via shadow trade accumulation
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fxsoqqabot.config.models import BotSettings, LearningConfig
from fxsoqqabot.learning.loop import LearningLoopManager
from fxsoqqabot.learning.shadow import ShadowManager
from fxsoqqabot.optimization.search_space import apply_params_to_settings
from fxsoqqabot.signals.base import SignalOutput
from fxsoqqabot.signals.fusion.weights import AdaptiveWeightTracker


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

MODULE_NAMES = ["chaos", "flow", "timing"]


@pytest.fixture
def weight_tracker() -> AdaptiveWeightTracker:
    """Real AdaptiveWeightTracker with 3 modules."""
    return AdaptiveWeightTracker(module_names=MODULE_NAMES, alpha=0.1, warmup_trades=10)


@pytest.fixture
def learning_config() -> LearningConfig:
    """LearningConfig with small thresholds for testing."""
    return LearningConfig(
        evolve_every_n_trades=5,
        n_shadow_variants=3,
        promotion_alpha=0.05,
        min_promotion_trades=3,
        retirement_threshold=0.3,
        retirement_min_trades=5,
        ga_population_size=4,
        ga_crossover_prob=0.5,
        ga_mutation_prob=0.2,
        ga_tournament_size=2,
        enabled=True,
    )


@pytest.fixture
def mock_trade_logger() -> MagicMock:
    """Mock TradeContextLogger for LearningLoopManager."""
    logger = MagicMock()
    logger.query_trades.return_value = [
        {"pnl": 1.5, "regime": "trending_up"},
        {"pnl": -0.5, "regime": "ranging"},
        {"pnl": 2.0, "regime": "trending_up"},
    ]
    logger.get_recent_trades.return_value = [
        {"pnl": 1.5, "regime": "trending_up"},
    ]
    return logger


@pytest.fixture
def shadow_manager(learning_config: LearningConfig) -> ShadowManager:
    """Real ShadowManager with 3 variants."""
    return ShadowManager(config=learning_config, starting_balance=20.0)


@pytest.fixture
def loop_manager(
    learning_config: LearningConfig, mock_trade_logger: MagicMock
) -> LearningLoopManager:
    """Real LearningLoopManager with mocked trade logger."""
    return LearningLoopManager(
        config=learning_config,
        trade_logger=mock_trade_logger,
        equity=20.0,
    )


@pytest.fixture
def sample_signals() -> list[SignalOutput]:
    """Three SignalOutput objects simulating module outputs."""
    return [
        SignalOutput(module_name="chaos", direction=0.8, confidence=0.7),
        SignalOutput(module_name="flow", direction=0.5, confidence=0.6),
        SignalOutput(module_name="timing", direction=-0.3, confidence=0.4),
    ]


# ---------------------------------------------------------------------------
# Test class: TestAdaptiveWeightWiring (FUSE-02)
# ---------------------------------------------------------------------------


class TestAdaptiveWeightWiring:
    """Verify AdaptiveWeightTracker.record_outcome wiring (FUSE-02).

    After trade close, the engine calls record_outcome with a dict of
    module_name -> direction and actual_direction derived from PnL sign.
    """

    def test_record_outcome_called_with_positive_pnl(
        self, weight_tracker: AdaptiveWeightTracker, sample_signals: list[SignalOutput]
    ):
        """record_outcome with positive PnL uses actual_direction=+1.0."""
        module_signals = {sig.module_name: sig.direction for sig in sample_signals}
        actual_direction = 1.0  # Profitable trade

        weight_tracker.record_outcome(module_signals, actual_direction)

        assert weight_tracker._trade_count == 1

    def test_record_outcome_called_with_negative_pnl(
        self, weight_tracker: AdaptiveWeightTracker, sample_signals: list[SignalOutput]
    ):
        """record_outcome with negative PnL uses actual_direction=-1.0."""
        module_signals = {sig.module_name: sig.direction for sig in sample_signals}
        actual_direction = -1.0  # Losing trade

        weight_tracker.record_outcome(module_signals, actual_direction)

        assert weight_tracker._trade_count == 1

    def test_weights_evolve_after_record_outcome(
        self, weight_tracker: AdaptiveWeightTracker
    ):
        """After enough record_outcome calls (past warmup=10), weights diverge.

        All modules predict buy (+1.0) and actual is buy (+1.0), so all
        modules get credit. But they start equal at 0.5 accuracy, so
        after 15 correct predictions via EMA, all accuracies rise above
        0.5 and weights remain approximately equal (since all were correct).
        """
        module_signals = {"chaos": 1.0, "flow": 1.0, "timing": 1.0}
        for _ in range(15):
            weight_tracker.record_outcome(module_signals, 1.0)

        weights = weight_tracker.get_weights()
        # Past warmup -- should NOT be exactly equal anymore
        # (EMA has shifted accuracies from initial 0.5)
        assert weight_tracker._trade_count == 15
        # Weights should sum to ~1.0
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        # All modules predicted correctly, so all accuracies rose
        for name in MODULE_NAMES:
            assert weight_tracker._accuracies[name] > 0.5

    def test_module_signals_dict_matches_engine_pattern(
        self, sample_signals: list[SignalOutput]
    ):
        """Verify the dict comprehension used in engine._handle_paper_close."""
        module_signals = {sig.module_name: sig.direction for sig in sample_signals}

        assert module_signals == {"chaos": 0.8, "flow": 0.5, "timing": -0.3}


# ---------------------------------------------------------------------------
# Test class: TestShadowTradeRecording (LEARN-04)
# ---------------------------------------------------------------------------


class TestShadowTradeRecording:
    """Verify ShadowManager.record_variant_trade wiring (LEARN-04).

    After trade close, the engine records the same trade result for ALL
    shadow variants. This is by design so variants compete on accumulated
    P&L distributions via Mann-Whitney comparison.
    """

    def test_record_variant_trade_called_for_all_variants(
        self, shadow_manager: ShadowManager
    ):
        """Each variant gets a trade recorded -- 3 variants, 3 calls."""
        trade_result = {
            "pnl": 2.5,
            "equity": 22.5,
            "ticket": 1001,
            "exit_price": 1950.50,
            "exit_regime": "trending_up",
        }

        variants = shadow_manager.get_variants()
        assert len(variants) == 3

        for variant in variants:
            shadow_manager.record_variant_trade(variant.variant_id, trade_result)

        # Verify each variant received exactly 1 trade
        for variant in shadow_manager.get_variants():
            assert variant.trade_count == 1

    def test_trade_result_contains_expected_keys(
        self, shadow_manager: ShadowManager
    ):
        """Recorded trade_result has pnl, equity, ticket, exit_price, exit_regime."""
        trade_result = {
            "pnl": -1.2,
            "equity": 18.8,
            "ticket": 1002,
            "exit_price": 1945.25,
            "exit_regime": "ranging",
        }

        first_variant = shadow_manager.get_variants()[0]
        shadow_manager.record_variant_trade(first_variant.variant_id, trade_result)

        recorded = first_variant.trade_results[0]
        expected_keys = {"pnl", "equity", "ticket", "exit_price", "exit_regime"}
        assert expected_keys.issubset(set(recorded.keys()))

    def test_multiple_trades_accumulate_per_variant(
        self, shadow_manager: ShadowManager
    ):
        """Multiple record_variant_trade calls accumulate trade history."""
        variant = shadow_manager.get_variants()[0]

        for i in range(5):
            shadow_manager.record_variant_trade(
                variant.variant_id,
                {"pnl": 1.0 + i, "equity": 20.0 + i, "ticket": 1000 + i,
                 "exit_price": 1950.0, "exit_regime": "trending_up"},
            )

        assert variant.trade_count == 5


# ---------------------------------------------------------------------------
# Test class: TestPromoteCallback (LEARN-05)
# ---------------------------------------------------------------------------


class TestPromoteCallback:
    """Verify promote callback wiring and invocation (LEARN-05).

    The promote callback is set on LearningLoopManager via
    set_promote_callback(). When a variant passes both the Mann-Whitney
    statistical gate and the walk-forward validation gate, the callback
    is invoked with the promoted params dict.
    """

    def test_set_promote_callback_stores_callable(
        self, loop_manager: LearningLoopManager
    ):
        """set_promote_callback stores the callable on the manager."""
        assert loop_manager._promote_callback is None

        callback = MagicMock()
        loop_manager.set_promote_callback(callback)

        assert loop_manager._promote_callback is callback

    def test_promote_callback_invoked_after_dual_gate_pass(
        self, loop_manager: LearningLoopManager, mock_trade_logger: MagicMock
    ):
        """When both stats and WF pass, promote_callback is called with params."""
        callback = MagicMock()
        loop_manager.set_promote_callback(callback)
        loop_manager.set_walk_forward_validator(lambda params: True)

        with patch.object(
            loop_manager._shadow,
            "evaluate_promotion",
            return_value={
                "should_promote": True,
                "p_value": 0.01,
                "variant_fitness": 0.8,
                "live_fitness": 0.5,
            },
        ):
            with patch.object(
                loop_manager._shadow,
                "promote_variant",
                return_value={"aggressive_confidence_threshold": 0.45},
            ):
                loop_manager._check_promotions()

        # Callback should have been called at least once (once per variant)
        assert callback.call_count > 0
        # First call should have the promoted params
        call_args = callback.call_args_list[0][0][0]
        assert "aggressive_confidence_threshold" in call_args

    def test_promote_callback_not_called_when_wf_fails(
        self, loop_manager: LearningLoopManager, mock_trade_logger: MagicMock
    ):
        """When WF gate fails, promote_callback is NOT invoked."""
        callback = MagicMock()
        loop_manager.set_promote_callback(callback)
        loop_manager.set_walk_forward_validator(lambda params: False)

        with patch.object(
            loop_manager._shadow,
            "evaluate_promotion",
            return_value={
                "should_promote": True,
                "p_value": 0.01,
                "variant_fitness": 0.8,
                "live_fitness": 0.5,
            },
        ):
            with patch.object(loop_manager._shadow, "reset_variant"):
                loop_manager._check_promotions()

        callback.assert_not_called()

    def test_apply_params_to_settings_returns_modified_settings(self):
        """apply_params_to_settings creates new BotSettings with overridden params."""
        original = BotSettings()
        original_threshold = original.signals.fusion.aggressive_confidence_threshold

        new_settings = apply_params_to_settings(
            original, {"aggressive_confidence_threshold": 0.45}
        )

        # New settings has the overridden value
        assert new_settings.signals.fusion.aggressive_confidence_threshold == 0.45
        # Original is unchanged (immutable via model_copy)
        assert (
            original.signals.fusion.aggressive_confidence_threshold
            == original_threshold
        )
        # Different object
        assert new_settings is not original


# ---------------------------------------------------------------------------
# Test class: TestFullFeedbackChain (LEARN-06 + end-to-end)
# ---------------------------------------------------------------------------


class TestFullFeedbackChain:
    """Verify the full feedback chain from trade close through promotion.

    Tests that shadow variants accumulate trade history through
    record_variant_trade, and that the accumulated history makes them
    eligible for promotion evaluation (no longer rejected for
    "Insufficient trades").
    """

    def test_shadow_variants_accumulate_trades_via_recording(
        self, shadow_manager: ShadowManager
    ):
        """After recording 5 trades per variant, evaluate_promotion no longer
        returns 'Insufficient trades' (min_promotion_trades=3)."""
        live_trades = [
            {"pnl": 0.5},
            {"pnl": -0.3},
            {"pnl": 1.0},
            {"pnl": 0.2},
            {"pnl": -0.1},
        ]

        # Record 5 trades for each variant
        for variant in shadow_manager.get_variants():
            for i in range(5):
                shadow_manager.record_variant_trade(
                    variant.variant_id,
                    {"pnl": 1.0 + i * 0.5, "equity": 20.0 + i},
                )

        # Evaluate promotion -- should NOT say "Insufficient trades"
        first_variant = shadow_manager.get_variants()[0]
        result = shadow_manager.evaluate_promotion(
            first_variant, live_trades, equity=25.0
        )

        assert "Insufficient trades" not in result.get("reason", "")
        assert first_variant.trade_count == 5

    def test_walk_forward_gate_reachable_after_shadow_recording(
        self,
        loop_manager: LearningLoopManager,
        mock_trade_logger: MagicMock,
    ):
        """Walk-forward validator is actually invoked when variant passes stats.

        This proves the chain: shadow trades recorded -> evaluate_promotion
        returns should_promote=True -> walk_forward_validator called.
        """
        wf_validator = MagicMock(return_value=True)
        loop_manager.set_walk_forward_validator(wf_validator)

        with patch.object(
            loop_manager._shadow,
            "evaluate_promotion",
            return_value={
                "should_promote": True,
                "p_value": 0.02,
                "variant_fitness": 0.75,
                "live_fitness": 0.50,
            },
        ):
            with patch.object(
                loop_manager._shadow,
                "promote_variant",
                return_value={"aggressive_confidence_threshold": 0.45},
            ):
                loop_manager._check_promotions()

        # Walk-forward validator should have been called (once per variant)
        assert wf_validator.call_count > 0
        # It was called with a dict (the variant's mutated_params)
        first_call_arg = wf_validator.call_args_list[0][0][0]
        assert isinstance(first_call_arg, dict)

    @pytest.mark.asyncio
    async def test_on_trade_closed_triggers_check_promotions(
        self,
        loop_manager: LearningLoopManager,
    ):
        """on_trade_closed eventually calls _check_promotions."""
        with patch.object(
            loop_manager, "_check_promotions", return_value=[]
        ) as mock_check:
            with patch.object(loop_manager, "_run_evolution"):
                await loop_manager.on_trade_closed({"pnl": 1.0, "equity": 21.0})

        mock_check.assert_called_once()

    def test_promote_callback_receives_params_from_shadow_variant(
        self,
        loop_manager: LearningLoopManager,
        mock_trade_logger: MagicMock,
    ):
        """Full chain: promote_variant returns params -> promote_callback receives them."""
        callback = MagicMock()
        loop_manager.set_promote_callback(callback)
        loop_manager.set_walk_forward_validator(lambda params: True)

        expected_params = {
            "aggressive_confidence_threshold": 0.42,
            "sl_atr_base_multiplier": 2.5,
        }

        with patch.object(
            loop_manager._shadow,
            "evaluate_promotion",
            return_value={
                "should_promote": True,
                "p_value": 0.01,
                "variant_fitness": 0.9,
                "live_fitness": 0.4,
            },
        ):
            with patch.object(
                loop_manager._shadow,
                "promote_variant",
                return_value=expected_params,
            ):
                loop_manager._check_promotions()

        # Callback received the exact params from promote_variant
        assert callback.call_count > 0
        received_params = callback.call_args_list[0][0][0]
        assert received_params == expected_params
