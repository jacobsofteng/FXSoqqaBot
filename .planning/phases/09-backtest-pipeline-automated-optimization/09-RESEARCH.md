# Phase 9: Backtest Pipeline & Automated Optimization - Research

**Researched:** 2026-03-28
**Domain:** Optuna multi-objective optimization, backtest pipeline orchestration, Rich progress reporting
**Confidence:** HIGH

## Summary

Phase 9 transforms the existing two-phase optimizer (Optuna TPE + DEAP GA) into a unified multi-objective NSGA-II pipeline, expands the search space from 11 to ~20 parameters, adds pipeline reliability features (progress bars, hang guards, log suppression), and implements warm-start via Optuna RDBStorage with SQLite persistence at `data/optuna_study.db`.

The existing codebase is well-structured for this refactor. The optimizer (`optimizer.py`) already has the synchronous-with-asyncio.run() pattern. The search space (`search_space.py`) has a clean dict-based param definition and `apply_params_to_settings()` mapper. The key changes are: (1) replace `TPESampler` with `NSGAIISampler` and `direction="maximize"` with `directions=["maximize", "maximize"]`, (2) fold the 3 DEAP weight params into the unified Optuna search space eliminating the two-phase design entirely, (3) extend `apply_params_to_settings()` to handle RiskConfig, ChaosConfig, and TimingConfig fields (currently only maps FusionConfig), and (4) wrap the pipeline in Rich progress bars with structlog WARNING suppression during trials.

**Primary recommendation:** Refactor `optimizer.py` to use a single `NSGAIISampler`-backed multi-objective study with ~20 parameters (including 3 signal weights, risk params, chaos thresholds, timing urgency), returning two objectives (profit factor, trades/day). Select from the Pareto front using trade count proximity to 10-20/day target. Persist via `sqlite:///data/optuna_study.db` with `load_if_exists=True`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Use Optuna's built-in NSGA-II (NSGAIISampler) for true multi-objective Pareto front optimization with two objectives: profit factor and normalized trade count
- **D-02:** Trade count normalized as trades per day based on backtest window calendar days -- directly comparable to the 10-20/day target
- **D-03:** Pareto front selection strategy: trade count priority -- select the Pareto-optimal config closest to 10-20 trades/day, then maximize profit factor within that band
- **D-04:** Minimum profit factor floor: PF >= 1.0 -- any profitable strategy qualifies at the demo stage
- **D-05:** Expand search space from 11 to ~20 parameters by adding three new categories: Risk params (risk_pct, SL ATR multiplier, daily drawdown limit), Chaos thresholds (Hurst threshold, Lyapunov threshold, entropy window, bifurcation sensitivity), Timing urgency (OU mean_reversion_strength, urgency_floor, phase_transition_threshold)
- **D-06:** Chaos direction_mode included as a categorical parameter (zero/drift/flow_follow) -- Optuna NSGA-II handles mixed continuous+categorical spaces
- **D-07:** Session windows stay fixed per Phase 8 decisions -- not included in search space
- **D-08:** Fold DEAP GA weight evolution into Optuna NSGA-II -- signal weights become 3 additional continuous parameters in the unified search. Eliminates the two-phase optimization design
- **D-09:** Progress reporting: Rich progress bar during processing + compact summary table at end. Per-window/per-trial detail suppressed to a log file. Terminal stays clean
- **D-10:** Hang guard: per-step timeout (e.g., 10 min per walk-forward window). If exceeded, log warning and skip to next window/step
- **D-11:** Log flooding control: suppress structlog to WARNING level during optimization trials. Each BacktestEngine run generates hundreds of log entries -- at 50+ trials that's thousands of lines
- **D-12:** Study persistence via Optuna SQLite backend (RDBStorage) at data/optuna_study.db. Re-running loads previous trials automatically
- **D-13:** Search space changes between runs: continue with new space -- Optuna handles natively. Old trials inform existing params, new params explored from scratch
- **D-14:** Config diff output: side-by-side table after optimization -- Parameter | Default | Optimized | Change%. Sorted by magnitude of change
- **D-15:** Clean up stale artifacts from previous incomplete runs before pipeline execution

