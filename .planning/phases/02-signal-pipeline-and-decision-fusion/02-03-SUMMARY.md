---
phase: 02-signal-pipeline-and-decision-fusion
plan: 03
subsystem: signals
tags: [order-flow, volume-delta, institutional, dom, hft, signal-module]

requires:
  - phase: 02-01
    provides: SignalModule Protocol, SignalOutput dataclass, FlowConfig model

provides:
  - OrderFlowModule implementing SignalModule Protocol
  - Volume delta computation from tick data (FLOW-01)
  - Bid-ask aggression imbalance with z-score significance (FLOW-02)
  - DOM depth analysis with quality auto-detection (FLOW-03, D-15)
  - Institutional footprint detection via absorption, iceberg, volume profile (FLOW-04, D-14)
  - HFT acceleration signature detection (FLOW-05)
  - Graceful tick-only degradation when DOM unavailable (FLOW-06, D-13)

affects: [02-05-fusion, 02-06-integration]

tech-stack:
  added: [structlog]
  patterns: [tick-first-dom-enhancement, dom-quality-auto-detection, weighted-signal-combination]

key-files:
  created:
    - src/fxsoqqabot/signals/flow/volume_delta.py
    - src/fxsoqqabot/signals/flow/aggression.py
    - src/fxsoqqabot/signals/flow/institutional.py
    - src/fxsoqqabot/signals/flow/dom_analyzer.py
    - src/fxsoqqabot/signals/flow/dom_quality.py
    - src/fxsoqqabot/signals/flow/module.py
    - tests/signals/test_flow.py
  modified:
    - src/fxsoqqabot/signals/flow/__init__.py

key-decisions:
  - "Perfect unanimity z-score saturation: when all ticks are same direction (std=0), assign saturated z-score=10 instead of 0, since zero variance with nonzero mean is the strongest possible signal"
  - "80/20 tick/DOM weighting per D-13: tick_direction = 0.6*delta + 0.2*aggression + 0.2*institutional, then 0.8*tick + 0.2*dom when DOM available"
  - "Ambiguous tick penalty: reduce confidence proportionally when ambiguous_pct exceeds 30% per Research Pitfall 3"

patterns-established:
  - "Tick classification: last >= ask = buy-initiated, last <= bid = sell-initiated, between = ambiguous"
  - "DOM quality auto-detection: sample snapshots, check depth+rate thresholds, enable/disable with logging"
  - "Weighted signal combination: normalize sub-signals to [-1,+1], combine with fixed weights, clip output"

requirements-completed: [FLOW-01, FLOW-02, FLOW-03, FLOW-04, FLOW-05, FLOW-06]

duration: 7min
completed: 2026-03-27
---

# Phase 02 Plan 03: Order Flow Module Summary

**Order flow signal module with volume delta tick classification, bid-ask aggression z-scores, institutional absorption/iceberg/volume-profile detection, DOM quality auto-detection per D-15, and 80/20 tick/DOM weighted fusion per D-13**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-27T12:15:19Z
- **Completed:** 2026-03-27T12:23:00Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Volume delta classifies ticks as buy/sell/ambiguous from bid-ask comparison with rolling window
- Aggression imbalance measures directional pressure with z-score significance testing
- Institutional footprints detected via absorption (large volume, no movement), iceberg reload (repeated at same price), and volume-at-price profile clustering
- HFT acceleration signatures identified from tick velocity spikes with spread widening
- DOM analysis with automatic quality detection: samples depth/rate, enables/disables with logging
- OrderFlowModule implements SignalModule Protocol with graceful tick-only degradation
- 31 tests covering all components including edge cases (empty arrays, single ticks)

## Task Commits

Each task was committed atomically:

1. **Task 1: Volume delta, aggression, HFT, institutional** - `322bb1e` (test) + `33feab3` (feat)
2. **Task 2: DOM analysis, quality checker, OrderFlowModule** - `a2a4762` (feat)

_TDD: test commit followed by implementation commit for Task 1_

## Files Created/Modified
- `src/fxsoqqabot/signals/flow/volume_delta.py` - Cumulative volume delta from tick classification (FLOW-01)
- `src/fxsoqqabot/signals/flow/aggression.py` - Bid-ask aggression imbalance + HFT detection (FLOW-02, FLOW-05)
- `src/fxsoqqabot/signals/flow/institutional.py` - Absorption, iceberg, volume profile institutional detection (FLOW-04)
- `src/fxsoqqabot/signals/flow/dom_analyzer.py` - DOM depth order book imbalance analysis (FLOW-03)
- `src/fxsoqqabot/signals/flow/dom_quality.py` - DOM quality auto-detection with depth/rate thresholds (D-15)
- `src/fxsoqqabot/signals/flow/module.py` - OrderFlowModule combining all components (FLOW-06, D-13)
- `src/fxsoqqabot/signals/flow/__init__.py` - Module exports
- `tests/signals/test_flow.py` - 31 tests for all order flow components

## Decisions Made
- Perfect unanimity z-score saturation: when std=0 with nonzero mean (all ticks same direction), assign saturated z-score of +/-10 rather than 0, because zero variance with nonzero mean is the strongest possible unanimity signal
- 80/20 tick/DOM effort split per D-13: tick direction weighted 0.6 delta + 0.2 aggression + 0.2 institutional, blended 80% tick + 20% DOM when DOM enabled
- Ambiguous tick penalty per Research Pitfall 3: reduce confidence when ambiguous fraction exceeds 30%
- HFT confidence reduction: multiply confidence by 0.8 when HFT detected (noise reduction)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Z-score zero variance edge case**
- **Found during:** Task 1 (aggression imbalance)
- **Issue:** When all ticks are same direction, per-tick imbalance std=0, causing z-score=0 despite maximum signal strength
- **Fix:** Saturate z-score to +/-10.0 when std=0 and mean is nonzero
- **Files modified:** src/fxsoqqabot/signals/flow/aggression.py
- **Verification:** test_confidence_scales_with_zscore passes
- **Committed in:** 33feab3

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential fix for correctness -- zero-variance unanimity is the strongest signal, not no signal.

## Issues Encountered
None beyond the z-score edge case handled above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- OrderFlowModule ready for fusion layer integration (Plan 05)
- All 6 FLOW requirements implemented and tested
- Module produces valid output with tick-only data (no DOM dependency)
- DOM enhancement activates automatically when quality passes D-15 checks

## Self-Check: PASSED

- All 8 files verified present on disk
- All 3 commits verified in git log (322bb1e, 33feab3, a2a4762)
- 31/31 tests passing
- SignalModule Protocol isinstance check passes
- Import from fxsoqqabot.signals.flow succeeds

---
*Phase: 02-signal-pipeline-and-decision-fusion*
*Completed: 2026-03-27*
