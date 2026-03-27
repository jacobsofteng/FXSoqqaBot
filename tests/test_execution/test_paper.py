"""Tests for the paper trading fill simulation engine.

Tests verify:
- Paper fills have is_paper=True
- Spread modeled correctly (ask for buy, bid for sell)
- Random slippage within deviation range
- Sequential ticket numbering from 1000000
- Position tracking (open/close)
- SL/TP hit detection
- Virtual equity and balance tracking
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fxsoqqabot.core.events import FillEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def paper_executor():
    """Fresh PaperExecutor with $20 starting balance."""
    from fxsoqqabot.execution.paper import PaperExecutor

    return PaperExecutor(starting_balance=20.0, max_slippage_points=5)


@pytest.fixture
def mock_tick():
    """Mock tick with bid=2950.0, ask=2950.50."""
    return SimpleNamespace(bid=2950.0, ask=2950.50)


@pytest.fixture
def buy_request():
    """Standard buy order request dict."""
    return {
        "action": 1,  # TRADE_ACTION_DEAL
        "symbol": "XAUUSD",
        "volume": 0.01,
        "type": 0,  # ORDER_TYPE_BUY
        "price": 2950.50,  # ask
        "sl": 2948.0,
        "tp": 2955.0,
        "deviation": 20,
        "magic": 20260327,
        "comment": "fxsoqqabot",
        "type_time": 0,
        "type_filling": 2,
    }


@pytest.fixture
def sell_request():
    """Standard sell order request dict."""
    return {
        "action": 1,
        "symbol": "XAUUSD",
        "volume": 0.01,
        "type": 1,  # ORDER_TYPE_SELL
        "price": 2950.0,  # bid
        "sl": 2953.0,
        "tp": 2947.0,
        "deviation": 20,
        "magic": 20260327,
        "comment": "fxsoqqabot",
        "type_time": 0,
        "type_filling": 2,
    }


# ---------------------------------------------------------------------------
# Test: simulate_fill() returns FillEvent with is_paper=True
# ---------------------------------------------------------------------------


class TestPaperFillBasics:
    """Basic paper fill simulation tests."""

    def test_simulate_fill_returns_fill_event_with_is_paper_true(
        self, paper_executor, buy_request, mock_tick
    ):
        """simulate_fill() returns FillEvent with is_paper=True."""
        fill = paper_executor.simulate_fill(buy_request, mock_tick)
        assert isinstance(fill, FillEvent)
        assert fill.is_paper is True

    def test_simulate_fill_buy_fills_at_ask(
        self, paper_executor, buy_request, mock_tick
    ):
        """Buy orders fill at ask price (same as live), possibly with slippage."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            # Force no slippage (20% chance: 0.7 <= r < 0.9)
            mock_random.random.return_value = 0.8
            fill = paper_executor.simulate_fill(buy_request, mock_tick)
            # Base price should be ask (2950.50), no slippage
            assert fill.fill_price == mock_tick.ask

    def test_simulate_fill_sell_fills_at_bid(
        self, paper_executor, sell_request, mock_tick
    ):
        """Sell orders fill at bid price (same as live), possibly with slippage."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.8  # No slippage
            fill = paper_executor.simulate_fill(sell_request, mock_tick)
            assert fill.fill_price == mock_tick.bid

    def test_simulate_fill_generates_sequential_tickets(
        self, paper_executor, buy_request, mock_tick
    ):
        """Paper tickets start at 1000000 and increment."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.8
            fill1 = paper_executor.simulate_fill(buy_request, mock_tick)
            fill2 = paper_executor.simulate_fill(buy_request, mock_tick)
            assert fill1.ticket == 1000000
            assert fill2.ticket == 1000001


# ---------------------------------------------------------------------------
# Test: Slippage simulation
# ---------------------------------------------------------------------------


class TestPaperSlippage:
    """Slippage simulation tests per D-01 realism."""

    def test_simulate_fill_adds_slippage_within_deviation(
        self, paper_executor, buy_request, mock_tick
    ):
        """simulate_fill() adds random slippage within configured deviation range."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            # Adverse slippage path (r < 0.7)
            mock_random.random.return_value = 0.3
            mock_random.randint.return_value = 3  # 3 points slippage
            fill = paper_executor.simulate_fill(buy_request, mock_tick)
            expected_price = mock_tick.ask + 3 * 0.01
            assert fill.fill_price == pytest.approx(expected_price)

    def test_slippage_tracked_in_fill_event(
        self, paper_executor, buy_request, mock_tick
    ):
        """Slippage = fill_price - requested_price."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.3
            mock_random.randint.return_value = 2
            fill = paper_executor.simulate_fill(buy_request, mock_tick)
            expected_slippage = fill.fill_price - buy_request["price"]
            assert fill.slippage == pytest.approx(expected_slippage)


# ---------------------------------------------------------------------------
# Test: simulate_close()
# ---------------------------------------------------------------------------


