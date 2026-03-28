---
phase: 06-dashboard-live-state-wiring
plan: 01
subsystem: dashboard, core
tags: [websocket, equity, circuit-breakers, pause, state-snapshot, fastapi]

# Dependency graph
requires:
  - phase: 04-observability-and-self-learning
    provides: "TUI/web dashboard framework, TradingEngineState, DashboardServer, CircuitBreakerManager"
provides:
  - "Live equity from MT5 account info flowing to TUI and web dashboards"
  - "Accurate connection status (True/False boolean from bridge.connected)"
  - "Synchronous is_killed property on CircuitBreakerManager (not async coroutine)"
  - "Equity sparkline data (equity_history populated over time, capped at 1000)"
  - "Module weights from AdaptiveWeightTracker in /api/module-weights and WebSocket stream"
  - "All 6 breaker states in breaker_status dict"
  - "Pause guards in _tick_loop, _bar_loop, _signal_loop"
affects: [07-end-to-end-integration-and-dry-run]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Synchronous property on CircuitBreakerManager for dashboard reads (avoids async in state update)"
    - "Explicit instance attrs (_current_equity, _connected) set in __init__ and assigned in loops"
    - "Equity history append-and-cap pattern (append each cycle, trim to 500 when exceeding 1000)"

key-files:
  created: []
  modified:
    - src/fxsoqqabot/core/state_snapshot.py
    - src/fxsoqqabot/risk/circuit_breakers.py
    - src/fxsoqqabot/core/engine.py
    - src/fxsoqqabot/dashboard/web/server.py

key-decisions:
  - "Synchronous is_killed reads from CircuitBreakerSnapshot in-memory state, not async KillSwitch.is_killed DB call"
  - "Equity history capped at 1000 entries with trim-to-500 to avoid unbounded growth"
  - "to_dict() sends last 50 equity_history entries over WebSocket (bandwidth efficiency)"

patterns-established:
  - "Explicit instance attrs in __init__ for dashboard state tracking rather than getattr with defaults"
  - "get_breaker_status() returns flat dict from snapshot for dashboard consumption"

requirements-completed: [OBS-01, OBS-04]

# Metrics
duration: 4min
completed: 2026-03-28
---

# Phase 06 Plan 01: Dashboard Live State Wiring Summary

**Fixed all dashboard wiring bugs: equity, connection, kill switch, pause guards, module weights, breaker status now flow from engine to TUI/web dashboards in real time**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-28T08:32:47Z
- **Completed:** 2026-03-28T08:36:47Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Equity reads from MT5 account info and flows to dashboards (was always 0.0)
- Connection status reads from bridge.connected (was always False)
- is_killed reads synchronously from breaker snapshot (was a truthy coroutine object)
- Equity sparkline has data (equity_history populated over time, capped at 1000)
- /api/module-weights returns real fusion weights (was hardcoded empty array)
- Breaker status dict contains all 6 breaker names with their state values (was silently failing)
- Pause command now stops all three loops (_tick_loop, _bar_loop, _signal_loop)
- _handle_kill calls activate() with no arguments (matches KillSwitch.activate(self) signature)

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix state_snapshot.py and circuit_breakers.py contracts** - `2add978` (feat)
2. **Task 2: Fix engine.py wiring bugs and server.py endpoint** - `db6731f` (fix)

## Files Created/Modified
- `src/fxsoqqabot/core/state_snapshot.py` - Added module_weights field, equity_history and module_weights in to_dict()
- `src/fxsoqqabot/risk/circuit_breakers.py` - Added synchronous is_killed property and get_breaker_status() method
- `src/fxsoqqabot/core/engine.py` - Fixed all wiring: equity assignment, connection tracking, is_killed sync read, equity_history population, module_weights population, breaker_status via get_breaker_status(), pause guards in 3 loops, _handle_kill signature
- `src/fxsoqqabot/dashboard/web/server.py` - Fixed /api/module-weights to return state.module_weights instead of empty array

## Decisions Made
- Synchronous is_killed reads from CircuitBreakerSnapshot in-memory state, not async KillSwitch.is_killed DB call -- avoids await in non-async _update_engine_state
- Equity history capped at 1000 entries with trim-to-500 to avoid unbounded memory growth while keeping sufficient history for charts
- to_dict() sends last 50 equity_history entries over WebSocket for bandwidth efficiency (full 1000 stays in-memory for REST endpoints)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness
- All dashboard wiring bugs fixed, TUI and web dashboards now display live accurate data
- Ready for Plan 02 (test coverage for the wiring fixes) and Phase 07 integration testing
- No blockers or concerns

## Self-Check: PASSED

All 4 modified files exist on disk. Both task commits (2add978, db6731f) verified in git log. SUMMARY.md created.

---
*Phase: 06-dashboard-live-state-wiring*
*Completed: 2026-03-28*
