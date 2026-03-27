"""Tests for DEAP-based GA EvolutionManager per D-14/D-15/D-16.

Tests cover:
- Population creation and sizing
- Phase-aware fitness (profit factor, Sharpe, Sharpe - DD penalty)
- Parameter bounds enforcement
- GA does NOT include module internal params
- Generation execution
- Individual-to-params conversion
- State serialization/deserialization
"""

from __future__ import annotations

import math

import pytest

from fxsoqqabot.config.models import LearningConfig
from fxsoqqabot.learning.evolution import (
    EvolutionManager,
    PARAM_BOUNDS,
    PARAM_NAMES,
)


@pytest.fixture
def config() -> LearningConfig:
    """Small population config for fast tests."""
    return LearningConfig(
        ga_population_size=5,
        ga_crossover_prob=0.5,
        ga_mutation_prob=0.2,
        ga_tournament_size=3,
    )


@pytest.fixture
def manager(config: LearningConfig) -> EvolutionManager:
    return EvolutionManager(config)


def _make_trades(
    pnl_values: list[float],
    regime: str = "trending_up",
    chaos_conf: float = 0.6,
    flow_conf: float = 0.7,
    timing_conf: float = 0.5,
) -> list[dict]:
    """Create mock trade dicts with given P&L values."""
    trades = []
    for i, pnl in enumerate(pnl_values):
        trades.append({
            "trade_id": i + 1,
            "pnl": pnl,
            "regime": regime,
            "chaos_confidence": chaos_conf,
            "flow_confidence": flow_conf,
            "timing_confidence": timing_conf,
        })
    return trades


class TestPopulationCreation:
    """Test 1: Population is created with correct size."""

    def test_population_size_matches_config(self, manager: EvolutionManager) -> None:
        pop = manager._population
        assert len(pop) == 5

    def test_individual_has_correct_number_of_genes(
        self, manager: EvolutionManager
    ) -> None:
        individual = manager._population[0]
        assert len(individual) == len(PARAM_NAMES)

    def test_individuals_have_fitness_attribute(
        self, manager: EvolutionManager
    ) -> None:
        individual = manager._population[0]
        assert hasattr(individual, "fitness")


class TestPhaseAwareFitness:
    """Tests 2-5: Phase-aware fitness per D-14."""

    def test_aggressive_phase_uses_profit_factor(
        self, manager: EvolutionManager
    ) -> None:
        """Test 2: equity < 100 => profit_factor fitness."""
        trades = _make_trades([10.0, 5.0, -3.0, 8.0, -2.0])
        individual = manager._population[0]
        result = manager._phase_aware_fitness(individual, trades, equity=50.0)
        # profit_factor = sum(wins) / abs(sum(losses)) = 23 / 5 = 4.6
        assert isinstance(result, tuple)
        assert len(result) == 1
        expected_pf = (10.0 + 5.0 + 8.0) / abs(-3.0 + -2.0)
        assert abs(result[0] - expected_pf) < 0.01

    def test_selective_phase_uses_sharpe(
        self, manager: EvolutionManager
    ) -> None:
        """Test 3: 100 <= equity < 300 => sharpe_ratio fitness."""
        trades = _make_trades([10.0, 5.0, -3.0, 8.0, -2.0])
        individual = manager._population[0]
        result = manager._phase_aware_fitness(individual, trades, equity=150.0)
        assert isinstance(result, tuple)
        assert len(result) == 1
        # Should be sharpe_ratio (annualized)
        pnl_list = [10.0, 5.0, -3.0, 8.0, -2.0]
        mean_pnl = sum(pnl_list) / len(pnl_list)
        import statistics
        std_pnl = statistics.stdev(pnl_list)
        expected_sharpe = (mean_pnl / std_pnl) * math.sqrt(252)
        assert abs(result[0] - expected_sharpe) < 0.01

    def test_conservative_phase_uses_sharpe_minus_dd(
        self, manager: EvolutionManager
    ) -> None:
        """Test 4: equity >= 300 => sharpe - dd_penalty fitness."""
        trades = _make_trades([10.0, 5.0, -3.0, 8.0, -2.0])
        individual = manager._population[0]
        result = manager._phase_aware_fitness(individual, trades, equity=500.0)
        assert isinstance(result, tuple)
        assert len(result) == 1
        # Should be sharpe_ratio - max_drawdown_penalty
        # Result should be less than sharpe alone
        sharpe_result = manager._phase_aware_fitness(individual, trades, equity=150.0)
        assert result[0] <= sharpe_result[0]

    def test_fitness_always_returns_tuple(
        self, manager: EvolutionManager
    ) -> None:
        """Test 5: DEAP requires fitness as tuple (Pitfall 8)."""
        trades = _make_trades([1.0, -1.0])
        individual = manager._population[0]
        for equity in [20.0, 150.0, 500.0]:
            result = manager._phase_aware_fitness(individual, trades, equity=equity)
            assert isinstance(result, tuple)
            assert len(result) == 1
            assert isinstance(result[0], (int, float))

    def test_profit_factor_no_losses(
        self, manager: EvolutionManager
    ) -> None:
        """Profit factor capped at 10.0 when no losses."""
        trades = _make_trades([10.0, 5.0, 8.0])
        individual = manager._population[0]
        result = manager._phase_aware_fitness(individual, trades, equity=50.0)
        assert result[0] == 10.0

    def test_profit_factor_no_wins(
        self, manager: EvolutionManager
    ) -> None:
        """Profit factor is 0.0 when no wins."""
        trades = _make_trades([-5.0, -3.0, -8.0])
        individual = manager._population[0]
        result = manager._phase_aware_fitness(individual, trades, equity=50.0)
        assert result[0] == 0.0


