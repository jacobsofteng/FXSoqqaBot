# Phase 7: Validation Pipeline Entry Points - Research

**Researched:** 2026-03-28
**Domain:** CLI wiring, backtest pipeline integration, regime-aware evaluation, chaos stress testing
**Confidence:** HIGH

## Summary

Phase 7 closes two orphaned integration gaps identified in the v1.0 milestone audit: `RegimeTagger` (TEST-05) and `FeigenbaumStressTest` (TEST-06) are fully implemented with passing tests (10 tests total) but have zero callers anywhere in the codebase. No runner, CLI command, or other module ever imports or invokes them.

The work is purely integration wiring. Both classes already exist in `src/fxsoqqabot/backtest/regime_tagger.py` and `src/fxsoqqabot/backtest/stress_test.py` with complete implementations, including data classes for results (`RegimeEvalResult`, `RegimePerformance`, `StressTestResult`). The task is to: (1) add CLI subcommands that invoke them, (2) integrate them into the existing `run_full_backtest()` runner so they execute as part of the standard validation pipeline.

**Primary recommendation:** Add two new CLI subcommands (`validate-regimes` and `stress-test`) and extend `run_full_backtest()` in `runner.py` to call both tools as steps [5/6] and [6/6] after the existing Monte Carlo step, with formatted console output matching the existing runner pattern.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TEST-05 | Regime-aware evaluation measures performance separately across trending, ranging, high-volatility, low-volatility, and news-driven market regimes | `RegimeTagger` class exists with `tag_bars()` and `evaluate_regime_performance()`. Needs CLI entry point + runner integration to make it callable. |
| TEST-06 | Feigenbaum stress testing injects simulated regime transitions into backtests to verify the chaos module correctly anticipates and adapts to bifurcation events | `FeigenbaumStressTest` class exists with `run_stress_test()` and `generate_bifurcation_price_series()`. Needs CLI entry point + runner integration to make it callable. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **CLI pattern:** argparse with subcommands dispatched from `main()` in `cli.py`. Async commands wrapped in `asyncio.run()`, sync commands returned as `None`.
- **Testing:** pytest with `pytest-asyncio` for async tests. Test at component level with mocked I/O.
- **Logging:** structlog with context binding (`component=` key).
- **Config:** `BotSettings` loaded via `load_settings(args.config)`. `ChaosConfig` accessed as `settings.signals.chaos`.
- **Backtest config:** `BacktestConfig` Pydantic model, separate from `BotSettings`.
- **Type safety:** Pydantic for config validation, frozen dataclasses for results.
- **Code organization:** All backtest modules under `src/fxsoqqabot/backtest/`.

## Standard Stack

No new libraries needed. This phase exclusively wires existing components.

### Core (already installed)
| Library | Version | Purpose | Already Used In |
|---------|---------|---------|-----------------|
| argparse | stdlib | CLI subcommand dispatch | `cli.py` |
| structlog | 25.5.0 | Structured logging | All modules |
| numpy | 2.4.3 | Array operations for regime tagger | `regime_tagger.py`, `stress_test.py` |
| pandas | 2.2.x | DataFrame for bar data | `regime_tagger.py`, `engine.py` |
| pydantic | 2.12.5 | Config validation | `config/models.py`, `backtest/config.py` |

## Architecture Patterns

### Existing Runner Pattern (MUST follow)
The `run_full_backtest()` function in `runner.py` uses a numbered step pattern:
```
[1/4] Data Ingestion
[2/4] Walk-Forward Validation
[3/4] Out-of-Sample Evaluation
[4/4] Monte Carlo Simulation
```
Each step prints a header, runs the operation, prints formatted results, and contributes to a final pass/fail summary. The new tools extend this to [1/6] through [6/6].

### Existing CLI Pattern (MUST follow)
Every CLI subcommand in `cli.py` follows this pattern:
1. Add subparser via `subparsers.add_parser("name", help="...")`
2. Add `--config` argument for TOML overrides
3. Define `async def cmd_name(args)` or `def cmd_name(args)` function
4. Load settings via `load_settings(args.config)`
5. Register in `commands` dict in `main()`
6. Async commands return coroutines, dispatched via `asyncio.run()`

### Existing Test Pattern (MUST follow)
Test file `tests/test_backtest/test_regime_eval.py` already has 10 tests covering:
- `RegimeTagger.tag_bars()` with mocked chaos module
- `evaluate_regime_performance()` grouping and metrics
- `FeigenbaumStressTest.generate_bifurcation_price_series()` shape and properties
- `StressTestResult` structure
New tests should cover the CLI wiring and runner integration, not re-test the existing classes.

