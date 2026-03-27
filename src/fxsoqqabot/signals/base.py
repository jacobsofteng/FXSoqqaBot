"""Base types for the FXSoqqaBot signal pipeline.

Defines the SignalModule Protocol (structural typing contract all signal
modules implement), the SignalOutput frozen dataclass (canonical output
from every signal module), and the RegimeState enum for market regime
classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

import numpy as np

from fxsoqqabot.core.events import DOMSnapshot


class RegimeState(str, Enum):
    """Market regime classification from the chaos/fractal module.

    Used by the fusion layer to adapt position sizing, stop-loss
    placement, and confidence thresholds per regime (D-06, D-09, D-10).
    """

    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_CHAOS = "high_chaos"
    PRE_BIFURCATION = "pre_bifurcation"


@dataclass(frozen=True, slots=True)
class SignalOutput:
    """Canonical output from a signal module.

    Frozen for immutability; uses __slots__ for memory efficiency.
    Follows Phase 1 pattern (TickEvent, BarEvent, FillEvent).

    Attributes:
        module_name: Identifier for the source module ("chaos", "flow", "timing").
        direction: Signal direction from -1.0 (strong sell) to +1.0 (strong buy).
            0.0 indicates neutral / no signal.
        confidence: Confidence level from 0.0 (no confidence) to 1.0 (maximum).
        regime: Current market regime state. Primarily set by the chaos module;
            other modules may leave as None.
        metadata: Arbitrary key-value data for debugging and logging.
        timestamp: UTC timestamp when the signal was generated.
    """

    module_name: str
    direction: float  # -1.0 (sell) to +1.0 (buy), 0.0 = neutral
    confidence: float  # 0.0 to 1.0
    regime: RegimeState | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class SignalModule(Protocol):
    """Protocol defining the contract all signal modules must satisfy.

    Uses structural typing (Protocol) rather than ABC per research
    recommendation -- any class with matching methods is a valid
    SignalModule without explicit inheritance.

    Methods:
        name: Property returning the module identifier.
        update: Process new market data and produce a signal.
        initialize: One-time async setup (load models, warm caches).

    The update method receives:
        tick_arrays: Output of TickBuffer.as_arrays() -- keys are
            time_msc, bid, ask, last, spread, volume_real.
        bar_arrays: Dict of timeframe -> BarBuffer.as_arrays() output.
            e.g. bar_arrays["M1"]["close"] is the M1 close array.
        dom: DOMSnapshot or None for graceful degradation (D-13/FLOW-06).
    """

    @property
    def name(self) -> str: ...

    async def update(
        self,
        tick_arrays: dict[str, np.ndarray],
        bar_arrays: dict[str, dict[str, np.ndarray]],
        dom: DOMSnapshot | None,
    ) -> SignalOutput: ...

    async def initialize(self) -> None: ...
