"""Learning loop manager orchestrating all learning sub-components.

Coordinates evolution (GA), shadow variant management, regime classification,
rule retirement tracking, and signal combination analysis into a unified
learning pipeline. Triggered by trade close events.

Key behaviors:
- Evolution runs in thread after N trades (DEAP is blocking per Pattern 3)
- Shadow variants evaluated for promotion after each trade
- Classifier retrains periodically (every 100 trades)
- Retirement tracker monitors rule EMA scores
- All blocking ML/GA work runs via asyncio.to_thread
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import structlog

from fxsoqqabot.config.models import LearningConfig
from fxsoqqabot.learning.analyzer import SignalAnalyzer
from fxsoqqabot.learning.classifier import RegimeClassifier
from fxsoqqabot.learning.evolution import PARAM_NAMES, EvolutionManager
from fxsoqqabot.learning.retirement import RuleRetirementTracker
from fxsoqqabot.learning.shadow import ShadowManager
from fxsoqqabot.learning.trade_logger import TradeContextLogger

logger = structlog.get_logger().bind(component="learning_loop")


class LearningLoopManager:
    """Orchestrates all learning sub-components per D-14 through D-20.

    Coordinates evolution, shadow variants, regime classification,
    rule retirement, and signal analysis into a cohesive learning loop.
    Triggered by on_trade_closed() from the TradingEngine.

    Args:
        config: LearningConfig with all learning hyperparameters.
        trade_logger: TradeContextLogger for querying trade history.
        equity: Starting equity for shadow variant PaperExecutors.
    """

    def __init__(
        self,
        config: LearningConfig,
        trade_logger: TradeContextLogger,
        equity: float = 20.0,
    ) -> None:
        self._config = config
        self._trade_logger = trade_logger
        self._current_equity = equity

        # Sub-components
        self._evolution = EvolutionManager(config)
        self._shadow = ShadowManager(config, starting_balance=equity)
        self._classifier = RegimeClassifier()
        self._retirement = RuleRetirementTracker(
            rule_names=PARAM_NAMES,
            alpha=0.1,
            min_trades=config.retirement_min_trades,
            retirement_threshold=config.retirement_threshold,
        )
        self._analyzer = SignalAnalyzer()

        # Counters
        self._trades_since_evolve: int = 0
        self._trades_since_retrain: int = 0
        self._total_trades: int = 0

        # Walk-forward validation gate for variant promotion (LEARN-06)
        # Callable that takes variant params and returns bool (pass/fail)
        # Injected by engine or set to None for statistical-only mode
        self._walk_forward_validator: Callable[[dict[str, float]], bool] | None = None

        # Promote callback to apply promoted params to live engine (LEARN-05)
        # Callable that takes param dict and applies to live strategy
        self._promote_callback: Callable[[dict[str, float]], None] | None = None

        # Mutation event log for TUI display
        self._last_mutation_events: list[dict] = []

        logger.info(
            "learning_loop_initialized",
            evolve_every=config.evolve_every_n_trades,
            n_shadow_variants=config.n_shadow_variants,
        )

    def set_walk_forward_validator(
        self, validator: Callable[[dict[str, float]], bool]
    ) -> None:
        """Set the walk-forward validation callback for LEARN-06.

        The callback receives a dict of variant params (param_name -> value)
        and returns True if walk-forward validation passes, False otherwise.
        Called only when a variant passes the Mann-Whitney statistical gate.

        Args:
            validator: Callable that takes param dict and returns bool.
        """
        self._walk_forward_validator = validator
        logger.info("walk_forward_validator_set")

    def set_promote_callback(
        self, callback: Callable[[dict[str, float]], None]
    ) -> None:
        """Set callback to apply promoted params to live strategy.

        Called when a variant passes both statistical and walk-forward gates.
        The callback receives the promoted parameter dict and should apply
        it to the live trading engine's settings.

        Args:
            callback: Callable that takes param dict and applies to engine.
        """
        self._promote_callback = callback
        logger.info("promote_callback_set")

    async def on_trade_closed(self, trade_result: dict) -> list[dict]:
        """Main entry point called when a live trade closes.

        Increments counters, records outcomes, triggers evolution at
        threshold, retrains classifier periodically, and checks shadow
        variant promotions.

        Args:
            trade_result: Dict with at least "pnl" and "equity" keys.

        Returns:
            List of mutation event dicts (for TUI display).
        """
        # 1. Increment counters
        self._total_trades += 1
        self._trades_since_evolve += 1
        self._trades_since_retrain += 1

        # 2. Update equity from trade result
        if "equity" in trade_result:
            self._current_equity = trade_result["equity"]

        # 3. Record outcome for retirement tracker
        pnl = trade_result.get("pnl", 0.0)
        success = pnl > 0
        active_rules = self._retirement.get_active_rules()
        for rule_name in active_rules:
            self._retirement.record_outcome(rule_name, success)

        # 4. Check evolution trigger
        if self._trades_since_evolve >= self._config.evolve_every_n_trades:
            await asyncio.to_thread(self._run_evolution)
            self._trades_since_evolve = 0

        # 5. Check classifier retrain trigger (every 100 trades)
        if self._trades_since_retrain >= 100:
            await asyncio.to_thread(self._retrain_classifier)
            self._trades_since_retrain = 0

        # 6. Check shadow variant promotions
        mutations = self._check_promotions()

        return mutations

    def _run_evolution(self) -> None:
        """Run one generation of the GA. Blocking -- runs in thread.

        Queries recent trades from trade_logger, runs DEAP evolution
        generation, and logs results.
        """
        trades = self._trade_logger.query_trades(limit=200)
        result = self._evolution.run_generation(trades, self._current_equity)

        logger.info(
            "evolution_generation_complete",
            generation=result["generation"],
            best_fitness=result["best_fitness"],
        )

    def _retrain_classifier(self) -> None:
        """Retrain the regime classifier. Blocking -- runs in thread.

        Queries all available trades and retrains the RandomForest
        classifier on the accumulated data.
        """
        trades = self._trade_logger.query_trades(limit=1000)
        result = self._classifier.train(trades)

        logger.info(
            "classifier_retrained",
            is_trained=result.get("is_trained", False),
            accuracy=result.get("cv_accuracy", 0.0),
        )

    def _check_promotions(self) -> list[dict]:
        """Evaluate each shadow variant for promotion to live.

        For each variant, runs Mann-Whitney U evaluation against live
        trades. If statistically significant, applies walk-forward
        validation gate (LEARN-06) before promoting. Both gates must
        pass for promotion.

        Returns:
            List of mutation event dicts for tracking/display.
        """
        mutations: list[dict] = []
        live_trades = self._trade_logger.query_trades(limit=200)
        variants = self._shadow.get_variants()

        for variant in variants:
            eval_result = self._shadow.evaluate_promotion(
                variant, live_trades, self._current_equity
            )

            if eval_result.get("should_promote", False):
                # LEARN-06: Walk-forward validation gate
                wf_pass = True  # Default if no validator
                if self._walk_forward_validator is not None:
                    try:
                        wf_pass = self._walk_forward_validator(
                            variant.mutated_params
                        )
                        logger.info(
                            "walk_forward_gate_result",
                            variant_id=variant.variant_id,
                            walk_forward_pass=wf_pass,
                        )
                    except Exception:
                        logger.error(
                            "walk_forward_gate_error",
                            variant_id=variant.variant_id,
                            exc_info=True,
                        )
                        wf_pass = False  # Fail-safe: reject on error
                else:
                    logger.warning(
                        "walk_forward_validator_not_set",
                        variant_id=variant.variant_id,
                        msg="Promoting on statistical significance only -- LEARN-06 gate inactive",
                    )

                if not wf_pass:
                    logger.info(
                        "variant_promotion_rejected_walk_forward",
                        variant_id=variant.variant_id,
                        p_value=eval_result.get("p_value"),
                    )
                    # Reset variant since it passed stats but failed walk-forward
                    self._shadow.reset_variant(variant.variant_id)
                    continue

                # Both gates passed -- promote
                promoted_params = self._shadow.promote_variant(
                    variant.variant_id
                )

                # LEARN-05: Apply promoted params to live engine
                if self._promote_callback is not None:
                    try:
                        self._promote_callback(promoted_params)
                    except Exception:
                        logger.error(
                            "promote_callback_error",
                            variant_id=variant.variant_id,
                            exc_info=True,
                        )

                mutation_event = {
                    "mutation": True,
                    "param": "multiple",
                    "old": "live_params",
                    "new": str(promoted_params),
                    "reason": f"variant promoted p={eval_result.get('p_value', 0.0):.4f}, walk-forward={'pass' if wf_pass else 'fail'}",
                }
                mutations.append(mutation_event)
                self._last_mutation_events.append(mutation_event)

                logger.info(
                    "variant_promoted_to_live",
                    variant_id=variant.variant_id,
                    p_value=eval_result.get("p_value"),
                    walk_forward_pass=wf_pass,
                )

        return mutations

    def get_learning_status(self) -> dict[str, Any]:
        """Return comprehensive status of all learning sub-components.

        Returns:
            Dict with total_trades, trades_until_evolve,
            evolution_generation, shadow_variants, classifier_trained,
            rule_status, analysis, and recent_mutations.
        """
        analysis: dict = {}
        if self._total_trades > 0:
            recent = self._trade_logger.get_recent_trades(200)
            analysis = self._analyzer.get_summary(recent)

        return {
            "total_trades": self._total_trades,
            "trades_until_evolve": (
                self._config.evolve_every_n_trades - self._trades_since_evolve
            ),
            "evolution_generation": self._evolution._generation,
            "shadow_variants": self._shadow.get_variant_status(),
            "classifier_trained": self._classifier.is_trained,
            "rule_status": self._retirement.get_rule_status(),
            "analysis": analysis,
            "recent_mutations": self._last_mutation_events[-10:],
        }

    def get_shadow_manager(self) -> ShadowManager:
        """Return shadow manager for variant access.

        Returns:
            The ShadowManager instance.
        """
        return self._shadow

    def get_retirement_tracker(self) -> RuleRetirementTracker:
        """Return retirement tracker for status queries.

        Returns:
            The RuleRetirementTracker instance.
        """
        return self._retirement
