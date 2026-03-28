---
phase: 07-validation-pipeline-entry-points
plan: 01
subsystem: testing
tags: [cli, backtest, regime-tagger, stress-test, feigenbaum, chaos]

# Dependency graph
requires:
  - phase: 03-backtesting-and-validation
    provides: BacktestEngine, WalkForwardValidator, HistoricalDataLoader, Monte Carlo
  - phase: 02-signal-pipeline-and-decision-fusion
    provides: ChaosRegimeModule, RegimeState
provides:
  - validate-regimes CLI subcommand for standalone regime evaluation
  - stress-test CLI subcommand for standalone Feigenbaum stress testing
  - 6-step backtest runner with regime eval (step 5) and stress test (step 6)
  - Stress test contributes to overall pipeline pass/fail verdict
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Informational-only pipeline step (regime eval does not gate pass/fail)"
    - "Async CLI handler with lazy imports for backtest components"

key-files:
  created: []
  modified:
    - src/fxsoqqabot/cli.py
    - src/fxsoqqabot/backtest/runner.py

key-decisions:
  - "Regime eval is informational only -- does not contribute to pipeline pass/fail per research recommendation"
  - "Stress test failure causes overall FAIL -- it validates chaos module correctness"
  - "Import _ts_to_str and _pass_fail from runner.py in CLI helpers to avoid code duplication"

patterns-established:
  - "Informational pipeline step: step 5 reports metrics without gating the verdict"
  - "Pipeline gate step: step 6 stress test contributes to pass/fail like steps 2-4"

requirements-completed: [TEST-05, TEST-06]

# Metrics
duration: 3min
completed: 2026-03-28
---

# Phase 07 Plan 01: Validation Pipeline Entry Points Summary

**CLI subcommands (validate-regimes, stress-test) and 6-step backtest runner wiring RegimeTagger and FeigenbaumStressTest into the validation pipeline**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-28T09:18:48Z
- **Completed:** 2026-03-28T09:22:01Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Two new CLI subcommands (validate-regimes, stress-test) registered and callable from command line
- Backtest runner extended from 4 to 6 steps with regime-aware evaluation and Feigenbaum stress test
- Stress test pass/fail contributes to overall pipeline verdict; regime eval is informational only
- Both subcommands follow existing CLI patterns with --config and --skip-ingestion args

## Task Commits

Each task was committed atomically:

1. **Task 1: Add validate-regimes and stress-test CLI subcommands** - `68a1fad` (feat)
2. **Task 2: Extend backtest runner from 4 steps to 6 steps** - `a405c23` (feat)

## Files Created/Modified
- `src/fxsoqqabot/cli.py` - Added validate-regimes and stress-test subparsers, async handler functions, formatted output helpers, and command dispatch entries
- `src/fxsoqqabot/backtest/runner.py` - Extended from 4 to 6 pipeline steps, added RegimeTagger/FeigenbaumStressTest imports, updated all step headers to /6, added stress_passed to overall_pass

## Decisions Made
- Regime eval is informational only -- does not contribute to pipeline pass/fail per research recommendation
- Stress test failure causes overall FAIL -- it validates chaos module correctness
- Import _ts_to_str and _pass_fail from runner.py in CLI helpers to avoid code duplication
- MONTH_SECONDS imported from validation.py for consistent holdout boundary calculation

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all functions are fully wired to real implementations (RegimeTagger, FeigenbaumStressTest).

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Both CLI entry points are ready for Phase 07-02 integration tests
- Runner pipeline is complete at 6 steps for end-to-end validation

## Self-Check: PASSED

- FOUND: src/fxsoqqabot/cli.py
- FOUND: src/fxsoqqabot/backtest/runner.py
- FOUND: 07-01-SUMMARY.md
- FOUND: commit 68a1fad (Task 1)
- FOUND: commit a405c23 (Task 2)

---
*Phase: 07-validation-pipeline-entry-points*
*Completed: 2026-03-28*
