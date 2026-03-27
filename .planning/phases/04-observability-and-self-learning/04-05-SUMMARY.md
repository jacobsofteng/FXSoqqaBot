---
phase: 04-observability-and-self-learning
plan: 05
subsystem: learning
tags: [shadow-mode, genetic-algorithm, random-forest, mann-whitney, regime-classifier, paper-trading]

# Dependency graph
requires:
  - phase: 04-01
    provides: "LearningConfig with shadow/promotion settings, TradingEngineState"
  - phase: 04-04
    provides: "EvolutionManager with PARAM_BOUNDS and PARAM_NAMES for mutation"
provides:
  - "ShadowManager for running mutated strategy variants in paper mode"
  - "ShadowVariant with independent PaperExecutor instances"
  - "Mann-Whitney U statistical promotion gate (p < 0.05)"
  - "RegimeClassifier with RandomForest on 14-feature trade context"
  - "Feature importance analysis for regime prediction"
affects: [04-06, engine-integration, self-learning-loop]

# Tech tracking
tech-stack:
  added: [scipy.stats.mannwhitneyu, sklearn.ensemble.RandomForestClassifier, sklearn.preprocessing.LabelEncoder, sklearn.model_selection.cross_val_score]
  patterns: [non-parametric-statistical-testing, ml-regime-classification, shadow-variant-lifecycle]

key-files:
  created:
    - src/fxsoqqabot/learning/shadow.py
    - src/fxsoqqabot/learning/classifier.py
    - tests/test_shadow.py
    - tests/test_classifier.py

key-decisions:
  - "Mann-Whitney U (non-parametric) over t-test for promotion -- no normality assumption on P&L distributions"
  - "Win rate as simple fitness metric for shadow variants -- future plans can upgrade to risk-adjusted metrics"
  - "RandomForest with n_jobs=-1 for parallel regime prediction -- acceptable for single-machine deployment"
  - "3-fold cross-validation when sufficient data, training accuracy fallback otherwise"

patterns-established:
  - "Shadow variant isolation: each variant gets own PaperExecutor instance, never shared"
  - "Statistical promotion gate: significance test before walk-forward, not just fitness comparison"
  - "Gaussian perturbation from center of PARAM_BOUNDS with sigma=0.1*range for mutations"
  - "Graceful untrained default: RegimeClassifier returns RANGING with 0.0 confidence when not trained"

requirements-completed: [LEARN-03, LEARN-04, LEARN-06]

# Metrics
duration: 5min
completed: 2026-03-27
---

# Phase 04 Plan 05: Shadow Mode and ML Classifier Summary

**Shadow mode variant management with Mann-Whitney U promotion gates and RandomForest regime classifier on 14-feature trade context**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-27T18:42:54Z
- **Completed:** 2026-03-27T18:48:11Z
- **Tasks:** 2
- **Files created:** 4

## Accomplishments
- ShadowManager creates 3-5 independent variants each with own PaperExecutor -- no shared state between variants
- Promotion requires Mann-Whitney U statistical significance (p < 0.05) over configurable minimum trades
- RegimeClassifier trains RandomForest on 14 trade context features to predict regime with confidence
- Feature importance analysis reveals which signals contribute most to regime prediction accuracy
- All 20 tests passing (10 shadow + 10 classifier)

## Task Commits

Each task was committed atomically:

1. **Task 1: ShadowManager with variant lifecycle** - `13630a0` (test: RED) -> `4fcacd0` (feat: GREEN)
2. **Task 2: ML regime classifier** - `95f7d22` (test: RED) -> `9e892e2` (feat: GREEN)

_TDD tasks: test -> implementation commits_

## Files Created/Modified
- `src/fxsoqqabot/learning/shadow.py` - ShadowManager and ShadowVariant classes with variant lifecycle, mutation generation, Mann-Whitney U promotion evaluation
- `src/fxsoqqabot/learning/classifier.py` - RegimeClassifier with RandomForest, 14-feature extraction, cross-validation, feature importance
- `tests/test_shadow.py` - 10 tests covering variant creation, isolation, mutation bounds, promotion logic, lifecycle
- `tests/test_classifier.py` - 10 tests covering RF initialization, training, prediction, importance, insufficient data handling

## Decisions Made
- Mann-Whitney U (non-parametric) over t-test for promotion evaluation per research recommendation -- P&L distributions are not necessarily normal
- Win rate as simple fitness metric -- adequate for promotion comparison, can upgrade to Sharpe or profit factor later
- RandomForest with n_jobs=-1 for parallel tree fitting -- single-machine deployment makes this safe
- 3-fold cross-validation when >= 6 samples per class, training accuracy as fallback -- prevents sklearn errors with small datasets
- Walk-forward validation gate referenced but called externally by engine integration -- clean separation of concerns

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - both modules are fully functional with no placeholder data or TODO markers.

## Next Phase Readiness
- Shadow mode and ML classifier ready for engine integration (Plan 06)
- ShadowManager.evaluate_promotion returns promotion dict; engine wires walk-forward validation as additional gate
- RegimeClassifier.train() accepts trade log dicts directly compatible with TradeContextLogger output
- Both modules follow existing patterns (structlog, LearningConfig, PaperExecutor)

## Self-Check: PASSED

All 4 files exist. All 4 commits verified.

---
*Phase: 04-observability-and-self-learning*
*Completed: 2026-03-27*
