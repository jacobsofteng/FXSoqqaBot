---
phase: 05-self-learning-feedback-loop-wiring
plan: 01
subsystem: learning
tags: [adaptive-weights, shadow-variants, promote-callback, feedback-loop, pydantic, fusion]

# Dependency graph
requires:
  - phase: 04-observability-and-self-learning
    provides: LearningLoopManager, ShadowManager, AdaptiveWeightTracker, TradeContextLogger
  - phase: 02-signal-pipeline-and-decision-fusion
    provides: FusionCore, PhaseBehavior, TradeManager, SignalOutput
provides:
  - FUSE-02 wiring: adaptive weight feedback after every trade close
  - LEARN-04 wiring: shadow variant trade recording after every trade close
  - LEARN-05 wiring: promote callback applying variant params to live strategy
  - Complete self-learning feedback chain from trade outcome to strategy adaptation
affects: [05-02-PLAN, backtesting, optimization]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Promote callback closure pattern: engine creates closure that rebuilds FusionCore/PhaseBehavior/TradeManager without full restart"
    - "GIL-atomic reference swap for component replacement during promote"
    - "apply_params_to_settings model_copy chain for immutable Pydantic config updates"

key-files:
  created: []
  modified:
    - src/fxsoqqabot/core/engine.py
    - src/fxsoqqabot/learning/loop.py

key-decisions:
  - "Promote callback rebuilds only FusionCore/PhaseBehavior/TradeManager -- not bridge, buffers, storage, or signal modules"
  - "Late import of apply_params_to_settings inside _create_promote_callback to avoid circular imports"
  - "actual_direction derived from PnL sign (1.0 if profit, -1.0 if loss) per AdaptiveWeightTracker contract"
  - "All shadow variants record the same trade outcome on every close -- by design for Mann-Whitney comparison"

patterns-established:
  - "Promote callback pattern: engine._create_promote_callback returns closure wired to LearningLoopManager.set_promote_callback"
  - "Weight persistence pattern: save_signal_weights called immediately after record_outcome in trade close pipeline"

requirements-completed: [FUSE-02, LEARN-04, LEARN-05, LEARN-06]

# Metrics
duration: 4min
completed: 2026-03-28
---

# Phase 05 Plan 01: Self-Learning Feedback Loop Wiring Summary

**Wired all four self-learning feedback gaps: adaptive weight updates, shadow variant trade recording, promote callback with FusionCore/PhaseBehavior/TradeManager rebuild, and walk-forward gate reachability**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-28T07:01:28Z
- **Completed:** 2026-03-28T07:05:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- FUSE-02: AdaptiveWeightTracker.record_outcome() called after every paper trade close with module signals and actual direction, weights persisted to SQLite
- LEARN-04: ShadowManager.record_variant_trade() called for every shadow variant after every paper trade close
- LEARN-05: LearningLoopManager.set_promote_callback() wired in engine, _check_promotions invokes callback after dual-gate promotion, callback rebuilds FusionCore/PhaseBehavior/TradeManager with new params
- LEARN-06: Walk-forward validation gate now reachable because LEARN-04 populates shadow variant trade history upstream

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire adaptive weight feedback and shadow trade recording** - `fa984ac` (feat)
2. **Task 2: Add promote callback to LearningLoopManager and wire in engine** - `47bec3a` (feat)

## Files Created/Modified
- `src/fxsoqqabot/core/engine.py` - Added FUSE-02 weight feedback, LEARN-04 shadow recording, LEARN-05 promote callback wiring and _create_promote_callback method
- `src/fxsoqqabot/learning/loop.py` - Added _promote_callback instance variable, set_promote_callback method, callback invocation in _check_promotions

## Decisions Made
- Promote callback rebuilds only FusionCore, PhaseBehavior, and TradeManager -- not the full engine. Bridge, buffers, storage, signal modules remain untouched for lightweight hot-swap.
- Late import of apply_params_to_settings inside _create_promote_callback body follows established pattern of avoiding circular imports in engine.py.
- actual_direction is derived purely from PnL sign (1.0 if profit, -1.0 if loss), matching AdaptiveWeightTracker.record_outcome contract.
- All shadow variants receive the same trade result on every close -- this is the correct design since variants compete on accumulated P&L distributions via Mann-Whitney U test.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all wiring points are fully connected with no placeholder values.

## Next Phase Readiness
- All four self-learning feedback loop gaps (FUSE-02, LEARN-04, LEARN-05, LEARN-06) are now wired
- Trade outcomes flow through: weight adaptation -> shadow recording -> promotion evaluation -> param application
- Ready for 05-02 plan (if applicable) or milestone verification

## Self-Check: PASSED

- FOUND: src/fxsoqqabot/core/engine.py
- FOUND: src/fxsoqqabot/learning/loop.py
- FOUND: 05-01-SUMMARY.md
- FOUND: commit fa984ac (Task 1)
- FOUND: commit 47bec3a (Task 2)

---
*Phase: 05-self-learning-feedback-loop-wiring*
*Completed: 2026-03-28*
