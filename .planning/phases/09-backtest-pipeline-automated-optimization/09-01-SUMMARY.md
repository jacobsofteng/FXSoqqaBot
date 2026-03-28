---
phase: 09-backtest-pipeline-automated-optimization
plan: 01
subsystem: optimization
tags: [optuna, search-space, chaos-config, regime-thresholds, pydantic]

# Dependency graph
requires:
  - phase: 08-signal-risk-calibration
    provides: ChaosConfig direction_mode, FusionConfig thresholds, RiskConfig phase-aware sizing
provides:
  - Unified 25-parameter Optuna search space across 5 config categories
  - Configurable regime classification thresholds via ChaosConfig
  - Multi-model apply_params_to_settings mapper (Fusion, Risk, Chaos, Timing)
  - TimingConfig urgency_floor field for optimizer tuning
affects: [09-02, optimization, backtest-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns: [multi-model-param-override, configurable-thresholds, categorical-optuna-param]

key-files:
  created: []
  modified:
    - src/fxsoqqabot/optimization/search_space.py
    - src/fxsoqqabot/config/models.py
    - src/fxsoqqabot/signals/chaos/regime.py
    - src/fxsoqqabot/signals/chaos/module.py
    - config/default.toml

key-decisions:
  - "Default threshold values match previous hardcoded values for backward compatibility"
  - "DEAP weight seeds folded into unified Optuna search space per D-08"
  - "Confidence floor checks (>0.3, >0.2) left hardcoded -- not tunable thresholds"

patterns-established:
  - "Multi-model param override: apply_params_to_settings routes params to correct config model via model_fields check"
  - "Configurable thresholds: regime classifier accepts ChaosConfig with None default for backward compat"

requirements-completed: [OPT-02]

# Metrics
duration: 5min
completed: 2026-03-28
---

# Phase 09 Plan 01: Expanded Search Space Summary

**25-parameter unified Optuna search space across Fusion, Risk, Chaos, Timing configs with configurable regime thresholds**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-28T14:22:16Z
- **Completed:** 2026-03-28T14:28:01Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Expanded search space from 11 FusionConfig-only params to 25 params across 5 categories (fusion, weights, risk, chaos, timing)
- Made regime classifier thresholds configurable via ChaosConfig fields instead of hardcoded magic numbers
- Extended apply_params_to_settings to handle FusionConfig, RiskConfig, ChaosConfig, and TimingConfig
- Added categorical direction_mode parameter via suggest_categorical
- All 821 existing tests pass with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add configurable regime threshold fields to ChaosConfig and TimingConfig** - `ed858df` (feat)
2. **Task 2: Expand search space to ~20 params and extend apply_params_to_settings** - `9e47d8c` (feat)

## Files Created/Modified
- `src/fxsoqqabot/config/models.py` - Added 5 regime threshold fields to ChaosConfig, urgency_floor to TimingConfig
- `src/fxsoqqabot/signals/chaos/regime.py` - Refactored classify_regime to accept ChaosConfig with configurable thresholds
- `src/fxsoqqabot/signals/chaos/module.py` - Updated classify_regime call to pass self._config
- `src/fxsoqqabot/optimization/search_space.py` - Complete rewrite with 25-param unified space and multi-model mapper
- `config/default.toml` - Added new chaos threshold and timing urgency_floor defaults

## Decisions Made
- Default threshold values (0.6, 0.45, 0.5, 0.7, 0.7) match previous hardcoded values for backward compatibility
- DEAP weight seeds (3 params) folded into unified Optuna search space per D-08
- Confidence floor checks (>0.3, >0.2) left hardcoded -- these are not regime thresholds to tune
- Confidence threshold bounds tightened (0.20-0.50, 0.30-0.60, 0.40-0.75) per plan specification

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Search space ready for 09-02 (pipeline orchestrator and NSGA-II optimization)
- apply_params_to_settings handles all 4 config models needed by the optimizer
- Regime thresholds are now tunable parameters for automated optimization

## Self-Check: PASSED

- All 5 modified files exist on disk
- Both task commits (ed858df, 9e47d8c) found in git log
- 821 tests passing, 0 failures

---
*Phase: 09-backtest-pipeline-automated-optimization*
*Completed: 2026-03-28*
