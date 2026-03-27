---
phase: 04-observability-and-self-learning
plan: 07
subsystem: learning
tags: [duckdb, trade-logging, learning-loop, paper-executor, trade-lifecycle]

# Dependency graph
requires:
  - phase: 04-06
    provides: LearningLoopManager, TradeContextLogger, TradingEngine integration
provides:
  - Working trade logging pipeline: every buy/sell logs open row, every SL/TP close updates row and triggers learning
  - FillEvent tuple return from TradeManager.evaluate_and_execute
  - _handle_paper_close method for full close/log/learn pipeline
affects: [04-08, learning, dashboard, backtesting]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Tuple return for multi-value async results: (TradeDecision, FillEvent | None)"
    - "Helper method extraction: _handle_paper_close isolates close pipeline for testability"

key-files:
  created:
    - tests/test_trade_logging_wiring.py
  modified:
    - src/fxsoqqabot/signals/fusion/trade_manager.py
    - src/fxsoqqabot/core/engine.py
    - tests/signals/test_fusion.py

key-decisions:
  - "Tuple return (TradeDecision, FillEvent | None) over adding fill field to TradeDecision -- keeps TradeDecision frozen and immutable"
  - "Extract _handle_paper_close as separate async method for testability instead of inlining in _tick_loop"
  - "PnL computation duplicated from PaperExecutor.simulate_close for logging accuracy -- simulate_close already computed PnL internally but doesn't expose it"

patterns-established:
  - "Tuple return for evaluate_and_execute: callers must unpack (decision, fill)"
  - "_handle_paper_close pipeline: simulate_close -> log_trade_close -> on_trade_closed -> record_position_closed"

requirements-completed: [LEARN-01, LEARN-02, LEARN-03, LEARN-05]

# Metrics
duration: 9min
completed: 2026-03-28
---

# Phase 04 Plan 07: Trade Logging Pipeline Gap Closure Summary

**Fixed trade open/close logging pipeline so every trade is captured in DuckDB trade_log, unblocking GA evolution, ML training, and signal analysis**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-27T19:39:15Z
- **Completed:** 2026-03-27T19:49:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Eliminated hasattr(decision, 'fill') guard bug that prevented all trade open logging to DuckDB
- TradeManager.evaluate_and_execute now returns (TradeDecision, FillEvent | None) tuple, making fill available to the engine
- Paper SL/TP triggers now execute full close pipeline: simulate_close, log_trade_close, on_trade_closed, record_position_closed
- LEARN-01/02/03/05 unblocked: trade_log table will receive real rows when trades execute at runtime

## Task Commits

Each task was committed atomically:

1. **Task 1: Return FillEvent from TradeManager and fix engine trade open logging** - `fddf969` (feat)
2. **Task 2: Wire trade close logging and learning loop callback on paper SL/TP trigger** - `c255346` (feat)

## Files Created/Modified
- `src/fxsoqqabot/signals/fusion/trade_manager.py` - Changed evaluate_and_execute to return tuple[TradeDecision, FillEvent | None], added FillEvent import
- `src/fxsoqqabot/core/engine.py` - Fixed trade open logging guard, added _handle_paper_close method with full close/log/learn pipeline, added datetime import
- `tests/test_trade_logging_wiring.py` - 11 tests covering tuple return, engine open logging, and close wiring
- `tests/signals/test_fusion.py` - Updated 7 existing tests to unpack tuple return

## Decisions Made
- Used tuple return (TradeDecision, FillEvent | None) over adding a fill field to the frozen TradeDecision dataclass -- preserves immutability and type safety
- Extracted _handle_paper_close as a separate async method rather than inlining all close logic in _tick_loop -- enables focused unit testing
- Duplicated PnL computation (contract_size * price_diff * volume) in _handle_paper_close because PaperExecutor.simulate_close computes PnL internally but does not expose it on the returned FillEvent

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated existing test_fusion.py tests for tuple return**
- **Found during:** Task 2 (running full test suite)
- **Issue:** 7 existing tests in tests/signals/test_fusion.py assigned evaluate_and_execute result to plain `decision` variable, now fails because result is a tuple
- **Fix:** Changed all 7 occurrences from `decision = await trade_manager.evaluate_and_execute(...)` to `decision, _fill = await trade_manager.evaluate_and_execute(...)`
- **Files modified:** tests/signals/test_fusion.py
- **Verification:** All 622 non-backtest tests pass (excluding pre-existing test_events.py failure)
- **Committed in:** c255346 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Auto-fix was necessary to maintain existing test suite compatibility after changing evaluate_and_execute return type. No scope creep.

## Issues Encountered
- Pre-existing test failure in tests/test_config/test_events.py (EventType enum test missing learning event types added in 04-06) -- not related to this plan, left for separate fix

## Known Stubs
None -- all connections are wired to real implementations.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Trade logging pipeline is fully wired end-to-end
- DuckDB trade_log will receive rows on every trade open and close
- Learning loop will be triggered on every trade close
- Ready for 04-08 (walk-forward gate integration) or any plan depending on trade data

## Self-Check: PASSED

- FOUND: tests/test_trade_logging_wiring.py
- FOUND: .planning/phases/04-observability-and-self-learning/04-07-SUMMARY.md
- FOUND: fddf969 (Task 1 commit)
- FOUND: c255346 (Task 2 commit)
- 622 tests pass (all non-backtest, excluding pre-existing test_events.py failure)

---
*Phase: 04-observability-and-self-learning*
*Completed: 2026-03-28*
