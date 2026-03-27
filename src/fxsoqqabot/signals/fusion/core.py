"""Confidence-weighted signal fusion core per D-01.

Combines upstream SignalOutput instances into a single FusionResult
using the formula: weighted_score = direction * confidence * weight.
Composite is normalized by total confidence weight.

The edge is the fusion, not any single module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import structlog

from fxsoqqabot.config.models import FusionConfig
from fxsoqqabot.signals.base import RegimeState, SignalOutput


@dataclass(frozen=True, slots=True)
class FusionResult:
    """Result of signal fusion -- the fused trade decision.

    Frozen for immutability; uses __slots__ for memory efficiency.
    Follows Phase 1 frozen dataclass pattern (TickEvent, BarEvent, FillEvent).

    Attributes:
        direction: Final trade direction from -1.0 (sell) to +1.0 (buy).
        composite_score: Fused confidence-weighted score.
        fused_confidence: Overall fusion confidence 0-1.
        should_trade: True if fused confidence exceeds threshold for current phase.
        regime: Market regime from chaos module (defaults to RANGING).
        module_scores: Individual module contributions for debugging.
        confidence_threshold: Active threshold for this decision.
    """

    direction: float
    composite_score: float
    fused_confidence: float
    should_trade: bool
    regime: RegimeState
    module_scores: dict[str, float]
    confidence_threshold: float


class FusionCore:
    """Confidence-weighted signal fusion per D-01.

    Fusion formula:
      For each signal: weighted_score = direction * confidence * weight
      composite = sum(weighted_scores) / sum(confidence * weight)
      fused_confidence = sum(confidence * weight) / len(signals)
      should_trade = abs(composite) > 0 and fused_confidence >= threshold

    Per D-05: weights adapt from accuracy only, NOT from regime state.
    Per D-07: no hardcoded ranging behavior -- if fusion says trade, trade.
    """

    def __init__(self, config: FusionConfig) -> None:
        self._config = config
        self._logger = structlog.get_logger().bind(component="fusion_core")

    def fuse(
        self,
        signals: list[SignalOutput],
        weights: dict[str, float],
        confidence_threshold: float,
    ) -> FusionResult:
        """Fuse multiple signal outputs into a single trade decision.

        Args:
            signals: List of SignalOutput from upstream modules.
            weights: Module name -> normalized weight mapping.
            confidence_threshold: Minimum fused confidence to trade.

        Returns:
            FusionResult with fused direction, score, and trade decision.
        """
        if not signals:
            return FusionResult(
                direction=0.0,
                composite_score=0.0,
                fused_confidence=0.0,
                should_trade=False,
                regime=RegimeState.RANGING,
                module_scores={},
                confidence_threshold=confidence_threshold,
            )

        # Compute weighted scores per D-01
        weighted_scores: dict[str, float] = {}
        total_confidence_weight = 0.0

        for signal in signals:
            w = weights.get(signal.module_name, 0.0)
            conf_weight = signal.confidence * w
            weighted_score = signal.direction * conf_weight
            weighted_scores[signal.module_name] = weighted_score
            total_confidence_weight += conf_weight

        # Composite: normalized by total confidence weight
        if total_confidence_weight > 0:
            composite = sum(weighted_scores.values()) / total_confidence_weight
        else:
            composite = 0.0

        # Fused confidence: weighted average of signal confidences.
        # When weights are normalized (sum to 1.0), this equals
        # sum(confidence * weight) -- the overall confidence level.
        fused_confidence = total_confidence_weight

        # Direction from sign of composite
        if composite > 0:
            direction = 1.0
        elif composite < 0:
            direction = -1.0
        else:
            direction = 0.0

        # Should trade: composite is nonzero AND fused confidence meets threshold
        should_trade = abs(composite) > 0 and fused_confidence >= confidence_threshold

        # Extract regime from first signal with regime set; default RANGING
        regime = RegimeState.RANGING
        for signal in signals:
            if signal.regime is not None:
                regime = signal.regime
                break

        self._logger.debug(
            "fusion_computed",
            composite=composite,
            direction=direction,
            fused_confidence=fused_confidence,
            should_trade=should_trade,
            regime=regime.value,
            module_scores=weighted_scores,
        )

        return FusionResult(
            direction=direction,
            composite_score=composite,
            fused_confidence=fused_confidence,
            should_trade=should_trade,
            regime=regime,
            module_scores=weighted_scores,
            confidence_threshold=confidence_threshold,
        )
