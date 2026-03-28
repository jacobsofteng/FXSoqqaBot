"""DEAP GA for signal weight seed evolution (Phase B).

Evolves the 3 co-dependent signal weight seeds (chaos/flow/timing) using
walk-forward aggregate profit factor as fitness. Runs after Optuna Phase A
with the best Optuna params frozen as baseline.

Reuses DEAP creator.FitnessMax and creator.Individual from learning/evolution.py
(already registered at module level with hasattr guard).
"""

from __future__ import annotations

import random

import structlog
from deap import algorithms, base, creator, tools

from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.backtest.engine import BacktestEngine
from fxsoqqabot.backtest.historical import HistoricalDataLoader
from fxsoqqabot.backtest.results import BacktestResult
from fxsoqqabot.config.models import BotSettings
from fxsoqqabot.learning.evolution import PARAM_BOUNDS
from fxsoqqabot.optimization.search_space import apply_params_to_settings

_logger = structlog.get_logger().bind(component="deap_weights")

# The 3 signal weight seeds evolved by DEAP
WEIGHT_NAMES: list[str] = [
    "weight_chaos_seed",
    "weight_flow_seed",
    "weight_timing_seed",
]

WEIGHT_BOUNDS: list[tuple[float, float]] = [
    PARAM_BOUNDS[name] for name in WEIGHT_NAMES
]

# Ensure DEAP creator types exist (hasattr guard matches evolution.py pattern)
if not hasattr(creator, "FitnessMax"):
    creator.create("FitnessMax", base.Fitness, weights=(1.0,))
if not hasattr(creator, "Individual"):
    creator.create("Individual", list, fitness=creator.FitnessMax)


def _create_weight_individual() -> list[float]:
    """Create a random individual with 3 weight seed genes."""
    return [random.uniform(lo, hi) for lo, hi in WEIGHT_BOUNDS]


def _clamp_individual(individual: list[float]) -> None:
    """Clamp each gene to its respective bounds."""
    for i, (lo, hi) in enumerate(WEIGHT_BOUNDS):
        individual[i] = max(lo, min(hi, individual[i]))


async def evolve_weights(
    base_settings: BotSettings,
    bt_config: BacktestConfig,
    n_generations: int = 10,
    population_size: int = 20,
    seed: int = 42,
) -> dict[str, float]:
    """Evolve signal weight seeds via DEAP GA with walk-forward fitness.

    Each individual is evaluated by running walk-forward validation with the
    weight seeds applied to base_settings (which already has frozen Optuna
    params). Fitness is the aggregate profit factor, capped at 10.0.

    Args:
        base_settings: BotSettings with best Optuna params already applied.
        bt_config: Backtest configuration for walk-forward validation.
        n_generations: Number of GA generations.
        population_size: GA population size.
        seed: Random seed for reproducibility.

    Returns:
        Dict mapping weight names to best evolved values.
    """
    random.seed(seed)

    # Create DEAP toolbox for 3-gene individuals
    toolbox = base.Toolbox()
    toolbox.register(
        "individual",
        tools.initIterate,
        creator.Individual,
        _create_weight_individual,
    )
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("mate", tools.cxBlend, alpha=0.5)
    toolbox.register(
        "mutate", tools.mutGaussian, mu=0, sigma=0.1, indpb=0.3,
    )
    toolbox.register("select", tools.selTournament, tournsize=3)

    # Create data loader once -- reused across all fitness evaluations
    loader = HistoricalDataLoader(bt_config)

    # Pre-compute the fast optimization window (same as optimizer.py _fast_backtest)
    data_start, data_end = loader.get_time_range()
    holdout_months_sec = bt_config.holdout_months * int(30.44 * 86400)
    holdout_start = data_end - holdout_months_sec
    opt_window_sec = 3 * int(30.44 * 86400)
    opt_start = max(holdout_start - opt_window_sec, data_start)
    opt_end = holdout_start
    opt_bars = loader.load_bars(opt_start, opt_end)

    async def _evaluate(individual: list[float]) -> float:
        """Evaluate fitness via fast 3-month backtest (same proxy as Optuna)."""
        params = dict(zip(WEIGHT_NAMES, individual))
        trial_settings = apply_params_to_settings(base_settings, params)
        if len(opt_bars) < 100:
            return 0.0
        engine = BacktestEngine(trial_settings, bt_config)
        result: BacktestResult = await engine.run(opt_bars, run_id="deap_fast")
        pf = min(result.profit_factor, 10.0)
        if result.n_trades < 5:
            pf *= 0.1
        return pf

    # Initialize population
    population = toolbox.population(n=population_size)

    # Evaluate initial population
    for ind in population:
        fitness_val = await _evaluate(ind)
        ind.fitness.values = (fitness_val,)

    _logger.info(
        "deap_weights_start",
        population_size=population_size,
        n_generations=n_generations,
    )

    # Evolution loop
    for gen in range(1, n_generations + 1):
        # Produce offspring
        offspring = algorithms.varAnd(
            population, toolbox, cxpb=0.5, mutpb=0.2,
        )

        # Clamp to bounds
        for ind in offspring:
            _clamp_individual(ind)

        # Evaluate individuals that need fitness
        invalid_ind = [ind for ind in offspring if not ind.fitness.valid]
        for ind in invalid_ind:
            fitness_val = await _evaluate(ind)
            ind.fitness.values = (fitness_val,)

        # Select next generation
        population = toolbox.select(
            offspring + population, k=population_size,
        )

        # Report progress
        best_ind = max(population, key=lambda ind: ind.fitness.values[0])
        best_fitness = best_ind.fitness.values[0]
        print(
            f"  DEAP Gen {gen}/{n_generations}: "
            f"best_fitness={best_fitness:.4f}"
        )

    # Extract best individual
    best = max(population, key=lambda ind: ind.fitness.values[0])
    best_weights = dict(zip(WEIGHT_NAMES, best))

    _logger.info(
        "deap_weights_complete",
        best_weights=best_weights,
        best_fitness=best.fitness.values[0],
    )

    return best_weights