### Claude's Discretion
- Exact per-step timeout duration (10 min suggested, but Claude can adjust based on profiling)
- Specific bounds for new search space parameters (chaos thresholds, timing urgency ranges)
- Whether to use Rich or tqdm for progress bars (Rich already a dependency)
- Implementation of the Pareto front selection algorithm (knee point vs target proximity)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OPT-01 | Backtest pipeline completes full 6-step run on 3.8M bars without hanging or log flooding | Rich progress bars (verified available v14.3.3), structlog WARNING suppression (pattern already in cli.py cmd_optimize), per-step timeout via asyncio.wait_for or signal.alarm, data cleanup step 0 |
| OPT-02 | Optimization search space expanded from 11 to ~20 parameters including chaos thresholds, timing urgency, risk/SL config | Verified FusionConfig, RiskConfig, ChaosConfig, TimingConfig model fields. apply_params_to_settings() needs extension to handle all 4 config models. NSGA-II handles mixed categorical+continuous (verified in venv) |
| OPT-03 | Multi-objective optimization maximizes profit factor AND normalized trade count via Pareto front | Optuna 4.8.0 NSGAIISampler verified working with directions=["maximize","maximize"]. study.best_trials returns Pareto front. Trade count normalization: n_trades / (backtest_days) |
| OPT-04 | Optimization supports warm-start from previous study and displays config diff after completion | RDBStorage with sqlite:///data/optuna_study.db + load_if_exists=True verified. Rich Table for config diff. tomli_w 1.2.0 for TOML output |
</phase_requirements>

## Standard Stack

### Core (already installed -- verified in venv)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Optuna | 4.8.0 | Multi-objective Bayesian optimization with NSGA-II | NSGAIISampler handles mixed continuous+categorical, built-in Pareto front via study.best_trials, RDBStorage for warm-start |
| Rich | 14.3.3 | Progress bars, summary tables, config diff rendering | Already a project dependency. Progress, Table, Console all verified available |
| tomli_w | 1.2.0 | TOML serialization for optimized.toml output | Already used in optimizer.py |
| structlog | installed | Structured logging with filtering | Already configured. WARNING filter pattern exists in cli.py cmd_optimize |

### Removed from Stack (per D-08)
| Library | Reason |
|---------|--------|
| DEAP | Weight evolution folded into Optuna NSGA-II. deap_weights.py becomes dead code |

**Installation:** No new packages needed. All dependencies already installed.

## Architecture Patterns

### Recommended Changes to Existing Structure
```
src/fxsoqqabot/
├── optimization/
│   ├── optimizer.py          # REFACTOR: TPESampler -> NSGAIISampler, single-phase, multi-objective
│   ├── search_space.py       # EXTEND: 11 -> ~20 params, add Risk/Chaos/Timing params
│   ├── deap_weights.py       # DEPRECATED: weights folded into search_space.py
│   └── pareto.py             # NEW: Pareto front selection (trade count proximity)
├── backtest/
│   ├── runner.py             # EXTEND: Rich progress bars, hang guard, cleanup step
│   └── ...                   # Unchanged
└── cli.py                    # EXTEND: CLI args for warm-start, config diff display
```

### Pattern 1: Unified Multi-Objective Optimizer
**What:** Single Optuna study with NSGA-II replaces two-phase TPE + DEAP
**When to use:** This is the sole optimization path
**Example:**
```python
# Source: Verified against Optuna 4.8.0 in project venv
import optuna
from optuna.samplers import NSGAIISampler
from optuna.storages import RDBStorage

storage = RDBStorage(url="sqlite:///data/optuna_study.db")
study = optuna.create_study(
    study_name="fxsoqqabot-nsga2",
    storage=storage,
    directions=["maximize", "maximize"],  # profit_factor, trades_per_day
    sampler=NSGAIISampler(
        population_size=50,
        seed=42,
    ),
    load_if_exists=True,  # warm-start
)

def objective(trial: optuna.Trial) -> tuple[float, float]:
    params = sample_trial(trial)  # all ~20 params including weights
    settings = apply_params_to_settings(base_settings, params)
    result = asyncio.run(_fast_backtest(settings, bt_config, loader))

    profit_factor = min(result.profit_factor, 10.0)
    # Normalize trade count to trades/day
    backtest_days = (result.end_time - result.start_time) / 86400
    trades_per_day = result.n_trades / max(backtest_days, 1.0)

    return profit_factor, trades_per_day

study.optimize(objective, n_trials=n_trials)

# Pareto front selection
pareto_trials = study.best_trials
best = select_by_trade_target(pareto_trials, target_min=10, target_max=20)
```

