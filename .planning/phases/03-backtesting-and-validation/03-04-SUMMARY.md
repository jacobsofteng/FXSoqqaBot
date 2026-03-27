---
phase: 03-backtesting-and-validation
plan: 04
subsystem: testing
tags: [walk-forward, oos-holdout, overfitting, validation, backtest]

# Dependency graph
requires:
  - phase: 03-backtesting-and-validation/03-03
    provides: "BacktestEngine.run(), BacktestResult with profit_factor/max_drawdown_pct, HistoricalDataLoader.load_bars()/get_time_range()"
provides:
  - "WalkForwardValidator with generate_windows(), run_walk_forward(), evaluate_oos()"
  - "WindowResult, WalkForwardResult, OOSResult frozen dataclasses"
  - "Rolling 6m train + 2m val window generation excluding holdout period"
  - "Dual threshold pass/fail evaluation (70% profitable + PF > 1.5)"
  - "OOS hard fail detection (PF ratio < 0.50 or DD ratio > 2.0)"
affects: [03-backtesting-and-validation/03-05, self-learning]

# Tech tracking
tech-stack:
  added: []
  patterns: [frozen-dataclass-results, mock-engine-testing, calendar-month-approximation]

key-files:
  created:
    - src/fxsoqqabot/backtest/validation.py
    - tests/test_backtest/test_validation.py
  modified: []

key-decisions:
  - "Calendar month approximation: 30.44 days * 86400 seconds for consistent window boundaries"
  - "Aggregate in-sample metrics from training windows for OOS comparison (not validation windows)"
  - "Fixed parameters across all walk-forward windows per Pitfall 6 -- no per-window optimization"

patterns-established:
  - "Walk-forward window generation: data_range - holdout -> rolling windows with configurable train/val/step"
  - "Dual threshold validation: both criteria must pass for overall pass (AND logic)"
  - "OOS divergence detection: ratio-based comparison with configurable thresholds"

requirements-completed: [TEST-02, TEST-04]

# Metrics
duration: 4min
completed: 2026-03-27
---

# Phase 03 Plan 04: Walk-Forward Validation Summary

**Walk-forward coordinator with rolling 6m/2m windows, dual-threshold pass/fail (70% profitable + PF > 1.5), and OOS holdout with hard fail on divergence**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-27T14:32:09Z
- **Completed:** 2026-03-27T14:35:49Z
- **Tasks:** 1 (TDD: RED -> GREEN)
- **Files modified:** 2

## Accomplishments
- Walk-forward window generation that splits data into rolling 6-month train + 2-month validation windows, respecting holdout exclusion
- Dual-threshold walk-forward evaluation: >= 70% of windows must be net profitable AND aggregate profit factor must exceed 1.5 (D-06)
- Out-of-sample holdout evaluation with hard fail when OOS profit factor < 50% of in-sample or OOS max drawdown > 2x in-sample (D-13)
- 14 tests covering window generation, pass/fail thresholds, OOS divergence, and integration with mocked engine/loader

## Task Commits

Each task was committed atomically:

1. **Task 1: Walk-forward coordinator with rolling windows and dual threshold**
   - `68c698d` (test: add failing tests for walk-forward validation)
   - `684e64d` (feat: implement walk-forward validation and OOS holdout)

## Files Created/Modified
- `src/fxsoqqabot/backtest/validation.py` - WalkForwardValidator, WindowResult, WalkForwardResult, OOSResult
- `tests/test_backtest/test_validation.py` - 14 tests covering window generation, thresholds, OOS evaluation

## Decisions Made
- Calendar month approximation of 30.44 days * 86400 seconds for consistent window boundary computation
- In-sample metrics aggregated from training windows (not validation) for OOS comparison -- training is the true "in-sample" data
- Fixed parameters across all walk-forward windows per Pitfall 6: the purpose is generalization validation, not per-window optimization
- Division-by-zero guard on PF and DD ratios returns 0.0 when denominator is zero

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all data flows are fully wired through BacktestEngine and HistoricalDataLoader interfaces.

## Next Phase Readiness
- Walk-forward validation and OOS holdout evaluation complete
- Ready for Plan 05 (Monte Carlo simulation and regime-aware evaluation)
- WalkForwardResult provides the window-level trade data needed for Monte Carlo resampling

## Self-Check: PASSED

- [x] src/fxsoqqabot/backtest/validation.py exists
- [x] tests/test_backtest/test_validation.py exists
- [x] 03-04-SUMMARY.md exists
- [x] Commit 68c698d (test RED) exists
- [x] Commit 684e64d (feat GREEN) exists
- [x] All 14 tests pass

---
*Phase: 03-backtesting-and-validation*
*Completed: 2026-03-27*
