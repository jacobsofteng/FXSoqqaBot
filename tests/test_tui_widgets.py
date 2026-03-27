"""Tests for TUI widget formatting functions.

All formatting functions are pure -- they take data and return Rich markup
strings. No Textual app or widget instantiation is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fxsoqqabot.dashboard.tui.widgets import (
    format_mutation_row,
    format_order_flow,
    format_position_panel,
    format_regime_panel,
    format_risk_panel,
    format_signals_panel,
    format_stats_panel,
    format_trade_row,
    is_mutation_event,
)
from fxsoqqabot.signals.base import RegimeState


class TestFormatRegimePanel:
    """Tests for format_regime_panel."""

    def test_format_regime_trending_up(self) -> None:
        result = format_regime_panel(RegimeState.TRENDING_UP, 0.82)
        assert "green" in result
        assert "TRENDING_UP" in result
        assert "82%" in result

    def test_format_regime_trending_down(self) -> None:
        result = format_regime_panel(RegimeState.TRENDING_DOWN, 0.75)
        assert "green" in result
        assert "TRENDING_DOWN" in result

    def test_format_regime_ranging(self) -> None:
        result = format_regime_panel(RegimeState.RANGING, 0.50)
        assert "yellow" in result
        assert "RANGING" in result

    def test_format_regime_high_chaos(self) -> None:
        result = format_regime_panel(RegimeState.HIGH_CHAOS, 0.65)
        assert "red" in result
        assert "HIGH_CHAOS" in result

    def test_format_regime_pre_bifurcation(self) -> None:
        result = format_regime_panel(RegimeState.PRE_BIFURCATION, 0.90)
        assert "red" in result
        assert "PRE_BIFURCATION" in result

    def test_format_regime_disconnected(self) -> None:
        result = format_regime_panel(
            RegimeState.RANGING, 0.50, is_connected=False,
        )
        assert "MT5 DISCONNECTED" in result
        assert "Reconnecting" in result


class TestFormatSignalsPanel:
    """Tests for format_signals_panel."""

    def test_format_signals_high_confidence(self) -> None:
        result = format_signals_panel(
            {"chaos": 0.80}, {"chaos": 1.0},
        )
        assert "green" in result
        assert "80%" in result
        assert "^" in result

    def test_format_signals_low_confidence(self) -> None:
        result = format_signals_panel(
            {"flow": 0.30}, {"flow": -1.0},
        )
        assert "red" in result
        assert "30%" in result
        assert "v" in result

    def test_format_signals_medium_confidence(self) -> None:
        result = format_signals_panel(
            {"timing": 0.55}, {"timing": 0.0},
        )
        assert "yellow" in result
        assert "-" in result

    def test_format_signals_empty(self) -> None:
        result = format_signals_panel({}, {})
        assert "No signals" in result


class TestFormatPositionPanel:
    """Tests for format_position_panel."""

    def test_format_position_none(self) -> None:
        result = format_position_panel(None)
        assert "No open position" in result

    def test_format_position_open(self) -> None:
        pos = {
            "action": "buy",
            "lots": 0.01,
            "price": 2345.50,
            "pnl": 1.20,
            "sl": 2340.00,
        }
        result = format_position_panel(pos)
        assert "BUY" in result
        assert "P&L" in result
        assert "green" in result
        assert "SL:" in result

    def test_format_position_negative_pnl(self) -> None:
        pos = {
            "action": "sell",
            "lots": 0.02,
            "price": 2350.00,
            "pnl": -0.50,
            "sl": 2355.00,
        }
        result = format_position_panel(pos)
        assert "SELL" in result
        assert "red" in result


class TestFormatRiskPanel:
    """Tests for format_risk_panel."""

    def test_format_risk_killed(self) -> None:
        result = format_risk_panel({}, is_killed=True)
        assert "KILLED" in result
        assert "bold red on white" in result

    def test_format_risk_all_ok(self) -> None:
        result = format_risk_panel(
            {"daily_drawdown": "1.2%", "max_loss": "OK"}, is_killed=False,
        )
        assert "Daily DD:" in result
        assert "OK" in result

    def test_format_risk_tripped(self) -> None:
        result = format_risk_panel(
            {"daily_drawdown": "TRIPPED"}, is_killed=False,
        )
        assert "HALTED" in result
        assert "daily_drawdown" in result


class TestFormatOrderFlow:
    """Tests for format_order_flow."""

    def test_format_order_flow(self) -> None:
        result = format_order_flow(142.0, 0.62, 0.38)
        assert "Delta:" in result
        assert "+142" in result
        assert "Bid:" in result
        assert "Ask:" in result


class TestFormatStatsPanel:
    """Tests for format_stats_panel."""

    def test_format_stats_positive(self) -> None:
        result = format_stats_panel(3, 0.67, 2.10, 22.10)
        assert "Trades: 3" in result
        assert "67%" in result
        assert "green" in result
        assert "$22.10" in result

    def test_format_stats_negative(self) -> None:
        result = format_stats_panel(5, 0.40, -1.50, 18.50)
        assert "red" in result


class TestFormatTradeRow:
    """Tests for format_trade_row."""

    def test_format_trade_row_with_timestamp(self) -> None:
        trade = {
            "timestamp": datetime(2026, 3, 27, 14, 32, tzinfo=timezone.utc),
            "action": "buy",
            "lots": 0.01,
            "entry": 2345.00,
            "exit": 2348.00,
            "pnl": 0.80,
            "regime": "trending_up",
        }
        row = format_trade_row(trade)
        assert len(row) == 7
        assert row[0] == "14:32"
        assert row[1] == "BUY"

    def test_format_trade_row_with_epoch(self) -> None:
        # 2026-03-27 14:32 UTC epoch
        trade = {
            "timestamp": 1774636320.0,
            "action": "sell",
            "lots": 0.02,
            "entry": 2350.00,
            "exit": 2351.00,
            "pnl": -0.20,
            "regime": "ranging",
        }
        row = format_trade_row(trade)
        assert row[1] == "SELL"
        assert len(row) == 7


class TestMutationHelpers:
    """Tests for is_mutation_event and format_mutation_row."""

    def test_is_mutation_event_true(self) -> None:
        assert is_mutation_event({"mutation": True}) is True

    def test_is_mutation_event_false(self) -> None:
        assert is_mutation_event({"action": "buy"}) is False

    def test_is_mutation_event_explicit_false(self) -> None:
        assert is_mutation_event({"mutation": False}) is False

    def test_format_mutation_row(self) -> None:
        mutation = {
            "param": "sl_mult",
            "old": "1.5",
            "new": "1.8",
            "reason": "sharpe improvement",
        }
        result = format_mutation_row(mutation)
        assert "MUTATED" in result
        assert "magenta" in result
        assert "sl_mult" in result
        assert "1.5" in result
        assert "1.8" in result
        assert "sharpe improvement" in result
