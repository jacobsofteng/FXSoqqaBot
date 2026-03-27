"""Tests for shadow mode variant management per D-17/D-18/LEARN-04.

Verifies:
- ShadowManager creates independent variants with own PaperExecutors
- Variant mutation within bounds
- Mann-Whitney U statistical promotion
- Variant lifecycle (create, trade, evaluate, promote/reset)
"""

from __future__ import annotations

import random

from fxsoqqabot.config.models import LearningConfig
from fxsoqqabot.learning.evolution import PARAM_BOUNDS, PARAM_NAMES
from fxsoqqabot.learning.shadow import ShadowManager, ShadowVariant


def _make_manager(n: int = 3, alpha: float = 0.05, min_trades: int = 50) -> ShadowManager:
    """Create a ShadowManager with small population for testing."""
    config = LearningConfig(
        n_shadow_variants=n,
        promotion_alpha=alpha,
        min_promotion_trades=min_trades,
    )
    return ShadowManager(config)


# ── Test 1: ShadowManager creates n_shadow_variants ShadowVariant instances ──


def test_creates_correct_number_of_variants() -> None:
    mgr = _make_manager(n=3)
    assert len(mgr.get_variants()) == 3

    mgr5 = _make_manager(n=5)
    assert len(mgr5.get_variants()) == 5


# ── Test 2: Each variant has its own PaperExecutor (no shared state) ──


def test_each_variant_has_unique_paper_executor() -> None:
    mgr = _make_manager(n=3)
    variants = mgr.get_variants()

    executor_ids = [id(v.paper_executor) for v in variants]
    # All executor IDs must be unique
    assert len(set(executor_ids)) == 3, "Each variant must have its own PaperExecutor"


# ── Test 3: ShadowVariant mutated_params is dict of param_name -> float ──


def test_variant_mutated_params_is_dict() -> None:
    mgr = _make_manager(n=3)
    variant = mgr.get_variants()[0]

    assert isinstance(variant.mutated_params, dict)
    for key, val in variant.mutated_params.items():
        assert isinstance(key, str)
        assert isinstance(val, float)


# ── Test 4: evaluate_promotion returns False with too few trades ──


def test_evaluate_promotion_insufficient_trades() -> None:
    mgr = _make_manager(n=3, min_trades=50)
    variant = mgr.get_variants()[0]

    # Add only 10 trades (less than min_promotion_trades=50)
    for _ in range(10):
        variant.trade_results.append({"pnl": 1.0})

    live_trades = [{"pnl": 0.5} for _ in range(60)]
    result = mgr.evaluate_promotion(variant, live_trades, equity=20.0)

    assert result["should_promote"] is False
    assert "insufficient" in result["reason"].lower()


# ── Test 5: evaluate_promotion returns False when p >= alpha ──


def test_evaluate_promotion_not_significant() -> None:
    mgr = _make_manager(n=3, min_trades=10)
    variant = mgr.get_variants()[0]

    # Both distributions have similar P&L -- no statistical difference
    random.seed(42)
    for _ in range(50):
        variant.trade_results.append({"pnl": random.gauss(1.0, 2.0)})

    live_trades = [{"pnl": random.gauss(1.0, 2.0)} for _ in range(50)]
    result = mgr.evaluate_promotion(variant, live_trades, equity=20.0)

    assert result["should_promote"] is False
    assert result["p_value"] >= mgr._config.promotion_alpha


# ── Test 6: evaluate_promotion returns True when significant and better ──


def test_evaluate_promotion_significant_improvement() -> None:
    mgr = _make_manager(n=3, min_trades=10)
    variant = mgr.get_variants()[0]

    # Variant: clearly better P&L distribution
    for _ in range(60):
        variant.trade_results.append({"pnl": 5.0 + random.gauss(0, 0.5)})

    # Live: clearly worse P&L distribution
    live_trades = [{"pnl": 1.0 + random.gauss(0, 0.5)} for _ in range(60)]
    result = mgr.evaluate_promotion(variant, live_trades, equity=20.0)

    assert result["should_promote"] is True
    assert result["p_value"] < mgr._config.promotion_alpha
    assert result["variant_fitness"] > 0


# ── Test 7: Mann-Whitney U test is used (not t-test) ──


def test_uses_mann_whitney_u(monkeypatch: object) -> None:
    """Verify that mannwhitneyu is imported and called, not ttest_ind."""
    from unittest.mock import MagicMock, patch

    from scipy import stats

    mgr = _make_manager(n=3, min_trades=5)
    variant = mgr.get_variants()[0]

    for _ in range(20):
        variant.trade_results.append({"pnl": 3.0})

    live_trades = [{"pnl": 1.0} for _ in range(20)]

    with patch.object(stats, "mannwhitneyu", wraps=stats.mannwhitneyu) as mock_mwu:
        mgr.evaluate_promotion(variant, live_trades, equity=20.0)
        mock_mwu.assert_called_once()


# ── Test 8: promote_variant replaces live params and resets variant ──


def test_promote_variant_returns_params_and_resets() -> None:
    mgr = _make_manager(n=3)
    variant = mgr.get_variants()[0]
    original_params = dict(variant.mutated_params)
    variant_id = variant.variant_id

    # Add some trades so variant has state
    for _ in range(10):
        variant.trade_results.append({"pnl": 2.0})

    promoted_params = mgr.promote_variant(variant_id)

    # Promoted params should match the original variant params
    assert promoted_params == original_params

    # After promotion, variant should be reset
    refreshed = [v for v in mgr.get_variants() if v.variant_id == variant_id][0]
    assert refreshed.trade_count == 0
    assert refreshed.mutated_params != original_params  # New mutations


# ── Test 9: _generate_mutations produces params within PARAM_BOUNDS ──


def test_generate_mutations_within_bounds() -> None:
    mgr = _make_manager(n=3)

    # Test many times for randomness coverage
    for _ in range(20):
        mutations = mgr._generate_mutations()

        assert set(mutations.keys()) == set(PARAM_NAMES)
        for param_name, val in mutations.items():
            lo, hi = PARAM_BOUNDS[param_name]
            assert lo <= val <= hi, (
                f"{param_name}={val} outside bounds [{lo}, {hi}]"
            )


# ── Test 10: get_variant_status returns trade counts and fitness ──


def test_get_variant_status() -> None:
    mgr = _make_manager(n=3)
    variants = mgr.get_variants()

    # Add trades to first variant
    for _ in range(5):
        variants[0].trade_results.append({"pnl": 1.0})
    for _ in range(3):
        variants[0].trade_results.append({"pnl": -0.5})

    status = mgr.get_variant_status()

    assert len(status) == 3
    assert status[0]["variant_id"] == "shadow_0"
    assert status[0]["trade_count"] == 8
    assert status[0]["fitness_score"] > 0
    assert "mutated_params" in status[0]
    assert "age" in status[0]

    # Other variants should have 0 trades
    assert status[1]["trade_count"] == 0
    assert status[2]["trade_count"] == 0
