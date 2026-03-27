---
phase: 02-signal-pipeline-and-decision-fusion
plan: 02
subsystem: signals
tags: [nolds, scipy, chaos, hurst, lyapunov, fractal, feigenbaum, entropy, regime, asyncio]

# Dependency graph
requires:
  - phase: 02-signal-pipeline-and-decision-fusion
    plan: 01
    provides: "SignalModule Protocol, SignalOutput dataclass, RegimeState enum, ChaosConfig model, nolds/scipy dependencies"
provides:
  - "compute_hurst() -- Hurst exponent via nolds.hurst_rs for trend/mean-reversion classification"
  - "compute_lyapunov() -- Largest Lyapunov exponent via nolds.lyap_r Rosenstein algorithm"
  - "compute_fractal_dimension() -- Correlation dimension via nolds.corr_dim Grassberger-Procaccia"
  - "detect_bifurcation_proximity() -- Feigenbaum period-doubling ratio detection"
  - "compute_crowd_entropy() -- Shannon entropy on log-return distribution via scipy.stats"
  - "classify_regime() -- Threshold-based 5-state regime classifier combining all metrics"
  - "ChaosRegimeModule -- Full SignalModule Protocol implementation for chaos/regime detection"
affects: [02-05-decision-fusion, 02-06-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure function chaos metrics: accept numpy arrays, return (value, confidence) tuples"
    - "asyncio.to_thread for blocking nolds/scipy computations off the event loop"
    - "Threshold-based regime classification with priority ordering"
    - "Safe defaults with zero confidence for insufficient data"

key-files:
  created:
    - src/fxsoqqabot/signals/chaos/hurst.py
    - src/fxsoqqabot/signals/chaos/lyapunov.py
    - src/fxsoqqabot/signals/chaos/fractal.py
    - src/fxsoqqabot/signals/chaos/feigenbaum.py
    - src/fxsoqqabot/signals/chaos/entropy.py
    - src/fxsoqqabot/signals/chaos/regime.py
    - src/fxsoqqabot/signals/chaos/module.py
  modified:
    - src/fxsoqqabot/signals/chaos/__init__.py
    - tests/signals/test_chaos.py

key-decisions:
  - "nolds RANSAC fit mode gracefully falls back to poly when sklearn unavailable -- acceptable for v1"
  - "Feigenbaum delta constant at module level (4.669201609) referenced by function -- clean separation"
  - "Price direction from 20-bar lookback (close[-1] - close[-20]) -- simple and effective"

patterns-established:
  - "Chaos metric pattern: pure function, numpy-in tuple-out, min_length guard, try/except fallback"
  - "Confidence scaling: linear from 0.0 to 1.0 at metric-specific data length thresholds"
  - "Regime priority: PRE_BIFURCATION > HIGH_CHAOS > TRENDING > RANGING > default"

requirements-completed: [CHAOS-01, CHAOS-02, CHAOS-03, CHAOS-04, CHAOS-05, CHAOS-06]

# Metrics
duration: 6min
completed: 2026-03-27
---

# Phase 02 Plan 02: Chaos Regime Module Summary

**Six chaos metrics (Hurst, Lyapunov, fractal, Feigenbaum, entropy) with threshold-based 5-state regime classifier via ChaosRegimeModule implementing SignalModule Protocol**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-27T12:15:09Z
- **Completed:** 2026-03-27T12:20:52Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- Implemented all 5 individual chaos metrics using nolds and scipy as the scientific computing backend
- Built threshold-based regime classifier combining all metrics into 5 discrete market states with confidence levels
- ChaosRegimeModule passes SignalModule Protocol isinstance check with full async support
- All computations run via asyncio.to_thread for non-blocking event loop operation
- Graceful degradation: insufficient data returns safe defaults (random walk / neutral) with zero confidence

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement individual chaos metrics** - TDD RED `900490e` (test) + GREEN `a4cdefb` (feat)
2. **Task 2: Implement regime classifier and ChaosRegimeModule** - TDD RED `68a99b8` (test) + GREEN `dc2b082` (feat)

_Note: TDD tasks have separate test and implementation commits._

## Files Created/Modified
- `src/fxsoqqabot/signals/chaos/hurst.py` - Hurst exponent via nolds.hurst_rs with [0,1] clamping (CHAOS-01)
- `src/fxsoqqabot/signals/chaos/lyapunov.py` - Largest Lyapunov exponent via nolds.lyap_r Rosenstein (CHAOS-02)
- `src/fxsoqqabot/signals/chaos/fractal.py` - Correlation dimension via nolds.corr_dim Grassberger-Procaccia (CHAOS-03)
- `src/fxsoqqabot/signals/chaos/feigenbaum.py` - Bifurcation proximity via period-doubling peak ratios (CHAOS-04)
- `src/fxsoqqabot/signals/chaos/entropy.py` - Shannon entropy on log-return distribution via scipy.stats (CHAOS-05)
- `src/fxsoqqabot/signals/chaos/regime.py` - Threshold-based 5-state regime classifier (CHAOS-06)
- `src/fxsoqqabot/signals/chaos/module.py` - ChaosRegimeModule implementing SignalModule Protocol
- `src/fxsoqqabot/signals/chaos/__init__.py` - Package exports ChaosRegimeModule
- `tests/signals/test_chaos.py` - 44 tests covering all metrics, regime classifier, and module

## Decisions Made
- nolds RANSAC fit mode gracefully falls back to poly when sklearn is not installed -- the warning is harmless and the algorithm still works. sklearn will be added in Phase 4 for ML classifiers.
- Feigenbaum delta constant (4.669201609) defined at module level and referenced by the function -- keeps the function body clean while making the constant searchable.
- Price direction computed from 20-bar lookback (close[-1] - close[-20]) -- simple sign-based direction is sufficient for regime classification; more sophisticated trend detection is not needed at this stage.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Chaos/regime module complete and ready for fusion integration (Plan 02-05)
- ChaosRegimeModule satisfies SignalModule Protocol -- can be plugged into the signal analysis loop
- All 6 CHAOS requirements implemented and tested
- 44 tests passing with full coverage of edge cases and regime classification logic

## Self-Check: PASSED

All 9 created/modified files verified present. All 4 commits (900490e, a4cdefb, 68a99b8, dc2b082) verified in git log.

---
*Phase: 02-signal-pipeline-and-decision-fusion*
*Completed: 2026-03-27*
