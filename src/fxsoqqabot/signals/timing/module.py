"""Quantum timing engine signal module.

Implements the SignalModule Protocol by combining OU mean-reversion
timing (QTIM-01), volatility phase transition detection (QTIM-02),
and probability-weighted timing windows (QTIM-03) into a unified
timing signal for the fusion core.

Per D-12: timing has NO veto or delay power. It contributes to the
confidence-weighted blend like any other module.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import numpy as np
import structlog

from fxsoqqabot.signals.base import SignalOutput
from fxsoqqabot.signals.timing.ou_model import (
    compute_entry_window,
    estimate_ou_parameters,
)
from fxsoqqabot.signals.timing.phase_transition import detect_phase_transition

if TYPE_CHECKING:
    from fxsoqqabot.config.models import TimingConfig
    from fxsoqqabot.core.events import DOMSnapshot

logger = structlog.get_logger().bind(component="timing_module")


class QuantumTimingModule:
    """Quantum timing engine implementing SignalModule Protocol.

    Combines Ornstein-Uhlenbeck mean-reversion timing with volatility
    compression/expansion phase transition detection to produce
    probability-weighted timing signals.

    The module estimates:
    - WHEN a mean-reversion move is likely (OU half-life)
    - WHETHER volatility is compressed (breakout imminent) or
      expanding (move in progress)
    - HOW confident the timing signal is (fit quality * urgency)

    Attributes:
        _config: TimingConfig with OU and phase transition parameters.
    """

    def __init__(self, config: TimingConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        """Module identifier for the fusion layer."""
        return "timing"

    async def initialize(self) -> None:
        """One-time async setup. No warm-up needed for scipy."""
        await logger.ainfo("timing_module_initialized")

    async def update(
        self,
        tick_arrays: dict[str, np.ndarray],
        bar_arrays: dict[str, dict[str, np.ndarray]],
        dom: DOMSnapshot | None,
    ) -> SignalOutput:
        """Process bar data and produce a timing signal.

        1. Extract close/high/low from primary timeframe bars.
        2. Estimate OU parameters on recent bars.
        3. Compute entry window from OU displacement.
        4. Detect volatility phase transition.
        5. Combine timing signals with weighted confidence.

        Args:
            tick_arrays: Tick buffer output (unused by timing module).
            bar_arrays: Dict of timeframe -> arrays (close, high, low, etc).
            dom: DOM snapshot (unused by timing module).

        Returns:
            SignalOutput with direction, confidence, and timing metadata.
        """
        tf = self._config.primary_timeframe

        # Check data availability
        if tf not in bar_arrays:
            return self._neutral("no_bar_data")

        bars = bar_arrays[tf]
        close = bars.get("close")
        high = bars.get("high")
        low = bars.get("low")

        if close is None or len(close) == 0:
            return self._neutral("empty_bars")

        if high is None or low is None:
            return self._neutral("missing_ohlc")

        # OU estimation on recent bars (offload to thread for numerical work)
        lookback = self._config.ou_lookback_bars
        close_slice = close[-lookback:]

        kappa, theta, sigma, ou_conf = await asyncio.to_thread(
            estimate_ou_parameters, close_slice
        )

        # Entry window
        direction, urgency, window_conf = compute_entry_window(
            kappa, theta, sigma, float(close[-1]), ou_conf
        )

        # Phase transition detection
        state, energy, phase_conf = detect_phase_transition(
            close,
            high,
            low,
            self._config.phase_transition_atr_period,
            self._config.phase_transition_compression_threshold,
            self._config.phase_transition_expansion_threshold,
        )

        # Combine timing signals
        if state == "compression" and energy > 0.3:
            # Breakout imminent -- boost urgency
            urgency = min(1.0, urgency + energy * 0.5)
        elif state == "expansion":
            # Move already happening -- reduce confidence slightly
            window_conf *= 0.8

        final_direction = direction
        # Final confidence: weighted blend of OU fit and phase quality,
        # scaled by urgency (low urgency near mean = low confidence)
        final_confidence = (window_conf * 0.6 + phase_conf * 0.4) * urgency
        final_confidence = float(np.clip(final_confidence, 0.0, 1.0))

        # Compute half-life for metadata
        half_life = float(np.log(2) / kappa) if kappa > 0 else float("inf")

        return SignalOutput(
            module_name="timing",
            direction=float(np.clip(final_direction, -1, 1)),
            confidence=final_confidence,
            metadata={
                "kappa": kappa,
                "theta": theta,
                "sigma": sigma,
                "half_life": half_life,
                "phase_state": state,
                "energy": energy,
                "urgency": urgency,
            },
        )

    def _neutral(self, reason: str) -> SignalOutput:
        """Return a neutral signal with zero direction and confidence."""
        return SignalOutput(
            module_name="timing",
            direction=0.0,
            confidence=0.0,
            metadata={"reason": reason},
        )