### Pattern 2: Extended apply_params_to_settings
**What:** Map flat param dict to nested BotSettings across multiple config models
**When to use:** Every time trial params need to be applied to settings
**Example:**
```python
def apply_params_to_settings(
    settings: BotSettings,
    params: dict[str, Any],
) -> BotSettings:
    """Apply parameter overrides to BotSettings across all config models."""
    # FusionConfig overrides (existing)
    fusion_overrides = {k: v for k, v in params.items() if k in FusionConfig.model_fields}
    # RiskConfig overrides (new)
    risk_overrides = {k: v for k, v in params.items() if k in RiskConfig.model_fields}
    # ChaosConfig overrides (new)
    chaos_overrides = {k: v for k, v in params.items() if k in ChaosConfig.model_fields}
    # TimingConfig overrides (new)
    timing_overrides = {k: v for k, v in params.items() if k in TimingConfig.model_fields}

    new_settings = settings
    if fusion_overrides:
        new_fusion = settings.signals.fusion.model_copy(update=fusion_overrides)
        new_signals = settings.signals.model_copy(update={"fusion": new_fusion})
        new_settings = new_settings.model_copy(update={"signals": new_signals})
    if risk_overrides:
        new_risk = settings.risk.model_copy(update=risk_overrides)
        new_settings = new_settings.model_copy(update={"risk": new_risk})
    if chaos_overrides:
        new_chaos = settings.signals.chaos.model_copy(update=chaos_overrides)
        new_signals = new_settings.signals.model_copy(update={"chaos": new_chaos})
        new_settings = new_settings.model_copy(update={"signals": new_signals})
    if timing_overrides:
        new_timing = settings.signals.timing.model_copy(update=timing_overrides)
        new_signals = new_settings.signals.model_copy(update={"timing": new_timing})
        new_settings = new_settings.model_copy(update={"signals": new_signals})

    return new_settings
```

### Pattern 3: Rich Progress Bar for Synchronous Trials
**What:** Rich Progress wrapping Optuna's synchronous optimize loop
**When to use:** Around the trial callback in optimizer.py
**Example:**
```python
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, MofNCompleteColumn

with Progress(
    SpinnerColumn(),
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    MofNCompleteColumn(),
    TimeElapsedColumn(),
) as progress:
    task = progress.add_task("Optimizing...", total=n_trials)

    def objective(trial):
        # ... objective logic ...
        progress.advance(task)
        return pf, trades_per_day

    study.optimize(objective, n_trials=n_trials)
```

### Pattern 4: Pareto Front Selection with Trade Count Target
**What:** Select from Pareto front trials the one closest to the 10-20 trades/day target
**When to use:** After optimization completes
**Example:**
```python
def select_from_pareto(
    trials: list[optuna.trial.FrozenTrial],
    target_min_tpd: float = 10.0,
    target_max_tpd: float = 20.0,
    min_pf: float = 1.0,
) -> optuna.trial.FrozenTrial:
    """Select Pareto-optimal trial closest to trade count target with PF floor."""
    # Filter by minimum profit factor
    viable = [t for t in trials if t.values[0] >= min_pf]
    if not viable:
        viable = trials  # Fallback: take best available

    # Score by proximity to target trade count band
    target_mid = (target_min_tpd + target_max_tpd) / 2

    def score(trial):
        tpd = trial.values[1]
        if target_min_tpd <= tpd <= target_max_tpd:
            # Within band: prefer higher PF
            return (0, -trial.values[0])
        else:
            # Outside band: distance penalty
            dist = min(abs(tpd - target_min_tpd), abs(tpd - target_max_tpd))
            return (dist, -trial.values[0])

    return min(viable, key=score)
```

