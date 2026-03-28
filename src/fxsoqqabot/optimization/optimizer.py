"""Unified NSGA-II multi-objective optimizer per Phase 9 decisions.

Single-phase optimization with ~20 parameters (fusion, weights, risk,
chaos, timing) using Optuna NSGAIISampler. Two objectives: maximize
profit factor AND maximize trades per day (per D-01).

Pipeline features:
- Rich progress bar during optimization (per D-09)
- Per-step timeout / hang guard (per D-10)
- structlog WARNING suppression during trials (per D-11)
- Optuna RDBStorage SQLite warm-start (per D-12)
- Search space change detection (per D-13)
- Config diff table after optimization (per D-14)
- Stale artifact cleanup before run (per D-15)

This module is SYNCHRONOUS. Each objective call uses its own
asyncio.run() to bridge to async BacktestEngine. The CLI dispatch
must NOT wrap run_optimization() in asyncio.run().
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import structlog
import tomli_w
from optuna.samplers import NSGAIISampler
from optuna.storages import RDBStorage
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.backtest.engine import BacktestEngine
from fxsoqqabot.backtest.historical import HistoricalDataLoader
from fxsoqqabot.backtest.monte_carlo import run_monte_carlo
from fxsoqqabot.backtest.results import BacktestResult
from fxsoqqabot.backtest.validation import WalkForwardValidator
from fxsoqqabot.config.models import BotSettings
from fxsoqqabot.optimization.pareto import select_from_pareto
from fxsoqqabot.optimization.search_space import (
    ALL_FLOAT_PARAMS,
    apply_params_to_settings,
    get_all_param_names,
    sample_trial,
)

STEP_TIMEOUT_SEC = 600  # 10 minutes per D-10
STUDY_NAME = "fxsoqqabot-nsga2"
STORAGE_URL = "sqlite:///data/optuna_study.db"

STALE_ARTIFACTS = [
    "data/backtest_results.log",
    "data/optimizer_results.log",
    "data/optimizer_scalping_results.log",
    "data/analytics.duckdb",
]

console = Console()
_logger = structlog.get_logger().bind(component="optimizer")


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


def _create_or_load_study(
    storage_url: str = STORAGE_URL,
    study_name: str = STUDY_NAME,
) -> optuna.Study:
    """Create or load study with search space change detection per D-13."""
    Path(storage_url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
    storage = RDBStorage(url=storage_url)
    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        directions=["maximize", "maximize"],  # PF, trades/day per D-01
        sampler=NSGAIISampler(population_size=50, seed=42),
        load_if_exists=True,
    )

    # Search space change detection per D-13
    if len(study.trials) > 0:
        old_params = set(study.trials[0].params.keys())
        new_params = get_all_param_names()
        added = new_params - old_params
        removed = old_params - new_params
        if added or removed:
            _logger.warning(
                "search_space_changed",
                added=sorted(added),
                removed=sorted(removed),
                existing_trials=len(study.trials),
            )
            console.print(
                f"[yellow]Search space changed: "
                f"+{len(added)} params, -{len(removed)} params. "
                f"Continuing with {len(study.trials)} existing trials.[/yellow]"
            )

    return study


async def _fast_backtest(
    settings: BotSettings,
    bt_config: BacktestConfig,
    loader: HistoricalDataLoader,
) -> tuple[float, float]:
    """Run a FAST single backtest returning (profit_factor, trades_per_day).

    Uses the most recent 3 months before the OOS holdout period.
    Per D-02: trades normalized as trades/day based on calendar days.
    """
    data_start, data_end = loader.get_time_range()
    holdout_months_sec = bt_config.holdout_months * int(30.44 * 86400)
    holdout_start = data_end - holdout_months_sec

    opt_window_sec = 3 * int(30.44 * 86400)
    opt_start = max(holdout_start - opt_window_sec, data_start)
    opt_end = holdout_start

    bars = loader.load_bars(opt_start, opt_end)
    if len(bars) < 100:
        return 0.0, 0.0

    engine = BacktestEngine(settings, bt_config)
    result: BacktestResult = await engine.run(bars, run_id="opt_fast")

    # Profit factor capped at 10.0
    pf = min(result.profit_factor, 10.0)
    if result.n_trades < 5:
        pf *= 0.1  # Harsh penalty for strategies that barely trade

    # Trades per day per D-02
    if result.end_time > result.start_time:
        backtest_days = (result.end_time - result.start_time) / 86400
        trades_per_day = result.n_trades / max(backtest_days, 1.0)
    else:
        trades_per_day = 0.0

    return pf, trades_per_day


async def _fast_backtest_with_timeout(
    settings: BotSettings,
    bt_config: BacktestConfig,
    loader: HistoricalDataLoader,
) -> tuple[float, float]:
    """Run fast backtest with timeout guard per D-10."""
    try:
        return await asyncio.wait_for(
            _fast_backtest(settings, bt_config, loader),
            timeout=STEP_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        _logger.warning("backtest_timeout", timeout_sec=STEP_TIMEOUT_SEC)
        return 0.0, 0.0


def print_config_diff(
    defaults: dict[str, Any],
    optimized: dict[str, Any],
) -> None:
    """Print side-by-side config diff table per D-14.

    Sorted by magnitude of change (largest first).
    """
    table = Table(title="Configuration Diff: Default vs Optimized")
    table.add_column("Parameter", style="cyan")
    table.add_column("Default", justify="right")
    table.add_column("Optimized", justify="right", style="green")
    table.add_column("Change%", justify="right")

    rows: list[tuple[float, str, Any, Any, str]] = []
    for key in sorted(set(defaults.keys()) | set(optimized.keys())):
        default_val = defaults.get(key)
        opt_val = optimized.get(key)
        if opt_val is None:
            continue

        if isinstance(default_val, str) or isinstance(opt_val, str):
            change_pct = "N/A" if default_val != opt_val else "0.0%"
            abs_change = 1.0 if default_val != opt_val else 0.0
        elif default_val is not None and default_val != 0:
            pct = ((opt_val - default_val) / abs(default_val)) * 100
            change_pct = f"{pct:+.1f}%"
            abs_change = abs(pct)
        elif default_val == 0:
            change_pct = "new" if opt_val != 0 else "0.0%"
            abs_change = abs(opt_val) if opt_val != 0 else 0.0
        else:
            change_pct = "new"
            abs_change = 1.0

        rows.append((abs_change, key, default_val, opt_val, change_pct))

    rows.sort(key=lambda r: r[0], reverse=True)
    for _, key, default_val, opt_val, change_pct in rows:
        def_str = f"{default_val}" if isinstance(default_val, str) else (
            f"{default_val:.6f}" if isinstance(default_val, float) else str(default_val)
        )
        opt_str = f"{opt_val}" if isinstance(opt_val, str) else (
            f"{opt_val:.6f}" if isinstance(opt_val, float) else str(opt_val)
        )
        table.add_row(key, def_str, opt_str, change_pct)

    console.print(table)


def _get_default_params(settings: BotSettings) -> dict[str, Any]:
    """Extract default param values from settings for config diff."""
    defaults: dict[str, Any] = {}
    from fxsoqqabot.config.models import (
        ChaosConfig,
        FusionConfig,
        RiskConfig,
        TimingConfig,
    )

    for name in ALL_FLOAT_PARAMS:
        if name in FusionConfig.model_fields:
            defaults[name] = getattr(settings.signals.fusion, name)
        elif name in RiskConfig.model_fields:
            defaults[name] = getattr(settings.risk, name)
        elif name in ChaosConfig.model_fields:
            defaults[name] = getattr(settings.signals.chaos, name)
        elif name in TimingConfig.model_fields:
            defaults[name] = getattr(settings.signals.timing, name)
    # Categorical
    defaults["direction_mode"] = settings.signals.chaos.direction_mode
    return defaults


def _fmt_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}min"
    hours = minutes / 60
    return f"{hours:.1f}h"


async def _validate_final(
    final_settings: BotSettings,
    bt_config: BacktestConfig,
) -> tuple:
    """Run full validation: walk-forward + OOS + Monte Carlo.

    Returns:
        Tuple of (WalkForwardResult, OOSResult, MonteCarloResult | None).
    """
    loader = HistoricalDataLoader(bt_config)
    engine = BacktestEngine(final_settings, bt_config)
    validator = WalkForwardValidator(engine, loader, bt_config)

    wf = await validator.run_walk_forward()
    oos = await validator.evaluate_oos(wf)

    # Collect validation trade PnLs for Monte Carlo
    pnls: list[float] = [
        t.pnl for w in wf.windows for t in w.val_result.trades
    ]

    mc = None
    if pnls:
        mc = run_monte_carlo(
            np.array(pnls, dtype=np.float64),
            bt_config.starting_equity,
            bt_config.n_monte_carlo,
            bt_config.mc_max_drawdown_pct,
            bt_config.mc_seed,
        )

    return wf, oos, mc


def run_optimization(
    settings: BotSettings,
    bt_config: BacktestConfig,
    n_trials: int = 50,
    output_path: str = "config/optimized.toml",
    skip_ingestion: bool = False,
    storage_url: str = STORAGE_URL,
) -> None:
    """Run the unified NSGA-II multi-objective optimization pipeline.

    SYNCHRONOUS function. Each Optuna objective call uses asyncio.run()
    to bridge to async BacktestEngine. The CLI must NOT wrap this in
    asyncio.run().

    Args:
        settings: Base BotSettings to optimize.
        bt_config: Backtest configuration.
        n_trials: Number of NSGA-II trials.
        output_path: Path for optimized TOML output.
        skip_ingestion: If True, skip CSV-to-Parquet ingestion.
        storage_url: Optuna RDBStorage URL for warm-start.
    """
    total_start = time.time()

    console.print()
    console.print("=" * 70)
    console.print("  FXSoqqaBot Parameter Optimizer (NSGA-II)")
    console.print("=" * 70)
    console.print()

    # ------------------------------------------------------------------
    # [0] Cleanup stale artifacts per D-15
    # ------------------------------------------------------------------
    removed = cleanup_stale_artifacts()
    if removed:
        console.print("[dim]Cleaned stale artifacts:[/dim]")
        for r in removed:
            console.print(f"  [dim]{r}[/dim]")
        console.print()

    # ------------------------------------------------------------------
    # [1] Data Ingestion (optional)
    # ------------------------------------------------------------------
    if not skip_ingestion:
        console.print("[bold]Step 1: Data Ingestion[/bold]")
        console.print("-" * 40)
        loader = HistoricalDataLoader(bt_config)
        report = loader.ingest_all()
        files_processed = report.get("files_processed", 0)
        final_rows = report.get("final_rows", 0)
        console.print(f"  Files processed: {files_processed}")
        console.print(f"  Total rows:      {final_rows:,}")
        console.print()

    # Create a shared loader for optimization trials (reuses DuckDB connection)
    opt_loader = HistoricalDataLoader(bt_config)

    # ------------------------------------------------------------------
    # [2] Create/load study with warm-start per D-12
    # ------------------------------------------------------------------
    console.print("[bold]Step 2: Create/Load Optuna Study[/bold]")
    console.print("-" * 40)
    study = _create_or_load_study(storage_url)
    existing_trials = len(study.trials)
    if existing_trials > 0:
        console.print(f"  [green]Warm-start: {existing_trials} existing trials loaded[/green]")
    console.print(f"  New trials to run: {n_trials}")
    console.print(f"  Objectives: maximize(profit_factor), maximize(trades/day)")
    console.print(f"  Sampler: NSGA-II (pop=50, seed=42)")
    console.print()

    # ------------------------------------------------------------------
    # [3] Suppress logs during optimization per D-11
    # ------------------------------------------------------------------
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    )
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    # ------------------------------------------------------------------
    # [4] Run NSGA-II optimization with Rich progress bar
    # ------------------------------------------------------------------
    console.print("[bold]Step 3: NSGA-II Multi-Objective Optimization[/bold]")
    console.print("-" * 40)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("Optimizing (NSGA-II)...", total=n_trials)

        def objective(trial: optuna.Trial) -> tuple[float, float]:
            params = sample_trial(trial)
            trial_settings = apply_params_to_settings(settings, params)
            pf, tpd = asyncio.run(
                _fast_backtest_with_timeout(trial_settings, bt_config, opt_loader)
            )
            progress.advance(task)
            return pf, tpd

        opt_start = time.time()
        study.optimize(objective, n_trials=n_trials)
        opt_elapsed = time.time() - opt_start

    console.print()
    console.print(f"  Optimization complete in {_fmt_duration(opt_elapsed)}")
    console.print(f"  Total trials (incl. warm-start): {len(study.trials)}")
    console.print()

    # ------------------------------------------------------------------
    # [5] Pareto front selection per D-03, D-04
    # ------------------------------------------------------------------
    console.print("[bold]Step 4: Pareto Front Selection[/bold]")
    console.print("-" * 40)
    pareto_trials = study.best_trials
    console.print(f"  Pareto front size: {len(pareto_trials)}")

    best_trial = select_from_pareto(pareto_trials)
    best_params = best_trial.params
    console.print(f"  Selected trial #{best_trial.number}:")
    console.print(f"    Profit Factor:  {best_trial.values[0]:.4f}")
    console.print(f"    Trades/Day:     {best_trial.values[1]:.2f}")
    console.print()

    # ------------------------------------------------------------------
    # [6] Restore logging
    # ------------------------------------------------------------------
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )

    # ------------------------------------------------------------------
    # [7] Validation -- walk-forward + OOS + Monte Carlo
    # ------------------------------------------------------------------
    console.print("[bold]Step 5: Final Parameter Validation (full walk-forward)[/bold]")
    console.print("-" * 40)
    console.print("  Running full walk-forward across all data...")
    console.print()

    final_settings = apply_params_to_settings(settings, best_params)

    val_start = time.time()
    wf, oos, mc = asyncio.run(_validate_final(final_settings, bt_config))
    val_elapsed = time.time() - val_start

    # Walk-forward results
    console.print(f"  Walk-Forward: ({_fmt_duration(val_elapsed)})")
    console.print(f"    Windows:        {len(wf.windows)}")
    console.print(f"    Profitable:     {wf.profitable_pct * 100:.1f}% (req: {wf.min_profitable_pct_required * 100:.1f}%)")
    console.print(f"    Aggregate PF:   {wf.aggregate_profit_factor:.2f} (req: {wf.min_profit_factor_required:.2f})")
    wf_status = "[green]PASS[/green]" if wf.passes_threshold else "[red]FAIL[/red]"
    console.print(f"    Status:         {wf_status}")
    console.print()

    # OOS results
    console.print(f"  Out-of-Sample:")
    console.print(f"    OOS PF:         {oos.oos_profit_factor:.2f}")
    console.print(f"    OOS Max DD:     {oos.oos_max_drawdown_pct * 100:.1f}%")
    console.print(f"    PF Ratio:       {oos.pf_ratio:.2f} (req: >= {bt_config.oos_min_pf_ratio:.2f})")
    console.print(f"    DD Ratio:       {oos.dd_ratio:.2f} (req: <= {bt_config.oos_max_dd_ratio:.2f})")
    oos_status = "[green]PASS[/green]" if oos.passes_threshold else "[red]FAIL[/red]"
    console.print(f"    Status:         {oos_status}")
    console.print()

    # Monte Carlo results
    mc_passed = False
    if mc is not None:
        mc_passed = mc.passes_threshold
        console.print(f"  Monte Carlo:")
        console.print(f"    Simulations:    {mc.n_simulations:,}")
        console.print(f"    5th Pct Equity: ${mc.pct_5_equity:.2f}")
        console.print(f"    Median Equity:  ${mc.median_equity:.2f}")
        console.print(f"    95th Pct DD:    {mc.pct_95_max_dd * 100:.1f}%")
        mc_status = "[green]PASS[/green]" if mc.passes_threshold else "[red]FAIL[/red]"
        console.print(f"    Status:         {mc_status}")
    else:
        console.print("  Monte Carlo:      SKIPPED (no validation trades)")
    console.print()

    # ------------------------------------------------------------------
    # [8] Write TOML with ALL config models (not just fusion)
    # ------------------------------------------------------------------
    from fxsoqqabot.config.models import (
        ChaosConfig,
        FusionConfig,
        RiskConfig,
        TimingConfig,
    )

    optimized_toml: dict[str, Any] = {}
    fusion_vals = {k: v for k, v in best_params.items() if k in FusionConfig.model_fields}
    risk_vals = {k: v for k, v in best_params.items() if k in RiskConfig.model_fields}
    chaos_vals = {k: v for k, v in best_params.items() if k in ChaosConfig.model_fields}
    timing_vals = {k: v for k, v in best_params.items() if k in TimingConfig.model_fields}

    if fusion_vals:
        optimized_toml.setdefault("signals", {})["fusion"] = fusion_vals
    if risk_vals:
        optimized_toml["risk"] = risk_vals
    if chaos_vals:
        optimized_toml.setdefault("signals", {})["chaos"] = chaos_vals
    if timing_vals:
        optimized_toml.setdefault("signals", {})["timing"] = timing_vals

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        tomli_w.dump(optimized_toml, f)

    # ------------------------------------------------------------------
    # [9] Config diff per D-14
    # ------------------------------------------------------------------
    console.print("[bold]Step 6: Configuration Diff[/bold]")
    console.print("-" * 40)
    print_config_diff(_get_default_params(settings), best_params)
    console.print()

    # ------------------------------------------------------------------
    # [10] Summary
    # ------------------------------------------------------------------
    all_pass = (
        wf.passes_threshold
        and oos.passes_threshold
        and (mc is None or mc_passed)
    )

    total_elapsed = time.time() - total_start

    console.print("=" * 70)
    if all_pass:
        console.print(f"  OVERALL: [green]PASS[/green] - All validation gates passed")
        console.print(f"  Optimized config written to {output_path}")
    else:
        console.print(f"  OVERALL: [red]FAIL[/red] - Validation gates failed")
        failures: list[str] = []
        if not wf.passes_threshold:
            failures.append("Walk-Forward")
        if not oos.passes_threshold:
            failures.append("OOS")
        if mc is not None and not mc_passed:
            failures.append("Monte Carlo")
        console.print(f"  Failed:  {', '.join(failures)}")
        console.print(f"  Best-effort config still written to {output_path}")

    console.print(f"  Pareto front:   {len(pareto_trials)} trials")
    console.print(f"  Study storage:  {storage_url}")
    console.print(f"  Total time:     {_fmt_duration(total_elapsed)}")
    console.print("=" * 70)
    console.print()
