---
phase: 04-observability-and-self-learning
plan: 04
subsystem: learning
tags: [deap, genetic-algorithm, ema, signal-analysis, rule-retirement, evolution]

# Dependency graph
requires:
  - phase: 04-01
    provides: "LearningConfig, TradeContextLogger, TradingEngineState"
provides:
  - "EvolutionManager: DEAP-based GA evolution engine with phase-aware fitness"
  - "SignalAnalyzer: signal combination win rate analysis and degrading rule detection"
  - "RuleRetirementTracker: EMA-based rule retirement with cooldown pool"
  - "PARAM_BOUNDS: 10 strategy-level parameters the GA evolves"
affects: [04-05, 04-06]

# Tech tracking
tech-stack:
  added: [deap]
  patterns: [phase-aware-fitness, ema-decay-retirement, cooldown-pool-reactivation]

key-files:
  created:
    - src/fxsoqqabot/learning/evolution.py
    - src/fxsoqqabot/learning/analyzer.py
    - src/fxsoqqabot/learning/retirement.py
    - tests/test_evolution.py
    - tests/test_analyzer.py
    - tests/test_retirement.py
  modified: []

key-decisions:
  - "DEAP creator.create at module level with hasattr guard to avoid duplicate registration"
  - "Profit factor capped at 10.0 to avoid infinity when no losses"
  - "Sample standard deviation (N-1) for Sharpe ratio to match statistics.stdev"
  - "Max drawdown penalty normalized by peak equity as fraction"
  - "Signal active threshold at 0.4 confidence for combination analysis"
  - "15 percentage-point decline threshold for degrading rule detection"

patterns-established:
  - "Phase-aware fitness: profit_factor (aggressive), Sharpe (selective), Sharpe-DD (conservative)"
  - "EMA-based retirement mirrors AdaptiveWeightTracker pattern from signals/fusion/weights.py"
  - "Cooldown pool with metadata (retired_at, ema_at_retirement) for never-delete rule lifecycle"

requirements-completed: [LEARN-02, LEARN-05]

# Metrics
duration: 7min
completed: 2026-03-27
---

# Phase 04 Plan 04: GA Evolution Engine Summary

**DEAP-based GA evolution engine with phase-aware fitness, signal combination analyzer, and EMA-based rule retirement tracker with cooldown pool**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-27T18:30:10Z
- **Completed:** 2026-03-27T18:37:09Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- DEAP GA evolution engine evolving 10 strategy parameters with bounds enforcement and phase-aware fitness (profit factor / Sharpe / Sharpe-DD)
- Signal combination analyzer identifying winning 2-module and 3-module combos, per-regime performance, and degrading rules
- EMA-based rule retirement tracker mirroring AdaptiveWeightTracker pattern with cooldown pool and reactivation support
- 48 tests covering all GA, analyzer, and retirement behaviors

## Task Commits

Each task was committed atomically:

1. **Task 1: DEAP-based EvolutionManager with phase-aware fitness** - `6acdd8e` (feat)
2. **Task 2: Signal combination analyzer and EMA rule retirement tracker** - `db00c0e` (feat)

_Note: TDD tasks -- tests written first (RED), implementation passes all tests (GREEN)._

## Files Created/Modified
- `src/fxsoqqabot/learning/evolution.py` - DEAP GA evolution manager with PARAM_BOUNDS, phase-aware fitness, population management
- `src/fxsoqqabot/learning/analyzer.py` - Signal combination analysis, regime performance, degrading rule detection
- `src/fxsoqqabot/learning/retirement.py` - EMA-based rule retirement with cooldown pool and reactivation
- `tests/test_evolution.py` - 22 tests for EvolutionManager
- `tests/test_analyzer.py` - 11 tests for SignalAnalyzer
- `tests/test_retirement.py` - 15 tests for RuleRetirementTracker

## Decisions Made
- DEAP creator.create at module level with hasattr guard to avoid duplicate class registration across test runs
- Profit factor capped at 10.0 to avoid infinity division when no losing trades
- Sample standard deviation (N-1 denominator) for Sharpe ratio consistency with statistics.stdev
- Max drawdown penalty normalized by peak equity value as a fraction
- Signal combination analysis uses 0.4 confidence threshold for "active" module detection
- Degrading rule detection uses 15 percentage-point decline between overall and recent window
- GA explicitly excludes module internals (hurst_window, lyapunov_embedding_dim, fractal_rmin) -- only evolves strategy-level parameters

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing DEAP dependency**
- **Found during:** Task 1 (EvolutionManager implementation)
- **Issue:** DEAP 1.4.3 not installed in virtual environment
- **Fix:** Installed via `uv pip install deap` into the project venv
- **Files modified:** None (runtime dependency only)
- **Verification:** `import deap` succeeds, all tests pass

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary dependency installation. No scope creep.

## Issues Encountered
- Python 3.15 system interpreter cannot build numpy from source (no C compiler). Used project venv with Python 3.12 and PYTHONPATH for test execution in worktree.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- EvolutionManager, SignalAnalyzer, RuleRetirementTracker ready for integration
- Shadow mode (04-05) can use EvolutionManager for variant parameter generation
- Learning orchestrator (04-05/04-06) can wire these components together

## Self-Check: PASSED

All 7 files verified present. Both task commits (6acdd8e, db00c0e) verified in git log. 48 tests passing.

---
*Phase: 04-observability-and-self-learning*
*Completed: 2026-03-27*
