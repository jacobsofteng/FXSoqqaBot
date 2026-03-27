---
phase: 02-signal-pipeline-and-decision-fusion
plan: 04
subsystem: signals
tags: [scipy, numpy, ornstein-uhlenbeck, atr, phase-transition, timing, mean-reversion, volatility]

# Dependency graph
requires:
  - phase: 02-signal-pipeline-and-decision-fusion
    plan: 01
    provides: "SignalModule Protocol, SignalOutput dataclass, TimingConfig, signal package structure"
provides:
  - "QuantumTimingModule implementing SignalModule Protocol"
  - "OU process parameter estimation (kappa, theta, sigma) via OLS regression"
  - "Entry/exit timing windows with half-life, urgency, and confidence"
  - "ATR computation with Wilder smoothing"
  - "Volatility compression/expansion phase transition detection"
  - "Energy model: compression stores energy, expansion releases it"
affects: [02-05-decision-fusion, 02-06-integration]

# Tech tracking
tech-stack:
  added: []
  patterns: [OU mean-reversion timing, Wilder ATR smoothing, volatility energy model, asyncio.to_thread for numerical offload]

key-files:
  created:
    - src/fxsoqqabot/signals/timing/ou_model.py
    - src/fxsoqqabot/signals/timing/phase_transition.py
    - src/fxsoqqabot/signals/timing/module.py
    - tests/signals/test_timing.py
  modified:
    - src/fxsoqqabot/signals/timing/__init__.py

key-decisions:
  - "OLS regression for OU estimation rather than MLE -- simpler, robust, and matches research reference code"
  - "Wilder smoothing (exponential) for ATR rather than SMA -- standard in technical analysis, smooths better"
  - "asyncio.to_thread for OU estimation to avoid blocking the event loop during numerical computation"
  - "60/40 weighted confidence blend: 60% OU fit quality + 40% phase transition quality, scaled by urgency"
  - "No veto power per D-12: timing purely contributes to the confidence-weighted fusion blend"

patterns-established:
  - "OU parameter estimation: OLS on dx = a + b*x for kappa/theta/sigma extraction"
  - "Volatility energy model: compression = stored energy (1 - ratio), expansion = releasing energy (ratio - 1)"
  - "Timing module: neutral signal on missing/empty data, valid signal only with sufficient bar data"

requirements-completed: [QTIM-01, QTIM-02, QTIM-03]

# Metrics
duration: 5min
completed: 2026-03-27
---

# Phase 02 Plan 04: Quantum Timing Engine Summary

**OU mean-reversion timing with half-life entry windows, Wilder-smoothed ATR, and volatility compression/expansion energy model for breakout timing**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-27T12:15:35Z
- **Completed:** 2026-03-27T12:21:09Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Implemented Ornstein-Uhlenbeck parameter estimation (kappa, theta, sigma) via OLS regression with R-squared confidence
- Built entry/exit timing windows with half-life urgency and direction from mean displacement
- Created ATR computation with Wilder smoothing and graceful short-data fallback
- Implemented volatility phase transition detection: compression (energy storing), expansion (energy releasing), normal states
- Built QuantumTimingModule implementing SignalModule Protocol with async update and structlog integration

## Task Commits

Each task was committed atomically:

1. **Task 1: OU model, ATR/phase transition, and timing windows (TDD)** - `409cd1a` (test RED), `2e418ea` (feat GREEN)
2. **Task 2: QuantumTimingModule** - `62ace12` (feat)

_Note: Task 1 used TDD with separate RED and GREEN commits._

## Files Created/Modified
- `src/fxsoqqabot/signals/timing/ou_model.py` - OU parameter estimation, entry/exit windows with half-life timing
- `src/fxsoqqabot/signals/timing/phase_transition.py` - ATR Wilder smoothing, volatility compression/expansion detection
- `src/fxsoqqabot/signals/timing/module.py` - QuantumTimingModule implementing SignalModule Protocol
- `src/fxsoqqabot/signals/timing/__init__.py` - Updated exports with QuantumTimingModule
- `tests/signals/test_timing.py` - 30 tests covering all timing components

## Decisions Made
- Used OLS regression for OU estimation (dx = a + b*x) rather than MLE -- simpler, matches research reference, and provides R-squared confidence measure directly
- Wilder smoothing for ATR: standard exponential smoothing with initial simple average window, matching the established Wilder method
- asyncio.to_thread wraps OU estimation to avoid blocking the async event loop during numerical computation
- 60/40 weighted confidence blend (OU fit quality 60% + phase transition quality 40%) scaled by urgency, so near-mean positions produce low confidence
- No veto power per D-12: the timing module contributes to the confidence-weighted blend like any other module, cannot block or delay trades

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all planned functionality implemented and tested.

## Next Phase Readiness
- Timing module complete: OU timing (QTIM-01), phase transition detection (QTIM-02), probability windows (QTIM-03)
- QuantumTimingModule passes SignalModule Protocol isinstance check
- Ready for Plan 02-05 (decision fusion) to consume timing signals in the confidence-weighted blend
- 30 tests pass covering edge cases (short data, constant prices, zero kappa, empty bars)

## Self-Check: PASSED

All 5 created/modified files verified present. All 3 commits (409cd1a, 2e418ea, 62ace12) verified in git log.

---
*Phase: 02-signal-pipeline-and-decision-fusion*
*Completed: 2026-03-27*
