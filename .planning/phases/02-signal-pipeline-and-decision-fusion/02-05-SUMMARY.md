---
phase: 02-signal-pipeline-and-decision-fusion
plan: 05
subsystem: signals
tags: [fusion, decision-engine, signal-combination, ema-weights, regime-awareness, sl-tp, trailing-stops]

# Dependency graph
requires:
  - phase: 02-signal-pipeline-and-decision-fusion (plans 01-04)
    provides: SignalModule Protocol, SignalOutput, RegimeState, ChaosModule, FlowModule, TimingModule
provides:
  - FusionCore for confidence-weighted signal combination per D-01
  - AdaptiveWeightTracker for EMA-based module accuracy tracking per D-02
  - PhaseBehavior for smooth capital phase transitions per FUSE-04
  - TradeManager for regime-aware trade execution per FUSE-05
  - FusionResult and TradeDecision frozen dataclasses
affects: [03-backtesting, 04-self-learning, engine-integration]

# Tech tracking
tech-stack:
  added: []
  patterns: [additive-sigmoid-staircase, confidence-weighted-fusion, ema-accuracy-tracking]

key-files:
  created:
    - src/fxsoqqabot/signals/fusion/core.py
    - src/fxsoqqabot/signals/fusion/weights.py
    - src/fxsoqqabot/signals/fusion/phase_behavior.py
    - src/fxsoqqabot/signals/fusion/trade_manager.py
    - tests/signals/test_fusion.py
  modified:
    - src/fxsoqqabot/signals/fusion/__init__.py

key-decisions:
  - "Fused confidence = sum(confidence * weight) not mean -- when weights are normalized, this IS the weighted average confidence"
  - "Additive sigmoid staircase for monotonic phase transitions: base + sigmoid_step1 + sigmoid_step2"
  - "TYPE_CHECKING import for OrderManager and CircuitBreakerManager to avoid circular dependencies"

patterns-established:
  - "Additive sigmoid staircase: monotonic smooth threshold from base + cumulative sigmoid steps"
  - "TradeManager with optional OrderManager (None in testing) for testable trade execution"
  - "Regime adjustments as dict (empty for normal regimes) for clean conditional logic"

requirements-completed: [FUSE-01, FUSE-02, FUSE-03, FUSE-04, FUSE-05]

# Metrics
duration: 7min
completed: 2026-03-27
---

# Phase 02 Plan 05: Decision Fusion Core Summary

**Confidence-weighted signal fusion with EMA adaptive weights, smooth sigmoid phase transitions, and regime-aware trade execution**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-27T12:28:27Z
- **Completed:** 2026-03-27T12:35:50Z
- **Tasks:** 2 (TDD: RED-GREEN each)
- **Files modified:** 6

## Accomplishments
- FusionCore combines upstream SignalOutput instances using confidence-weighted blend per D-01 formula
- AdaptiveWeightTracker tracks module accuracy via EMA with warmup period and SQLite persistence support per D-02
- PhaseBehavior provides smooth sigmoid confidence thresholds across capital phases per FUSE-04, regime adjustments per D-06, RR ratios per D-09, and trailing stop params per D-10
- TradeManager bridges fusion decisions to trade execution with regime-aware SL/TP, single position limit per D-11, adverse regime tightening per D-08, and high-chaos size reduction per D-06

## Task Commits

Each task was committed atomically (TDD RED-GREEN):

1. **Task 1 RED: Failing tests for FusionCore, AdaptiveWeightTracker, PhaseBehavior** - `a5b4bac` (test)
2. **Task 1 GREEN: Implement FusionCore, AdaptiveWeightTracker, PhaseBehavior** - `3fc70ea` (feat)
3. **Task 2 RED: Failing tests for TradeManager** - `aa73218` (test)
4. **Task 2 GREEN: Implement TradeManager and fusion __init__ exports** - `4835037` (feat)

## Files Created/Modified
- `src/fxsoqqabot/signals/fusion/core.py` - FusionCore class with confidence-weighted fusion and FusionResult frozen dataclass
- `src/fxsoqqabot/signals/fusion/weights.py` - AdaptiveWeightTracker with EMA accuracy tracking and state persistence
- `src/fxsoqqabot/signals/fusion/phase_behavior.py` - PhaseBehavior with sigmoid transitions, regime adjustments, RR ratios, trailing stops
- `src/fxsoqqabot/signals/fusion/trade_manager.py` - TradeManager with regime-aware SL/TP, position limits, adverse tightening
- `src/fxsoqqabot/signals/fusion/__init__.py` - Exports all 6 public types
- `tests/signals/test_fusion.py` - 46 tests covering all fusion components

## Decisions Made
- **Fused confidence formula:** Used `sum(confidence * weight)` instead of `sum(confidence * weight) / len(signals)` because when weights are normalized (sum to 1.0), the sum IS the weighted average confidence, producing sensible threshold comparisons
- **Additive sigmoid staircase:** Used `base + sigmoid_step_1 + sigmoid_step_2` for monotonically increasing threshold across three capital phases, instead of `max(t1, t2)` which had a floor effect
- **TYPE_CHECKING imports:** Used `TYPE_CHECKING` guard for OrderManager and CircuitBreakerManager imports in TradeManager to avoid circular dependencies between signals and execution modules

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed fused confidence formula producing unreachable thresholds**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** Plan specified `fused_confidence = sum(confidence * weight) / len(signals)` which produces values ~0.24 even with all high-confidence signals -- below any reasonable threshold
- **Fix:** Changed to `fused_confidence = sum(confidence * weight)` which gives the weighted average confidence (0.715 for typical inputs)
- **Files modified:** src/fxsoqqabot/signals/fusion/core.py
- **Verification:** All buy signals with threshold=0.5 now correctly produce should_trade=True
- **Committed in:** 3fc70ea (Task 1 GREEN)

**2. [Rule 1 - Bug] Fixed PhaseBehavior threshold using max() creating floor effect**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** Using `max(t1, t2)` where t2 has a floor of 0.6 (selective threshold), so aggressive equity ($50) returned 0.6 instead of ~0.5
- **Fix:** Changed to additive sigmoid staircase: `base + step1_sigmoid + step2_sigmoid` for monotonic increase
- **Files modified:** src/fxsoqqabot/signals/fusion/phase_behavior.py
- **Verification:** Equity=50 returns ~0.5, equity=200 returns ~0.6, equity=500 returns ~0.7
- **Committed in:** 3fc70ea (Task 1 GREEN)

---

**Total deviations:** 2 auto-fixed (2 bugs in plan-specified formulas)
**Impact on plan:** Both fixes necessary for correctness. Formulas still honor the intent of D-01 and FUSE-04.

## Issues Encountered
- Position sizing at $50 equity with ATR=5.0 exceeds aggressive risk limit (10% risk for 0.01 lot) -- adjusted test parameters to use equity=$200 and ATR=1.0 for feasible trade scenarios

## Next Phase Readiness
- Complete fusion pipeline ready: signals -> FusionCore -> TradeManager -> OrderManager
- TradeManager integrates with existing OrderManager (None-safe for testing)
- AdaptiveWeightTracker supports get_state/load_state for SQLite persistence
- Ready for Plan 06 (engine integration) to wire fusion into TradingEngine

## Self-Check: PASSED

- All 6 files exist on disk
- All 4 commits verified in git history (a5b4bac, 3fc70ea, aa73218, 4835037)
- All 46 tests pass
- All imports from fxsoqqabot.signals.fusion succeed

---
*Phase: 02-signal-pipeline-and-decision-fusion*
*Completed: 2026-03-27*
