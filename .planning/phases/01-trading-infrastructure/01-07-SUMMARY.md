---
phase: 01-trading-infrastructure
plan: 07
subsystem: core
tags: [asyncio, engine, cli, crash-recovery, orchestration]

# Dependency graph
requires:
  - phase: 01-trading-infrastructure/01-02
    provides: "MT5Bridge async wrapper, MarketDataFeed, TickBuffer, BarBufferSet"
  - phase: 01-trading-infrastructure/01-03
    provides: "DuckDB/Parquet TickStorage for tick persistence"
  - phase: 01-trading-infrastructure/01-04
    provides: "OrderManager, PaperExecutor for order execution"
  - phase: 01-trading-infrastructure/01-05
    provides: "PositionSizer with three-phase capital model"
  - phase: 01-trading-infrastructure/01-06
    provides: "CircuitBreakerManager, KillSwitch, SessionFilter, StateManager"
provides:
  - "TradingEngine: async orchestrator tying all components together"
  - "CLI entry points: run, kill, status, reset"
  - "Crash recovery: close all positions on startup per D-05/EXEC-04"
  - "python -m fxsoqqabot entry point for all commands"
affects: [phase-02-signal-modules, phase-03-backtesting, phase-04-self-learning]

# Tech tracking
tech-stack:
  added: [argparse]
  patterns: [async-engine-orchestration, cli-subcommands, crash-recovery-close-all, concurrent-asyncio-gather]

key-files:
  created:
    - src/fxsoqqabot/core/engine.py
    - src/fxsoqqabot/cli.py
    - tests/test_core/__init__.py
    - tests/test_core/test_engine.py
    - tests/test_core/test_cli.py
  modified:
    - src/fxsoqqabot/__main__.py

key-decisions:
  - "asyncio.gather for concurrent tick, bar, and health loops"
  - "Module-level asyncio_sleep alias for testable async delays (same pattern as mt5_bridge.py)"
  - "Crash recovery always closes ALL positions before resuming per D-05/EXEC-04"
  - "CLI uses argparse with subcommands, not click or typer, to avoid additional dependencies"
  - "Health loop runs on 10-second interval for equity monitoring and session reset checks"

patterns-established:
  - "Async engine pattern: _initialize_components -> _connect_mt5 -> _crash_recovery -> asyncio.gather(loops)"
  - "CLI pattern: argparse subcommands dispatching to async functions via asyncio.run()"
  - "Crash recovery pattern: load_state -> check_positions -> close_all -> check_session_reset -> set_equity"

requirements-completed: [EXEC-04, DATA-01, DATA-02, DATA-03, DATA-06]

# Metrics
duration: 5min
completed: 2026-03-27
---

# Phase 1 Plan 7: Engine and CLI Summary

**Async TradingEngine orchestrating all Phase 1 components with crash recovery, concurrent data loops, and argparse CLI for run/kill/status/reset**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-27T10:12:44Z
- **Completed:** 2026-03-27T10:17:58Z
- **Tasks:** 3 (2 auto + 1 checkpoint)
- **Files modified:** 6

## Accomplishments
- TradingEngine ties MT5Bridge, MarketDataFeed, buffers, storage, execution, risk, and state into a single async orchestrator
- Crash recovery closes all open positions on startup per D-05/EXEC-04, loads breaker state per D-07, checks session boundary per D-10
- Three concurrent loops (tick, bar, health) via asyncio.gather for non-blocking operation
- CLI with run/kill/status/reset commands, kill switch invocable independently via `python -m fxsoqqabot kill` per D-09
- Full Phase 1 test suite: 286 tests passing across all modules

## Task Commits

Each task was committed atomically:

1. **Task 1: Async trading engine with startup, data loop, and crash recovery** - `a43ae6e` (feat)
2. **Task 2: CLI entry points (run, kill, status, reset)** - `42be16c` (feat)
3. **Task 3: Verify complete Phase 1 trading infrastructure** - Auto-approved (286/286 tests pass, all imports OK, CLI help shows all commands)

## Files Created/Modified
- `src/fxsoqqabot/core/engine.py` - TradingEngine class: async orchestrator with tick/bar/health loops, crash recovery, graceful shutdown
- `src/fxsoqqabot/cli.py` - CLI entry points: cmd_run, cmd_kill, cmd_status, cmd_reset with argparse
- `src/fxsoqqabot/__main__.py` - Updated to dispatch to cli.main() for python -m fxsoqqabot support
- `tests/test_core/__init__.py` - Test package init
- `tests/test_core/test_engine.py` - 16 tests: initialization, crash recovery, lifecycle, connection
- `tests/test_core/test_cli.py` - 12 tests: argument parsing, status reading, reset behavior

## Decisions Made
- Used argparse over click/typer to avoid adding dependencies -- CLI needs are simple (4 subcommands)
- asyncio.gather for concurrent loops rather than separate tasks with manual lifecycle management
- Health loop at 10s interval balances equity monitoring frequency vs MT5 API load
- Module-level asyncio_sleep alias follows established pattern from mt5_bridge.py for testability

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required

None - no external service configuration required.

## Known Stubs

None - all components are fully wired with real data sources from prior plans.

## Next Phase Readiness
- Phase 1 Trading Infrastructure is complete: data pipeline, MT5 bridge, risk management, engine, CLI all operational
- Ready for Phase 2: Signal and Analysis Modules -- engine provides hooks for signal processing integration
- TradingEngine exposes breakers, kill_switch, and state properties for Phase 2 module integration
- All 286 tests pass, providing regression safety net for Phase 2 development

## Self-Check: PASSED

- All 6 created/modified files exist on disk
- Commit a43ae6e (Task 1) verified in git log
- Commit 42be16c (Task 2) verified in git log
- 286/286 tests pass across full test suite

---
*Phase: 01-trading-infrastructure*
*Completed: 2026-03-27*