### Pattern 5: Config Diff Table
**What:** Side-by-side comparison of default vs optimized parameters
**When to use:** After writing optimized.toml
**Example:**
```python
from rich.table import Table
from rich.console import Console

def print_config_diff(defaults: dict[str, float], optimized: dict[str, float]) -> None:
    table = Table(title="Configuration Diff")
    table.add_column("Parameter", style="cyan")
    table.add_column("Default", justify="right")
    table.add_column("Optimized", justify="right")
    table.add_column("Change%", justify="right")

    rows = []
    for key in sorted(optimized.keys()):
        default_val = defaults.get(key, 0.0)
        opt_val = optimized[key]
        if isinstance(default_val, str) or isinstance(opt_val, str):
            change_pct = "N/A"
        elif default_val != 0:
            change_pct = f"{((opt_val - default_val) / abs(default_val)) * 100:+.1f}%"
        else:
            change_pct = "new"
        rows.append((abs_change(default_val, opt_val), key, default_val, opt_val, change_pct))

    # Sort by magnitude of change
    rows.sort(key=lambda r: r[0], reverse=True)
    for _, key, default_val, opt_val, change_pct in rows:
        table.add_row(key, fmt(default_val), fmt(opt_val), change_pct)

    Console().print(table)
```

### Anti-Patterns to Avoid
- **Two-phase optimization:** Do NOT keep the DEAP GA weight evolution separate. D-08 explicitly folds weights into the unified NSGA-II search. The old two-phase design (TPE then DEAP) artificially separates co-dependent parameters
- **Per-trial print statements:** Do NOT print each trial's result to stdout during optimization. Use Rich progress bar. Trial details go to a log file only
- **asyncio.run() in main optimize function:** The optimizer is SYNCHRONOUS. Each objective call uses asyncio.run() individually. Do NOT wrap run_optimization() in asyncio.run() (existing pattern, keep it)
- **In-memory Optuna study:** Always use RDBStorage for persistence. Never use the default in-memory storage

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multi-objective optimization | Custom NSGA-II or weighted sum | `optuna.samplers.NSGAIISampler` | Proven implementation with crowding distance, crossover, mutation. Handles categorical params |
| Pareto front computation | Custom domination sorting | `study.best_trials` | Returns all non-dominated trials automatically after optimize() |
| Study persistence | Custom SQLite tables | `optuna.storages.RDBStorage` | Handles schema, migration, warm-start, trial deduplication |
| Progress bars | Custom print-based counters | `rich.progress.Progress` | Handles terminal width, elapsed time, ETA, spinner, clean output |
| Config diff formatting | Custom string formatting | `rich.table.Table` | Handles column alignment, colors, borders, terminal width |
| TOML serialization | Custom dict-to-string | `tomli_w.dump()` | Already used in optimizer.py. Handles quoting, escaping, nested sections |

**Key insight:** Optuna 4.8.0 already has everything needed for multi-objective optimization with persistence. The DEAP dependency becomes completely unnecessary once weights are folded into the Optuna search space.

## Common Pitfalls

### Pitfall 1: asyncio.run() Nesting
**What goes wrong:** Calling asyncio.run() inside an already-running event loop causes RuntimeError
**Why it happens:** If cmd_optimize is dispatched via asyncio.run(), and objective also calls asyncio.run()
**How to avoid:** cmd_optimize is already a SYNC function (not async). The CLI correctly dispatches it without asyncio.run(). Keep this pattern. Each objective call uses its own asyncio.run() independently
**Warning signs:** "RuntimeError: This event loop is already running" during optimization

### Pitfall 2: Optuna Study Direction Mismatch on Warm-Start
**What goes wrong:** Creating a study with different directions than the existing persisted study causes ValueError
**Why it happens:** RDBStorage stores study metadata including direction. If you change from single-objective to multi-objective, the stored study conflicts
**How to avoid:** When migrating from the old TPE single-objective to NSGA-II multi-objective, use a NEW study_name (e.g., "fxsoqqabot-nsga2" instead of "fxsoqqabot-optimize"). Or delete the old study DB
**Warning signs:** ValueError on study creation with load_if_exists=True