class TestPaperClose:
    """Paper position close tests."""

    def test_simulate_close_returns_fill_event_with_close_action(
        self, paper_executor, buy_request, mock_tick
    ):
        """simulate_close() returns FillEvent with action='close' and is_paper=True."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.8
            # Open position first
            fill = paper_executor.simulate_fill(buy_request, mock_tick)
            # Close it
            close_request = {
                "action": 1,
                "symbol": "XAUUSD",
                "volume": 0.01,
                "type": 1,  # Opposite: sell to close buy
                "price": mock_tick.bid,
                "position": fill.ticket,
            }
            close_fill = paper_executor.simulate_close(close_request, mock_tick)
            assert close_fill is not None
            assert close_fill.action == "close"
            assert close_fill.is_paper is True

    def test_position_removed_after_close(
        self, paper_executor, buy_request, mock_tick
    ):
        """Paper position removed from open positions after simulate_close."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.8
            fill = paper_executor.simulate_fill(buy_request, mock_tick)
            assert len(paper_executor.get_paper_positions()) == 1

            close_request = {
                "action": 1, "symbol": "XAUUSD", "volume": 0.01,
                "type": 1, "price": mock_tick.bid, "position": fill.ticket,
            }
            paper_executor.simulate_close(close_request, mock_tick)
            assert len(paper_executor.get_paper_positions()) == 0

    def test_simulate_close_nonexistent_returns_none(
        self, paper_executor, mock_tick
    ):
        """simulate_close() returns None for nonexistent position ticket."""
        close_request = {
            "action": 1, "symbol": "XAUUSD", "volume": 0.01,
            "type": 1, "price": mock_tick.bid, "position": 999999,
        }
        result = paper_executor.simulate_close(close_request, mock_tick)
        assert result is None


# ---------------------------------------------------------------------------
# Test: Paper positions
# ---------------------------------------------------------------------------


class TestPaperPositions:
    """Paper position tracking tests."""

    def test_get_paper_positions_returns_open_positions(
        self, paper_executor, buy_request, sell_request, mock_tick
    ):
        """get_paper_positions() returns list of currently open paper positions."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.8
            paper_executor.simulate_fill(buy_request, mock_tick)
            paper_executor.simulate_fill(sell_request, mock_tick)
            positions = paper_executor.get_paper_positions()
            assert len(positions) == 2


# ---------------------------------------------------------------------------
# Test: Balance and equity tracking
# ---------------------------------------------------------------------------


class TestPaperBalanceEquity:
    """Virtual balance and equity tests."""

    def test_starting_balance(self, paper_executor):
        """Initial balance matches starting_balance."""
        assert paper_executor.balance == 20.0

    def test_balance_updates_after_close(
        self, paper_executor, buy_request, mock_tick
    ):
        """get_paper_balance tracks cumulative P&L from closed paper trades."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.8  # No slippage
            fill = paper_executor.simulate_fill(buy_request, mock_tick)
            # Close at higher price (profitable)
            profit_tick = SimpleNamespace(bid=2952.0, ask=2952.50)
            close_request = {
                "action": 1, "symbol": "XAUUSD", "volume": 0.01,
                "type": 1, "price": profit_tick.bid, "position": fill.ticket,
            }
            paper_executor.simulate_close(close_request, profit_tick)
            # PnL = (close - open) * volume * contract_size
            # = (2952.0 - 2950.50) * 0.01 * 100 = 1.50
            assert paper_executor.balance == pytest.approx(21.50)

    def test_equity_includes_unrealized_pnl(
        self, paper_executor, buy_request, mock_tick
    ):
        """get_paper_equity() = balance + unrealized P&L."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.8
            paper_executor.simulate_fill(buy_request, mock_tick)
            # Current prices moved up
            current_bid = 2952.0
            current_ask = 2952.50
            equity = paper_executor.get_paper_equity(current_bid, current_ask)
            # Unrealized for buy: (bid - open_price) * volume * contract_size
            # = (2952.0 - 2950.50) * 0.01 * 100 = 1.50
            expected = 20.0 + 1.50
            assert equity == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Test: SL/TP checking
# ---------------------------------------------------------------------------


class TestPaperSLTP:
    """SL/TP hit detection tests."""

    def test_check_sl_buy_triggered(
        self, paper_executor, buy_request, mock_tick
    ):
        """check_sl_tp() detects when bid crosses SL for buy position."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.8
            fill = paper_executor.simulate_fill(buy_request, mock_tick)
            # SL is 2948.0, bid drops below
            triggered = paper_executor.check_sl_tp(bid=2947.0, ask=2947.50)
            assert fill.ticket in triggered

    def test_check_tp_buy_triggered(
        self, paper_executor, buy_request, mock_tick
    ):
        """check_sl_tp() detects when bid crosses TP for buy position."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.8
            fill = paper_executor.simulate_fill(buy_request, mock_tick)
            # TP is 2955.0, bid rises above
            triggered = paper_executor.check_sl_tp(bid=2956.0, ask=2956.50)
            assert fill.ticket in triggered

    def test_check_sl_sell_triggered(
        self, paper_executor, sell_request, mock_tick
    ):
        """check_sl_tp() detects when ask crosses SL for sell position."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.8
            fill = paper_executor.simulate_fill(sell_request, mock_tick)
            # SL is 2953.0, ask rises above
            triggered = paper_executor.check_sl_tp(bid=2953.50, ask=2954.0)
            assert fill.ticket in triggered

    def test_check_tp_sell_triggered(
        self, paper_executor, sell_request, mock_tick
    ):
        """check_sl_tp() detects when ask crosses TP for sell position."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.8
            fill = paper_executor.simulate_fill(sell_request, mock_tick)
            # TP is 2947.0, ask drops below
            triggered = paper_executor.check_sl_tp(bid=2946.0, ask=2946.50)
            assert fill.ticket in triggered

    def test_no_trigger_within_range(
        self, paper_executor, buy_request, mock_tick
    ):
        """check_sl_tp() returns empty list when price is between SL and TP."""
        with patch("fxsoqqabot.execution.paper.random") as mock_random:
            mock_random.random.return_value = 0.8
            paper_executor.simulate_fill(buy_request, mock_tick)
            # Price between SL (2948) and TP (2955)
            triggered = paper_executor.check_sl_tp(bid=2951.0, ask=2951.50)
            assert triggered == []
