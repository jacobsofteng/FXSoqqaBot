"""Two-phase optimization orchestrator: Optuna TPE + DEAP GA.

Phase A: Optuna TPE searches 11 FusionConfig parameters using a FAST
single-backtest objective on a representative 3-month window.

Phase B: DEAP GA evolves 3 signal weight seeds with best Optuna
params frozen, using the same fast objective.

Final validation: FULL walk-forward + OOS + Monte Carlo on all data.
Writes config/optimized.toml only if ALL gates pass.

Design: optimization uses a fast proxy (single 3-month backtest at ~3min/trial)
while validation uses the rigorous full pipeline (~hours). This makes
50 Optuna trials + 50 DEAP evaluations feasible overnight.

This module is SYNCHRONOUS. Each objective call uses its own
asyncio.run() to bridge to async BacktestEngine. The CLI dispatch
must NOT wrap run_optimization() in asyncio.run().
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import numpy as np
import optuna
from optuna.samplers import TPESampler

from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.backtest.engine import BacktestEngine
from fxsoqqabot.backtest.historical import HistoricalDataLoader
from fxsoqqabot.backtest.monte_carlo import run_monte_carlo
from fxsoqqabot.backtest.results import BacktestResult
from fxsoqqabot.backtest.validation import WalkForwardValidator
from fxsoqqabot.config.models import BotSettings
from fxsoqqabot.optimization.deap_weights import evolve_weights
from fxsoqqabot.optimization.search_space import (
    apply_params_to_settings,
    sample_trial,
)


def _pass_fail(passed: bool) -> str:
    """Return colored PASS/FAIL string."""
    if passed:
        return "\033[32mPASS\033[0m"
    return "\033[31mFAIL\033[0m"


def _fmt_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}min"
    hours = minutes / 60
    return f"{hours:.1f}h"


async def _fast_backtest(
    settings: BotSettings,
    bt_config: BacktestConfig,
    loader: HistoricalDataLoader,
) -> float:
    """Run a FAST single backtest on 3 months of recent data.

    Uses the most recent 3 months before the OOS holdout period as a
    representative sample. Returns profit factor capped at 10.0.

    This is the optimization proxy objective -- fast enough for 50+ trials.
    Full walk-forward is only used for final validation.
    """
    data_start, data_end = loader.get_time_range()
    holdout_months_sec = bt_config.holdout_months * int(30.44 * 86400)
    holdout_start = data_end - holdout_months_sec

    # Use 3 months just before the holdout as the optimization window
    opt_window_sec = 3 * int(30.44 * 86400)
    opt_start = holdout_start - opt_window_sec
    opt_end = holdout_start

    # Clamp to available data
    opt_start = max(opt_start, data_start)

    bars = loader.load_bars(opt_start, opt_end)
    if len(bars) < 100:
        return 0.0

    engine = BacktestEngine(settings, bt_config)
    result: BacktestResult = await engine.run(bars, run_id="opt_fast")

    # Fitness: profit factor (capped), with penalty for too few trades
    pf = min(result.profit_factor, 10.0)
    if result.n_trades < 5:
        pf *= 0.1  # Harsh penalty for strategies that barely trade

    return pf


def run_optimization(
    settings: BotSettings,
    bt_config: BacktestConfig,
    n_trials: int = 50,
    n_generations: int = 10,
    output_path: str = "config/optimized.toml",
    skip_ingestion: bool = False,
) -> None:
    """Run the full two-phase optimization pipeline.

    SYNCHRONOUS function. Each Optuna objective call uses asyncio.run()
    to bridge to async BacktestEngine. The CLI must NOT wrap this in
    asyncio.run() (Pitfall 2).

    Args:
        settings: Base BotSettings to optimize.
        bt_config: Backtest configuration.
        n_trials: Number of Optuna TPE trials.
        n_generations: Number of DEAP GA generations for weight evolution.
        output_path: Path for optimized TOML output.
        skip_ingestion: If True, skip CSV-to-Parquet ingestion.
    """
    total_start = time.time()

    print()
    print("=" * 70)
    print("  FXSoqqaBot Parameter Optimizer")
    print("=" * 70)
    print()

    # ------------------------------------------------------------------
    # [0] Data Ingestion (optional)
    # ------------------------------------------------------------------
    if not skip_ingestion:
        print("[0] Data Ingestion")
        print("-" * 40)
        loader = HistoricalDataLoader(bt_config)
        report = loader.ingest_all()
        files_processed = report.get("files_processed", 0)
        final_rows = report.get("final_rows", 0)
        print(f"  Files processed: {files_processed}")
        print(f"  Total rows:      {final_rows:,}")
        print()

    # Create a shared loader for optimization trials (reuses DuckDB connection)
    opt_loader = HistoricalDataLoader(bt_config)

    # ------------------------------------------------------------------
    # [Phase A] Optuna TPE: 11 FusionConfig parameters
    # ------------------------------------------------------------------
    print("[Phase A] Optuna TPE Parameter Search")
    print("-" * 40)
    print(f"  Trials:    {n_trials}")
    print(f"  Objective: fast 3-month backtest (proxy for walk-forward)")
    print()

    study = optuna.create_study(
        direction="maximize",
        sampler=TPESampler(seed=42),
        study_name="fxsoqqabot-optimize",
    )

    trial_times: list[float] = []

    def objective(trial: optuna.Trial) -> float:
        """Optuna objective: fast backtest profit factor."""
        t0 = time.time()
        params = sample_trial(trial)
        trial_settings = apply_params_to_settings(settings, params)
        pf = asyncio.run(_fast_backtest(trial_settings, bt_config, opt_loader))
        elapsed = time.time() - t0
        trial_times.append(elapsed)
        print(
            f"  Trial {trial.number:>3}/{n_trials}: "
            f"PF={pf:.4f}  ({_fmt_duration(elapsed)})"
        )
        return pf

    # Suppress Optuna's verbose trial logging
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    phase_a_start = time.time()
    study.optimize(objective, n_trials=n_trials)
    phase_a_elapsed = time.time() - phase_a_start

    best = study.best_trial
    print()
    print(f"  Phase A complete in {_fmt_duration(phase_a_elapsed)}")
    print(f"  Best trial:  #{best.number}")
    print(f"  Best value:  {best.value:.4f} (profit factor)")
    print("  Best params:")
    for k, v in sorted(best.params.items()):
        print(f"    {k}: {v:.6f}")
    print()

    # ------------------------------------------------------------------
    # [Phase B] DEAP GA: 3 signal weight seeds
    # ------------------------------------------------------------------
    print("[Phase B] DEAP GA Signal Weight Evolution")
    print("-" * 40)
    print(f"  Generations:  {n_generations}")
    print(f"  Population:   10")
    print(f"  Objective:    fast 3-month backtest")
    print()

    # Build settings with best Optuna params frozen
    optuna_settings = apply_params_to_settings(settings, best.params)

    phase_b_start = time.time()
    best_weights = asyncio.run(
        evolve_weights(
            optuna_settings,
            bt_config,
            n_generations=n_generations,
            population_size=10,
        )
    )
    phase_b_elapsed = time.time() - phase_b_start

    print()
    print(f"  Phase B complete in {_fmt_duration(phase_b_elapsed)}")
    print("  Best weights:")
    for k, v in sorted(best_weights.items()):
        print(f"    {k}: {v:.6f}")
    print()

    # Merge Optuna params + DEAP weights
    final_params: dict[str, float] = {**best.params, **best_weights}

    # Build final settings
    final_settings = apply_params_to_settings(optuna_settings, best_weights)

    # ------------------------------------------------------------------
    # [Validation] Walk-Forward + OOS + Monte Carlo (FULL -- not fast proxy)
    # ------------------------------------------------------------------
    print("[Validation] Final Parameter Validation (full walk-forward)")
    print("-" * 40)
    print("  Running full walk-forward across all data...")
    print()

    val_start = time.time()
    wf, oos, mc = asyncio.run(_validate_final(final_settings, bt_config))
    val_elapsed = time.time() - val_start

    # Walk-forward results
    print(f"  Walk-Forward: ({_fmt_duration(val_elapsed)})")
    print(f"    Windows:        {len(wf.windows)}")
    print(f"    Profitable:     {wf.profitable_pct * 100:.1f}% (req: {wf.min_profitable_pct_required * 100:.1f}%)")
    print(f"    Aggregate PF:   {wf.aggregate_profit_factor:.2f} (req: {wf.min_profit_factor_required:.2f})")
    print(f"    Status:         {_pass_fail(wf.passes_threshold)}")
    print()

    # OOS results
    print(f"  Out-of-Sample:")
    print(f"    OOS PF:         {oos.oos_profit_factor:.2f}")
    print(f"    OOS Max DD:     {oos.oos_max_drawdown_pct * 100:.1f}%")
    print(f"    PF Ratio:       {oos.pf_ratio:.2f} (req: >= {bt_config.oos_min_pf_ratio:.2f})")
    print(f"    DD Ratio:       {oos.dd_ratio:.2f} (req: <= {bt_config.oos_max_dd_ratio:.2f})")
    print(f"    Status:         {_pass_fail(oos.passes_threshold)}")
    print()

    # Monte Carlo results
    mc_passed = False
    if mc is not None:
        mc_passed = mc.passes_threshold
        print(f"  Monte Carlo:")
        print(f"    Simulations:    {mc.n_simulations:,}")
        print(f"    5th Pct Equity: ${mc.pct_5_equity:.2f}")
        print(f"    Median Equity:  ${mc.median_equity:.2f}")
        print(f"    95th Pct DD:    {mc.pct_95_max_dd * 100:.1f}%")
        print(f"    Status:         {_pass_fail(mc.passes_threshold)}")
    else:
        print("  Monte Carlo:      SKIPPED (no validation trades)")
    print()

    # ------------------------------------------------------------------
    # [Output] Write TOML (even if validation fails, write best-effort)
    # ------------------------------------------------------------------
    all_pass = (
        wf.passes_threshold
        and oos.passes_threshold
        and (mc is None or mc_passed)
    )

    total_elapsed = time.time() - total_start

    print("=" * 70)

    import tomli_w

    optimized = {
        "signals": {
            "fusion": {k: v for k, v in final_params.items()},
        },
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        tomli_w.dump(optimized, f)

    if all_pass:
        print(f"  OVERALL: \033[32mPASS\033[0m - All validation gates passed")
        print(f"  Optimized config written to {output_path}")
    else:
        print(f"  OVERALL: \033[31mFAIL\033[0m - Validation gates failed")
        failures: list[str] = []
        if not wf.passes_threshold:
            failures.append("Walk-Forward")
        if not oos.passes_threshold:
            failures.append("OOS")
        if mc is not None and not mc_passed:
            failures.append("Monte Carlo")
        print(f"  Failed:  {', '.join(failures)}")
        print(f"  Best-effort config still written to {output_path}")

    print(f"  Total time: {_fmt_duration(total_elapsed)}")
    print("=" * 70)
    print()


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