### Pitfall 3: Log Flooding During Multi-Trial Optimization
**What goes wrong:** 811 MB of optimizer log output (verified -- the file exists at data/optimizer_results.log)
**Why it happens:** Each BacktestEngine.run() produces hundreds of structlog entries. At 50+ trials, this compounds to millions of lines
**How to avoid:** Set structlog to WARNING level before optimization loop (D-11). The pattern already exists in cli.py cmd_optimize but is fragile. Apply it inside the optimizer itself
**Warning signs:** Terminal output flooding, large log files, slow I/O

### Pitfall 4: FusionConfig-Only apply_params_to_settings
**What goes wrong:** New params for RiskConfig, ChaosConfig, TimingConfig silently ignored
**Why it happens:** Current apply_params_to_settings() only checks `k in FusionConfig.model_fields`. Params like `aggressive_risk_pct` or `direction_mode` would be silently dropped
**How to avoid:** Extend apply_params_to_settings() to check all 4 config models (FusionConfig, RiskConfig, ChaosConfig, TimingConfig) and apply to appropriate nested model

### Pitfall 5: Categorical Parameter Formatting in suggest_float
**What goes wrong:** Optuna raises error when trying suggest_float on "direction_mode" (a categorical)
**Why it happens:** direction_mode is a string enum ("zero"/"drift"/"flow_follow"), not a float
**How to avoid:** Use `trial.suggest_categorical("direction_mode", ["zero", "drift", "flow_follow"])` for this one parameter. The rest are floats. NSGAIISampler handles mixed types (verified in venv)

### Pitfall 6: Hang on Long Walk-Forward Windows
**What goes wrong:** Single walk-forward window takes > 30 minutes, pipeline appears hung
**Why it happens:** 3.8M bars across ~50 walk-forward windows with bar-by-bar signal pipeline is CPU-intensive
**How to avoid:** Use the FAST 3-month proxy for optimization trials (already implemented as _fast_backtest). Only run full walk-forward for final validation. Add per-step timeout (D-10)
**Warning signs:** No output for > 10 minutes during optimization

### Pitfall 7: Pareto Front Empty or Single-Point
**What goes wrong:** study.best_trials returns 0 or 1 trial, selection algorithm has nothing to pick from
**Why it happens:** If all trials have PF < 1.0 or zero trades, the Pareto front degenerates
**How to avoid:** Ensure PF floor (D-04: PF >= 1.0) is a soft constraint, not a hard one. Use the full Pareto front for selection, then filter. If no trials meet criteria, return the best available with a warning

## Code Examples

### Expanded Search Space (~20 parameters)
```python
# Based on D-05, D-06, D-08 and analysis of config models

# Existing FusionConfig params (11, minus 3 threshold ordering = 8 independent)
FUSION_PARAMS: dict[str, tuple[float, float]] = {
    "aggressive_confidence_threshold": (0.20, 0.50),
    "selective_confidence_threshold": (0.30, 0.60),
    "conservative_confidence_threshold": (0.40, 0.75),
    "sl_atr_base_multiplier": (0.5, 3.0),
    "trending_rr_ratio": (1.5, 5.0),
    "ranging_rr_ratio": (1.0, 3.0),
    "high_chaos_size_reduction": (0.2, 0.8),
    "high_chaos_rr_ratio": (1.0, 4.0),
    "sl_chaos_widen_factor": (1.0, 2.5),
    "high_chaos_confidence_boost": (0.05, 0.3),
    "ema_alpha": (0.01, 0.3),
}

# Signal weights (from DEAP, now in Optuna per D-08)
WEIGHT_PARAMS: dict[str, tuple[float, float]] = {
    "weight_chaos_seed": (0.1, 0.9),
    "weight_flow_seed": (0.1, 0.9),
    "weight_timing_seed": (0.1, 0.9),
}

# Risk params (new per D-05)
RISK_PARAMS: dict[str, tuple[float, float]] = {
    "aggressive_risk_pct": (0.05, 0.20),
    "daily_drawdown_pct": (0.03, 0.15),
}

# Chaos thresholds (new per D-05) -- these affect regime.py classification
# Note: These would require passing through to classify_regime() which
# currently uses hardcoded thresholds. Alternative: tune the existing
# chaos config params that feed into the regime classifier indirectly
CHAOS_PARAMS: dict[str, tuple[float, float]] = {
    "entropy_bins": (20, 100),  # Affects entropy computation sensitivity
}
# Categorical
CHAOS_CATEGORICAL: dict[str, list[str]] = {
    "direction_mode": ["zero", "drift", "flow_follow"],
}

# Timing urgency params (new per D-05)
TIMING_PARAMS: dict[str, tuple[float, float]] = {
    "phase_transition_compression_threshold": (0.3, 0.8),
    "phase_transition_expansion_threshold": (1.5, 3.0),
}

# Total: 11 fusion + 3 weights + 2 risk + 1 chaos_float + 1 chaos_cat + 2 timing = 20
```

