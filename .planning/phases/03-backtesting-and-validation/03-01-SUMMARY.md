---
phase: 03-backtesting-and-validation
plan: 01
subsystem: backtesting
tags: [protocol, pydantic, clock, adapter, structural-typing, tdd]

# Dependency graph
requires:
  - phase: 01-trading-infrastructure
    provides: "TickBuffer, BarBufferSet, BarBuffer, TickEvent, BarEvent, DOMSnapshot, DataConfig"
  - phase: 02-signal-pipeline-and-decision-fusion
    provides: "SignalModule Protocol pattern (structural typing for interfaces)"
provides:
  - "DataFeedProtocol: runtime_checkable protocol for live/backtest data sources"
  - "Clock Protocol with WallClock and BacktestClock implementations"
  - "BacktestConfig Pydantic model with walk-forward, Monte Carlo, OOS parameters"
  - "SpreadModel: session-aware XAUUSD spread sampling per D-09"
  - "SlippageModel: stochastic adverse slippage distribution per D-10"
  - "LiveDataFeedAdapter: wraps existing TickBuffer + BarBufferSet as DataFeedProtocol"
affects: [03-02, 03-03, 03-04, 03-05, backtesting-engine, historical-data-replay]

# Tech tracking
tech-stack:
  added: []
  patterns: [DataFeedProtocol structural typing, adapter pattern for live/backtest bridging, deterministic clock for reproducible backtests, session-aware stochastic spread/slippage modeling]

key-files:
  created:
    - src/fxsoqqabot/data/protocol.py
    - src/fxsoqqabot/backtest/__init__.py
    - src/fxsoqqabot/backtest/clock.py
    - src/fxsoqqabot/backtest/config.py
    - src/fxsoqqabot/backtest/adapter.py
    - tests/test_backtest/__init__.py
    - tests/test_backtest/test_protocol_clock.py
    - tests/test_backtest/test_adapter.py
  modified: []

key-decisions:
  - "DataFeedProtocol uses structural typing (Protocol) matching Phase 2 SignalModule pattern -- no ABC inheritance required"
  - "BacktestClock starts at 0 and advances only on explicit advance() call for deterministic replay"
  - "SpreadModel uses session-aware UTC hour ranges: 13-17 London-NY overlap (tight), 8-12 London, 0-7 Asian, 18-23 low liquidity"
  - "SlippageModel uses discrete probability distribution with exponential tail for 3+ pip slippage"
  - "LiveDataFeedAdapter delegates to existing TickBuffer/BarBufferSet without modifying Phase 1 code"

patterns-established:
  - "DataFeedProtocol pattern: all data consumers depend on protocol, not concrete sources"
  - "Clock injection: all time-dependent code uses Clock protocol for testability"
  - "Adapter pattern: wrap existing infra to match new protocols without modifying originals"

requirements-completed: [TEST-07]

# Metrics
duration: 5min
completed: 2026-03-27
---

# Phase 03 Plan 01: Protocol Abstraction Layer Summary

**DataFeedProtocol + Clock Protocol + BacktestConfig decoupling signal pipeline from live MT5 data for backtest-ready architecture**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-27T14:09:14Z
- **Completed:** 2026-03-27T14:14:17Z
- **Tasks:** 2
- **Files created:** 8

## Accomplishments
- DataFeedProtocol defines the exact dict shapes matching TickBuffer.as_arrays() and BarBufferSet[tf].as_arrays() -- same signal code runs live and backtest
- Clock Protocol with WallClock (real time) and BacktestClock (deterministic, advance-on-demand) enables reproducible backtest execution
- BacktestConfig validates all D-05 through D-13 parameters (walk-forward windows, Monte Carlo, OOS holdout, spread, slippage, commission) via Pydantic
- LiveDataFeedAdapter wraps existing Phase 1 buffers without modifying their code -- adapter pattern preserves all existing infrastructure
- 32 tests covering protocol conformance, clock behavior, config validation, spread/slippage sampling, and adapter correctness

## Task Commits

Each task was committed atomically (TDD: test then feat):

1. **Task 1: DataFeedProtocol, Clock Protocol, BacktestConfig** - `dbdd9f2` (test: failing tests) + `ddd2ad4` (feat: implementation)
2. **Task 2: LiveDataFeedAdapter** - `fcd0827` (test: failing tests) + `0d0373b` (feat: implementation)

_TDD tasks have paired commits: RED (failing test) then GREEN (passing implementation)_

## Files Created/Modified
- `src/fxsoqqabot/data/protocol.py` - DataFeedProtocol with get_tick_arrays, get_bar_arrays, get_dom, check_tick_freshness
- `src/fxsoqqabot/backtest/__init__.py` - Package init enabling backtest module imports
- `src/fxsoqqabot/backtest/clock.py` - Clock Protocol, WallClock (real time), BacktestClock (deterministic)
- `src/fxsoqqabot/backtest/config.py` - BacktestConfig, SpreadModel, SlippageModel with Pydantic validators
- `src/fxsoqqabot/backtest/adapter.py` - LiveDataFeedAdapter wrapping TickBuffer + BarBufferSet
- `tests/test_backtest/__init__.py` - Test package init
- `tests/test_backtest/test_protocol_clock.py` - 21 tests for protocol, clock, config, spread, slippage
- `tests/test_backtest/test_adapter.py` - 11 tests for adapter protocol conformance and data retrieval

## Decisions Made
- DataFeedProtocol uses structural typing (Protocol) matching Phase 2 SignalModule pattern -- no ABC inheritance required
- BacktestClock starts at 0 and advances only on explicit advance() call for deterministic replay
- SpreadModel uses session-aware UTC hour ranges: 13-17 London-NY overlap (tightest), 8-12 London, 0-7 Asian, 18-23 low liquidity (widest)
- SlippageModel uses discrete probability distribution (80% no slip, 15% 1-pip, 4% 2-pip, 1% 3+ with exponential tail)
- LiveDataFeedAdapter delegates to existing TickBuffer/BarBufferSet -- existing Phase 1 code is completely untouched

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- DataFeedProtocol is ready for BacktestDataFeed (Plan 02) to implement directly for historical data replay
- BacktestConfig centralizes all parameters that the backtest engine (Plan 03) will consume
- Clock Protocol ready for injection into any time-dependent component
- All 5 remaining Phase 03 plans can now depend on these abstractions

## Self-Check: PASSED

- All 8 created files exist on disk
- All 4 commits (dbdd9f2, ddd2ad4, fcd0827, 0d0373b) verified in git log
- 32/32 tests pass

---
*Phase: 03-backtesting-and-validation*
*Completed: 2026-03-27*
