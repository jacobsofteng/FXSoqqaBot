"""DEAP-based genetic algorithm evolution engine per D-14/D-15/D-16.

Evolves strategy parameters (confidence thresholds, SL/TP multipliers,
risk-reward ratios, module weight seeds) using DEAP 1.4.x. Fitness is
phase-aware: profit factor for aggressive, Sharpe for selective,
Sharpe - drawdown penalty for conservative.

GA does NOT evolve module internals (Hurst window, Lyapunov embedding,
fractal parameters). Those are physics-level parameters fixed at research.
The GA tunes how the bot uses the module outputs.
"""

from __future__ import annotations

import math
import random
from typing import Any

import structlog
from deap import algorithms, base, creator, tools

from fxsoqqabot.config.models import LearningConfig

_logger = structlog.get_logger().bind(component="evolution")

# ---------------------------------------------------------------------------
# Parameter bounds: ONLY strategy-level parameters the GA evolves.
# Module internals (hurst_window, lyapunov_embedding_dim, fractal_rmin)
# are explicitly excluded per D-16.
# ---------------------------------------------------------------------------
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "aggressive_confidence_threshold": (0.3, 0.7),
    "selective_confidence_threshold": (0.4, 0.8),
    "conservative_confidence_threshold": (0.5, 0.9),
    "sl_atr_base_multiplier": (1.0, 4.0),
    "trending_rr_ratio": (1.5, 5.0),
    "ranging_rr_ratio": (1.0, 3.0),
    "high_chaos_size_reduction": (0.2, 0.8),
    "weight_chaos_seed": (0.1, 0.5),
    "weight_flow_seed": (0.1, 0.5),
    "weight_timing_seed": (0.1, 0.5),
}
PARAM_NAMES: list[str] = list(PARAM_BOUNDS.keys())

# ---------------------------------------------------------------------------
# Module-level DEAP creator setup (must be at module level, not inside
# __init__, per DEAP best practices -- Pitfall 8).
# ---------------------------------------------------------------------------
if not hasattr(creator, "FitnessMax"):
    creator.create("FitnessMax", base.Fitness, weights=(1.0,))
if not hasattr(creator, "Individual"):
    creator.create("Individual", list, fitness=creator.FitnessMax)


def _create_random_individual() -> list[float]:
    """Create a random individual with each gene within its PARAM_BOUNDS."""
    return [
        random.uniform(lo, hi) for lo, hi in PARAM_BOUNDS.values()
    ]


def _compute_profit_factor(trades: list[dict]) -> float:
    """Compute profit factor: sum(wins) / abs(sum(losses)).

    Returns:
        Profit factor capped at 10.0. Returns 0.0 if no wins.
    """
    wins = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    losses = sum(t["pnl"] for t in trades if t["pnl"] < 0)

    if wins == 0:
        return 0.0
    if losses == 0:
        return 10.0  # Cap to avoid infinity

    return min(wins / abs(losses), 10.0)


def _compute_sharpe_ratio(trades: list[dict]) -> float:
    """Compute annualized Sharpe ratio: mean(pnl) / std(pnl) * sqrt(252).

    Returns:
        Annualized Sharpe ratio. Returns 0.0 if std is zero or < 2 trades.
    """
    if len(trades) < 2:
        return 0.0

    pnl_values = [t["pnl"] for t in trades]
    mean_pnl = sum(pnl_values) / len(pnl_values)

    variance = sum((p - mean_pnl) ** 2 for p in pnl_values) / (len(pnl_values) - 1)
    std_pnl = math.sqrt(variance)

    if std_pnl == 0:
        return 0.0

    return (mean_pnl / std_pnl) * math.sqrt(252)


