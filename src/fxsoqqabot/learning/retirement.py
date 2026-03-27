"""EMA-based rule retirement tracker per D-19.

Mirrors the AdaptiveWeightTracker EMA pattern from signals/fusion/weights.py.
Tracks rule performance via exponential moving average and retires rules
whose EMA score drops below a threshold after sufficient trades. Retired
rules enter a cooldown pool and can be re-activated with mutated parameters.

Rules are never permanently deleted -- they can always be brought back.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

_logger = structlog.get_logger().bind(component="rule_retirement")


class RuleRetirementTracker:
    """EMA-based rule retirement tracker per D-19.

    Tracks each rule's performance via EMA. When a rule's EMA score
    drops below the retirement threshold after at least min_trades,
    it is retired to the cooldown pool. Rules can be re-activated
    (optionally with mutated parameters) from the cooldown pool.

    Mirrors the EMA pattern from AdaptiveWeightTracker:
        new_ema = alpha * observation + (1 - alpha) * old_ema

    Args:
        rule_names: List of rule identifiers to track.
        alpha: EMA decay factor (0 < alpha <= 1). Default 0.1.
        min_trades: Minimum trades before retirement is possible. Default 50.
        retirement_threshold: EMA below this triggers retirement. Default 0.3.
    """

    def __init__(
        self,
        rule_names: list[str],
        alpha: float = 0.1,
        min_trades: int = 50,
        retirement_threshold: float = 0.3,
    ) -> None:
        self._alpha = alpha
        self._min_trades = min_trades
        self._retirement_threshold = retirement_threshold

        # EMA scores initialized to 0.5 (neutral)
        self._ema_scores: dict[str, float] = {name: 0.5 for name in rule_names}
        self._trade_counts: dict[str, int] = {name: 0 for name in rule_names}
        self._active_rules: set[str] = set(rule_names)
        self._cooldown_pool: dict[str, dict[str, Any]] = {}

    def record_outcome(self, rule_name: str, success: bool) -> None:
        """Record a trade outcome for a rule and update its EMA score.

        EMA formula: new_ema = alpha * observation + (1 - alpha) * old_ema
        where observation = 1.0 for success, 0.0 for failure.

        After updating, checks if the rule should be retired (EMA below
        threshold and trade count >= min_trades).

        Args:
            rule_name: Identifier of the rule.
            success: True if the trade was profitable, False otherwise.
        """
        if rule_name not in self._ema_scores:
            return
        if rule_name not in self._active_rules:
            return

        observation = 1.0 if success else 0.0
        old_ema = self._ema_scores[rule_name]
        new_ema = self._alpha * observation + (1.0 - self._alpha) * old_ema
        self._ema_scores[rule_name] = new_ema
        self._trade_counts[rule_name] = self._trade_counts.get(rule_name, 0) + 1

        # Check retirement condition
        if (
            self._trade_counts[rule_name] >= self._min_trades
            and new_ema < self._retirement_threshold
            and rule_name in self._active_rules
        ):
            self._retire_rule(rule_name)

    def _retire_rule(self, rule_name: str) -> None:
        """Move a rule from active to cooldown pool.

        Args:
            rule_name: Identifier of the rule to retire.
        """
        self._active_rules.discard(rule_name)
        self._cooldown_pool[rule_name] = {
            "rule_name": rule_name,
            "retired_at": datetime.now(timezone.utc).isoformat(),
            "ema_at_retirement": self._ema_scores[rule_name],
        }

        _logger.info(
            "rule_retired",
            rule=rule_name,
            ema=self._ema_scores[rule_name],
            trade_count=self._trade_counts[rule_name],
        )

    def reactivate_rule(
        self, rule_name: str, mutated_params: dict | None = None
    ) -> None:
        """Re-activate a rule from the cooldown pool.

        Resets the rule's EMA to 0.5 and trade count to 0.
        Optionally accepts mutated parameters for the rule.

        Args:
            rule_name: Identifier of the rule to reactivate.
            mutated_params: Optional new parameters for the rule.
        """
        if rule_name in self._cooldown_pool:
            del self._cooldown_pool[rule_name]

        self._active_rules.add(rule_name)
        self._ema_scores[rule_name] = 0.5
        self._trade_counts[rule_name] = 0

        _logger.info(
            "rule_reactivated",
            rule=rule_name,
            mutated=mutated_params is not None,
        )

    def get_rule_status(self) -> dict[str, dict[str, Any]]:
        """Return status for all rules.

        Returns:
            Dict mapping rule name to status dict with ema, trade_count,
            and status ("active", "retired", or "cooldown").
        """
        result: dict[str, dict[str, Any]] = {}
        all_rules = set(self._ema_scores.keys())

        for rule_name in all_rules:
            if rule_name in self._active_rules:
                status = "active"
            elif rule_name in self._cooldown_pool:
                status = "cooldown"
            else:
                status = "retired"

            result[rule_name] = {
                "ema": self._ema_scores[rule_name],
                "trade_count": self._trade_counts.get(rule_name, 0),
                "status": status,
            }

        return result

    def get_active_rules(self) -> list[str]:
        """Return list of currently active rule names.

        Returns:
            Sorted list of active rule identifiers.
        """
        return sorted(self._active_rules)

    def get_retired_rules(self) -> list[dict[str, Any]]:
        """Return cooldown pool entries.

        Returns:
            List of dicts with rule_name, retired_at, ema_at_retirement.
        """
        return list(self._cooldown_pool.values())

    def get_state(self) -> dict[str, Any]:
        """Serialize tracker state for persistence.

        Returns:
            Dict with ema_scores, trade_counts, active_rules, cooldown_pool.
        """
        return {
            "ema_scores": dict(self._ema_scores),
            "trade_counts": dict(self._trade_counts),
            "active_rules": sorted(self._active_rules),
            "cooldown_pool": dict(self._cooldown_pool),
            "alpha": self._alpha,
            "min_trades": self._min_trades,
            "retirement_threshold": self._retirement_threshold,
        }

    def load_state(self, state: dict[str, Any]) -> None:
        """Restore from serialized state.

        Args:
            state: Dict from get_state().
        """
        self._ema_scores = dict(state["ema_scores"])
        self._trade_counts = dict(state["trade_counts"])
        self._active_rules = set(state["active_rules"])
        self._cooldown_pool = dict(state["cooldown_pool"])
        if "alpha" in state:
            self._alpha = state["alpha"]
        if "min_trades" in state:
            self._min_trades = state["min_trades"]
        if "retirement_threshold" in state:
            self._retirement_threshold = state["retirement_threshold"]

        _logger.info(
            "retirement_state_restored",
            active_count=len(self._active_rules),
            cooldown_count=len(self._cooldown_pool),
        )
