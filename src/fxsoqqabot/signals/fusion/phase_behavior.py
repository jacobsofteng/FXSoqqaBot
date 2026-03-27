"""Phase-aware behavior with smooth transitions per D-04, D-06, FUSE-04.

Provides:
- Smooth confidence thresholds across capital phases (sigmoid interpolation)
- Regime-specific adjustments (high-chaos, pre-bifurcation)
- Risk-reward ratios per regime (D-09)
- Trailing stop parameters per regime (D-10)

Per FUSE-04: transitions are smooth (sigmoid), not step functions.
Per D-07: no hardcoded ranging behavior -- let fusion decide.
"""

from __future__ import annotations

import math

from fxsoqqabot.config.models import FusionConfig, RiskConfig
from fxsoqqabot.signals.base import RegimeState


class PhaseBehavior:
    """Phase-aware behavior with smooth sigmoid transitions.

    Confidence threshold varies by capital phase per D-04:
    - Aggressive ($20-$100): threshold ~0.5
    - Selective ($100-$300): threshold ~0.6
    - Conservative ($300+): threshold ~0.7

    Transitions use sigmoid interpolation over a configurable equity
    buffer (default $10) per FUSE-04. No sudden strategy flip at
    exact threshold boundaries.
    """

    def __init__(self, fusion_config: FusionConfig, risk_config: RiskConfig) -> None:
        self._fusion = fusion_config
        self._risk = risk_config

    @staticmethod
    def _sigmoid(x: float) -> float:
        """Compute sigmoid function: 1 / (1 + exp(-x))."""
        # Clamp to avoid overflow
        x = max(-500.0, min(500.0, x))
        return 1.0 / (1.0 + math.exp(-x))

    def _smooth_interpolate(
        self,
        equity: float,
        midpoint: float,
        low_threshold: float,
        high_threshold: float,
        buffer: float,
    ) -> float:
        """Sigmoid interpolation between two threshold values.

        Formula per FUSE-04:
            threshold = low + (high - low) * sigmoid((equity - midpoint) / (buffer / 4))

        Args:
            equity: Current account equity.
            midpoint: Equity value at transition center.
            low_threshold: Threshold for lower phase.
            high_threshold: Threshold for higher phase.
            buffer: Width of the smooth transition zone.

        Returns:
            Interpolated threshold value.
        """
        scale = buffer / 4.0 if buffer > 0 else 1.0
        t = (equity - midpoint) / scale
        blend = self._sigmoid(t)
        return low_threshold + (high_threshold - low_threshold) * blend

    def get_confidence_threshold(self, equity: float) -> float:
        """Return smooth confidence threshold for current equity per D-04/FUSE-04.

        Uses additive sigmoid interpolation at phase boundaries:
        - aggressive_max ($100): smooth transition from 0.5 to 0.6
        - selective_max ($300): smooth transition from 0.6 to 0.7

        The threshold is computed as:
            base (aggressive) + sigmoid_step_1 + sigmoid_step_2

        Each sigmoid step adds the difference between adjacent phases,
        gated by a sigmoid centered at the boundary. This produces a
        monotonically increasing, smooth staircase.

        Args:
            equity: Current account equity in USD.

        Returns:
            Confidence threshold (0.0 to 1.0).
        """
        buffer = self._fusion.phase_transition_equity_buffer
        agg_max = self._risk.aggressive_max
        sel_max = self._risk.selective_max
        agg_thresh = self._fusion.aggressive_confidence_threshold
        sel_thresh = self._fusion.selective_confidence_threshold
        con_thresh = self._fusion.conservative_confidence_threshold

        # Start with aggressive threshold
        threshold = agg_thresh

        # Add smooth step at aggressive_max boundary
        scale = buffer / 4.0 if buffer > 0 else 1.0
        step1_blend = self._sigmoid((equity - agg_max) / scale)
        threshold += (sel_thresh - agg_thresh) * step1_blend

        # Add smooth step at selective_max boundary
        step2_blend = self._sigmoid((equity - sel_max) / scale)
        threshold += (con_thresh - sel_thresh) * step2_blend

        return threshold

    def get_regime_adjustments(self, regime: RegimeState) -> dict[str, float]:
        """Return regime-specific behavior adjustments per D-06/D-07.

        For HIGH_CHAOS or PRE_BIFURCATION per D-06:
        - confidence_boost: raise confidence threshold
        - size_reduction: reduce position size
        - sl_widen_factor: widen stop-loss

        For RANGING per D-07: empty dict -- let fusion decide.
        For TRENDING: empty dict -- normal behavior.

        Args:
            regime: Current market regime.

        Returns:
            Dict of adjustments (empty for normal regimes).
        """
        if regime in (RegimeState.HIGH_CHAOS, RegimeState.PRE_BIFURCATION):
            return {
                "confidence_boost": self._fusion.high_chaos_confidence_boost,
                "size_reduction": self._fusion.high_chaos_size_reduction,
                "sl_widen_factor": self._fusion.sl_chaos_widen_factor,
            }
        # RANGING per D-07: no special adjustments
        # TRENDING: normal behavior
        return {}

    def get_rr_ratio(self, regime: RegimeState) -> float:
        """Return risk-reward ratio for current regime per D-09.

        - TRENDING_UP/TRENDING_DOWN: 3.0 (let profits run)
        - RANGING: 1.5 (quick scalp)
        - HIGH_CHAOS/PRE_BIFURCATION: 2.0 (balanced)

        Args:
            regime: Current market regime.

        Returns:
            Risk-reward ratio.
        """
        if regime in (RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN):
            return self._fusion.trending_rr_ratio
        elif regime == RegimeState.RANGING:
            return self._fusion.ranging_rr_ratio
        else:  # HIGH_CHAOS, PRE_BIFURCATION
            return self._fusion.high_chaos_rr_ratio

    def get_trailing_stop_params(self, regime: RegimeState) -> dict[str, float] | None:
        """Return trailing stop parameters for current regime per D-10.

        - TRENDING: activate after 1x SL distance profit, trail at 0.5x ATR
        - HIGH_CHAOS/PRE_BIFURCATION: activate at 0.5x, aggressive trail at 0.3x ATR
        - RANGING: None (no trailing, use fixed TP)

        Args:
            regime: Current market regime.

        Returns:
            Dict with activation_atr and trail_distance_atr, or None.
        """
        if regime in (RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN):
            return {
                "activation_atr": self._fusion.trending_trail_activation_atr,
                "trail_distance_atr": self._fusion.trending_trail_distance_atr,
            }
        elif regime in (RegimeState.HIGH_CHAOS, RegimeState.PRE_BIFURCATION):
            return {
                "activation_atr": 0.5,
                "trail_distance_atr": self._fusion.high_chaos_trail_distance_atr,
            }
        else:  # RANGING
            return None
