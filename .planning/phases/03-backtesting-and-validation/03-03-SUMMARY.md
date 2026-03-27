---
phase: 03-backtesting-and-validation
plan: 03
subsystem: backtesting
tags: [backtest-engine, data-feed, executor, signal-replay, fill-simulation, walk-forward]

# Dependency graph
requires:
  - phase: 03-01
    provides: "BacktestClock, BacktestConfig, SpreadModel, SlippageModel, DataFeedProtocol, LiveDataFeedAdapter"
  - phase: 02
    provides: "ChaosRegimeModule, OrderFlowModule, QuantumTimingModule, FusionCore, AdaptiveWeightTracker, PhaseBehavior, PositionSizer"
provides:
  - "BacktestDataFeed implementing DataFeedProtocol with bar-only tick synthesis"
  - "BacktestExecutor with session-aware spread, stochastic slippage, and commission simulation"
  - "BacktestEngine replaying M1 bars through the same signal pipeline as live trading"
  - "BacktestResult and TradeRecord frozen dataclasses with computed metrics"
affects: [03-04-walk-forward, 03-05-monte-carlo, 04-self-learning]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bar-by-bar replay with synchronous signal pipeline (no async polling)"
    - "BacktestDataFeed synthesizes tick arrays from M1 close + sampled spread"
    - "Multi-timeframe resampling via numpy reshape for M5/M15/H1/H4 from M1"
    - "Separate BacktestExecutor from PaperExecutor (bar-based vs tick-based pricing)"
    - "Fresh component instances per run() call for clean walk-forward state"

key-files:
  created:
    - src/fxsoqqabot/backtest/data_feed.py
    - src/fxsoqqabot/backtest/executor.py
    - src/fxsoqqabot/backtest/engine.py
    - src/fxsoqqabot/backtest/results.py
    - tests/test_backtest/test_engine.py
    - tests/test_backtest/test_engine_replay.py
  modified: []

key-decisions:
  - "BacktestExecutor is separate from PaperExecutor because PaperExecutor uses live tick pricing while BacktestExecutor uses bar OHLCV + simulated spread"
  - "Commission deducted at position open time (not at close) for realistic equity tracking"
  - "Fresh BacktestClock, DataFeed, Executor instances created per run() for clean walk-forward window state"
  - "Numpy reshape-based M1 resampling for higher timeframes avoids pandas groupby overhead"

patterns-established:
  - "BacktestDataFeed tick synthesis: one synthetic tick per M1 bar with bid=close, ask=close+spread"
  - "Anti-lookahead enforcement via array slicing up to current_idx only"
  - "BacktestPosition dataclass separate from PaperPosition for backtest-specific fields"
  - "BacktestResult frozen dataclass with computed properties (win_rate, profit_factor, max_drawdown_pct)"

requirements-completed: [TEST-01, TEST-07]

# Metrics
duration: 9min
completed: 2026-03-27
---

# Phase 03 Plan 03: Backtesting Engine Summary

**Core backtest engine replaying M1 bars through ChaosRegimeModule, OrderFlowModule, QuantumTimingModule, FusionCore with realistic fill simulation (spread + slippage + commission)**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-27T14:18:27Z
- **Completed:** 2026-03-27T14:27:30Z
- **Tasks:** 2 (both TDD: RED-GREEN)
- **Files modified:** 6

## Accomplishments
- BacktestDataFeed implementing DataFeedProtocol with M1 bar tick synthesis and multi-timeframe resampling (M1/M5/M15/H1/H4) with strict anti-lookahead enforcement
- BacktestExecutor with session-aware spread (D-09), stochastic slippage (D-10), configurable commission (D-11), and SL/TP checking against bar high/low
- BacktestEngine wiring the exact same signal modules (ChaosRegimeModule, OrderFlowModule, QuantumTimingModule) and fusion logic (FusionCore, AdaptiveWeightTracker, PhaseBehavior) as TradingEngine -- zero separate backtest code paths for analysis
- TradeRecord and BacktestResult frozen dataclasses with computed metrics (win_rate, profit_factor, max_drawdown_pct)

## Task Commits

Each task was committed atomically (TDD: test then feat):

1. **Task 1: BacktestDataFeed, BacktestExecutor, and result types** - `10ce6ef` (test) + `0ed4720` (feat)
2. **Task 2: BacktestEngine replay loop wiring signal modules and fusion** - `d05f4d9` (test) + `bcf9094` (feat)

## Files Created/Modified
- `src/fxsoqqabot/backtest/data_feed.py` - BacktestDataFeed implementing DataFeedProtocol with tick synthesis and multi-TF bar resampling
- `src/fxsoqqabot/backtest/executor.py` - BacktestExecutor with fill simulation (spread + slippage + commission) and SL/TP management
- `src/fxsoqqabot/backtest/engine.py` - BacktestEngine replaying M1 bars through the live signal pipeline
- `src/fxsoqqabot/backtest/results.py` - TradeRecord and BacktestResult frozen dataclasses
- `tests/test_backtest/test_engine.py` - 12 tests for DataFeed, Executor, and result types
- `tests/test_backtest/test_engine_replay.py` - 7 integration tests for engine replay loop

## Decisions Made
- BacktestExecutor is separate from PaperExecutor because PaperExecutor uses live tick pricing while BacktestExecutor uses bar OHLCV + simulated spread -- different data sources require different fill calculation
- Commission deducted at position open time (not at close) for realistic equity tracking during the backtest
- Fresh BacktestClock, DataFeed, Executor instances created per run() call to ensure clean state between walk-forward windows
- Numpy reshape-based M1 resampling for higher timeframes (M5/M15/H1/H4) avoids pandas groupby overhead in the hot path

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Test fixture in test_engine_replay.py used same start timestamp for both bar sets, causing the reset test to fail on start_time comparison. Fixed by using distinct start_time values for each fixture.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None - all components are fully wired to their data sources and signal pipeline.

## Next Phase Readiness
- BacktestEngine is ready for walk-forward validation (Plan 04) -- accepts any M1 DataFrame and returns BacktestResult
- BacktestResult provides all metrics needed for Monte Carlo simulation (Plan 05)
- DataFeedProtocol abstraction means signal modules are tested in both live and backtest contexts

## Self-Check: PASSED

- All 6 created files exist on disk
- All 4 commit hashes found in git log (10ce6ef, 0ed4720, d05f4d9, bcf9094)
- 19/19 tests pass across both test files

---
*Phase: 03-backtesting-and-validation*
*Completed: 2026-03-27*