### Recommended Changes Structure
```
src/fxsoqqabot/
  cli.py                    # Add 2 new subcommands: validate-regimes, stress-test
  backtest/
    runner.py               # Extend run_full_backtest() to [6/6] steps
tests/
  test_backtest/
    test_validation_pipeline.py   # New: test CLI dispatch and runner integration
```

### Pattern 1: CLI Subcommand for Regime Evaluation
**What:** Add `validate-regimes` subcommand that loads backtest data, tags bars with regimes via `RegimeTagger`, then evaluates per-regime performance on backtest trades.
**When to use:** Standalone analysis of existing backtest results, or post-backtest regime breakdown.
**Key implementation detail:** The `RegimeTagger` needs:
1. A `ChaosConfig` (from `settings.signals.chaos`)
2. A bars DataFrame (from `HistoricalDataLoader.load_bars()`)
3. Trade records (from running a backtest via `BacktestEngine`)

The flow is: load settings -> load historical data -> run backtest -> tag bars -> evaluate per-regime performance -> print formatted results.

```python
# Source: existing cli.py pattern
async def cmd_validate_regimes(args: argparse.Namespace) -> None:
    """Run regime-aware evaluation on backtest results."""
    from fxsoqqabot.backtest.config import BacktestConfig
    from fxsoqqabot.backtest.engine import BacktestEngine
    from fxsoqqabot.backtest.historical import HistoricalDataLoader
    from fxsoqqabot.backtest.regime_tagger import RegimeTagger

    settings = load_settings(args.config)
    _setup_logging(settings)
    bt_config = BacktestConfig()

    # Load data, run backtest, tag regimes, evaluate
    loader = HistoricalDataLoader(bt_config)
    start, end = loader.get_time_range()
    bars_df = loader.load_bars(start, end)

    engine = BacktestEngine(settings, bt_config)
    result = await engine.run(bars_df, run_id="regime_eval")

    tagger = RegimeTagger(settings.signals.chaos)
    tags = await tagger.tag_bars(bars_df)
    eval_result = tagger.evaluate_regime_performance(result.trades, tags)

    # Print formatted results (matching runner style)
    _print_regime_eval(eval_result)
```

### Pattern 2: CLI Subcommand for Feigenbaum Stress Test
**What:** Add `stress-test` subcommand that runs the Feigenbaum stress test with synthetic data.
**When to use:** Verify chaos module correctly detects regime transitions.
**Key implementation detail:** The `FeigenbaumStressTest` is self-contained -- it generates its own synthetic data and runs the chaos module internally. It only needs a `ChaosConfig`.

```python
# Source: existing cli.py pattern
async def cmd_stress_test(args: argparse.Namespace) -> None:
    """Run Feigenbaum stress test on chaos module."""
    from fxsoqqabot.backtest.stress_test import FeigenbaumStressTest

    settings = load_settings(args.config)
    _setup_logging(settings)

    stress = FeigenbaumStressTest(settings.signals.chaos)
    result = await stress.run_stress_test()

    # Print formatted results
    _print_stress_test(result)
```

### Pattern 3: Runner Integration
**What:** Extend `run_full_backtest()` to run RegimeTagger and FeigenbaumStressTest as steps 5 and 6.
**When to use:** Every time the full backtest pipeline runs.
**Key implementation detail:** After Monte Carlo (step 4), add:
- Step 5: Regime-aware evaluation using trades from walk-forward windows + regime tagging on all data
- Step 6: Feigenbaum stress test (independent of backtest data, uses synthetic series)

Both contribute to the overall pass/fail summary.

### Anti-Patterns to Avoid
- **Re-implementing existing classes:** Both `RegimeTagger` and `FeigenbaumStressTest` are complete. Do not modify their internals.
- **Breaking the existing 4-step runner:** The existing steps must continue to work exactly as before. Only ADD steps 5 and 6.
- **Adding new config parameters:** Both tools use `ChaosConfig` which already exists with all needed parameters.
- **Heavy coupling:** The standalone CLI commands should work independently of `run_full_backtest()`. Both entry points (standalone CLI and integrated runner) should exist.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Regime classification | Custom regime classifier | `RegimeTagger` (already built) | Runs the actual `ChaosRegimeModule` over bar data windows |
| Stress test data generation | Manual synthetic data creation | `FeigenbaumStressTest.generate_bifurcation_price_series()` | Already implements 3-phase bifurcation series with correct statistical properties |
| Per-regime metrics | Custom P&L grouping | `RegimeTagger.evaluate_regime_performance()` | Already computes win_rate, profit_factor, avg_pnl, total_pnl, max_drawdown per regime |
| Formatted output | Custom formatting | Follow `runner.py` `_pass_fail()` and print pattern | Consistent visual output across all pipeline steps |