class TestRunGeneration:
    """Test 6: run_generation produces offspring."""

    def test_run_generation_returns_dict(
        self, manager: EvolutionManager
    ) -> None:
        trades = _make_trades([10.0, 5.0, -3.0, 8.0, -2.0])
        result = manager.run_generation(trades, equity=50.0)
        assert isinstance(result, dict)
        assert "generation" in result
        assert "best_fitness" in result
        assert "best_params" in result

    def test_generation_increments(
        self, manager: EvolutionManager
    ) -> None:
        trades = _make_trades([10.0, 5.0, -3.0])
        r1 = manager.run_generation(trades, equity=50.0)
        r2 = manager.run_generation(trades, equity=50.0)
        assert r2["generation"] == r1["generation"] + 1

    def test_population_size_preserved_after_generation(
        self, manager: EvolutionManager
    ) -> None:
        trades = _make_trades([10.0, 5.0, -3.0])
        manager.run_generation(trades, equity=50.0)
        assert len(manager._population) == 5


class TestParameterBounds:
    """Test 7: Parameters stay within PARAM_BOUNDS after mutation."""

    def test_all_individuals_within_bounds(
        self, manager: EvolutionManager
    ) -> None:
        trades = _make_trades([10.0, 5.0, -3.0, 8.0, -2.0])
        # Run several generations to trigger mutations
        for _ in range(5):
            manager.run_generation(trades, equity=50.0)

        for individual in manager._population:
            for i, param_name in enumerate(PARAM_NAMES):
                lo, hi = PARAM_BOUNDS[param_name]
                assert lo <= individual[i] <= hi, (
                    f"{param_name}: {individual[i]} not in [{lo}, {hi}]"
                )


class TestNoModuleInternals:
    """Test 8: GA does NOT include module internal params."""

    def test_no_hurst_window(self) -> None:
        assert "hurst_window" not in PARAM_BOUNDS
        assert "hurst_window" not in PARAM_NAMES

    def test_no_lyapunov_embedding(self) -> None:
        assert "lyapunov_embedding_dim" not in PARAM_BOUNDS
        assert "lyapunov_embedding" not in PARAM_NAMES

    def test_no_fractal_rmin(self) -> None:
        assert "fractal_rmin" not in PARAM_BOUNDS
        assert "fractal_rmin" not in PARAM_NAMES

    def test_only_strategy_params(self) -> None:
        """All params must be strategy-level, not module internals."""
        strategy_prefixes = (
            "aggressive", "selective", "conservative",
            "sl_", "trending", "ranging", "high_chaos",
            "weight_",
        )
        for name in PARAM_NAMES:
            assert any(name.startswith(p) for p in strategy_prefixes), (
                f"Unexpected param in GA: {name}"
            )


class TestGetBestIndividual:
    """Test 9: get_best_individual returns highest fitness."""

    def test_best_individual_after_generation(
        self, manager: EvolutionManager
    ) -> None:
        trades = _make_trades([10.0, 5.0, -3.0, 8.0, -2.0])
        manager.run_generation(trades, equity=50.0)
        best, fitness = manager.get_best_individual()
        assert isinstance(best, list)
        assert isinstance(fitness, float)
        # Best should have highest fitness in population
        for ind in manager._population:
            if ind.fitness.valid:
                assert fitness >= ind.fitness.values[0]


class TestIndividualToParams:
    """Test 10: individual_to_params maps param names to values."""

    def test_returns_dict_with_all_param_names(
        self, manager: EvolutionManager
    ) -> None:
        individual = manager._population[0]
        params = manager.individual_to_params(individual)
        assert isinstance(params, dict)
        assert set(params.keys()) == set(PARAM_NAMES)

    def test_values_match_individual(
        self, manager: EvolutionManager
    ) -> None:
        individual = manager._population[0]
        params = manager.individual_to_params(individual)
        for i, name in enumerate(PARAM_NAMES):
            assert params[name] == individual[i]


class TestStateSerialization:
    """State persistence for EvolutionManager."""

    def test_get_state_returns_dict(
        self, manager: EvolutionManager
    ) -> None:
        state = manager.get_state()
        assert isinstance(state, dict)
        assert "population" in state
        assert "generation" in state

    def test_load_state_restores(
        self, config: LearningConfig
    ) -> None:
        m1 = EvolutionManager(config)
        trades = _make_trades([10.0, -5.0])
        m1.run_generation(trades, equity=50.0)
        state = m1.get_state()

        m2 = EvolutionManager(config)
        m2.load_state(state)
        assert m2._generation == m1._generation
        assert len(m2._population) == len(m1._population)
