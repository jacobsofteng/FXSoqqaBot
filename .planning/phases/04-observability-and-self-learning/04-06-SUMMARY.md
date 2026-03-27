---
phase: 04-observability-and-self-learning
plan: 06
subsystem: integration
tags: [learning-loop, engine-wiring, cli, toml-config, dashboard-integration, evolution, shadow-mode]

# Dependency graph
requires:
  - phase: 04-01
    provides: "TradingEngineState and TradeContextLogger"
  - phase: 04-02
    provides: "FXSoqqaBotTUI terminal dashboard"
  - phase: 04-03
    provides: "DashboardServer web dashboard"
  - phase: 04-04
    provides: "EvolutionManager, SignalAnalyzer, RuleRetirementTracker"
  - phase: 04-05
    provides: "ShadowManager, RegimeClassifier"
provides:
  - "LearningLoopManager orchestrating all learning sub-components"
  - "TradingEngine integrated with TradingEngineState, dashboards, and learning loop"
  - "CLI with --no-tui, --no-web, --no-learning flags and dashboard/learning subcommands"
  - "Default TOML config with [tui], [web], [learning] sections"
affects: [phase-transition, production-readiness]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "asyncio.to_thread for blocking GA/ML operations in async engine"
    - "TYPE_CHECKING imports for heavy dashboard/learning modules to avoid circular deps"
    - "CLI feature flags (--no-tui, --no-web, --no-learning) for granular control"
    - "LearningLoopManager as facade pattern over evolution, shadow, classifier, retirement, analyzer"

key-files:
  created:
    - "src/fxsoqqabot/learning/loop.py"
    - "tests/test_learning_loop.py"
  modified:
    - "src/fxsoqqabot/core/engine.py"
    - "src/fxsoqqabot/cli.py"
    - "config/default.toml"

key-decisions:
  - "LearningLoopManager as facade orchestrating all 5 learning sub-components"
  - "asyncio.to_thread wraps blocking DEAP evolution and sklearn classifier training"
  - "Learning disabled by default (enabled=false) until explicitly enabled"
  - "Web dashboard runs as parallel async task in engine.start() gather"
  - "TUI runs as main loop with engine as background task when enabled"

patterns-established:
  - "Facade pattern: LearningLoopManager coordinates EvolutionManager, ShadowManager, RegimeClassifier, RuleRetirementTracker, SignalAnalyzer"
  - "CLI feature flags: --no-tui/--no-web/--no-learning disable Phase 4 features at runtime"
  - "Config-driven feature gates: settings.tui.enabled / settings.web.enabled / settings.learning.enabled"

requirements-completed: [LEARN-01, LEARN-02, LEARN-04, LEARN-06]

# Metrics
duration: 5min
completed: 2026-03-27
---

# Phase 04 Plan 06: Integration Summary

**LearningLoopManager orchestrating GA evolution, shadow variants, and regime classifier, wired into TradingEngine with dashboard state updates and CLI feature flags**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-27T18:50:45Z
- **Completed:** 2026-03-27T18:56:21Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- LearningLoopManager coordinates all 5 learning sub-components (evolution, shadow, classifier, retirement, analyzer) with async trade-closed triggers
- TradingEngine writes to TradingEngineState after each signal cycle, enabling live dashboard updates
- CLI extended with dashboard/learning subcommands and --no-tui/--no-web/--no-learning flags
- Default TOML config includes [tui], [web], [learning] sections with learning disabled by default
- 27 tests covering LearningLoopManager initialization, trade counters, evolution triggers, promotions, classifier retraining, retirement tracking, and status queries

## Task Commits

Each task was committed atomically:

1. **Task 1: LearningLoopManager (TDD)** - `2c250d2` (test: RED), `e5c8acb` (feat: GREEN)
2. **Task 2: Engine integration, CLI, config** - `9daff4f` (feat)

## Files Created/Modified
- `src/fxsoqqabot/learning/loop.py` - LearningLoopManager facade orchestrating all learning sub-components
- `tests/test_learning_loop.py` - 27 tests for LearningLoopManager behaviors
- `src/fxsoqqabot/core/engine.py` - Extended TradingEngine with Phase 4 state updates, dashboards, learning loop
- `src/fxsoqqabot/cli.py` - Added dashboard/learning subcommands and --no-tui/--no-web/--no-learning flags
- `config/default.toml` - Added [tui], [web], [learning] config sections

## Decisions Made
- **LearningLoopManager as facade**: Single entry point (on_trade_closed) coordinates all learning activities, keeping TradingEngine simple
- **asyncio.to_thread for blocking operations**: DEAP evolution and sklearn classifier training run in threads to avoid blocking the async event loop
- **Learning disabled by default**: enabled=false in default.toml prevents accidental learning before sufficient trade history accumulates
- **Web dashboard as async task**: DashboardServer.start() added to asyncio.gather in engine.start() for parallel execution
- **TUI as main loop**: When TUI enabled, engine runs as background task with TUI controlling the main event loop

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All Phase 4 components are fully wired together
- TradingEngine updates shared state for both TUI and web dashboards
- Learning loop ready to evolve strategy parameters when enabled
- Phase 4 (observability-and-self-learning) is complete

## Self-Check: PASSED

All files exist. All commits verified.

---
*Phase: 04-observability-and-self-learning*
*Completed: 2026-03-27*
