"""Tests for walk-forward validation gate in variant promotion (LEARN-06).

Verifies dual-gate promotion:
1. Statistical significance (Mann-Whitney U, p < alpha)
2. Walk-forward validation (passes_threshold=True)

A variant must pass BOTH gates to be promoted. If walk-forward fails but
stats pass, the variant is rejected and reset. When no validator is
configured, statistical-only mode is used with a warning log.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fxsoqqabot.config.models import LearningConfig


@pytest.fixture
def learning_config() -> LearningConfig:
    """Create a LearningConfig for testing."""
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


# -- Test 1: Promotion blocked when walk-forward fails --


def test_promotion_blocked_when_wf_fails(loop_manager, mock_trade_logger):
    """Variant passes stats but fails walk-forward -> NOT promoted, reset."""
    # Mock evaluate_promotion to return should_promote=True (stats pass)
    with patch.object(
        loop_manager._shadow,
        "evaluate_promotion",
        return_value={
            "should_promote": True,
            "p_value": 0.01,
            "variant_fitness": 0.8,
            "live_fitness": 0.5,
            "walk_forward_pass": None,
        },
    ):
        with patch.object(
            loop_manager._shadow, "promote_variant"
        ) as mock_promote:
            with patch.object(
                loop_manager._shadow, "reset_variant"
            ) as mock_reset:
                # Set walk-forward validator that always returns False
                loop_manager.set_walk_forward_validator(lambda params: False)

                mutations = loop_manager._check_promotions()

                # No promotions should occur
                assert len(mutations) == 0
                mock_promote.assert_not_called()
                # Variants should be reset since they passed stats but failed WF
                assert mock_reset.call_count > 0


# -- Test 2: Promotion allowed when both gates pass --


def test_promotion_allowed_when_both_gates_pass(loop_manager, mock_trade_logger):
    """Variant passes both stats and walk-forward -> promoted."""
    with patch.object(
        loop_manager._shadow,
        "evaluate_promotion",
        return_value={
            "should_promote": True,
            "p_value": 0.01,
            "variant_fitness": 0.8,
            "live_fitness": 0.5,
            "walk_forward_pass": None,
        },
    ):
        with patch.object(
            loop_manager._shadow,
            "promote_variant",
            return_value={"param1": 0.5},
        ) as mock_promote:
            # Set walk-forward validator that always returns True
            loop_manager.set_walk_forward_validator(lambda params: True)

            mutations = loop_manager._check_promotions()

            # Promotions should occur
            assert len(mutations) > 0
            assert mock_promote.call_count > 0
            # Check mutation event includes walk-forward pass info
            assert "walk-forward=pass" in mutations[0]["reason"]


# -- Test 3: Walk-forward skipped when stats fail --


def test_wf_skipped_when_stats_fail(loop_manager, mock_trade_logger):
    """When evaluate_promotion returns should_promote=False, WF is never called."""
    # Mock evaluate_promotion to return should_promote=False
    with patch.object(
        loop_manager._shadow,
        "evaluate_promotion",
        return_value={
            "should_promote": False,
            "p_value": 0.5,
            "variant_fitness": 0.4,
            "live_fitness": 0.5,
        },
    ):
        # Set validator that raises Exception -- proves it was never called
        def exploding_validator(params):
            raise RuntimeError("Should never be called!")

        loop_manager.set_walk_forward_validator(exploding_validator)

        # Should not raise -- validator never invoked
        mutations = loop_manager._check_promotions()
        assert len(mutations) == 0


# -- Test 4: Fallback to stats-only when no validator set --


def test_wf_fallback_when_no_validator(loop_manager, mock_trade_logger, caplog):
    """No validator set -> promotion proceeds on stats only with warning."""
    import structlog
    import logging

    with patch.object(
        loop_manager._shadow,
        "evaluate_promotion",
        return_value={
            "should_promote": True,
            "p_value": 0.01,
            "variant_fitness": 0.8,
            "live_fitness": 0.5,
            "walk_forward_pass": None,
        },
    ):
        with patch.object(
            loop_manager._shadow,
            "promote_variant",
            return_value={"param1": 0.5},
        ) as mock_promote:
            # Do NOT set walk_forward_validator (leave as None)
            # Ensure _walk_forward_validator is None
            assert loop_manager._walk_forward_validator is None

            mutations = loop_manager._check_promotions()

            # Promotion should proceed (statistical-only mode)
            assert len(mutations) > 0
            mock_promote.assert_called()


# -- Test 5: Walk-forward error fails safe (reject on error) --


def test_wf_error_fails_safe(loop_manager, mock_trade_logger):
    """Walk-forward validator raises error -> variant rejected and reset."""
    with patch.object(
        loop_manager._shadow,
        "evaluate_promotion",
        return_value={
            "should_promote": True,
            "p_value": 0.01,
            "variant_fitness": 0.8,
            "live_fitness": 0.5,
            "walk_forward_pass": None,
        },
    ):
        with patch.object(
            loop_manager._shadow, "promote_variant"
        ) as mock_promote:
            with patch.object(
                loop_manager._shadow, "reset_variant"
            ) as mock_reset:
                # Set validator that raises RuntimeError
                def failing_validator(params):
                    raise RuntimeError("Walk-forward engine crashed!")

                loop_manager.set_walk_forward_validator(failing_validator)

                mutations = loop_manager._check_promotions()

                # No promotions -- error means reject
                assert len(mutations) == 0
                mock_promote.assert_not_called()
                # Variant should be reset
                assert mock_reset.call_count > 0
