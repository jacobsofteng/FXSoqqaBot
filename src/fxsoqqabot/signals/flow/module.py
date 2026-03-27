"""OrderFlowModule -- signal module for order flow analysis (FLOW-06, D-13).

Implements the SignalModule Protocol. Combines volume delta, aggression
imbalance, HFT detection, institutional footprints, and optional DOM
analysis into a single signal output. Degrades gracefully from DOM+tick
to tick-only mode per D-13.
"""

from __future__ import annotations

import numpy as np
import structlog

from fxsoqqabot.config.models import FlowConfig
from fxsoqqabot.core.events import DOMSnapshot
from fxsoqqabot.signals.base import SignalOutput
from fxsoqqabot.signals.flow.aggression import (
    compute_aggression_imbalance,
    detect_hft_signatures,
)
from fxsoqqabot.signals.flow.dom_analyzer import analyze_dom
from fxsoqqabot.signals.flow.dom_quality import DOMQualityChecker
from fxsoqqabot.signals.flow.institutional import detect_institutional_footprints
from fxsoqqabot.signals.flow.volume_delta import compute_volume_delta

logger = structlog.get_logger().bind(component="flow_module")


class OrderFlowModule:
    """Order flow signal module implementing SignalModule Protocol.

    Combines tick-level analysis (volume delta, aggression, HFT detection,
    institutional footprints) with optional DOM analysis when quality
    passes D-15 checks. Effort split: ~80% tick / ~20% DOM per D-13.
    """

    def __init__(self, config: FlowConfig) -> None:
        self._config = config
        self._dom_checker = DOMQualityChecker(config)

    @property
    def name(self) -> str:
        """Module identifier."""
        return "flow"

    async def initialize(self) -> None:
        """One-time async setup."""
        logger.info("flow_module_initialized")

    async def update(
        self,
        tick_arrays: dict[str, np.ndarray],
        bar_arrays: dict[str, dict[str, np.ndarray]],
        dom: DOMSnapshot | None,
    ) -> SignalOutput:
        """Process new market data and produce flow signal.

        Steps:
        1. Extract tick arrays
        2. If empty, return neutral
        3. Compute volume delta (FLOW-01)
        4. Compute aggression imbalance (FLOW-02)
        5. Detect HFT signatures (FLOW-05)
        6. Detect institutional footprints (FLOW-04)
        7. DOM analysis if available and quality passes (FLOW-03, D-13, D-15)
        8. Combine signals: ~80% tick / ~20% DOM

        Args:
            tick_arrays: Output of TickBuffer.as_arrays().
            bar_arrays: Dict of timeframe -> BarBuffer.as_arrays().
            dom: DOMSnapshot or None for graceful degradation.

        Returns:
            SignalOutput with combined flow direction and confidence.
        """
        config = self._config

        # 1. Extract tick arrays
        bid = tick_arrays.get("bid", np.array([], dtype=np.float64))
        ask = tick_arrays.get("ask", np.array([], dtype=np.float64))
        last = tick_arrays.get("last", np.array([], dtype=np.float64))
        volume_real = tick_arrays.get("volume_real", np.array([], dtype=np.float64))
        spread = tick_arrays.get("spread", np.array([], dtype=np.float64))
        time_msc = tick_arrays.get("time_msc", np.array([], dtype=np.int64))

        # 2. Empty tick data -> neutral
        if len(bid) == 0:
            return SignalOutput(
                module_name="flow",
                direction=0.0,
                confidence=0.0,
                metadata={"reason": "no_tick_data"},
            )

        # 3. Volume delta (FLOW-01)
        cum_delta, buy_vol, sell_vol, ambiguous_pct = compute_volume_delta(
            bid, ask, last, volume_real, config.volume_delta_window
        )

        # 4. Aggression imbalance (FLOW-02)
        aggression_imbalance, aggression_zscore, aggression_conf = (
            compute_aggression_imbalance(
                bid, ask, last, volume_real, config.aggression_window
            )
        )

        # 5. HFT signatures (FLOW-05)
        is_hft, hft_confidence = detect_hft_signatures(
            time_msc,
            spread,
            volume_real,
            config.hft_tick_velocity_threshold,
            config.hft_spread_widen_multiplier,
        )

        # 6. Institutional footprints (FLOW-04)
        inst_score, inst_confidence, inst_signals = detect_institutional_footprints(
            bid,
            ask,
            last,
            volume_real,
            spread,
            time_msc,
            config.institutional_volume_threshold,
            config.institutional_price_tolerance,
            config.institutional_min_repeats,
        )

        # 7. DOM analysis (FLOW-03, D-13, D-15)
        dom_imbalance = 0.0
        dom_conf = 0.0
        if dom is not None:
            self._dom_checker.record_snapshot(dom)
            if self._dom_checker.is_dom_enabled:
                dom_imbalance, dom_conf = analyze_dom(dom, config.dom_min_depth)

        # 8. Combine signals: ~80% tick / ~20% DOM per D-13
        # Normalize volume delta to [-1, +1]
        total_vol = buy_vol + sell_vol + 1e-10
        normalized_delta = float(np.clip(cum_delta / total_vol, -1.0, 1.0))

        # Tick direction weighted combination
        tick_direction = (
            0.6 * normalized_delta
            + 0.2 * aggression_imbalance
            + 0.2 * inst_score
        )

        # Blend with DOM if available
        if dom_conf > 0:
            direction = 0.8 * tick_direction + 0.2 * dom_imbalance
        else:
            direction = tick_direction

        # Overall confidence: weighted average of component confidences
        # Volume delta confidence based on ambiguous percentage
        delta_conf = 1.0 - ambiguous_pct if ambiguous_pct < 1.0 else 0.0

        confidence_components = [
            (delta_conf, 0.3),
            (aggression_conf, 0.3),
            (inst_confidence, 0.2),
        ]

        if dom_conf > 0:
            confidence_components.append((dom_conf, 0.2))
            # Reweight to sum to 1.0
            total_weight = sum(w for _, w in confidence_components)
        else:
            total_weight = 0.8  # tick-only weights

        confidence = sum(c * w for c, w in confidence_components) / max(
            total_weight, 1e-10
        )

        # Reduce confidence if ambiguous percentage is high (>30%)
        if ambiguous_pct > 0.3:
            confidence *= 1.0 - (ambiguous_pct - 0.3) * 0.5

        # If HFT detected, reduce confidence (noise)
        if is_hft:
            confidence *= 0.8

        confidence = float(np.clip(confidence, 0.0, 1.0))
        direction = float(np.clip(direction, -1.0, 1.0))

        metadata = {
            "volume_delta": cum_delta,
            "buy_vol": buy_vol,
            "sell_vol": sell_vol,
            "ambiguous_pct": ambiguous_pct,
            "aggression_imbalance": aggression_imbalance,
            "aggression_zscore": aggression_zscore,
            "institutional_score": inst_score,
            "institutional_signals": inst_signals,
            "hft_detected": is_hft,
            "hft_confidence": hft_confidence,
            "dom_enabled": self._dom_checker.is_dom_enabled,
            "dom_imbalance": dom_imbalance,
            "dom_confidence": dom_conf,
        }

        return SignalOutput(
            module_name="flow",
            direction=direction,
            confidence=confidence,
            metadata=metadata,
        )
