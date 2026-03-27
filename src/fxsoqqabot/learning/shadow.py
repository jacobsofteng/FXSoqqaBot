"""Shadow mode variant management per D-17/D-18/LEARN-04/LEARN-06.

Runs 3-5 mutated strategy variants in paper mode alongside the live strategy.
Each variant gets its own PaperExecutor instance -- no shared state.
Promotion requires Mann-Whitney U statistical significance (p < 0.05) over
50+ virtual trades plus walk-forward validation (called externally by the
engine integration layer).

Key behaviors:
- Each ShadowVariant has independent PaperExecutor and mutated params
- Mutations are Gaussian perturbations of strategy params within PARAM_BOUNDS
- Promotion evaluation uses non-parametric Mann-Whitney U test (not t-test)
- Variant lifecycle: create -> trade -> evaluate -> promote/reset
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from scipy import stats
import structlog

from fxsoqqabot.config.models import LearningConfig
from fxsoqqabot.execution.paper import PaperExecutor
from fxsoqqabot.learning.evolution import PARAM_BOUNDS, PARAM_NAMES

logger = structlog.get_logger().bind(component="shadow")


@dataclass
class ShadowVariant:
    """A shadow strategy variant running in paper mode.

    NOT frozen -- needs mutable state for trade tracking.
    Each variant has its own PaperExecutor to prevent state contamination.
    """

    variant_id: str
    mutated_params: dict[str, float]
    paper_executor: PaperExecutor
    trade_results: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def trade_count(self) -> int:
        """Number of trades this variant has executed."""
        return len(self.trade_results)

    @property
    def fitness_score(self) -> float:
        """Win rate as a simple fitness metric.

        Returns fraction of trades with positive P&L.
        """
        if not self.trade_results:
            return 0.0
        pnls = [t.get("pnl", 0.0) for t in self.trade_results if t.get("pnl") is not None]
        if not pnls:
            return 0.0
        wins = sum(1 for p in pnls if p > 0)
        return wins / len(pnls) if pnls else 0.0


class ShadowManager:
    """Shadow mode variant lifecycle manager per D-17/D-18/LEARN-04.

    Creates and manages shadow variants that run mutated strategies in
    paper mode. Evaluates whether a variant statistically outperforms
    the live strategy using Mann-Whitney U test before promotion.

    Args:
        config: LearningConfig with shadow variant settings.
        starting_balance: Starting balance for each variant's PaperExecutor.
    """

    def __init__(
        self,
        config: LearningConfig,
        starting_balance: float = 20.0,
    ) -> None:
        self._config = config
        self._starting_balance = starting_balance
        self._variants: list[ShadowVariant] = []

        # Create initial variants, each with its own PaperExecutor
        for i in range(config.n_shadow_variants):
            variant = ShadowVariant(
                variant_id=f"shadow_{i}",
                mutated_params=self._generate_mutations(),
                paper_executor=PaperExecutor(starting_balance=starting_balance),
            )
            self._variants.append(variant)

        logger.info(
            "shadow_manager_initialized",
            n_variants=config.n_shadow_variants,
            starting_balance=starting_balance,
        )

    def _generate_mutations(self) -> dict[str, float]:
        """Generate mutated parameters within PARAM_BOUNDS.

        For each parameter, takes the center of its bounds as the base
        value and applies Gaussian perturbation (sigma = 0.1 * range),
        then clamps to bounds.

        Returns:
            Dict mapping parameter names to mutated float values.
        """
        mutations: dict[str, float] = {}

        for param_name in PARAM_NAMES:
            lo, hi = PARAM_BOUNDS[param_name]
            center = (lo + hi) / 2.0
            spread = hi - lo
            sigma = 0.1 * spread

            # Gaussian perturbation from center, clamped to bounds
            value = random.gauss(center, sigma)
            value = max(lo, min(hi, value))
            mutations[param_name] = value

        return mutations

    def record_variant_trade(self, variant_id: str, trade_result: dict) -> None:
        """Record a trade result for a specific variant.

        Args:
            variant_id: The variant identifier (e.g. "shadow_0").
            trade_result: Dict with at least a "pnl" key.
        """
        for variant in self._variants:
            if variant.variant_id == variant_id:
                variant.trade_results.append(trade_result)
                return

        logger.warning("variant_not_found", variant_id=variant_id)

    def evaluate_promotion(
        self,
        variant: ShadowVariant,
        live_trades: list[dict],
        equity: float,
    ) -> dict[str, Any]:
        """Evaluate whether a variant should be promoted to live.

        Uses Mann-Whitney U test (non-parametric, per research recommendation)
        to determine if the variant's P&L distribution is statistically
        significantly better than the live strategy's.

        Args:
            variant: The ShadowVariant to evaluate.
            live_trades: List of live trade dicts with "pnl" keys.
            equity: Current account equity.

        Returns:
            Dict with should_promote, p_value, variant_fitness,
            live_fitness, and reason fields.
        """
        # Step 1: Check minimum trade count
        if variant.trade_count < self._config.min_promotion_trades:
            return {
                "should_promote": False,
                "p_value": 1.0,
                "variant_fitness": variant.fitness_score,
                "live_fitness": 0.0,
                "reason": f"Insufficient trades: {variant.trade_count} < {self._config.min_promotion_trades}",
            }

        # Step 2: Extract P&L distributions
        variant_pnls = [
            t.get("pnl", 0.0)
            for t in variant.trade_results
            if t.get("pnl") is not None
        ]
        live_pnls = [
            t.get("pnl", 0.0)
            for t in live_trades
            if t.get("pnl") is not None
        ]

        if not live_pnls:
            return {
                "should_promote": False,
                "p_value": 1.0,
                "variant_fitness": variant.fitness_score,
                "live_fitness": 0.0,
                "reason": "No live trades for comparison",
            }

        # Step 3: Mann-Whitney U test (variant > live, one-sided)
        try:
            stat, p_value = stats.mannwhitneyu(
                variant_pnls, live_pnls, alternative="greater"
            )
        except ValueError:
            # All values identical or other edge case
            return {
                "should_promote": False,
                "p_value": 1.0,
                "variant_fitness": variant.fitness_score,
                "live_fitness": 0.0,
                "reason": "Mann-Whitney U test failed (identical distributions?)",
            }

        # Compute simple live fitness for comparison
        live_wins = sum(1 for p in live_pnls if p > 0)
        live_fitness = live_wins / len(live_pnls) if live_pnls else 0.0

        # Step 4: Check significance
        if p_value >= self._config.promotion_alpha:
            return {
                "should_promote": False,
                "p_value": float(p_value),
                "variant_fitness": variant.fitness_score,
                "live_fitness": live_fitness,
                "reason": f"p={p_value:.4f} >= {self._config.promotion_alpha}",
            }

        # Step 5: Statistically significant improvement
        logger.info(
            "variant_promotion_candidate",
            variant_id=variant.variant_id,
            p_value=float(p_value),
            variant_fitness=variant.fitness_score,
            live_fitness=live_fitness,
        )

        return {
            "should_promote": True,
            "p_value": float(p_value),
            "variant_fitness": variant.fitness_score,
            "live_fitness": live_fitness,
            "reason": f"Statistically significant improvement (p={p_value:.4f})",
        }

    def promote_variant(self, variant_id: str) -> dict[str, float]:
        """Promote a variant: return its params and reset it.

        Gets the variant's mutated_params (to apply to live strategy),
        then resets the variant with new mutations and a fresh PaperExecutor.

        Args:
            variant_id: The variant to promote.

        Returns:
            The promoted variant's parameter dict.
        """
        for i, variant in enumerate(self._variants):
            if variant.variant_id == variant_id:
                promoted_params = dict(variant.mutated_params)

                logger.info(
                    "variant_promoted",
                    variant_id=variant_id,
                    params=promoted_params,
                )

                # Reset the variant with new mutations and fresh executor
                self._variants[i] = ShadowVariant(
                    variant_id=variant_id,
                    mutated_params=self._generate_mutations(),
                    paper_executor=PaperExecutor(
                        starting_balance=self._starting_balance
                    ),
                )

                return promoted_params

        logger.error("promote_variant_not_found", variant_id=variant_id)
        return {}

    def reset_variant(self, variant_id: str) -> None:
        """Reset a variant with new mutations and fresh PaperExecutor.

        Args:
            variant_id: The variant to reset.
        """
        for i, variant in enumerate(self._variants):
            if variant.variant_id == variant_id:
                self._variants[i] = ShadowVariant(
                    variant_id=variant_id,
                    mutated_params=self._generate_mutations(),
                    paper_executor=PaperExecutor(
                        starting_balance=self._starting_balance
                    ),
                )
                logger.info("variant_reset", variant_id=variant_id)
                return

        logger.warning("reset_variant_not_found", variant_id=variant_id)

    def get_variant_status(self) -> list[dict[str, Any]]:
        """Get status of all variants.

        Returns:
            List of dicts with variant_id, trade_count, fitness_score,
            age (seconds since creation), and mutated_params.
        """
        now = datetime.now(UTC)
        return [
            {
                "variant_id": v.variant_id,
                "trade_count": v.trade_count,
                "fitness_score": v.fitness_score,
                "age": (now - v.created_at).total_seconds(),
                "mutated_params": dict(v.mutated_params),
            }
            for v in self._variants
        ]

    def get_variants(self) -> list[ShadowVariant]:
        """Return the list of shadow variants.

        Returns:
            List of ShadowVariant instances.
        """
        return list(self._variants)
