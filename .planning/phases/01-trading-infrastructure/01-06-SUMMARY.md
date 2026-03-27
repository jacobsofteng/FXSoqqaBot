---
phase: 01-trading-infrastructure
plan: 06
subsystem: risk
tags: [sqlite, wal, circuit-breakers, kill-switch, crash-recovery, aiosqlite, pydantic]

# Dependency graph
requires:
  - phase: 01-trading-infrastructure/01-01
    provides: "Pydantic config models (RiskConfig with circuit breaker thresholds)"
  - phase: 01-trading-infrastructure/01-04
    provides: "OrderManager.close_all_positions for kill switch"
  - phase: 01-trading-infrastructure/01-05
    provides: "SessionFilter for session date/week boundaries"
provides:
  - "StateManager: SQLite persistence with WAL mode for crash recovery"
  - "CircuitBreakerSnapshot: full breaker state Pydantic model"
  - "BreakerState enum: ACTIVE/TRIPPED/KILLED"
  - "CircuitBreakerManager: five automatic circuit breakers"
  - "KillSwitch: emergency position close with manual reset"
  - "PositionRecord: position tracking for crash recovery"
  - "TradeJournalEntry: trade journal persistence"
affects: [01-trading-infrastructure/01-07, decision-core, dashboard, backtesting]

# Tech tracking
tech-stack:
  added: [aiosqlite]
  patterns: [sqlite-wal-mode, singleton-state-row, pydantic-snapshot-model, deque-rolling-buffer]

key-files:
  created:
    - src/fxsoqqabot/core/state.py
    - src/fxsoqqabot/risk/circuit_breakers.py
    - src/fxsoqqabot/risk/kill_switch.py
    - tests/test_risk/test_state.py
    - tests/test_risk/test_circuit_breakers.py
    - tests/test_risk/test_kill_switch.py
  modified:
    - src/fxsoqqabot/risk/__init__.py

key-decisions:
  - "SQLite WAL mode with PRAGMA synchronous=NORMAL for crash safety without excessive fsync overhead"
  - "Singleton row pattern (id=1 CHECK constraint) for circuit breaker state -- only one global state"
  - "Total max drawdown reuses daily_drawdown TRIPPED state rather than a separate breaker field"
  - "KillSwitch uses TYPE_CHECKING import for OrderManager to avoid circular dependency"

patterns-established:
  - "SQLite WAL mode for all persistent state: PRAGMA journal_mode=WAL + synchronous=NORMAL + busy_timeout=5000"
  - "CircuitBreakerSnapshot as single Pydantic model for all breaker state, persisted as one row"
  - "collections.deque(maxlen=N) for rolling equity and spread history buffers"
  - "async fixture with yield for StateManager lifecycle in tests"

requirements-completed: [RISK-04, RISK-05, RISK-07]

# Metrics
duration: 6min
completed: 2026-03-27
---

# Phase 01 Plan 06: Circuit Breakers, Kill Switch, and SQLite State Persistence Summary

**Five circuit breakers (daily DD, loss streak, spread spike, rapid equity drop, max trades) with SQLite WAL-mode persistence and emergency kill switch requiring manual reset**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-27T10:03:04Z
- **Completed:** 2026-03-27T10:09:08Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- StateManager with SQLite WAL mode creates four tables (circuit_breaker_state, positions, trade_journal, account_snapshots) and survives crash/reopen cycles
- CircuitBreakerManager trips on five conditions: daily drawdown (5%), consecutive losses (5), rapid equity drop (5% in 15 min), max daily trades (20), spread spike (5x avg for 30s), plus total drawdown from equity high-water mark (25%)
- KillSwitch closes all positions via OrderManager and sets KILLED state requiring explicit manual reset -- NOT auto-reset at session boundary
- All daily breakers auto-reset at session boundary while kill switch persists across sessions

## Task Commits

Each task was committed atomically:

1. **Task 1: SQLite state persistence with WAL mode** - `c9ce0b1` (test), `cd3ae33` (feat)
2. **Task 2: Circuit breakers and kill switch** - `04c4554` (test), `9f67ba8` (feat)
3. **Risk module docstring update** - `025d2ea` (chore)

_TDD tasks have multiple commits (test -> feat)_

## Files Created/Modified
- `src/fxsoqqabot/core/state.py` - StateManager, BreakerState, CircuitBreakerSnapshot, PositionRecord, TradeJournalEntry models
- `src/fxsoqqabot/risk/circuit_breakers.py` - CircuitBreakerManager with five automatic breakers and session reset
- `src/fxsoqqabot/risk/kill_switch.py` - KillSwitch with activate/reset/is_killed
- `tests/test_risk/test_state.py` - 13 tests for state persistence
- `tests/test_risk/test_circuit_breakers.py` - 22 tests for circuit breakers
- `tests/test_risk/test_kill_switch.py` - 8 tests for kill switch
- `src/fxsoqqabot/risk/__init__.py` - Updated docstring

## Decisions Made
- SQLite WAL mode with `synchronous=NORMAL` for crash safety without excessive fsync -- per Pitfall 6 from research
- Singleton row pattern (`id INTEGER PRIMARY KEY CHECK (id = 1)`) for circuit breaker state -- guarantees exactly one state row
- Total max drawdown (RISK-07) reuses the `daily_drawdown` TRIPPED state rather than adding a separate breaker field -- both halt trading
- KillSwitch uses `TYPE_CHECKING` import for OrderManager to avoid circular dependency between risk and execution modules

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Circuit breaker system ready for integration with the main trading loop (Plan 07)
- StateManager ready to persist position reconciliation state on crash recovery
- Kill switch ready for CLI command and TUI dashboard button integration
- All 87 risk tests pass (including pre-existing session and sizing tests)

## Self-Check: PASSED

All 6 created files verified present. All 5 commits verified in git log.

---
*Phase: 01-trading-infrastructure*
*Completed: 2026-03-27*
