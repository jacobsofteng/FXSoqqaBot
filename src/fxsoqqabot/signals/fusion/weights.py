"""Adaptive EMA weight tracker per D-02.

Tracks module accuracy using exponential moving average and produces
normalized weights. During warmup, all weights are equal. After warmup,
weights diverge based on which modules have been more accurate.

Per D-05: weights adapt from accuracy only, NOT from regime state.
"""

from __future__ import annotations

from typing import Any

import structlog


class AdaptiveWeightTracker:
    """Track module accuracy via EMA and produce normalized weights.

    EMA formula per D-02:
        accuracy = alpha * correct + (1 - alpha) * old_accuracy

    Where correct = 1.0 if module predicted same direction as outcome,
    0.0 otherwise.

    During warmup (trade_count < warmup_trades), returns equal weights.
    After warmup, normalizes accuracies to sum to 1.0.

    Supports state serialization for SQLite persistence (Pitfall 6).
    """

    def __init__(
        self,
        module_names: list[str],
        alpha: float = 0.1,
        warmup_trades: int = 10,
    ) -> None:
        self._alpha = alpha
        self._warmup = warmup_trades
        self._accuracies: dict[str, float] = {name: 0.5 for name in module_names}
        self._trade_count: int = 0
        self._logger = structlog.get_logger().bind(component="weight_tracker")

    def record_outcome(
        self,
        module_signals: dict[str, float],
        actual_direction: float,
    ) -> None:
        """Record trade outcome and update module accuracies via EMA.

        Args:
            module_signals: Module name -> predicted direction mapping.
                Positive = buy prediction, negative = sell prediction.
            actual_direction: +1.0 if profitable, -1.0 if loss.
        """
        for module_name, predicted in module_signals.items():
            if module_name not in self._accuracies:
                continue

            # Correct if predicted and actual have same sign
            correct = 1.0 if (predicted * actual_direction > 0) else 0.0

            old_accuracy = self._accuracies[module_name]
            # EMA update per D-02: accuracy = alpha * correct + (1 - alpha) * old_accuracy
            new_accuracy = self._alpha * correct + (1 - self._alpha) * old_accuracy
            self._accuracies[module_name] = new_accuracy

            self._logger.debug(
                "weight_updated",
                module=module_name,
                predicted=predicted,
                actual=actual_direction,
                correct=correct,
                old_accuracy=old_accuracy,
                new_accuracy=new_accuracy,
            )

        self._trade_count += 1

    def get_weights(self) -> dict[str, float]:
        """Return normalized weights based on module accuracies.

        During warmup (trade_count < warmup_trades), returns equal weights.
        If all accuracies are zero, returns equal weights.

        Returns:
            Dict of module name -> normalized weight (sums to 1.0).
        """
        n = len(self._accuracies)
        if n == 0:
            return {}

        # During warmup, return equal weights
        if self._trade_count < self._warmup:
            equal = 1.0 / n
            return {name: equal for name in self._accuracies}

        # Normalize accuracies to sum to 1.0
        total = sum(self._accuracies.values())
        if total == 0:
            equal = 1.0 / n
            return {name: equal for name in self._accuracies}

        return {name: acc / total for name, acc in self._accuracies.items()}

    def get_state(self) -> dict[str, Any]:
        """Return serializable state for SQLite persistence (Pitfall 6).

        Returns:
            Dict with accuracies, trade_count, alpha, and warmup.
        """
        return {
            "accuracies": dict(self._accuracies),
            "trade_count": self._trade_count,
            "alpha": self._alpha,
            "warmup": self._warmup,
        }

    def load_state(self, state: dict[str, Any]) -> None:
        """Restore state from serialized dict.

        Args:
            state: Dict from get_state().
        """
        self._accuracies = dict(state["accuracies"])
        self._trade_count = state["trade_count"]
        self._alpha = state["alpha"]
        self._warmup = state["warmup"]
