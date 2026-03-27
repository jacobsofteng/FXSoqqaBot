"""Signal combination analyzer per D-20/LEARN-05.

Analyzes which signal module combinations produce the best results,
tracks per-regime performance, and identifies degrading rules whose
recent win rate has declined significantly from their overall average.

Feeds into the GA evolution loop and rule retirement system.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

import structlog

_logger = structlog.get_logger().bind(component="signal_analyzer")

# Confidence threshold for a module to be considered "active" in a trade
_ACTIVE_CONFIDENCE_THRESHOLD = 0.4

# Module names we track for combinations
_MODULE_NAMES = ("chaos", "flow", "timing")


class SignalAnalyzer:
    """Analyzes signal combinations and regime performance per D-20/LEARN-05.

    Examines trade history to determine which module combinations produce
    the best win rates, how performance varies by regime, and whether
    any rules are degrading over time.
    """

    def __init__(self) -> None:
        self._logger = structlog.get_logger().bind(component="signal_analyzer")

    def _get_active_modules(self, trade: dict) -> set[str]:
        """Determine which modules had confidence >= threshold for a trade.

        Args:
            trade: Trade dict with {module}_confidence fields.

        Returns:
            Set of active module names.
        """
        active = set()
        for module in _MODULE_NAMES:
            conf_key = f"{module}_confidence"
            if trade.get(conf_key, 0.0) >= _ACTIVE_CONFIDENCE_THRESHOLD:
                active.add(module)
        return active

    def analyze_combinations(self, trades: list[dict]) -> list[dict]:
        """Analyze win rates for each observed signal module combination.

        Computes all 2-module and 3-module combinations seen in the trade
        history. For each combination, calculates win rate, trade count,
        average P&L, and strength classification.

        Args:
            trades: List of trade dicts with pnl and {module}_confidence fields.

        Returns:
            List of combination dicts sorted by win_rate descending.
            Each dict: {combination, win_rate, trade_count, avg_pnl, strength}.
        """
        combo_trades: dict[tuple[str, ...], list[dict]] = defaultdict(list)

        for trade in trades:
            active = self._get_active_modules(trade)

            # Generate 2-module and 3-module combinations
            for size in (2, 3):
                for combo in combinations(sorted(active), size):
                    combo_trades[combo].append(trade)

        results: list[dict] = []
        for combo, combo_trade_list in combo_trades.items():
            wins = sum(1 for t in combo_trade_list if t["pnl"] > 0)
            trade_count = len(combo_trade_list)
            win_rate = wins / trade_count if trade_count > 0 else 0.0
            avg_pnl = (
                sum(t["pnl"] for t in combo_trade_list) / trade_count
                if trade_count > 0
                else 0.0
            )

            if win_rate > 0.7:
                strength = "strong"
            elif win_rate > 0.5:
                strength = "moderate"
            else:
                strength = "weak"

            results.append({
                "combination": combo,
                "win_rate": win_rate,
                "trade_count": trade_count,
                "avg_pnl": avg_pnl,
                "strength": strength,
            })

        # Sort by win_rate descending
        results.sort(key=lambda x: x["win_rate"], reverse=True)

        self._logger.debug(
            "combinations_analyzed",
            num_combinations=len(results),
            top_combo=(
                results[0]["combination"] if results else None
            ),
        )

        return results

    def analyze_regime_performance(
        self, trades: list[dict]
    ) -> dict[str, dict[str, Any]]:
        """Analyze performance grouped by market regime.

        For each regime, computes win rate, trade count, average P&L,
        and profit factor.

        Args:
            trades: List of trade dicts with pnl and regime fields.

        Returns:
            Dict keyed by regime name with performance stats.
        """
        regime_trades: dict[str, list[dict]] = defaultdict(list)
        for trade in trades:
            regime = trade.get("regime", "unknown")
            regime_trades[regime].append(trade)

        result: dict[str, dict[str, Any]] = {}
        for regime, regime_trade_list in regime_trades.items():
            trade_count = len(regime_trade_list)
            wins = sum(1 for t in regime_trade_list if t["pnl"] > 0)
            win_rate = wins / trade_count if trade_count > 0 else 0.0
            avg_pnl = (
                sum(t["pnl"] for t in regime_trade_list) / trade_count
                if trade_count > 0
                else 0.0
            )

            # Profit factor
            total_wins = sum(
                t["pnl"] for t in regime_trade_list if t["pnl"] > 0
            )
            total_losses = sum(
                t["pnl"] for t in regime_trade_list if t["pnl"] < 0
            )
            if total_losses == 0:
                profit_factor = 10.0 if total_wins > 0 else 0.0
            else:
                profit_factor = total_wins / abs(total_losses)

            result[regime] = {
                "win_rate": win_rate,
                "trade_count": trade_count,
                "avg_pnl": avg_pnl,
                "profit_factor": profit_factor,
            }

        self._logger.debug(
            "regime_performance_analyzed",
            regimes=list(result.keys()),
        )

        return result

    def identify_degrading_rules(
        self, trades: list[dict], window_size: int = 50
    ) -> list[dict]:
        """Identify rules whose recent performance has degraded.

        Compares win rate of last `window_size` trades vs all trades.
        Rules where recent win_rate is more than 15 percentage points
        below overall are flagged as "degrading".

        Args:
            trades: List of trade dicts with pnl field.
            window_size: Number of recent trades to compare against.

        Returns:
            List of dicts with rule, overall_win_rate, recent_win_rate, delta.
        """
        if len(trades) < window_size:
            return []

        all_wins = sum(1 for t in trades if t["pnl"] > 0)
        overall_win_rate = all_wins / len(trades)

        recent_trades = trades[-window_size:]
        recent_wins = sum(1 for t in recent_trades if t["pnl"] > 0)
        recent_win_rate = recent_wins / len(recent_trades)

        delta = overall_win_rate - recent_win_rate

        result: list[dict] = []
        if delta > 0.15:
            result.append({
                "rule": "overall_strategy",
                "overall_win_rate": overall_win_rate,
                "recent_win_rate": recent_win_rate,
                "delta": delta,
            })

        # Per-module degradation check
        for module in _MODULE_NAMES:
            conf_key = f"{module}_confidence"
            active_all = [
                t for t in trades
                if t.get(conf_key, 0.0) >= _ACTIVE_CONFIDENCE_THRESHOLD
            ]
            active_recent = [
                t for t in recent_trades
                if t.get(conf_key, 0.0) >= _ACTIVE_CONFIDENCE_THRESHOLD
            ]

            if len(active_all) < 5 or len(active_recent) < 3:
                continue

            mod_overall_wr = (
                sum(1 for t in active_all if t["pnl"] > 0) / len(active_all)
            )
            mod_recent_wr = (
                sum(1 for t in active_recent if t["pnl"] > 0)
                / len(active_recent)
            )
            mod_delta = mod_overall_wr - mod_recent_wr

            if mod_delta > 0.15:
                result.append({
                    "rule": module,
                    "overall_win_rate": mod_overall_wr,
                    "recent_win_rate": mod_recent_wr,
                    "delta": mod_delta,
                })

        self._logger.debug(
            "degrading_rules_checked",
            num_degrading=len(result),
        )

        return result

    def get_summary(self, trades: list[dict]) -> dict[str, Any]:
        """Return complete analysis summary.

        Combines combination analysis, regime performance, and
        degrading rule detection into a single report.

        Args:
            trades: List of trade dicts.

        Returns:
            Dict with best_combinations, worst_combinations,
            regime_performance, and degrading_rules.
        """
        combos = self.analyze_combinations(trades)
        regime_perf = self.analyze_regime_performance(trades)
        degrading = self.identify_degrading_rules(trades)

        # Best = top 5, worst = bottom 5
        best_combos = combos[:5]
        worst_combos = combos[-5:] if len(combos) > 5 else combos

        return {
            "best_combinations": best_combos,
            "worst_combinations": worst_combos,
            "regime_performance": regime_perf,
            "degrading_rules": degrading,
        }