**Key insight:** This phase is 100% wiring. Every computational component already exists and is tested. The only work is creating entry points that call them.

## Common Pitfalls

### Pitfall 1: RegimeTagger Needs Full Bar Data for Tagging
**What goes wrong:** Calling `tag_bars()` with insufficient data (< window_size bars) results in all bars tagged as RANGING, giving meaningless regime evaluation.
**Why it happens:** `tag_bars()` requires `window_size` (default 300) M1 bars minimum. Short data periods produce no meaningful regime diversity.
**How to avoid:** Use the full historical data range from `loader.get_time_range()` for tagging, not just a single walk-forward window. The tags are then applied to trades from all windows.
**Warning signs:** `regimes_with_trades == 1` in the output (all trades in RANGING).

### Pitfall 2: Trade Entry Times Must Match Bar Timestamps
**What goes wrong:** `evaluate_regime_performance()` looks up `trade.entry_time` in the `regime_tags` dict. If entry_time doesn't match any tagged bar timestamp, the trade falls back to its `.regime` field (set during backtest).
**Why it happens:** `RegimeTagger.tag_bars()` uses the bar's `time` column as keys (unix seconds). `TradeRecord.entry_time` is also unix seconds. But if the bar data was loaded from a different range than what the trades were executed on, keys won't match.
**How to avoid:** Tag the same bars that the backtest ran on. When integrating into the runner, use the same data range for both the backtest engine and the regime tagger.
**Warning signs:** Regime distribution doesn't change whether you pass `regime_tags` or not.

### Pitfall 3: FeigenbaumStressTest Is Async
**What goes wrong:** Calling `run_stress_test()` without `await` in the CLI handler.
**Why it happens:** The method is `async def run_stress_test()` because it calls `ChaosRegimeModule.update()` which is async.
**How to avoid:** Ensure the CLI command handler is `async def` and returns a coroutine that `main()` dispatches via `asyncio.run()`.
**Warning signs:** TypeError about coroutine not being awaited.

### Pitfall 4: Runner Step Numbering
**What goes wrong:** Changing step numbers from `[1/4]` to `[1/6]` breaks any downstream scripts or tests that parse the output.
**Why it happens:** When extending the pipeline from 4 to 6 steps.
**How to avoid:** Update ALL step headers consistently. Check that existing tests don't assert on specific step numbers. (Current tests use backtest engine/validation directly, not the runner's print output, so this is low risk.)
**Warning signs:** Step headers showing wrong totals like `[1/4]` mixed with `[5/6]`.

### Pitfall 5: Regime Tagging Is Slow on Large Datasets
**What goes wrong:** `tag_bars()` runs the chaos module over sliding windows of the full historical dataset. With 10+ years of M1 data (~5M bars), this can take significant time.
**Why it happens:** Each chaos module `update()` call involves Hurst exponent, Lyapunov exponent, fractal dimension, and entropy computations. Even with `window_size//10` step size, that's ~50K+ chaos module evaluations on 10 years of data.
**How to avoid:** For the runner integration, tag bars from the validation windows only (not the full dataset). For standalone CLI, warn about execution time or allow limiting the date range.
**Warning signs:** Pipeline hangs at the regime evaluation step for minutes/hours.

## Code Examples

### Example 1: Formatted Regime Eval Output (follows runner.py pattern)
```python
# Source: derived from runner.py print pattern
def _print_regime_eval(eval_result: RegimeEvalResult) -> None:
    """Print regime evaluation results in runner format."""
    print(f"  Regimes with trades:  {eval_result.regimes_with_trades}/5")
    print(f"  Best regime:          {eval_result.best_regime}")
    print(f"  Worst regime:         {eval_result.worst_regime}")
    print()
    # Per-regime table
    print(f"  {'Regime':<20}  {'Trades':>7}  {'WinRate':>8}  {'PF':>8}  {'AvgPnL':>10}  {'TotalPnL':>10}")
    print(f"  {'--------------------':<20}  {'-------':>7}  {'--------':>8}  {'--------':>8}  {'----------':>10}  {'----------':>10}")
    for regime, perf in eval_result.regime_performance.items():
        pf_str = f"{perf.profit_factor:.2f}" if perf.profit_factor != float("inf") else "inf"
        print(f"  {regime:<20}  {perf.n_trades:>7}  {perf.win_rate*100:>7.1f}%  {pf_str:>8}  ${perf.avg_pnl:>9.2f}  ${perf.total_pnl:>9.2f}")
```

