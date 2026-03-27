"""Two-phase optimization orchestrator: Optuna TPE + DEAP GA.

Phase A: Optuna TPE searches 11 FusionConfig parameters, maximizing
walk-forward aggregate profit factor.

Phase B: DEAP GA evolves 3 signal weight seeds with best Optuna
params frozen as baseline.

Final validation: walk-forward + OOS + Monte Carlo. Writes
config/optimized.toml only if ALL gates pass.

This module is SYNCHRONOUS. Each objective call uses its own
asyncio.run() to bridge to async BacktestEngine. The CLI dispatch
must NOT wrap run_optimization() in asyncio.run().
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import optuna
from optuna.samplers import TPESampler

from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.backtest.engine import BacktestEngine
from fxsoqqabot.backtest.historical import HistoricalDataLoader
from fxsoqqabot.backtest.monte_carlo import run_monte_carlo
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


async def _async_walk_forward(
    settings: BotSettings,
    bt_config: BacktestConfig,
) -> float:
    """Run walk-forward validation and return aggregate profit factor.

    Creates fresh engine/loader/validator per call for clean state.

    Returns:
        Aggregate profit factor capped at 10.0.
    """
    loader = HistoricalDataLoader(bt_config)
    engine = BacktestEngine(settings, bt_config)
    validator = WalkForwardValidator(engine, loader, bt_config)
    wf_result = await validator.run_walk_forward()
    return min(wf_result.aggregate_profit_factor, 10.0)


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

    # ------------------------------------------------------------------
    # [Phase A] Optuna TPE: 11 FusionConfig parameters
    # ------------------------------------------------------------------
    print("[Phase A] Optuna TPE Parameter Search")
    print("-" * 40)
    print(f"  Trials: {n_trials}")
    print()

    study = optuna.create_study(
        direction="maximize",
        sampler=TPESampler(seed=42),
        study_name="fxsoqqabot-optimize",
    )

    def objective(trial: optuna.Trial) -> float:
        """Optuna objective: walk-forward profit factor."""
        params = sample_trial(trial)
        trial_settings = apply_params_to_settings(settings, params)
        pf = asyncio.run(_async_walk_forward(trial_settings, bt_config))
        return pf

    # Suppress Optuna's verbose trial logging
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    best = study.best_trial
    print()
    print(f"  Best trial:  #{best.number}")
    print(f"  Best value:  {best.value:.4f} (aggregate profit factor)")
    print("  Best params:")
    for k, v in sorted(best.params.items()):
        print(f"    {k}: {v:.6f}")
    print()

    # ------------------------------------------------------------------
    # [Phase B] DEAP GA: 3 signal weight seeds
    # ------------------------------------------------------------------
    print("[Phase B] DEAP GA Signal Weight Evolution")
    print("-" * 40)
    print(f"  Generations: {n_generations}")
    print()

    # Build settings with best Optuna params frozen
    optuna_settings = apply_params_to_settings(settings, best.params)

    best_weights = asyncio.run(
        evolve_weights(
            optuna_settings,
            bt_config,
            n_generations=n_generations,
        )
    )

    print()
    print("  Best weights:")
    for k, v in sorted(best_weights.items()):
        print(f"    {k}: {v:.6f}")
    print()

    # Merge Optuna params + DEAP weights
    final_params: dict[str, float] = {**best.params, **best_weights}

    # Build final settings
    final_settings = apply_params_to_settings(optuna_settings, best_weights)

    # ------------------------------------------------------------------
    # [Validation] Walk-Forward + OOS + Monte Carlo
    # ------------------------------------------------------------------
    print("[Validation] Final Parameter Validation")
    print("-" * 40)

    wf, oos, mc = asyncio.run(_validate_final(final_settings, bt_config))

    # Walk-forward results
    print(f"  Walk-Forward:")
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
    # [Output] Write TOML if all gates pass
    # ------------------------------------------------------------------
    all_pass = (
        wf.passes_threshold
        and oos.passes_threshold
        and (mc is None or mc_passed)
    )

    print("=" * 70)

    if all_pass:
        import tomli_w

        optimized = {
            "signals": {
                "fusion": {k: v for k, v in final_params.items()},
            },
        }
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            tomli_w.dump(optimized, f)

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
        print()
        print("  Best params (NOT written -- did not pass validation):")
        for k, v in sorted(final_params.items()):
            print(f"    {k}: {v:.6f}")

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
