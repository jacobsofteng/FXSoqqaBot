"""Tests for signal pipeline base types.

Verifies SignalOutput immutability and __slots__, RegimeState enum completeness,
SignalModule Protocol runtime checking, and UTC timestamp defaults.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timezone

import numpy as np
import pytest

from fxsoqqabot.core.events import DOMSnapshot
from fxsoqqabot.signals.base import RegimeState, SignalModule, SignalOutput


class TestSignalOutput:
    """Tests for the SignalOutput frozen dataclass."""

    def test_frozen_cannot_assign(self) -> None:
        """SignalOutput is frozen -- field assignment raises FrozenInstanceError."""
        output = SignalOutput(module_name="test", direction=0.5, confidence=0.8)
        with pytest.raises(FrozenInstanceError):
            output.direction = -0.5  # type: ignore[misc]

    def test_has_slots(self) -> None:
        """SignalOutput uses __slots__ for memory efficiency."""
        assert hasattr(SignalOutput, "__slots__")

    def test_default_timestamp_is_utc(self) -> None:
        """Default timestamp uses UTC timezone."""
        output = SignalOutput(module_name="test", direction=0.0, confidence=0.5)
        assert output.timestamp.tzinfo is not None
        assert output.timestamp.tzinfo == UTC

    def test_default_metadata_is_empty_dict(self) -> None:
        """Default metadata is an empty dict, not shared across instances."""
        out1 = SignalOutput(module_name="a", direction=0.0, confidence=0.0)
        out2 = SignalOutput(module_name="b", direction=0.0, confidence=0.0)
        assert out1.metadata == {}
        assert out2.metadata == {}
        # They should be separate dict instances
        assert out1.metadata is not out2.metadata

    def test_default_regime_is_none(self) -> None:
        """Default regime is None (not all modules provide regime info)."""
        output = SignalOutput(module_name="flow", direction=0.3, confidence=0.7)
        assert output.regime is None

    def test_full_construction(self) -> None:
        """SignalOutput can be constructed with all fields."""
        ts = datetime.now(UTC)
        output = SignalOutput(
            module_name="chaos",
            direction=-0.8,
            confidence=0.95,
            regime=RegimeState.HIGH_CHAOS,
            metadata={"lyapunov": 0.42, "hurst": 0.35},
            timestamp=ts,
        )
        assert output.module_name == "chaos"
        assert output.direction == -0.8
        assert output.confidence == 0.95
        assert output.regime == RegimeState.HIGH_CHAOS
        assert output.metadata["lyapunov"] == 0.42
        assert output.timestamp == ts


class TestRegimeState:
    """Tests for the RegimeState enum."""

    def test_exactly_five_values(self) -> None:
        """RegimeState enum has exactly 5 values."""
        assert len(RegimeState) == 5

    def test_expected_members(self) -> None:
        """All expected regime states exist."""
        expected = {
            "TRENDING_UP",
            "TRENDING_DOWN",
            "RANGING",
            "HIGH_CHAOS",
            "PRE_BIFURCATION",
        }
        actual = {member.name for member in RegimeState}
        assert actual == expected

    def test_string_values(self) -> None:
        """RegimeState is a str enum with lowercase snake_case values."""
        assert RegimeState.TRENDING_UP == "trending_up"
        assert RegimeState.TRENDING_DOWN == "trending_down"
        assert RegimeState.RANGING == "ranging"
        assert RegimeState.HIGH_CHAOS == "high_chaos"
        assert RegimeState.PRE_BIFURCATION == "pre_bifurcation"

    def test_is_string_subclass(self) -> None:
        """RegimeState members are strings (str enum)."""
        assert isinstance(RegimeState.TRENDING_UP, str)


class TestSignalModuleProtocol:
    """Tests for the SignalModule Protocol runtime checking."""

    def test_conforming_class_passes_isinstance(self) -> None:
        """A class implementing all SignalModule methods passes isinstance check."""

        class MockSignal:
            @property
            def name(self) -> str:
                return "mock"

            async def update(
                self,
                tick_arrays: dict[str, np.ndarray],
                bar_arrays: dict[str, dict[str, np.ndarray]],
                dom: DOMSnapshot | None,
            ) -> SignalOutput:
                return SignalOutput(
                    module_name="mock", direction=0.0, confidence=0.0
                )

            async def initialize(self) -> None:
                pass

        mock = MockSignal()
        assert isinstance(mock, SignalModule)

    def test_non_conforming_class_fails_isinstance(self) -> None:
        """A class missing required methods does not pass isinstance check."""

        class NotASignal:
            pass

        assert not isinstance(NotASignal(), SignalModule)
