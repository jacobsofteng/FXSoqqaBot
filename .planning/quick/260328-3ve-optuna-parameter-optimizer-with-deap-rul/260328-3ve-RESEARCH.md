# Quick Task: Optuna Parameter Optimizer with DEAP Rule Evolution - Research

**Researched:** 2026-03-28
**Domain:** Hyperparameter optimization (Optuna TPE + DEAP GA) for trading strategy validation
**Confidence:** HIGH

## Summary

The optimizer CLI (`python -m fxsoqqabot optimize`) needs to bridge three existing systems: (1) BacktestEngine which is async and runs walk-forward windows, (2) WalkForwardValidator which evaluates parameter sets via rolling windows + OOS + Monte Carlo, and (3) EvolutionManager which uses DEAP for GA-based parameter evolution. The architecture is: Optuna drives the outer loop (TPE sampling of continuous params like ATR multipliers, RR ratios, fusion thresholds), each trial runs a walk-forward validation to get profit factor as the objective, and DEAP runs as a **separate post-Optuna phase** that evolves signal combination weights using the best Optuna params as a baseline.

**Primary recommendation:** Two-phase optimizer: Phase A = Optuna TPE with MedianPruner on walk-forward profit factor (50-200 trials), Phase B = DEAP GA evolving signal weights with Optuna-best params frozen. Write final merged params to `config/optimized.toml` via `tomli_w`.

## Project Constraints (from CLAUDE.md)

- Python 3.12.x runtime
- Optuna 4.8.0, DEAP 1.4.3, scikit-learn 1.8.0 are already in dependencies
- BacktestEngine.run() is async -- Optuna objective must bridge async/sync
- Walk-forward: 6mo train + 2mo validation, rolling by 2mo, 6mo OOS holdout
- GA does NOT evolve module internals (Hurst, Lyapunov, fractal params) per D-16 -- only strategy-level params
- Profit factor capped at 10.0 per existing convention
- `tomli_w` needed for TOML writing (not in current dependencies -- `tomllib` is read-only)

## Existing Code Interfaces

### BacktestEngine (backtest/engine.py)
- Constructor: `BacktestEngine(settings: BotSettings, backtest_config: BacktestConfig)`
- Entry point: `async run(bars_df: pd.DataFrame, run_id: str = "") -> BacktestResult`
- Creates fresh signal module instances per run (clean state between windows)
- Parameters come from `settings.signals.fusion.*` and `settings.risk.*`

### WalkForwardValidator (backtest/validation.py)
- Constructor: `WalkForwardValidator(engine: BacktestEngine, loader: HistoricalDataLoader, config: BacktestConfig)`
- `async run_walk_forward() -> WalkForwardResult` -- runs all rolling windows
- `async evaluate_oos(wf_result) -> OOSResult` -- holdout evaluation
- Key metrics: `WalkForwardResult.profitable_pct`, `.aggregate_profit_factor`, `.passes_threshold`

### EvolutionManager (learning/evolution.py)
- Already has `PARAM_BOUNDS` dict with 10 parameters and their ranges
- Already has `PARAM_NAMES` list for gene-to-param mapping
- `run_generation(trades, equity) -> dict` runs one GA generation
- `individual_to_params(individual) -> dict[str, float]` converts genes to named params
- `_phase_aware_fitness()` uses profit factor for aggressive phase ($20 equity)
- Population size, crossover, mutation configured via `LearningConfig`

### BacktestResult (backtest/results.py)
- `.profit_factor` property: gross_profit / gross_loss
- `.max_drawdown_pct` property: peak-to-trough drawdown fraction
- `.win_rate`, `.n_trades`, `.final_equity`

### Monte Carlo (backtest/monte_carlo.py)
- `run_monte_carlo(trade_pnls, starting_equity, n_sims, max_dd, seed) -> MonteCarloResult`
- `.passes_threshold` checks D-07 dual threshold

