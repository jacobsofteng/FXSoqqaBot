"""End-to-end backtest orchestrator.

Wires all existing backtest components (HistoricalDataLoader, BacktestEngine,
WalkForwardValidator, Monte Carlo, RegimeTagger, FeigenbaumStressTest) into a
single pipeline that runs:
1. CSV ingestion (histdata.com -> Parquet)
2. Walk-forward validation (rolling windows)
3. Out-of-sample holdout evaluation
4. Monte Carlo simulation (trade sequence shuffling)
5. Regime-aware evaluation (per-regime performance breakdown)
6. Feigenbaum stress test (chaos module transition detection)

Usage: called from the CLI `backtest` subcommand.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.backtest.engine import BacktestEngine
from fxsoqqabot.backtest.historical import HistoricalDataLoader
from fxsoqqabot.backtest.monte_carlo import run_monte_carlo
from fxsoqqabot.backtest.regime_tagger import RegimeTagger
from fxsoqqabot.backtest.results import TradeRecord
from fxsoqqabot.backtest.stress_test import FeigenbaumStressTest
from fxsoqqabot.backtest.validation import MONTH_SECONDS, WalkForwardValidator
from fxsoqqabot.config.models import BotSettings


def _ts_to_str(ts: int) -> str:
    """Convert Unix timestamp (seconds) to readable UTC string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _pass_fail(passed: bool) -> str:
    """Return colored PASS/FAIL string."""
    if passed:
        return "\033[32mPASS\033[0m"
    return "\033[31mFAIL\033[0m"


