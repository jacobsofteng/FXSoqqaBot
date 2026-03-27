---
phase: 01-trading-infrastructure
plan: 05
subsystem: risk
tags: [position-sizing, session-filter, risk-management, xauusd, capital-phases]

# Dependency graph
requires:
  - phase: 01-trading-infrastructure (plan 01)
    provides: "RiskConfig and SessionConfig Pydantic models with get_risk_pct method"
provides:
  - "PositionSizer engine with three-phase capital model (aggressive/selective/conservative)"
  - "SizingResult frozen dataclass with lot size, risk amount, can_trade flag"
  - "SymbolSpecs dataclass for broker-queried XAUUSD contract specifications"
  - "SessionFilter with configurable trading windows and session date boundaries"
affects: [01-trading-infrastructure plan 06 (circuit breakers), 01-trading-infrastructure plan 07 (state persistence)]

# Tech tracking
tech-stack:
  added: [structlog]
  patterns: [frozen-dataclass-results, config-injection, start-inclusive-end-exclusive-windows]

key-files:
  created:
    - src/fxsoqqabot/risk/sizing.py
    - src/fxsoqqabot/risk/session.py
    - tests/test_risk/__init__.py
    - tests/test_risk/test_sizing.py
    - tests/test_risk/test_session.py
  modified:
    - src/fxsoqqabot/risk/__init__.py

key-decisions:
  - "Frozen dataclass SizingResult over dict/tuple for type safety and immutability"
  - "SymbolSpecs with defaults rather than hardcoded values for future multi-symbol support"
  - "Start-inclusive end-exclusive window boundaries for consistent time range semantics"

patterns-established:
  - "Frozen dataclass for computation results: immutable, typed, self-documenting"
  - "Config injection via __init__(config) rather than module-level globals"
  - "Structured logging with component binding for per-module trace context"

requirements-completed: [RISK-02, RISK-06]

# Metrics
duration: 4min
completed: 2026-03-27
---

# Phase 01 Plan 05: Position Sizing and Session Filter Summary

**Three-phase capital model (10%/5%/2% risk) with XAUUSD lot sizing and London-NY session time filter**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-27T09:48:14Z
- **Completed:** 2026-03-27T09:52:15Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- PositionSizer calculates lot sizes across three capital phases with D-04 trade-skip protection
- SessionFilter gates trading to configured hours with multiple window and reset_hour support
- 44 tests covering all edge cases: phase boundaries, risk budget exceedance, volume constraints, window boundaries

## Task Commits

Each task was committed atomically (TDD red-green):

1. **Task 1: Position sizing engine** - `d9dda16` (test) + `b6343ae` (feat)
2. **Task 2: Session time filter** - `7f0aaf3` (test) + `9412f59` (feat)

## Files Created/Modified
- `src/fxsoqqabot/risk/__init__.py` - Risk module docstring
- `src/fxsoqqabot/risk/sizing.py` - PositionSizer, SizingResult, SymbolSpecs classes
- `src/fxsoqqabot/risk/session.py` - SessionFilter with trading window and session date logic
- `tests/test_risk/__init__.py` - Test package init
- `tests/test_risk/test_sizing.py` - 21 tests for position sizing across all capital phases
- `tests/test_risk/test_session.py` - 23 tests for session filtering and time calculations

## Decisions Made
- Frozen dataclass SizingResult over dict/tuple -- provides type safety and immutability for computation results passed between modules
- SymbolSpecs with defaults rather than hardcoded values -- the contract size (100 oz), volume_min (0.01), etc. come from broker at runtime, defaults for XAUUSD
- Start-inclusive end-exclusive window boundaries -- consistent with Python range semantics, 13:00 is in-window, 17:00 is out-of-window

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- PositionSizer ready for use by decision/execution core (plans 06-07)
- SessionFilter ready for circuit breaker integration (plan 06)
- RiskConfig.get_risk_pct wired end-to-end from config through PositionSizer

## Self-Check: PASSED

- All 6 files verified present on disk
- All 4 commits verified in git history (d9dda16, b6343ae, 7f0aaf3, 9412f59)
- 44/44 tests passing

---
*Phase: 01-trading-infrastructure*
*Completed: 2026-03-27*