### CLI (cli.py)
- Uses argparse with subcommands (run, backtest, kill, status, etc.)
- Pattern: add subparser, create `async cmd_optimize(args)`, register in `main()` dispatch
- `load_settings(args.config)` loads TOML config

### BotSettings.from_toml(toml_files)
- Creates dynamic subclass to override `model_config.toml_file`
- Can merge multiple TOML files (priority: last wins)

## Architecture Pattern

### Optuna Objective Function

The key challenge is that `BacktestEngine.run()` is async but Optuna's `study.optimize()` expects a sync objective. Solution: use `asyncio.run()` inside the objective, since `study.optimize()` runs in its own thread context.

```python
def objective(trial: optuna.Trial) -> float:
    # 1. Sample parameters from Optuna
    settings = _build_settings_from_trial(trial)

    # 2. Run walk-forward validation (async -> sync bridge)
    wf_result = asyncio.run(_run_walk_forward(settings, bt_config))

    # 3. Return profit factor as objective (maximize)
    # Report intermediate values for pruning per window
    return wf_result.aggregate_profit_factor
```

**IMPORTANT:** Cannot use `asyncio.run()` inside an already-running event loop. Since the CLI entry point uses `asyncio.run(cmd_optimize(args))`, the objective function runs inside the event loop. Two options:
1. **Use `loop.run_until_complete()` from a new thread** -- but this is fragile.
2. **Better: Make the entire optimization synchronous.** Run `asyncio.run()` per trial in the objective. This requires the CLI to NOT wrap `cmd_optimize` in `asyncio.run()`. Instead, make `cmd_optimize` synchronous and call `study.optimize()` directly. Each objective call uses its own `asyncio.run()`.

Recommended pattern:
```python
def cmd_optimize(args: argparse.Namespace) -> None:
    """Synchronous optimize command -- Optuna drives the event loop."""
    settings = load_settings(args.config)
    study = optuna.create_study(direction="maximize", ...)
    study.optimize(lambda trial: objective(trial, settings, bt_config), n_trials=args.n_trials)
```

### Parameter Search Space

Based on existing `PARAM_BOUNDS` in evolution.py and `FusionConfig` / `RiskConfig`:

| Parameter | Range | Type | Source |
|-----------|-------|------|--------|
| `aggressive_confidence_threshold` | 0.3 - 0.7 | float | FusionConfig |
| `selective_confidence_threshold` | 0.4 - 0.8 | float | FusionConfig |
| `conservative_confidence_threshold` | 0.5 - 0.9 | float | FusionConfig |
| `sl_atr_base_multiplier` | 1.0 - 4.0 | float | FusionConfig |
| `trending_rr_ratio` | 1.5 - 5.0 | float | FusionConfig |
| `ranging_rr_ratio` | 1.0 - 3.0 | float | FusionConfig |
| `high_chaos_rr_ratio` | 1.0 - 4.0 | float | FusionConfig |
| `high_chaos_size_reduction` | 0.2 - 0.8 | float | FusionConfig |
| `sl_chaos_widen_factor` | 1.0 - 2.5 | float | FusionConfig |
| `high_chaos_confidence_boost` | 0.05 - 0.3 | float | FusionConfig |
| `ema_alpha` | 0.01 - 0.3 | float | FusionConfig |

These align with the existing `PARAM_BOUNDS` in evolution.py. The weight seeds (`weight_chaos_seed`, `weight_flow_seed`, `weight_timing_seed`) are better handled by DEAP since they are co-dependent (must be optimized together as a group).

### Two-Phase Design

**Phase A: Optuna TPE (continuous params)**
- Optimizes: fusion thresholds, ATR multipliers, RR ratios, chaos adjustments
- Objective: walk-forward aggregate profit factor (maximize)
- Pruner: `MedianPruner(n_startup_trials=5, n_warmup_steps=2)` -- prune after seeing 2+ validation windows
- Sampler: `TPESampler(seed=42)` for reproducibility
- n_trials: 50-200 (configurable via CLI `--n-trials`)
- Intermediate reporting: report validation window profit factor at each step for pruning

