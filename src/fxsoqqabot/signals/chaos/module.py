"""ChaosRegimeModule -- signal module implementing SignalModule Protocol.

Orchestrates the five individual chaos metrics (Hurst, Lyapunov, fractal
dimension, Feigenbaum bifurcation, crowd entropy) and combines them
via the threshold-based regime classifier into a SignalOutput.

All blocking chaos computations run via asyncio.to_thread() per research
Pattern 2 (keep the event loop responsive).
"""

from __future__ import annotations

import asyncio

import numpy as np
import structlog

from fxsoqqabot.config.models import ChaosConfig
from fxsoqqabot.core.events import DOMSnapshot
from fxsoqqabot.signals.base import RegimeState, SignalOutput
from fxsoqqabot.signals.chaos.entropy import compute_crowd_entropy
from fxsoqqabot.signals.chaos.feigenbaum import detect_bifurcation_proximity
from fxsoqqabot.signals.chaos.fractal import compute_fractal_dimension
from fxsoqqabot.signals.chaos.hurst import compute_hurst
from fxsoqqabot.signals.chaos.lyapunov import compute_lyapunov
from fxsoqqabot.signals.chaos.regime import classify_regime

logger = structlog.get_logger().bind(component="chaos_module")


class ChaosRegimeModule:
    """Chaos/fractal/Feigenbaum regime classifier signal module.

    Implements the SignalModule Protocol (structural typing -- no
    explicit inheritance required).

    Computes all five chaos metrics on bar close prices and classifies
    the market into one of five discrete regime states with confidence
    levels.
    """

    def __init__(self, config: ChaosConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        """Module identifier."""
        return "chaos"

    async def initialize(self) -> None:
        """One-time async setup. No-op for now (Numba warm-up later)."""
        logger.info("chaos_module_initialized")

    async def update(
        self,
        tick_arrays: dict[str, np.ndarray],
        bar_arrays: dict[str, dict[str, np.ndarray]],
        dom: DOMSnapshot | None,
    ) -> SignalOutput:
        """Process bar data and produce regime classification signal.

        Args:
            tick_arrays: Tick buffer arrays (unused by chaos module).
            bar_arrays: Dict of timeframe -> {field -> ndarray}.
            dom: DOM snapshot (unused by chaos module).

        Returns:
            SignalOutput with regime classification and chaos metadata.
        """
        cfg = self._config
        tf = cfg.primary_timeframe

        # Guard: missing or empty bar data
        if tf not in bar_arrays or "close" not in bar_arrays[tf]:
            return self._neutral_output()

        close_prices = bar_arrays[tf]["close"]
        if len(close_prices) == 0:
            return self._neutral_output()

        # Run all five chaos metrics via asyncio.to_thread (non-blocking)
        hurst_val, hurst_conf = await asyncio.to_thread(
            compute_hurst, close_prices, cfg.hurst_min_length
        )
        lyap_val, lyap_conf = await asyncio.to_thread(
            compute_lyapunov, close_prices, cfg.lyapunov_emb_dim, cfg.lyapunov_min_length
        )
        fractal_val, fractal_conf = await asyncio.to_thread(
            compute_fractal_dimension, close_prices, cfg.fractal_emb_dim, cfg.fractal_min_length
        )
        bifurc_val, bifurc_conf = await asyncio.to_thread(
            detect_bifurcation_proximity, close_prices, cfg.feigenbaum_order
        )
        entropy_val, entropy_conf = await asyncio.to_thread(
            compute_crowd_entropy, close_prices, cfg.entropy_bins, cfg.entropy_min_length
        )

        # Price direction from recent close movement
        if len(close_prices) >= 20:
            price_direction = float(np.sign(close_prices[-1] - close_prices[-20]))
        else:
            price_direction = 0.0

        # Classify regime
        regime_state, regime_confidence = classify_regime(
            hurst=hurst_val,
            hurst_conf=hurst_conf,
            lyapunov=lyap_val,
            lyap_conf=lyap_conf,
            fractal_dim=fractal_val,
            fractal_conf=fractal_conf,
            bifurcation=bifurc_val,
            bifurcation_conf=bifurc_conf,
            entropy=entropy_val,
            entropy_conf=entropy_conf,
            price_direction=price_direction,
        )

        # Map regime to direction
        direction_map = {
            RegimeState.TRENDING_UP: 1.0,
            RegimeState.TRENDING_DOWN: -1.0,
            RegimeState.RANGING: 0.0,
            RegimeState.HIGH_CHAOS: 0.0,
            RegimeState.PRE_BIFURCATION: 0.0,
        }
        direction = direction_map.get(regime_state, 0.0)

        logger.debug(
            "chaos_update_complete",
            regime=regime_state.value,
            confidence=regime_confidence,
            hurst=hurst_val,
            lyapunov=lyap_val,
            fractal_dim=fractal_val,
            bifurcation=bifurc_val,
            entropy=entropy_val,
        )

        return SignalOutput(
            module_name="chaos",
            direction=direction,
            confidence=regime_confidence,
            regime=regime_state,
            metadata={
                "hurst": hurst_val,
                "lyapunov": lyap_val,
                "fractal_dim": fractal_val,
                "bifurcation": bifurc_val,
                "entropy": entropy_val,
            },
        )

    def _neutral_output(self) -> SignalOutput:
        """Return a neutral signal when data is insufficient."""
        return SignalOutput(
            module_name="chaos",
            direction=0.0,
            confidence=0.0,
            regime=RegimeState.RANGING,
        )
