"""Tests for event types and structured logging setup."""

from __future__ import annotations

from datetime import datetime

import pytest


# ---------------------------------------------------------------------------
# EventType enum
# ---------------------------------------------------------------------------


class TestEventType:
    """Tests for the EventType enumeration."""

    def test_all_expected_values(self):
        """EventType should have all documented event types."""
        from fxsoqqabot.core.events import EventType

        expected = {
            "tick",
            "bar",
            "dom",
            "fill",
            "order_rejected",
            "position_opened",
            "position_closed",
            "circuit_breaker_tripped",
            "kill_switch_activated",
            "connection_lost",
            "connection_restored",
        }
        actual = {e.value for e in EventType}
        assert actual == expected

    def test_is_str_enum(self):
        """EventType values should be usable as strings."""
        from fxsoqqabot.core.events import EventType

        assert EventType.TICK == "tick"
        assert str(EventType.FILL) == "EventType.FILL"


# ---------------------------------------------------------------------------
# TickEvent
# ---------------------------------------------------------------------------


class TestTickEvent:
    """Tests for the TickEvent dataclass."""

    def test_creation_with_all_fields(self):
        """TickEvent should be creatable with all required fields."""
        from fxsoqqabot.core.events import TickEvent

        tick = TickEvent(
            symbol="XAUUSD",
            time_msc=1711540800000,
            bid=2950.50,
            ask=2950.80,
            last=2950.65,
            volume=100,
            flags=6,
            volume_real=1.5,
            spread=0.30,
        )
        assert tick.symbol == "XAUUSD"
        assert tick.bid == 2950.50
        assert tick.ask == 2950.80
        assert tick.spread == 0.30

    def test_frozen_immutable(self):
        """TickEvent should be frozen (immutable after creation)."""
        from fxsoqqabot.core.events import TickEvent

        tick = TickEvent(
            symbol="XAUUSD",
            time_msc=1711540800000,
            bid=2950.50,
            ask=2950.80,
            last=2950.65,
            volume=100,
            flags=6,
            volume_real=1.5,
            spread=0.30,
        )
        with pytest.raises(AttributeError):
            tick.bid = 9999.99  # type: ignore[misc]

    def test_has_slots(self):
        """TickEvent should use __slots__ for memory efficiency."""
        from fxsoqqabot.core.events import TickEvent

        assert hasattr(TickEvent, "__slots__")


# ---------------------------------------------------------------------------
# BarEvent
# ---------------------------------------------------------------------------


class TestBarEvent:
    def test_creation(self):
        from fxsoqqabot.core.events import BarEvent

        bar = BarEvent(
            symbol="XAUUSD",
            timeframe="M1",
            time=1711540800,
            open=2950.00,
            high=2951.50,
            low=2949.80,
            close=2951.20,
            tick_volume=450,
            spread=3,
            real_volume=1200,
        )
        assert bar.timeframe == "M1"
        assert bar.close == 2951.20


# ---------------------------------------------------------------------------
# DOMSnapshot — graceful degradation (DATA-02)
# ---------------------------------------------------------------------------


class TestDOMSnapshot:
    """Tests for DOMSnapshot including empty entries for graceful degradation."""

    def test_creation_with_entries(self):
        """DOMSnapshot should accept a tuple of DOMEntry objects."""
        from fxsoqqabot.core.events import DOMEntry, DOMSnapshot

        entry = DOMEntry(type=2, price=2950.50, volume=10, volume_dbl=10.0)
        snap = DOMSnapshot(
            symbol="XAUUSD",
            time_msc=1711540800000,
            entries=(entry,),
        )
        assert len(snap.entries) == 1
        assert snap.entries[0].price == 2950.50

    def test_empty_entries_graceful_degradation(self):
        """DOMSnapshot with empty entries represents no DOM data (DATA-02)."""
        from fxsoqqabot.core.events import DOMSnapshot

        snap = DOMSnapshot(
            symbol="XAUUSD",
            time_msc=1711540800000,
            entries=(),
        )
        assert len(snap.entries) == 0


# ---------------------------------------------------------------------------
# FillEvent — paper/live distinction (D-01)
# ---------------------------------------------------------------------------


class TestFillEvent:
    """Tests for FillEvent with paper/live distinction."""

    def test_is_paper_field_exists(self):
        """FillEvent must have is_paper field per D-01."""
        from fxsoqqabot.core.events import FillEvent

        fill = FillEvent(
            ticket=12345,
            symbol="XAUUSD",
            action="buy",
            volume=0.01,
            fill_price=2950.50,
            requested_price=2950.40,
            slippage=0.10,
            sl=2948.00,
            tp=2955.00,
            magic=20260327,
            is_paper=True,
        )
        assert fill.is_paper is True

    def test_live_fill(self):
        """FillEvent with is_paper=False represents a live fill."""
        from fxsoqqabot.core.events import FillEvent

        fill = FillEvent(
            ticket=12346,
            symbol="XAUUSD",
            action="sell",
            volume=0.01,
            fill_price=2950.50,
            requested_price=2950.60,
            slippage=-0.10,
            sl=2953.00,
            tp=None,
            magic=20260327,
            is_paper=False,
        )
        assert fill.is_paper is False
        assert fill.tp is None

    def test_timestamp_default(self):
        """FillEvent should auto-generate timestamp if not provided."""
        from fxsoqqabot.core.events import FillEvent

        fill = FillEvent(
            ticket=12347,
            symbol="XAUUSD",
            action="buy",
            volume=0.01,
            fill_price=2950.50,
            requested_price=2950.50,
            slippage=0.0,
            sl=2948.00,
            tp=2955.00,
            magic=20260327,
            is_paper=True,
        )
        assert isinstance(fill.timestamp, datetime)

    def test_frozen_immutable(self):
        """FillEvent should be frozen (immutable)."""
        from fxsoqqabot.core.events import FillEvent

        fill = FillEvent(
            ticket=12348,
            symbol="XAUUSD",
            action="buy",
            volume=0.01,
            fill_price=2950.50,
            requested_price=2950.50,
            slippage=0.0,
            sl=2948.00,
            tp=None,
            magic=20260327,
            is_paper=True,
        )
        with pytest.raises(AttributeError):
            fill.volume = 0.02  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------


class TestSetupLogging:
    """Tests for structlog configuration."""

    def test_setup_logging_console_mode(self):
        """setup_logging with json_mode=False should configure console renderer."""
        from fxsoqqabot.config.models import LoggingConfig
        from fxsoqqabot.logging.setup import setup_logging

        config = LoggingConfig(json_mode=False, level="DEBUG")
        # Should not raise
        setup_logging(config)

    def test_setup_logging_json_mode(self):
        """setup_logging with json_mode=True should configure JSON renderer."""
        from fxsoqqabot.config.models import LoggingConfig
        from fxsoqqabot.logging.setup import setup_logging

        config = LoggingConfig(json_mode=True, level="INFO")
        # Should not raise
        setup_logging(config)

    def test_logging_module_exports(self):
        """The logging module should export setup_logging and get_logger."""
        from fxsoqqabot.logging import get_logger, setup_logging

        assert callable(setup_logging)
        assert callable(get_logger)