**Phase B: DEAP GA (signal weights)**
- Freezes best Optuna params
- Evolves: weight_chaos_seed, weight_flow_seed, weight_timing_seed (3 co-dependent weights)
- Fitness: walk-forward profit factor with frozen Optuna params + evolved weights
- Population: 20, Generations: 10-30
- Uses existing `EvolutionManager` machinery but with a custom fitness that runs BacktestEngine

### Pruning Strategy

Per-window intermediate reporting enables Optuna to prune bad trials early:
```python
def objective(trial, settings, bt_config):
    # ... build settings from trial ...
    for idx, window_result in enumerate(run_windows_incrementally(...)):
        trial.report(window_result.val_result.profit_factor, step=idx)
        if trial.should_prune():
            raise optuna.TrialPruned()
    return aggregate_profit_factor
```

This requires modifying the optimization to run windows one-by-one instead of using `WalkForwardValidator.run_walk_forward()` as a monolith. Options:
1. **Simpler:** Run full walk-forward, no pruning. Use fewer trials (50).
2. **Better:** Extract per-window loop from WalkForwardValidator and report after each window.

Recommendation: Start with option 1 (no pruning, full walk-forward per trial). Each walk-forward takes seconds-to-minutes on historical data. 50 trials is manageable.

### TOML Output

Use `tomli_w` to write optimized params. The output format should match `BotSettings` structure so it can be loaded via `BotSettings.from_toml(["config/default.toml", "config/optimized.toml"])` with the optimized file overriding defaults.

