"""Tests for LearningLoopManager orchestrating all learning sub-components.

Tests verify that:
- LearningLoopManager initializes all sub-components
- on_trade_closed() increments trade counter
- on_trade_closed() triggers _run_evolution() at threshold
- _run_evolution() calls evolution.run_generation()
- _check_promotions() evaluates shadow variants against live trades
- _retrain_classifier() is called periodically (every 100 trades)
- on_trade_closed() logs trade outcome to retirement tracker
- get_learning_status() returns comprehensive summary
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fxsoqqabot.config.models import LearningConfig


@pytest.fixture
def learning_config() -> LearningConfig:
    """Create a LearningConfig with small thresholds for testing."""
    return LearningConfig(
        evolve_every_n_trades=5,
        n_shadow_variants=2,
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
    """Create a mock TradeContextLogger."""
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
def loop_manager(learning_config, mock_trade_logger):
    """Create a LearningLoopManager with mocked dependencies."""
    from fxsoqqabot.learning.loop import LearningLoopManager

    return LearningLoopManager(
        config=learning_config,
        trade_logger=mock_trade_logger,
        equity=20.0,
    )


class TestLearningLoopManagerInit:
    """Test 1: LearningLoopManager initializes all sub-components."""

    def test_initializes_evolution_manager(self, loop_manager):
        from fxsoqqabot.learning.evolution import EvolutionManager

        assert isinstance(loop_manager._evolution, EvolutionManager)

    def test_initializes_shadow_manager(self, loop_manager):
        from fxsoqqabot.learning.shadow import ShadowManager

        assert isinstance(loop_manager._shadow, ShadowManager)

    def test_initializes_classifier(self, loop_manager):
        from fxsoqqabot.learning.classifier import RegimeClassifier

        assert isinstance(loop_manager._classifier, RegimeClassifier)

    def test_initializes_retirement_tracker(self, loop_manager):
        from fxsoqqabot.learning.retirement import RuleRetirementTracker

        assert isinstance(loop_manager._retirement, RuleRetirementTracker)

    def test_initializes_analyzer(self, loop_manager):
        from fxsoqqabot.learning.analyzer import SignalAnalyzer

        assert isinstance(loop_manager._analyzer, SignalAnalyzer)

    def test_counters_start_at_zero(self, loop_manager):
        assert loop_manager._trades_since_evolve == 0
        assert loop_manager._trades_since_retrain == 0
        assert loop_manager._total_trades == 0


class TestOnTradeClosed:
    """Test 2-3: on_trade_closed() increments counter and triggers evolution."""

    @pytest.mark.asyncio
    async def test_increments_trade_counter(self, loop_manager):
        trade_result = {"pnl": 1.5, "equity": 21.5}
        await loop_manager.on_trade_closed(trade_result)
        assert loop_manager._total_trades == 1
        assert loop_manager._trades_since_evolve == 1
        assert loop_manager._trades_since_retrain == 1

    @pytest.mark.asyncio
    async def test_triggers_evolution_at_threshold(self, loop_manager):
        """When trades_since_evolve reaches evolve_every_n_trades (5), evolution runs."""
        with patch.object(loop_manager, "_run_evolution") as mock_evolve:
            for i in range(5):
                await loop_manager.on_trade_closed({"pnl": 1.0, "equity": 21.0 + i})
            mock_evolve.assert_called_once()

    @pytest.mark.asyncio
    async def test_resets_evolve_counter_after_evolution(self, loop_manager):
        with patch.object(loop_manager, "_run_evolution"):
            for i in range(5):
                await loop_manager.on_trade_closed({"pnl": 1.0, "equity": 21.0 + i})
            assert loop_manager._trades_since_evolve == 0

    @pytest.mark.asyncio
    async def test_does_not_trigger_evolution_before_threshold(self, loop_manager):
        with patch.object(loop_manager, "_run_evolution") as mock_evolve:
            for i in range(4):
                await loop_manager.on_trade_closed({"pnl": 1.0, "equity": 21.0 + i})
            mock_evolve.assert_not_called()


class TestRunEvolution:
    """Test 4: _run_evolution() calls evolution.run_generation()."""

    def test_calls_evolution_run_generation(self, loop_manager, mock_trade_logger):
        mock_trade_logger.query_trades.return_value = [
            {"pnl": 1.0},
            {"pnl": -0.5},
        ]
        with patch.object(
            loop_manager._evolution, "run_generation", return_value={
                "generation": 1,
                "best_fitness": 2.0,
                "best_params": {},
            }
        ) as mock_gen:
            loop_manager._run_evolution()
            mock_gen.assert_called_once()

    def test_queries_trades_from_logger(self, loop_manager, mock_trade_logger):
        with patch.object(
            loop_manager._evolution, "run_generation", return_value={
                "generation": 1,
                "best_fitness": 2.0,
                "best_params": {},
            }
        ):
            loop_manager._run_evolution()
            mock_trade_logger.query_trades.assert_called_with(limit=200)


class TestCheckPromotions:
    """Test 5: _check_promotions() evaluates shadow variants."""

    def test_evaluates_each_variant(self, loop_manager, mock_trade_logger):
        with patch.object(
            loop_manager._shadow, "evaluate_promotion",
            return_value={"should_promote": False, "p_value": 0.5}
        ) as mock_eval:
            loop_manager._check_promotions()
            # Should call evaluate for each variant
            assert mock_eval.call_count == len(loop_manager._shadow.get_variants())

    def test_promotes_variant_when_should_promote(self, loop_manager, mock_trade_logger):
        with patch.object(
            loop_manager._shadow, "evaluate_promotion",
            return_value={
                "should_promote": True,
                "p_value": 0.01,
                "variant_fitness": 0.8,
                "live_fitness": 0.5,
            }
        ):
            with patch.object(
                loop_manager._shadow, "promote_variant",
                return_value={"param1": 0.5}
            ) as mock_promote:
                mutations = loop_manager._check_promotions()
                assert mock_promote.call_count > 0
                assert len(mutations) > 0


class TestRetrainClassifier:
    """Test 6: _retrain_classifier() is called periodically."""

    @pytest.mark.asyncio
    async def test_retrain_called_at_100_trades(self, loop_manager):
        with patch.object(loop_manager, "_run_evolution"):
            with patch.object(loop_manager, "_retrain_classifier") as mock_retrain:
                for i in range(100):
                    await loop_manager.on_trade_closed({"pnl": 0.5, "equity": 20.0 + i * 0.5})
                mock_retrain.assert_called_once()

    def test_retrain_calls_classifier_train(self, loop_manager, mock_trade_logger):
        with patch.object(
            loop_manager._classifier, "train", return_value={
                "is_trained": True,
                "cv_accuracy": 0.85,
            }
        ) as mock_train:
            loop_manager._retrain_classifier()
            mock_train.assert_called_once()


class TestRetirementTracking:
    """Test 7: on_trade_closed() logs trade outcome to retirement tracker."""

    @pytest.mark.asyncio
    async def test_records_outcome_for_rules(self, loop_manager):
        with patch.object(
            loop_manager._retirement, "record_outcome"
        ) as mock_record:
            await loop_manager.on_trade_closed({"pnl": 1.5, "equity": 21.5})
            # Should record outcome for active rules
            assert mock_record.call_count > 0


class TestGetLearningStatus:
    """Test 8: get_learning_status() returns summary of all sub-components."""

    def test_returns_total_trades(self, loop_manager):
        status = loop_manager.get_learning_status()
        assert "total_trades" in status
        assert status["total_trades"] == 0

    def test_returns_trades_until_evolve(self, loop_manager):
        status = loop_manager.get_learning_status()
        assert "trades_until_evolve" in status
        assert status["trades_until_evolve"] == 5  # evolve_every_n_trades

    def test_returns_shadow_variants(self, loop_manager):
        status = loop_manager.get_learning_status()
        assert "shadow_variants" in status
        assert isinstance(status["shadow_variants"], list)

    def test_returns_classifier_trained(self, loop_manager):
        status = loop_manager.get_learning_status()
        assert "classifier_trained" in status
        assert status["classifier_trained"] is False

    def test_returns_rule_status(self, loop_manager):
        status = loop_manager.get_learning_status()
        assert "rule_status" in status
        assert isinstance(status["rule_status"], dict)

    def test_returns_recent_mutations(self, loop_manager):
        status = loop_manager.get_learning_status()
        assert "recent_mutations" in status
        assert isinstance(status["recent_mutations"], list)

    def test_returns_evolution_generation(self, loop_manager):
        status = loop_manager.get_learning_status()
        assert "evolution_generation" in status

    def test_returns_analysis_when_trades_exist(self, loop_manager):
        loop_manager._total_trades = 10
        status = loop_manager.get_learning_status()
        assert "analysis" in status


class TestAccessors:
    """Test get_shadow_manager and get_retirement_tracker accessors."""

    def test_get_shadow_manager(self, loop_manager):
        from fxsoqqabot.learning.shadow import ShadowManager

        assert isinstance(loop_manager.get_shadow_manager(), ShadowManager)

    def test_get_retirement_tracker(self, loop_manager):
        from fxsoqqabot.learning.retirement import RuleRetirementTracker

        assert isinstance(loop_manager.get_retirement_tracker(), RuleRetirementTracker)