### Hang Guard with Timeout
```python
import asyncio
import signal as os_signal

STEP_TIMEOUT_SEC = 600  # 10 minutes per D-10

async def _fast_backtest_with_timeout(settings, bt_config, loader):
    """Run fast backtest with timeout guard."""
    try:
        return await asyncio.wait_for(
            _fast_backtest_async(settings, bt_config, loader),
            timeout=STEP_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        # Return penalty result instead of hanging
        return BacktestResult(
            trades=(), starting_equity=bt_config.starting_equity,
            final_equity=bt_config.starting_equity, total_commission=0.0,
            total_bars_processed=0, start_time=0, end_time=0,
        )
```

### Data Cleanup Step 0
```python
from pathlib import Path

STALE_ARTIFACTS = [
    "data/backtest_results.log",
    "data/optimizer_results.log",
    "data/optimizer_scalping_results.log",
    "data/analytics.duckdb",
]

def cleanup_stale_artifacts() -> list[str]:
    """Remove stale artifacts from previous incomplete runs per D-15."""
    removed = []
    for path_str in STALE_ARTIFACTS:
        path = Path(path_str)
        if path.exists():
            size_mb = path.stat().st_size / (1024 * 1024)
            path.unlink()
            removed.append(f"{path_str} ({size_mb:.1f} MB)")
    return removed
```