async def run_full_backtest(
    settings: BotSettings,
    config: BacktestConfig | None = None,
    skip_ingestion: bool = False,
) -> None:
    """Orchestrate the full backtesting pipeline.

    Runs ingestion, walk-forward validation, OOS evaluation, and Monte Carlo
    simulation in sequence, printing formatted results for each stage.

    Args:
        settings: Bot settings (signal configs, risk params, etc.).
        config: Backtest configuration. If None, uses default BacktestConfig().
        skip_ingestion: If True, skip CSV-to-Parquet ingestion step.
    """
    if config is None:
        config = BacktestConfig()

    print()
    print("=" * 70)
    print("  FXSoqqaBot Backtest Pipeline")
    print("=" * 70)
    print()

    # ----------------------------------------------------------------
    # [1/6] Data Ingestion
    # ----------------------------------------------------------------
    print("[1/6] Data Ingestion")
    print("-" * 40)

    if skip_ingestion:
        print("  Skipped (--skip-ingestion flag)")
    else:
        loader = HistoricalDataLoader(config)
        report = loader.ingest_all()

        files_processed = report.get("files_processed", 0)
        final_rows = report.get("final_rows", 0)
        duplicates = report.get("duplicates_removed", 0)
        gaps = report.get("gaps_interpolated", 0)
        extreme = report.get("extreme_bars_removed", 0)
        date_range = report.get("date_range", (None, None))

        print(f"  Files processed:      {files_processed}")
        print(f"  Total rows:           {final_rows:,}")
        print(f"  Duplicates removed:   {duplicates:,}")
        print(f"  Gaps interpolated:    {gaps:,}")
        print(f"  Extreme bars removed: {extreme:,}")

        if date_range[0] is not None and date_range[1] is not None:
            print(f"  Date range:           {date_range[0]} -> {date_range[1]}")

    print()

    # ----------------------------------------------------------------
    # [2/6] Walk-Forward Validation
    # ----------------------------------------------------------------
    print("[2/6] Walk-Forward Validation")
    print("-" * 40)

    loader = HistoricalDataLoader(config)
    engine = BacktestEngine(settings, config)
    validator = WalkForwardValidator(engine, loader, config)

    wf_result = await validator.run_walk_forward()

    n_windows = len(wf_result.windows)
    print(f"  Windows:              {n_windows}")
    print(f"  Profitable:           {wf_result.profitable_pct * 100:.1f}% (req: {wf_result.min_profitable_pct_required * 100:.1f}%)")
    print(f"  Aggregate PF:         {wf_result.aggregate_profit_factor:.2f} (req: {wf_result.min_profit_factor_required:.2f})")
    print(f"  Status:               {_pass_fail(wf_result.passes_threshold)}")
    print()

    # Window detail table
    if n_windows > 0:
        print(f"  {'#':>3}  {'Val Period':<27}  {'Equity':>10}  {'PF':>8}  {'Win':>5}")
        print(f"  {'---':>3}  {'---------------------------':<27}  {'----------':>10}  {'--------':>8}  {'-----':>5}")
        for w in wf_result.windows:
            val_period = f"{_ts_to_str(w.val_start)} - {_ts_to_str(w.val_end)}"
            pf_str = f"{w.val_result.profit_factor:.2f}" if w.val_result.profit_factor != float("inf") else "inf"
            profitable = "Yes" if w.is_profitable else "No"
            print(f"  {w.window_idx:>3}  {val_period:<27}  ${w.val_result.final_equity:>9.2f}  {pf_str:>8}  {profitable:>5}")
        print()

    # ----------------------------------------------------------------
    # [3/6] Out-of-Sample Evaluation
    # ----------------------------------------------------------------
    print("[3/6] Out-of-Sample Evaluation")
    print("-" * 40)

    oos_result = await validator.evaluate_oos(wf_result)

    print(f"  OOS Profit Factor:    {oos_result.oos_profit_factor:.2f}")
    print(f"  OOS Max Drawdown:     {oos_result.oos_max_drawdown_pct * 100:.1f}%")
    print(f"  IS Profit Factor:     {oos_result.in_sample_profit_factor:.2f}")
    print(f"  IS Max Drawdown:      {oos_result.in_sample_max_drawdown_pct * 100:.1f}%")
    print(f"  PF Ratio (OOS/IS):    {oos_result.pf_ratio:.2f} (req: >= {config.oos_min_pf_ratio:.2f})")
    print(f"  DD Ratio (OOS/IS):    {oos_result.dd_ratio:.2f} (req: <= {config.oos_max_dd_ratio:.2f})")
    print(f"  Overfit Detected:     {'Yes' if oos_result.is_overfit else 'No'}")
    print(f"  Status:               {_pass_fail(oos_result.passes_threshold)}")
    print()

    # ----------------------------------------------------------------
    # [4/6] Monte Carlo Simulation
    # ----------------------------------------------------------------
    print("[4/6] Monte Carlo Simulation")
    print("-" * 40)

    # Collect ALL trade PnLs from validation windows
    all_pnls: list[float] = []
    for w in wf_result.windows:
        for trade in w.val_result.trades:
            all_pnls.append(trade.pnl)

    mc_passed = False
    if len(all_pnls) == 0:
        print("  WARNING: No trades found in validation windows. Skipping Monte Carlo.")
        print()
    else:
        trade_pnls = np.array(all_pnls, dtype=np.float64)
        mc_result = run_monte_carlo(
            trade_pnls,
            config.starting_equity,
            config.n_monte_carlo,
            config.mc_max_drawdown_pct,
            config.mc_seed,
        )
        mc_passed = mc_result.passes_threshold

        print(f"  Simulations:          {mc_result.n_simulations:,}")
        print(f"  5th Pct Equity:       ${mc_result.pct_5_equity:.2f}")
        print(f"  Median Equity:        ${mc_result.median_equity:.2f}")
        print(f"  95th Pct Max DD:      {mc_result.pct_95_max_dd * 100:.1f}% (req: < {config.mc_max_drawdown_pct * 100:.1f}%)")
        print(f"  P-Value:              {mc_result.p_value:.4f}")
        print(f"  Status:               {_pass_fail(mc_result.passes_threshold)}")
        print()

    # ----------------------------------------------------------------
    # [5/6] Regime-Aware Evaluation
    # ----------------------------------------------------------------
    print("[5/6] Regime-Aware Evaluation")
    print("-" * 40)

    # Collect all validation trades for regime evaluation
    all_val_trades: list[TradeRecord] = []
    for w in wf_result.windows:
        all_val_trades.extend(w.val_result.trades)

    if len(all_val_trades) == 0:
        print("  WARNING: No validation trades. Skipping regime evaluation.")
        regime_eval = None
    else:
        # Tag bars from the walk-forward data range (not full dataset -- Pitfall 5)
        data_start, data_end = loader.get_time_range()
        holdout_start = data_end - config.holdout_months * MONTH_SECONDS
        wf_bars = loader.load_bars(data_start, holdout_start)

        tagger = RegimeTagger(settings.signals.chaos)
        tags = await tagger.tag_bars(wf_bars)
        regime_eval = tagger.evaluate_regime_performance(tuple(all_val_trades), tags)

        print(f"  Regimes with trades:  {regime_eval.regimes_with_trades}/5")
        print(f"  Best regime:          {regime_eval.best_regime}")
        print(f"  Worst regime:         {regime_eval.worst_regime}")
        print()
        # Per-regime table
        print(f"  {'Regime':<20}  {'Trades':>7}  {'WinRate':>8}  {'PF':>8}  {'AvgPnL':>10}  {'TotalPnL':>10}")
        print(f"  {'--------------------':<20}  {'-------':>7}  {'--------':>8}  {'--------':>8}  {'----------':>10}  {'----------':>10}")
        for regime, perf in regime_eval.regime_performance.items():
            if perf.n_trades == 0:
                continue
            pf_str = f"{perf.profit_factor:.2f}" if perf.profit_factor != float("inf") else "inf"
            print(f"  {regime:<20}  {perf.n_trades:>7}  {perf.win_rate*100:>7.1f}%  {pf_str:>8}  ${perf.avg_pnl:>9.2f}  ${perf.total_pnl:>9.2f}")

    print()

    # ----------------------------------------------------------------
    # [6/6] Feigenbaum Stress Test
    # ----------------------------------------------------------------
    print("[6/6] Feigenbaum Stress Test")
    print("-" * 40)

    stress = FeigenbaumStressTest(settings.signals.chaos)
    stress_result = await stress.run_stress_test()

    print(f"  Pre-transition:        {stress_result.pre_transition_regime} (stable: {_pass_fail(stress_result.pre_transition_detected)})")
    print(f"  Transition:            {stress_result.transition_regime} (detected: {_pass_fail(stress_result.transition_detected)})")
    print(f"  Post-transition:       {stress_result.post_transition_regime} (chaos: {_pass_fail(stress_result.chaos_detected)})")
    print(f"  Bifurcation proximity: {stress_result.bifurcation_proximity_at_transition:.4f}")
    print(f"  Status:                {_pass_fail(stress_result.passes)}")
    print()

    # ----------------------------------------------------------------
    # Final Summary
    # ----------------------------------------------------------------
    print("=" * 70)
    # Regime eval is informational only (no pass/fail gate per Research recommendation)
    stress_passed = stress_result.passes
    overall_pass = (
        wf_result.passes_threshold
        and oos_result.passes_threshold
        and mc_passed
        and stress_passed
    )
    if overall_pass:
        print(f"  OVERALL: \033[32mPASS\033[0m - Strategy passes all validation gates")
    else:
        print(f"  OVERALL: \033[31mFAIL\033[0m - Strategy fails one or more validation gates")
        failures: list[str] = []
        if not wf_result.passes_threshold:
            failures.append("Walk-Forward")
        if not oos_result.passes_threshold:
            failures.append("OOS")
        if not mc_passed:
            failures.append("Monte Carlo")
        if not stress_passed:
            failures.append("Stress Test")
        print(f"  Failed:  {', '.join(failures)}")
    print("=" * 70)
    print()
