---
phase: 04-observability-and-self-learning
plan: 01
subsystem: infra
tags: [duckdb, pydantic, textual, fastapi, deap, scikit-learn, optuna, structlog, config]

# Dependency graph
requires:
  - phase: 03-backtesting-and-validation
    provides: "Validated trading pipeline with signals, fusion, and execution"
provides:
  - "TUIConfig, WebConfig, LearningConfig Pydantic models with TOML defaults"
  - "EventType enum extended with MUTATION, RULE_RETIRED, VARIANT_PROMOTED"
  - "TradingEngineState mutable dataclass for dashboard consumption"
  - "TradeContextLogger with DuckDB trade_log table (~32 columns)"
  - "dashboard/ and learning/ package directories"
  - "Phase 4 dependencies in pyproject.toml"
affects: [04-02-tui-dashboard, 04-03-web-dashboard, 04-04-ga-evolution, 04-05-shadow-mode, 04-06-ml-regime-classifier]

# Tech tracking
tech-stack:
  added: [textual, fastapi, uvicorn, lightweight-charts, plotly, deap, scikit-learn, optuna]
  patterns: [mutable-dataclass-state-snapshot, trade-context-logging, per-module-signal-extraction]

key-files:
  created:
    - src/fxsoqqabot/core/state_snapshot.py
    - src/fxsoqqabot/learning/trade_logger.py
    - src/fxsoqqabot/learning/__init__.py
    - src/fxsoqqabot/dashboard/__init__.py
    - tests/test_config/test_phase4_models.py
    - tests/test_trade_logger.py
  modified:
    - pyproject.toml
    - src/fxsoqqabot/config/models.py
    - src/fxsoqqabot/core/events.py

key-decisions:
  - "Mutable TradingEngineState (not frozen) -- engine writes, dashboards read"
  - "to_dict() serializes regime as string value for WebSocket JSON"
  - "spread_at_entry defaults to 0.0 when FillEvent lacks ask field"
  - "Auto-incrementing trade_id via SELECT MAX + 1 (simple, no sequence needed for embedded DB)"

patterns-established:
  - "Mutable dataclass for shared state snapshot: engine writes, dashboards read (not frozen)"
  - "Per-module signal extraction pattern: _extract_signal() loops signals list by module_name"
  - "DuckDB trade_log table with ~32 columns for full trade context per D-11"

requirements-completed: [LEARN-01]

# Metrics
duration: 5min
completed: 2026-03-27
---

# Phase 4 Plan 01: Foundation Summary

**Phase 4 dependencies, config models (TUI/Web/Learning), extended events, TradingEngineState snapshot, and TradeContextLogger with 32-column DuckDB trade_log table**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-27T18:21:57Z
- **Completed:** 2026-03-27T18:27:02Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- All Phase 4 dependencies declared in pyproject.toml (textual, fastapi, uvicorn, plotly, deap, scikit-learn, optuna, lightweight-charts)
- TUIConfig, WebConfig, LearningConfig Pydantic models with validated TOML defaults added to BotSettings
- EventType enum extended with MUTATION, RULE_RETIRED, VARIANT_PROMOTED for learning subsystem events
- TradingEngineState mutable dataclass with to_dict() for WebSocket JSON serialization
- TradeContextLogger implemented with full D-11 trade context logging (~32 columns), filtered queries, and outcome tracking
- 36 tests covering all new types, configs, state snapshot, and trade logger

## Task Commits

Each task was committed atomically:

1. **Task 1: Dependencies, config models, event types, and shared state snapshot**
   - `2a60dbe` (test) -- Failing tests for Phase 4 config models, events, state snapshot
   - `5466163` (feat) -- Implementation: pyproject.toml deps, TUIConfig/WebConfig/LearningConfig, EventType learning members, TradingEngineState
   - `ee9f94a` (chore) -- uv.lock update with Phase 4 dependencies

2. **Task 2: Trade context logger with DuckDB trade_log table**
   - `3511faa` (test) -- Failing tests for TradeContextLogger
   - `b6cb5ae` (feat) -- Implementation: TradeContextLogger with CREATE TABLE, log_trade_open, log_trade_close, query_trades, get_recent_trades

## Files Created/Modified
- `pyproject.toml` -- Added 8 Phase 4 dependencies (textual, fastapi, uvicorn, lightweight-charts, plotly, deap, scikit-learn, optuna)
- `src/fxsoqqabot/config/models.py` -- Added TUIConfig, WebConfig, LearningConfig; extended BotSettings with tui/web/learning attributes
- `src/fxsoqqabot/core/events.py` -- Added MUTATION, RULE_RETIRED, VARIANT_PROMOTED EventType members
- `src/fxsoqqabot/core/state_snapshot.py` -- New file: TradingEngineState mutable dataclass with to_dict()
- `src/fxsoqqabot/dashboard/__init__.py` -- New package init for dashboard subsystem
- `src/fxsoqqabot/learning/__init__.py` -- New package init for learning subsystem
- `src/fxsoqqabot/learning/trade_logger.py` -- New file: TradeContextLogger with DuckDB trade_log table
- `tests/test_config/test_phase4_models.py` -- 23 tests for config, events, state snapshot
- `tests/test_trade_logger.py` -- 13 tests for trade logger CRUD and queries

## Decisions Made
- Mutable TradingEngineState (not frozen) because the engine writes updates and dashboards read -- frozen would require reconstructing the entire object on each update
- to_dict() serializes RegimeState enum as its string value for WebSocket JSON compatibility
- Auto-incrementing trade_id via SELECT MAX + 1 pattern (simple for embedded DuckDB, no sequence needed)
- spread_at_entry defaults to 0.0 when FillEvent lacks ask field (FillEvent doesn't store ask price)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All config models ready for TUI dashboard (Plan 02) and web dashboard (Plan 03)
- EventType learning events ready for GA evolution (Plan 04) and shadow mode (Plan 05)
- TradingEngineState ready for real-time dashboard consumption
- TradeContextLogger ready for learning loop trade logging (Plan 04/05)
- dashboard/ and learning/ package directories ready for implementation

## Self-Check: PASSED

All 6 created files verified present. All 5 commit hashes verified in git log.

---
*Phase: 04-observability-and-self-learning*
*Completed: 2026-03-27*