### Warm-Start with Search Space Change Detection
```python
def create_or_load_study(
    storage_url: str = "sqlite:///data/optuna_study.db",
    study_name: str = "fxsoqqabot-nsga2",
) -> optuna.Study:
    """Create or load study with search space change detection per D-13."""
    study = optuna.create_study(
        study_name=study_name,
        storage=storage_url,
        directions=["maximize", "maximize"],
        sampler=NSGAIISampler(population_size=50, seed=42),
        load_if_exists=True,
    )

    if len(study.trials) > 0:
        old_params = set(study.trials[0].params.keys())
        # new_params defined from current search space
        new_params = set(get_all_param_names())
        added = new_params - old_params
        removed = old_params - new_params
        if added or removed:
            import structlog
            logger = structlog.get_logger()
            logger.warning(
                "search_space_changed",
                added=sorted(added),
                removed=sorted(removed),
                existing_trials=len(study.trials),
            )

    return study
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Optuna TPESampler (single-objective) | NSGAIISampler (multi-objective) | D-01 decision | Two objectives instead of weighted sum. True Pareto front |
| DEAP GA for weight evolution (Phase B) | Weights in Optuna search space | D-08 decision | Eliminates DEAP dependency for optimization. Single unified search |
| In-memory Optuna study | RDBStorage SQLite persistence | D-12 decision | Warm-start across sessions. Resume interrupted runs |
| Print-based progress reporting | Rich Progress + Table | D-09 decision | Clean terminal, proper progress bars, formatted output |

**Deprecated/outdated:**
- `deap_weights.py`: Entire module superseded by folding weights into Optuna NSGA-II search space per D-08
- Two-phase optimization design: Replaced by unified single-phase multi-objective search

## Open Questions

1. **Chaos threshold indirection**
   - What we know: The regime classifier (`regime.py`) uses hardcoded thresholds (bifurcation > 0.7, lyapunov > 0.5, entropy > 0.7, hurst > 0.6, hurst < 0.45). D-05 says to add "Hurst threshold, Lyapunov threshold" to search space.
   - What's unclear: These thresholds live in `classify_regime()` function, not in any config model. To make them searchable, we either (a) add them to ChaosConfig and pass them through, or (b) search the existing ChaosConfig params that indirectly affect metric sensitivity (entropy_bins, etc.).
   - Recommendation: Add explicit threshold fields to ChaosConfig (e.g., `hurst_trending_threshold: float = 0.6`, `lyapunov_chaos_threshold: float = 0.5`, `entropy_chaos_threshold: float = 0.7`, `bifurcation_threshold: float = 0.7`) and pass them to `classify_regime()`. This is the cleanest approach and directly matches D-05. Adds ~4 more float params to the search space.

2. **Timing urgency floor and OU mean_reversion_strength**
   - What we know: D-05 mentions "OU mean_reversion_strength" and "urgency_floor" as new timing params. The OU model computes kappa (mean-reversion speed) from data. urgency is computed as `abs(displacement) / (2 * sigma)` in ou_model.py.
   - What's unclear: These are computed values, not config params. To make them searchable, we need to add config params that scale or floor these values.
   - Recommendation: Add to TimingConfig: `urgency_floor: float = 0.0` (minimum urgency value before scaling), and `mean_reversion_strength_scale: float = 1.0` (multiplier on kappa for urgency calculation). Then wire them through the module update logic.

3. **Timeout mechanism on Windows**
   - What we know: D-10 requires per-step timeout. `asyncio.wait_for()` works for async code. But the optimizer is synchronous with individual asyncio.run() calls.
   - What's unclear: Signal-based timeouts (SIGALRM) don't work on Windows.
   - Recommendation: Wrap each objective's asyncio.run() with a timeout inside the event loop: use `asyncio.wait_for()` inside the async function that _fast_backtest calls. This works because each asyncio.run() creates a fresh loop. Alternatively, use `concurrent.futures.ThreadPoolExecutor` with timeout.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All | Yes | 3.12.13 (.venv) | -- |
| Optuna | NSGA-II optimizer | Yes | 4.8.0 | -- |
| Rich | Progress bars, tables | Yes | 14.3.3 | -- |
| tomli_w | TOML output | Yes | 1.2.0 | -- |
| structlog | Log suppression | Yes | installed | -- |
| SQLite | RDBStorage persistence | Yes | stdlib | -- |

**Missing dependencies with no fallback:** None
**Missing dependencies with fallback:** None

## Sources

### Primary (HIGH confidence)
- Optuna 4.8.0 NSGAIISampler -- verified via live import test in project venv
- Optuna RDBStorage SQLite warm-start -- verified via live test with create/resume workflow
- Optuna mixed categorical+continuous NSGA-II -- verified via live test with suggest_categorical + suggest_float
- Rich 14.3.3 Progress, Table, Console -- verified via live import test
- tomli_w 1.2.0 -- verified installed
- Historical data: 3,888,389 bars from 2015-01-01 to 2026-03-20 -- verified via HistoricalDataLoader

### Secondary (MEDIUM confidence)
- [Optuna NSGAIISampler docs](https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.NSGAIISampler.html) -- constructor params, population_size, seed
- [Optuna multi-objective tutorial](https://optuna.readthedocs.io/en/stable/tutorial/20_recipes/002_multi_objective.html) -- study.best_trials Pareto front API
- [Optuna RDB backend tutorial](https://optuna.readthedocs.io/en/stable/tutorial/20_recipes/001_rdb.html) -- SQLite persistence, load_if_exists pattern
- [Rich Progress Display docs](https://rich.readthedocs.io/en/stable/progress.html) -- Progress columns, update API

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified installed and functional in project venv
- Architecture: HIGH -- patterns derived from reading actual source code and verified API behavior
- Pitfalls: HIGH -- Pitfall 3 (log flooding) verified by the 811 MB file on disk. Pitfall 4 (FusionConfig-only mapping) verified by reading apply_params_to_settings source. Others derived from verified codebase analysis

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (stable stack, no fast-moving dependencies)