```python
import tomli_w

optimized = {
    "signals": {
        "fusion": {
            "aggressive_confidence_threshold": best_trial.params["aggressive_confidence_threshold"],
            # ... all optimized fusion params ...
        }
    }
}

with open("config/optimized.toml", "wb") as f:
    tomli_w.dump(optimized, f)
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Bayesian optimization | Custom TPE sampler | `optuna.samplers.TPESampler` |
| Trial pruning | Custom early stopping | `optuna.pruners.MedianPruner` |
| TOML writing | String formatting | `tomli_w` package |
| Genetic algorithm | Custom GA loop | Existing `EvolutionManager` |
| Walk-forward windows | New window generation | Existing `WalkForwardValidator.generate_windows()` |

## Common Pitfalls

### Pitfall 1: Overfitting During Optimization
**What goes wrong:** Optimizer finds params that perfectly fit historical data but fail OOS.
**How to avoid:** The walk-forward profit factor IS already the validation metric (not training PF). The OOS holdout + Monte Carlo after optimization provides the final safety check. Do NOT optimize on the full dataset -- the existing 6-month holdout is reserved.

### Pitfall 2: Async Event Loop Nesting
**What goes wrong:** `asyncio.run()` inside an already-running loop raises `RuntimeError`.
**How to avoid:** Make `cmd_optimize` synchronous (not async). Each objective call uses its own `asyncio.run()`. The CLI dispatch for "optimize" should NOT wrap in `asyncio.run()`.

### Pitfall 3: DEAP Creator Duplicate Registration
**What goes wrong:** Calling `creator.create("FitnessMax", ...)` twice raises error.
**How to avoid:** Already handled in evolution.py with `hasattr(creator, "FitnessMax")` guard. Reuse that pattern.

### Pitfall 4: Parameter Constraint Violations
**What goes wrong:** Optuna suggests `selective_confidence_threshold < aggressive_confidence_threshold`.
**How to avoid:** Add constraint via Optuna's constraint parameter or enforce ordering: sample aggressive first, then selective with lower bound = aggressive, then conservative with lower bound = selective.

### Pitfall 5: Long Trial Runtime
**What goes wrong:** Each trial runs full walk-forward (many windows across years of data). 200 trials * 5 min/trial = 16+ hours.
**How to avoid:** Start with 50 trials. Add `--n-trials` CLI flag. Consider reduced window count for optimization (shorter training periods). Print progress with estimated time remaining.

### Pitfall 6: Weight Seeds Not Normalized
**What goes wrong:** DEAP evolves weight_chaos_seed, weight_flow_seed, weight_timing_seed independently, but they should sum to a meaningful total for the AdaptiveWeightTracker warmup initialization.
**How to avoid:** Normalize the 3 weights to sum to 1.0 before applying. The AdaptiveWeightTracker already does this via `get_weights()`, but the seed values set initial accuracy values. Ensure clamping after normalization.

## Code Integration Points

### New Files Required
1. `src/fxsoqqabot/optimization/__init__.py`
2. `src/fxsoqqabot/optimization/optimizer.py` -- Optuna study + objective function
3. `src/fxsoqqabot/optimization/search_space.py` -- Parameter bounds and trial-to-settings conversion
4. `src/fxsoqqabot/optimization/deap_weights.py` -- DEAP GA for signal weight evolution
5. Update `src/fxsoqqabot/cli.py` -- Add `optimize` subcommand

### New Dependency
- `tomli_w` -- for writing TOML output (add to pyproject.toml)

### CLI Interface
```
python -m fxsoqqabot optimize [--config ...] [--n-trials 50] [--n-generations 10] [--output config/optimized.toml] [--skip-ingestion]
```

### How Trial Params Map to BotSettings

Each Optuna trial suggests values that override specific `FusionConfig` fields. The objective function:
1. Deep-copies default settings
2. Overrides `settings.signals.fusion.*` with trial params
3. Creates BacktestEngine + WalkForwardValidator with modified settings
4. Runs walk-forward validation
5. Returns aggregate validation profit factor

The settings override uses Pydantic model_copy:
```python
fusion_overrides = {k: trial.params[k] for k in SEARCH_SPACE_KEYS}
new_fusion = settings.signals.fusion.model_copy(update=fusion_overrides)
new_signals = settings.signals.model_copy(update={"fusion": new_fusion})
new_settings = settings.model_copy(update={"signals": new_signals})
```

## Validation After Optimization

After Optuna + DEAP find best params:
1. Build final BotSettings with best params
2. Run full `WalkForwardValidator.run_walk_forward()`
3. Run `evaluate_oos(wf_result)` -- D-13 hard fail check
4. Run Monte Carlo on validation trades -- D-07 dual threshold
5. Print pass/fail summary (reuse runner.py formatting)
6. Write to `config/optimized.toml` only if ALL validation gates pass

## Sources

### Primary (HIGH confidence)
- Source code: `src/fxsoqqabot/backtest/engine.py` -- BacktestEngine async interface
- Source code: `src/fxsoqqabot/backtest/validation.py` -- WalkForwardValidator API
- Source code: `src/fxsoqqabot/learning/evolution.py` -- PARAM_BOUNDS, EvolutionManager
- Source code: `src/fxsoqqabot/config/models.py` -- FusionConfig, BotSettings, LearningConfig
- Source code: `src/fxsoqqabot/cli.py` -- CLI dispatch pattern
- [Optuna 4.8.0 docs](https://optuna.readthedocs.io/) -- study.optimize, TPESampler, MedianPruner
- [tomli_w on PyPI](https://pypi.org/project/tomli-w/) -- TOML writing

### Secondary (MEDIUM confidence)
- [DEAP 1.4.3 examples](https://deap.readthedocs.io/en/master/examples/) -- GA patterns

## Metadata

**Confidence breakdown:**
- Architecture pattern: HIGH -- based on direct source code reading
- Optuna integration: HIGH -- standard Optuna patterns, verified against docs
- DEAP integration: HIGH -- reuses existing EvolutionManager, well-understood
- Search space: HIGH -- derived directly from existing PARAM_BOUNDS and FusionConfig
- TOML writing: HIGH -- tomli_w is the standard approach for Python 3.12

**Research date:** 2026-03-28
**Valid until:** 2026-04-28
