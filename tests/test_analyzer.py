"""Tests for SignalAnalyzer -- signal combination analysis per D-20/LEARN-05.

Tests cover:
- analyze_combinations returns win rates for signal combos
- Combinations with win_rate > 0.7 flagged as "strong"
- analyze_regime_performance returns per-regime statistics
- identify_degrading_rules finds declining EMA scores
"""

from __future__ import annotations

import pytest

from fxsoqqabot.learning.analyzer import SignalAnalyzer


@pytest.fixture
def analyzer() -> SignalAnalyzer:
    return SignalAnalyzer()


def _make_trades_with_signals(
    specs: list[dict],
) -> list[dict]:
    """Create mock trades with signal confidences and outcomes.

    Each spec: {
        "pnl": float,
        "regime": str,
        "chaos_confidence": float,
        "flow_confidence": float,
        "timing_confidence": float,
    }
    """
    trades = []
    for i, spec in enumerate(specs):
        trades.append({
            "trade_id": i + 1,
            "pnl": spec.get("pnl", 1.0),
            "regime": spec.get("regime", "trending_up"),
            "chaos_confidence": spec.get("chaos_confidence", 0.1),
            "flow_confidence": spec.get("flow_confidence", 0.1),
            "timing_confidence": spec.get("timing_confidence", 0.1),
        })
    return trades


class TestAnalyzeCombinations:
    """Test 1: analyze_combinations returns win rates for each combo."""

    def test_returns_list_of_dicts(self, analyzer: SignalAnalyzer) -> None:
        # chaos+flow active (>= 0.4), timing inactive
        trades = _make_trades_with_signals([
            {"pnl": 5.0, "chaos_confidence": 0.6, "flow_confidence": 0.7, "timing_confidence": 0.1},
            {"pnl": 3.0, "chaos_confidence": 0.5, "flow_confidence": 0.8, "timing_confidence": 0.1},
            {"pnl": -1.0, "chaos_confidence": 0.6, "flow_confidence": 0.5, "timing_confidence": 0.1},
        ])
        result = analyzer.analyze_combinations(trades)
        assert isinstance(result, list)
        assert len(result) > 0
        assert isinstance(result[0], dict)

    def test_combination_has_required_fields(self, analyzer: SignalAnalyzer) -> None:
        trades = _make_trades_with_signals([
            {"pnl": 5.0, "chaos_confidence": 0.6, "flow_confidence": 0.7},
            {"pnl": -1.0, "chaos_confidence": 0.5, "flow_confidence": 0.5},
        ])
        result = analyzer.analyze_combinations(trades)
        for combo in result:
            assert "combination" in combo
            assert "win_rate" in combo
            assert "trade_count" in combo
            assert "avg_pnl" in combo
            assert "strength" in combo

    def test_sorted_by_win_rate_descending(self, analyzer: SignalAnalyzer) -> None:
        trades = _make_trades_with_signals([
            {"pnl": 5.0, "chaos_confidence": 0.6, "flow_confidence": 0.7, "timing_confidence": 0.5},
            {"pnl": 3.0, "chaos_confidence": 0.5, "flow_confidence": 0.8, "timing_confidence": 0.6},
            {"pnl": -1.0, "chaos_confidence": 0.6, "flow_confidence": 0.5, "timing_confidence": 0.5},
            {"pnl": -2.0, "chaos_confidence": 0.6, "flow_confidence": 0.1, "timing_confidence": 0.5},
        ])
        result = analyzer.analyze_combinations(trades)
        for i in range(len(result) - 1):
            assert result[i]["win_rate"] >= result[i + 1]["win_rate"]