### Example 2: Formatted Stress Test Output
```python
# Source: derived from runner.py print pattern
def _print_stress_test(result: StressTestResult) -> None:
    """Print stress test results in runner format."""
    print(f"  Pre-transition:       {result.pre_transition_regime} (stable: {_pass_fail(result.pre_transition_detected)})")
    print(f"  Transition:           {result.transition_regime} (detected: {_pass_fail(result.transition_detected)})")
    print(f"  Post-transition:      {result.post_transition_regime} (chaos: {_pass_fail(result.chaos_detected)})")
    print(f"  Bifurcation proximity:{result.bifurcation_proximity_at_transition:.4f}")
    print(f"  Status:               {_pass_fail(result.passes)}")
```

### Example 3: Runner Extension (steps 5 and 6)
```python
# Source: derived from existing runner.py structure
# [5/6] Regime-Aware Evaluation
print("[5/6] Regime-Aware Evaluation")
print("-" * 40)

tagger = RegimeTagger(settings.signals.chaos)
# Tag bars from ALL validation windows combined
all_bars = loader.load_bars(data_start, holdout_start)  # same range as walk-forward
tags = await tagger.tag_bars(all_bars)

# Collect trades from all validation windows
all_val_trades = []
for w in wf_result.windows:
    all_val_trades.extend(w.val_result.trades)

regime_eval = tagger.evaluate_regime_performance(tuple(all_val_trades), tags)
# ... print formatted results ...

# [6/6] Feigenbaum Stress Test
print("[6/6] Feigenbaum Stress Test")
print("-" * 40)

stress = FeigenbaumStressTest(settings.signals.chaos)
stress_result = await stress.run_stress_test()
# ... print formatted results ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Classes implemented but orphaned | CLI + runner entry points | Phase 7 (this phase) | TEST-05, TEST-06 satisfied |
| 4-step backtest pipeline | 6-step pipeline with regime eval + stress test | Phase 7 (this phase) | Complete validation pipeline |

## Open Questions

1. **Date range for standalone `validate-regimes` command**
   - What we know: Full historical dataset can be 10+ years of M1 data. Running `tag_bars()` on the entire dataset is slow.
   - What's unclear: Should standalone CLI default to full data or allow `--start-date` / `--end-date` args?
   - Recommendation: Default to full data with `--skip-ingestion` flag (matching backtest command). Add optional `--start-date` and `--end-date` if the planner decides it's worth the complexity. Given coarse granularity, defaulting to full data is sufficient.

2. **Regime eval pass/fail criteria**
   - What we know: `RegimeEvalResult` reports best/worst regime and per-regime metrics, but has no `passes` boolean field.
   - What's unclear: Should the runner apply a pass/fail threshold (e.g., "strategy must be profitable in at least 3 of 5 regimes")?
   - Recommendation: Report only (no pass/fail gate) for v1. The regime eval is informational -- it tells you WHERE the strategy works, not whether it should trade. Adding a hard gate is a policy decision that should come after observing real data. Include the report in the output but don't contribute to overall pass/fail.

3. **Stress test pass/fail contribution**
   - What we know: `StressTestResult.passes` is already a boolean (True if transition_detected AND chaos_detected).
   - What's unclear: Should stress test failure cause the overall backtest pipeline to fail?
   - Recommendation: Yes, include in overall pass/fail. The chaos module's ability to detect regime transitions is a fundamental requirement (CHAOS-04, CHAOS-06). If it can't detect synthetic bifurcation, the entire chaos signal is unreliable.

## Sources

### Primary (HIGH confidence)
- `src/fxsoqqabot/backtest/regime_tagger.py` - Complete RegimeTagger implementation (354 lines)
- `src/fxsoqqabot/backtest/stress_test.py` - Complete FeigenbaumStressTest implementation (251 lines)
- `src/fxsoqqabot/backtest/runner.py` - Existing run_full_backtest() pattern (199 lines)
- `src/fxsoqqabot/cli.py` - Existing CLI structure with 8 subcommands (461 lines)
- `tests/test_backtest/test_regime_eval.py` - Existing 10 tests for both classes
- `.planning/v1.0-MILESTONE-AUDIT.md` - Audit confirming TEST-05/TEST-06 orphaned status

### Secondary (HIGH confidence)
- `src/fxsoqqabot/backtest/engine.py` - BacktestEngine producing TradeRecord tuples
- `src/fxsoqqabot/backtest/results.py` - TradeRecord and BacktestResult data classes
- `src/fxsoqqabot/backtest/config.py` - BacktestConfig with all parameters
- `src/fxsoqqabot/backtest/historical.py` - HistoricalDataLoader with load_bars() and get_time_range()
- `src/fxsoqqabot/config/models.py` - ChaosConfig at settings.signals.chaos

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new libraries, all existing code
- Architecture: HIGH - Follows established patterns visible in cli.py and runner.py
- Pitfalls: HIGH - Identified from reading actual source code and understanding data flow

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (stable -- all code already exists, just needs wiring)
