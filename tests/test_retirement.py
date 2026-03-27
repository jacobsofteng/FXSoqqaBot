"""Tests for RuleRetirementTracker -- EMA-based rule retirement per D-19.

Tests cover:
- EMA score updates
- Retirement trigger when EMA below threshold after min_trades
- Retired rules move to cooldown pool
- Rule reactivation from cooldown
- Min trades guard prevents premature retirement
"""

from __future__ import annotations

import pytest

from fxsoqqabot.learning.retirement import RuleRetirementTracker


@pytest.fixture
def tracker() -> RuleRetirementTracker:
    return RuleRetirementTracker(
        rule_names=["rule_a", "rule_b", "rule_c"],
        alpha=0.1,
        min_trades=10,
        retirement_threshold=0.3,
    )


class TestRecordOutcome:
    """Test 5: record_outcome updates EMA score."""

    def test_ema_increases_on_success(self, tracker: RuleRetirementTracker) -> None:
        old_status = tracker.get_rule_status()["rule_a"]
        old_ema = old_status["ema"]
        tracker.record_outcome("rule_a", success=True)
        new_ema = tracker.get_rule_status()["rule_a"]["ema"]
        assert new_ema > old_ema

    def test_ema_decreases_on_failure(self, tracker: RuleRetirementTracker) -> None:
        old_ema = tracker.get_rule_status()["rule_a"]["ema"]
        tracker.record_outcome("rule_a", success=False)
        new_ema = tracker.get_rule_status()["rule_a"]["ema"]
        assert new_ema < old_ema

    def test_ema_formula_correct(self, tracker: RuleRetirementTracker) -> None:
        """EMA = alpha * observation + (1 - alpha) * old_ema."""
        initial_ema = 0.5  # default
        tracker.record_outcome("rule_a", success=True)
        expected = 0.1 * 1.0 + 0.9 * initial_ema
        actual = tracker.get_rule_status()["rule_a"]["ema"]
        assert abs(actual - expected) < 1e-10

    def test_trade_count_increments(self, tracker: RuleRetirementTracker) -> None:
        tracker.record_outcome("rule_a", success=True)
        tracker.record_outcome("rule_a", success=False)
        assert tracker.get_rule_status()["rule_a"]["trade_count"] == 2


class TestRetirementTrigger:
    """Test 6: Rule with EMA below threshold after min_trades is retired."""

    def test_retires_after_enough_failures(
        self, tracker: RuleRetirementTracker
    ) -> None:
        # Drive EMA below threshold with all failures after min_trades
        for _ in range(15):
            tracker.record_outcome("rule_a", success=False)
        status = tracker.get_rule_status()["rule_a"]
        assert status["status"] in ("retired", "cooldown")

    def test_retired_not_in_active_rules(
        self, tracker: RuleRetirementTracker
    ) -> None:
        for _ in range(15):
            tracker.record_outcome("rule_a", success=False)
        assert "rule_a" not in tracker.get_active_rules()


class TestCooldownPool:
    """Test 7: Retired rule moves to cooldown_pool, not deleted."""

    def test_retired_rule_in_cooldown(
        self, tracker: RuleRetirementTracker
    ) -> None:
        for _ in range(15):
            tracker.record_outcome("rule_a", success=False)
        retired = tracker.get_retired_rules()
        rule_names = [r["rule_name"] for r in retired]
        assert "rule_a" in rule_names

    def test_cooldown_has_metadata(
        self, tracker: RuleRetirementTracker
    ) -> None:
        for _ in range(15):
            tracker.record_outcome("rule_a", success=False)
        retired = tracker.get_retired_rules()
        entry = [r for r in retired if r["rule_name"] == "rule_a"][0]
        assert "retired_at" in entry
        assert "ema_at_retirement" in entry


class TestReactivation:
    """Test 8: Rule can be re-activated from cooldown pool."""

    def test_reactivate_restores_to_active(
        self, tracker: RuleRetirementTracker
    ) -> None:
        for _ in range(15):
            tracker.record_outcome("rule_a", success=False)
        assert "rule_a" not in tracker.get_active_rules()

        tracker.reactivate_rule("rule_a")
        assert "rule_a" in tracker.get_active_rules()

    def test_reactivate_resets_ema(
        self, tracker: RuleRetirementTracker
    ) -> None:
        for _ in range(15):
            tracker.record_outcome("rule_a", success=False)
        tracker.reactivate_rule("rule_a")
        status = tracker.get_rule_status()["rule_a"]
        assert status["ema"] == 0.5  # Reset to default
        assert status["trade_count"] == 0

    def test_reactivate_removes_from_cooldown(
        self, tracker: RuleRetirementTracker
    ) -> None:
        for _ in range(15):
            tracker.record_outcome("rule_a", success=False)
        tracker.reactivate_rule("rule_a")
        retired = tracker.get_retired_rules()
        rule_names = [r["rule_name"] for r in retired]
        assert "rule_a" not in rule_names


class TestMinTradesGuard:
    """Test 9: Rule with fewer than min_trades is never retired."""

    def test_no_retirement_before_min_trades(
        self, tracker: RuleRetirementTracker
    ) -> None:
        """Even with all failures, fewer than min_trades = no retirement."""
        for _ in range(9):  # min_trades is 10
            tracker.record_outcome("rule_a", success=False)
        assert "rule_a" in tracker.get_active_rules()
        status = tracker.get_rule_status()["rule_a"]
        assert status["status"] == "active"


class TestStateSerialization:
    """State persistence for RuleRetirementTracker."""

    def test_get_state_returns_dict(
        self, tracker: RuleRetirementTracker
    ) -> None:
        state = tracker.get_state()
        assert isinstance(state, dict)
        assert "ema_scores" in state
        assert "trade_counts" in state
        assert "active_rules" in state
        assert "cooldown_pool" in state

    def test_load_state_restores(self) -> None:
        t1 = RuleRetirementTracker(
            rule_names=["r1", "r2"], alpha=0.1, min_trades=5
        )
        for _ in range(3):
            t1.record_outcome("r1", success=True)
        state = t1.get_state()

        t2 = RuleRetirementTracker(
            rule_names=["r1", "r2"], alpha=0.1, min_trades=5
        )
        t2.load_state(state)
        assert t2.get_rule_status()["r1"]["trade_count"] == 3
        assert t2.get_rule_status()["r1"]["ema"] == t1.get_rule_status()["r1"]["ema"]


class TestGetActiveRules:
    """Test active rules listing."""

    def test_all_rules_active_initially(
        self, tracker: RuleRetirementTracker
    ) -> None:
        active = tracker.get_active_rules()
        assert set(active) == {"rule_a", "rule_b", "rule_c"}