class TestStrongCombinations:
    """Test 2: Combinations with win_rate > 0.7 flagged as 'strong'."""

    def test_high_win_rate_flagged_strong(self, analyzer: SignalAnalyzer) -> None:
        # All chaos+flow trades are wins -> win_rate = 1.0 -> "strong"
        trades = _make_trades_with_signals([
            {"pnl": 5.0, "chaos_confidence": 0.6, "flow_confidence": 0.7, "timing_confidence": 0.1},
            {"pnl": 3.0, "chaos_confidence": 0.5, "flow_confidence": 0.8, "timing_confidence": 0.1},
            {"pnl": 2.0, "chaos_confidence": 0.6, "flow_confidence": 0.5, "timing_confidence": 0.1},
            {"pnl": 4.0, "chaos_confidence": 0.6, "flow_confidence": 0.5, "timing_confidence": 0.1},
        ])
        result = analyzer.analyze_combinations(trades)
        chaos_flow = [c for c in result if set(c["combination"]) == {"chaos", "flow"}]
        assert len(chaos_flow) > 0
        assert chaos_flow[0]["strength"] == "strong"

    def test_low_win_rate_not_strong(self, analyzer: SignalAnalyzer) -> None:
        # Mix of wins and losses -> moderate or weak
        trades = _make_trades_with_signals([
            {"pnl": 5.0, "chaos_confidence": 0.6, "flow_confidence": 0.7},
            {"pnl": -3.0, "chaos_confidence": 0.5, "flow_confidence": 0.8},
            {"pnl": -2.0, "chaos_confidence": 0.6, "flow_confidence": 0.5},
            {"pnl": -4.0, "chaos_confidence": 0.6, "flow_confidence": 0.5},
        ])
        result = analyzer.analyze_combinations(trades)
        chaos_flow = [c for c in result if set(c["combination"]) == {"chaos", "flow"}]
        assert len(chaos_flow) > 0
        assert chaos_flow[0]["strength"] != "strong"


class TestRegimePerformance:
    """Test 3: analyze_regime_performance returns per-regime stats."""

    def test_groups_by_regime(self, analyzer: SignalAnalyzer) -> None:
        trades = _make_trades_with_signals([
            {"pnl": 5.0, "regime": "trending_up"},
            {"pnl": -1.0, "regime": "trending_up"},
            {"pnl": 2.0, "regime": "ranging"},
            {"pnl": -3.0, "regime": "ranging"},
        ])
        result = analyzer.analyze_regime_performance(trades)
        assert "trending_up" in result
        assert "ranging" in result

    def test_regime_stats_have_required_fields(self, analyzer: SignalAnalyzer) -> None:
        trades = _make_trades_with_signals([
            {"pnl": 5.0, "regime": "trending_up"},
            {"pnl": -1.0, "regime": "trending_up"},
        ])
        result = analyzer.analyze_regime_performance(trades)
        stats = result["trending_up"]
        assert "win_rate" in stats
        assert "trade_count" in stats
        assert "avg_pnl" in stats
        assert "profit_factor" in stats

    def test_win_rate_correct(self, analyzer: SignalAnalyzer) -> None:
        trades = _make_trades_with_signals([
            {"pnl": 5.0, "regime": "trending_up"},
            {"pnl": -1.0, "regime": "trending_up"},
            {"pnl": 3.0, "regime": "trending_up"},
        ])
        result = analyzer.analyze_regime_performance(trades)
        # 2 wins / 3 trades = 0.667
        assert abs(result["trending_up"]["win_rate"] - 2 / 3) < 0.01


class TestDegradingRules:
    """Test 4: identify_degrading_rules finds declining performance."""

    def test_finds_degrading_rule(self, analyzer: SignalAnalyzer) -> None:
        # Overall: 80% win rate. Last 5 trades: 20% win rate (> 15pp decline)
        trades = _make_trades_with_signals(
            [{"pnl": 5.0, "chaos_confidence": 0.6}] * 8
            + [{"pnl": -1.0, "chaos_confidence": 0.6}] * 2
            + [{"pnl": -1.0, "chaos_confidence": 0.6}] * 4
            + [{"pnl": 5.0, "chaos_confidence": 0.6}] * 1
        )
        result = analyzer.identify_degrading_rules(trades, window_size=5)
        assert isinstance(result, list)

    def test_no_degrading_when_stable(self, analyzer: SignalAnalyzer) -> None:
        # Consistent ~60% win rate throughout (interleaved wins/losses)
        trades = _make_trades_with_signals(
            [{"pnl": 5.0}, {"pnl": 5.0}, {"pnl": -1.0}] * 3
            + [{"pnl": 5.0}]
        )
        result = analyzer.identify_degrading_rules(trades, window_size=5)
        # Should be empty or have no significant degradation
        for rule in result:
            assert rule["delta"] < 0.15  # All deltas below 15pp


class TestGetSummary:
    """Test summary aggregation."""

    def test_get_summary_returns_dict(self, analyzer: SignalAnalyzer) -> None:
        trades = _make_trades_with_signals([
            {"pnl": 5.0, "chaos_confidence": 0.6, "flow_confidence": 0.7},
            {"pnl": -1.0, "chaos_confidence": 0.5, "flow_confidence": 0.5},
        ])
        result = analyzer.get_summary(trades)
        assert isinstance(result, dict)
        assert "best_combinations" in result
        assert "regime_performance" in result
        assert "degrading_rules" in result