def _compute_max_drawdown_penalty(trades: list[dict]) -> float:
    """Compute max peak-to-trough equity drawdown as fraction.

    Simulates equity curve from trade P&L sequence and computes
    the maximum drawdown as a positive penalty value.
    """
    if not trades:
        return 0.0

    equity = 0.0
    peak = 0.0
    max_dd = 0.0

    for t in trades:
        equity += t["pnl"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    # Normalize by peak (avoid division by zero)
    if peak > 0:
        return max_dd / peak
    return 0.0


class EvolutionManager:
    """DEAP-based GA evolution manager per D-14/D-15/D-16.

    Evolves strategy parameters using genetic algorithms with phase-aware
    fitness evaluation. Population is managed through DEAP's toolbox
    with tournament selection, blend crossover, and Gaussian mutation.

    Args:
        config: LearningConfig with GA hyperparameters.
    """

    def __init__(self, config: LearningConfig) -> None:
        self._config = config
        self._generation: int = 0

        # Create DEAP toolbox
        self._toolbox = base.Toolbox()
        self._toolbox.register(
            "individual",
            tools.initIterate,
            creator.Individual,
            _create_random_individual,
        )
        self._toolbox.register(
            "population", tools.initRepeat, list, self._toolbox.individual
        )
        self._toolbox.register("mate", tools.cxBlend, alpha=0.5)
        self._toolbox.register(
            "mutate", tools.mutGaussian, mu=0, sigma=0.1, indpb=0.2
        )
        self._toolbox.register(
            "select", tools.selTournament, tournsize=config.ga_tournament_size
        )

        # Initialize population
        self._population = self._toolbox.population(n=config.ga_population_size)

        _logger.info(
            "evolution_manager_initialized",
            population_size=config.ga_population_size,
            num_params=len(PARAM_NAMES),
            params=PARAM_NAMES,
        )

    def _clamp_individual(self, individual: list) -> None:
        """Clamp each gene to its PARAM_BOUNDS after mutation."""
        for i, param_name in enumerate(PARAM_NAMES):
            lo, hi = PARAM_BOUNDS[param_name]
            individual[i] = max(lo, min(hi, individual[i]))

    def _phase_aware_fitness(
        self,
        individual: list,
        trades: list[dict],
        equity: float,
    ) -> tuple[float]:
        """Compute fitness using phase-aware strategy per D-14.

        - Aggressive (equity < 100): profit factor
        - Selective (100 <= equity < 300): Sharpe ratio
        - Conservative (equity >= 300): Sharpe - drawdown penalty

        Args:
            individual: DEAP individual (list of floats).
            trades: List of trade dicts with "pnl" field.
            equity: Current account equity.

        Returns:
            Single-element tuple of fitness value (DEAP requirement).
        """
        if equity < 100:
            return (_compute_profit_factor(trades),)
        elif equity < 300:
            return (_compute_sharpe_ratio(trades),)
        else:
            sharpe = _compute_sharpe_ratio(trades)
            dd_penalty = _compute_max_drawdown_penalty(trades)
            return (sharpe - dd_penalty,)

    def run_generation(
        self, trades: list[dict], equity: float
    ) -> dict[str, Any]:
        """Run one generation of the GA.

        Uses DEAP's varAnd to produce offspring, evaluates fitness,
        clamps to bounds, selects next generation.

        Args:
            trades: List of trade dicts with "pnl" field.
            equity: Current account equity.

        Returns:
            Dict with generation number, best fitness, best params.
        """
        # Produce offspring via crossover and mutation
        offspring = algorithms.varAnd(
            self._population,
            self._toolbox,
            cxpb=self._config.ga_crossover_prob,
            mutpb=self._config.ga_mutation_prob,
        )

        # Clamp offspring to bounds
        for ind in offspring:
            self._clamp_individual(ind)

        # Evaluate fitness for individuals that need it
        invalid_ind = [ind for ind in offspring if not ind.fitness.valid]
        for ind in invalid_ind:
            ind.fitness.values = self._phase_aware_fitness(ind, trades, equity)

        # Also evaluate any population members without fitness
        for ind in self._population:
            if not ind.fitness.valid:
                ind.fitness.values = self._phase_aware_fitness(
                    ind, trades, equity
                )

        # Select next generation from combined pool
        self._population = self._toolbox.select(
            offspring + self._population, k=len(self._population)
        )

        self._generation += 1

        # Get best individual
        best, best_fitness = self.get_best_individual()
        best_params = self.individual_to_params(best)

        _logger.info(
            "generation_complete",
            generation=self._generation,
            best_fitness=best_fitness,
            best_params=best_params,
        )

        return {
            "generation": self._generation,
            "best_fitness": best_fitness,
            "best_params": best_params,
        }

    def individual_to_params(self, individual: list) -> dict[str, float]:
        """Convert a DEAP individual to a named parameter dict.

        Args:
            individual: DEAP individual (list of floats).

        Returns:
            Dict mapping parameter names to their values.
        """
        return dict(zip(PARAM_NAMES, individual))

    def get_best_individual(self) -> tuple[list[float], float]:
        """Return the individual with highest fitness.

        Returns:
            Tuple of (individual values, fitness value).
        """
        best = max(
            (ind for ind in self._population if ind.fitness.valid),
            key=lambda ind: ind.fitness.values[0],
            default=None,
        )
        if best is None:
            return list(self._population[0]), 0.0
        return list(best), best.fitness.values[0]

    def get_state(self) -> dict[str, Any]:
        """Serialize population and generation for persistence.

        Returns:
            Dict with population (as list of lists) and generation count.
        """
        return {
            "population": [list(ind) for ind in self._population],
            "generation": self._generation,
        }

    def load_state(self, state: dict[str, Any]) -> None:
        """Restore from serialized state.

        Args:
            state: Dict from get_state().
        """
        self._generation = state["generation"]
        self._population = []
        for genes in state["population"]:
            ind = creator.Individual(genes)
            self._population.append(ind)

        _logger.info(
            "state_restored",
            generation=self._generation,
            population_size=len(self._population),
        )
