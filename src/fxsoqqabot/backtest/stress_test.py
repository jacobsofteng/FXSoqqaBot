"""Feigenbaum stress testing per TEST-06.

Generates synthetic price series with controlled period-doubling bifurcation
and verifies that the chaos module correctly detects regime transitions.

Three-phase synthetic series:
- Phase 1: Stable single-period oscillation (TRENDING or RANGING)
- Phase 2: Period doubling approaching Feigenbaum delta (PRE_BIFURCATION)
- Phase 3: Chaotic regime with no clear period (HIGH_CHAOS)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import structlog

from fxsoqqabot.signals.base import RegimeState, SignalOutput
from fxsoqqabot.signals.chaos.feigenbaum import detect_bifurcation_proximity
from fxsoqqabot.signals.chaos.module import ChaosRegimeModule

if TYPE_CHECKING:
    from fxsoqqabot.config.models import ChaosConfig


@dataclass(frozen=True, slots=True)
class StressTestResult:
    """Result of Feigenbaum stress testing per TEST-06.

    Attributes:
        pre_transition_regime: Regime detected before transition.
        transition_regime: Regime detected during transition.
        post_transition_regime: Regime detected after transition.
        pre_transition_detected: True if classified as stable (TRENDING/RANGING).
        transition_detected: True if PRE_BIFURCATION or HIGH_CHAOS detected.
        chaos_detected: True if HIGH_CHAOS detected post-transition.
        bifurcation_proximity_at_transition: detect_bifurcation_proximity result
            on the transition segment.
        passes: True if transition_detected AND chaos_detected.
    """

    pre_transition_regime: str
    transition_regime: str
    post_transition_regime: str
    pre_transition_detected: bool
    transition_detected: bool
    chaos_detected: bool
    bifurcation_proximity_at_transition: float
    passes: bool


class FeigenbaumStressTest:
    """Injects synthetic regime transitions to verify chaos module behavior per TEST-06.

    Generates synthetic price series with controlled period-doubling bifurcation,
    then runs the chaos module over each phase to verify correct classification.
    """

    def __init__(self, config: ChaosConfig) -> None:
        self._config = config
        self._logger = structlog.get_logger().bind(component="stress_test")

    def generate_bifurcation_price_series(
        self,
        n_bars: int = 500,
        base_price: float = 2000.0,
        pre_transition_bars: int = 200,
        transition_bars: int = 100,
        post_transition_bars: int = 200,
        seed: int = 42,
    ) -> np.ndarray:
        """Generate synthetic price series with controlled bifurcation.

        Phase 1 (pre_transition_bars): Regular single-period oscillation
            prices[i] = base_price + 5.0 * sin(2*pi*i/20) + noise(0, 0.5)

        Phase 2 (transition_bars): Period doubling
            progress = (i - pre) / transition
            prices[i] = base + (1-prog)*5*sin(2*pi*i/20) + prog*3*sin(2*pi*i/10) + noise(0, 0.5 + prog*2)

        Phase 3 (post_transition_bars): Chaotic
            prices[i] = prices[i-1] + noise(0, 3.0) + 0.5*sin(random_phase)

        Args:
            n_bars: Total number of bars (should equal sum of phase bars).
            base_price: Center price level.
            pre_transition_bars: Bars in stable phase.
            transition_bars: Bars in period-doubling transition.
            post_transition_bars: Bars in chaotic phase.
            seed: Random seed for reproducibility.

        Returns:
            1D numpy array of synthetic close prices.
        """
        rng = np.random.default_rng(seed)
        total = pre_transition_bars + transition_bars + post_transition_bars
        prices = np.empty(total, dtype=np.float64)

        # Phase 1: Stable single-period oscillation
        for i in range(pre_transition_bars):
            prices[i] = (
                base_price
                + 5.0 * np.sin(2 * np.pi * i / 20)
                + rng.normal(0, 0.5)
            )

        # Phase 2: Period doubling transition
        for i in range(transition_bars):
            idx = pre_transition_bars + i
            progress = i / transition_bars
            prices[idx] = (
                base_price
                + (1 - progress) * 5.0 * np.sin(2 * np.pi * idx / 20)
                + progress * 3.0 * np.sin(2 * np.pi * idx / 10)
                + rng.normal(0, 0.5 + progress * 2.0)
            )

        # Phase 3: Chaotic (random walk with random-phase sine)
        last_price = prices[pre_transition_bars + transition_bars - 1]
        for i in range(post_transition_bars):
            idx = pre_transition_bars + transition_bars + i
            random_phase = rng.uniform(0, 2 * np.pi)
            last_price = last_price + rng.normal(0, 3.0) + 0.5 * np.sin(random_phase)
            prices[idx] = last_price

        return prices[:n_bars]

    async def run_stress_test(self) -> StressTestResult:
        """Run Feigenbaum stress test.

        1. Generate synthetic price series with three phases.
        2. Build bar arrays from the series (OHLCV with small random wicks).
        3. Run chaos module over pre-transition, transition, and post-transition.
        4. Check detect_bifurcation_proximity on the transition segment.
        5. Report whether each phase was correctly classified.

        Returns:
            StressTestResult with phase classifications and pass/fail.
        """
        prices = self.generate_bifurcation_price_series()
        chaos = ChaosRegimeModule(self._config)

        # Classify each phase
        pre_regime = await self._classify_segment(chaos, prices[:200])
        trans_regime = await self._classify_segment(chaos, prices[150:350])
        post_regime = await self._classify_segment(chaos, prices[300:])

        # Check bifurcation proximity on transition segment
        proximity, _ = detect_bifurcation_proximity(prices[150:350], order=3)

        # Evaluate correctness
        stable_regimes = {
            RegimeState.TRENDING_UP.value,
            RegimeState.TRENDING_DOWN.value,
            RegimeState.RANGING.value,
        }
        transition_regimes = {
            RegimeState.PRE_BIFURCATION.value,
            RegimeState.HIGH_CHAOS.value,
        }

        pre_detected = pre_regime in stable_regimes
        trans_detected = trans_regime in transition_regimes
        chaos_detected = post_regime == RegimeState.HIGH_CHAOS.value

        self._logger.info(
            "stress_test_complete",
            pre_regime=pre_regime,
            transition_regime=trans_regime,
            post_regime=post_regime,
            bifurcation_proximity=proximity,
            pre_detected=pre_detected,
            transition_detected=trans_detected,
            chaos_detected=chaos_detected,
        )

        return StressTestResult(
            pre_transition_regime=pre_regime,
            transition_regime=trans_regime,
            post_transition_regime=post_regime,
            pre_transition_detected=pre_detected,
            transition_detected=trans_detected,
            chaos_detected=chaos_detected,
            bifurcation_proximity_at_transition=proximity,
            passes=trans_detected and chaos_detected,
        )

    async def _classify_segment(
        self,
        chaos: ChaosRegimeModule,
        close_prices: np.ndarray,
    ) -> str:
        """Run chaos module on a price segment and return regime string.

        Builds synthetic bar_arrays and tick_arrays from close prices,
        then calls the chaos module update.

        Args:
            chaos: ChaosRegimeModule instance.
            close_prices: 1D array of close prices for this segment.

        Returns:
            RegimeState.value string.
        """
        n = len(close_prices)
        rng = np.random.default_rng(0)

        # Build M5 bars by grouping every 5 M1 bars
        m5_n = n // 5
        if m5_n < 10:
            return RegimeState.RANGING.value

        m5_close = close_prices[:m5_n * 5].reshape(-1, 5)[:, -1]
        m5_open = close_prices[:m5_n * 5].reshape(-1, 5)[:, 0]
        m5_high = close_prices[:m5_n * 5].reshape(-1, 5).max(axis=1)
        m5_low = close_prices[:m5_n * 5].reshape(-1, 5).min(axis=1)
        m5_time = np.arange(m5_n, dtype=np.float64) * 300 + 1000000
        m5_vol = rng.integers(100, 500, m5_n).astype(np.float64)

        bar_arrays = {
            "M5": {
                "close": m5_close,
                "open": m5_open,
                "high": m5_high,
                "low": m5_low,
                "time": m5_time,
                "tick_volume": m5_vol,
            },
        }

        tick_arrays = {
            "time_msc": (m5_time * 1000).astype(np.int64),
            "bid": m5_close,
            "ask": m5_close + 0.03,
            "last": m5_close,
            "spread": np.full_like(m5_close, 3.0),
            "volume_real": m5_vol,
        }

        try:
            signal: SignalOutput = await chaos.update(tick_arrays, bar_arrays, None)
            return (
                signal.regime.value
                if signal.regime is not None
                else RegimeState.RANGING.value
            )
        except Exception:
            return RegimeState.RANGING.value
