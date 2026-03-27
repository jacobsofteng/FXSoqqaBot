---
phase: 03-backtesting-and-validation
plan: 05
subsystem: backtesting
tags: [monte-carlo, regime-evaluation, feigenbaum, stress-testing, chaos, numpy]

# Dependency graph
requires:
  - phase: 03-backtesting-and-validation/03-03
    provides: BacktestResult with TradeRecord and backtest executor
provides:
  - run_monte_carlo function with MonteCarloResult (D-07 dual threshold)
  - RegimeTagger for tagging bars with RegimeState via chaos module (D-08)
  - RegimeEvalResult with per-regime RegimePerformance (D-08)
  - FeigenbaumStressTest generating synthetic bifurcation price series (TEST-06)
  - StressTestResult with phase detection accuracy tracking
affects: [03-backtesting-and-validation/03-04, walk-forward-validation, anti-overfitting]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Numpy vectorized Monte Carlo simulation with seed-based reproducibility"
    - "Numpy reshape-based M1-to-M5 resampling for chaos module input (no pandas groupby)"
    - "Three-phase synthetic bifurcation series: stable->period-doubling->chaotic"

key-files:
  created:
    - src/fxsoqqabot/backtest/monte_carlo.py
    - src/fxsoqqabot/backtest/regime_tagger.py
    - src/fxsoqqabot/backtest/stress_test.py
    - tests/test_backtest/test_monte_carlo.py
    - tests/test_backtest/test_regime_eval.py
  modified: []

key-decisions:
  - "D-07 dual threshold: criterion 1 (5th pct > starting) AND criterion 2 (median > starting AND 95th pct DD < 40%)"
  - "Monte Carlo p_value defined as fraction of runs with final equity below starting equity"
  - "Regime tagger forward-fills regime tags for bars before first analysis window"
  - "Stress test uses 200/100/200 bar split for pre-transition/transition/post-transition phases"

patterns-established:
  - "Frozen dataclass results (MonteCarloResult, RegimePerformance, RegimeEvalResult, StressTestResult) for immutable analysis outputs"
  - "Numpy reshape for M1-to-M5 resampling with configurable aggregation (last/first/max/min/sum)"

requirements-completed: [TEST-03, TEST-05, TEST-06]

# Metrics
duration: 6min
completed: 2026-03-27
---

# Phase 03 Plan 05: Monte Carlo Simulation, Regime Evaluation, and Feigenbaum Stress Testing Summary

**Monte Carlo trade sequence shuffler with D-07 dual threshold, regime-aware per-regime performance evaluation (5 RegimeStates), and Feigenbaum bifurcation stress testing with synthetic 3-phase price series**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-27T14:31:56Z
- **Completed:** 2026-03-27T14:38:46Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Monte Carlo simulation shuffles trade P&L sequences 10,000+ times, computes 5th/50th percentile equity and 95th percentile max drawdown, evaluates D-07 dual threshold with seed-based reproducibility
- Regime tagger runs chaos module over sliding bar windows to classify historical data into 5 RegimeState values, then evaluates per-regime win rate, profit factor, avg PnL for all regimes
- Feigenbaum stress test generates synthetic 3-phase price series (stable, period-doubling, chaotic) and verifies chaos module detects regime transitions

## Task Commits

Each task was committed atomically:

1. **Task 1: Monte Carlo trade sequence shuffler with dual threshold** - `14c7cc7` (feat)
2. **Task 2: Regime-aware evaluation tagger and Feigenbaum stress testing** - `bc8820e` (feat)

_Note: TDD tasks -- both tasks followed RED (failing tests) then GREEN (implementation) flow._

## Files Created/Modified
- `src/fxsoqqabot/backtest/monte_carlo.py` - MonteCarloResult dataclass and run_monte_carlo function per D-07
- `src/fxsoqqabot/backtest/regime_tagger.py` - RegimeTagger, RegimePerformance, RegimeEvalResult, evaluate_regime_performance per D-08
- `src/fxsoqqabot/backtest/stress_test.py` - FeigenbaumStressTest, StressTestResult, generate_bifurcation_price_series per TEST-06
- `tests/test_backtest/test_monte_carlo.py` - 11 tests covering MonteCarloResult, dual threshold, reproducibility, edge cases
- `tests/test_backtest/test_regime_eval.py` - 10 tests covering regime tagger, per-regime evaluation, stress test structure and properties

## Decisions Made
- D-07 dual threshold: criterion 1 (5th percentile equity > starting equity) AND criterion 2 (median equity > starting AND 95th percentile max DD < 40%) -- matches plan specification exactly
- Monte Carlo p_value defined as fraction of runs with final equity below starting equity -- standard statistical approach
- Regime tagger forward-fills regime classification for bars prior to first analysis window -- avoids NaN/None gaps
- Stress test uses 200/100/200 bar split for pre-transition/transition/post-transition phases -- sufficient data for each phase's statistical properties

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all functionality is fully wired to existing chaos module and backtest infrastructure.

## Next Phase Readiness
- Monte Carlo, regime evaluation, and stress testing complete all Plan 05 requirements
- These tools integrate with BacktestResult.trades from Plan 03 for full validation pipeline
- Ready for walk-forward validation integration in Plan 04

## Self-Check: PASSED

- All 5 created files exist on disk
- Commit 14c7cc7 (Task 1) found in git log
- Commit bc8820e (Task 2) found in git log
- 21/21 tests passing

---
*Phase: 03-backtesting-and-validation*
*Completed: 2026-03-27*
