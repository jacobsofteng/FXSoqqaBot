---
phase: 01-trading-infrastructure
plan: 01
subsystem: infra
tags: [pydantic, toml, structlog, config, events, dataclass]

# Dependency graph
requires:
  - phase: none
    provides: greenfield project
provides:
  - Pydantic config models (BotSettings, RiskConfig, ExecutionConfig, SessionConfig, DataConfig, LoggingConfig)
  - Three-phase capital risk model (get_risk_pct) per D-03
  - TOML config loading with env var overrides (FXBOT_ prefix)
  - Frozen dataclass event types (TickEvent, BarEvent, DOMSnapshot, FillEvent)
  - EventType str enum with 11 event types
  - structlog dual-mode logging (console/JSON)
  - Project package structure (src/fxsoqqabot/)
  - config/default.toml, paper.toml, live.toml
  - load_settings() convenience function
affects: [01-02, 01-03, 01-04, 01-05, 01-06, 01-07]

# Tech tracking
tech-stack:
  added: [pydantic, pydantic-settings, structlog, rich, metatrader5, numpy, pandas, duckdb, pyarrow, aiosqlite, pytz, pytest, ruff, mypy]
  patterns: [pydantic-settings TOML loading, frozen dataclass events with __slots__, structlog dual renderer, field_validator for pct range, BotSettings.from_toml() for safe TOML override]

key-files:
  created:
    - pyproject.toml
    - src/fxsoqqabot/config/models.py
    - src/fxsoqqabot/config/loader.py
    - src/fxsoqqabot/core/events.py
    - src/fxsoqqabot/logging/setup.py
    - config/default.toml
    - config/paper.toml
    - config/live.toml
    - tests/test_config/test_models.py
    - tests/test_config/test_events.py
    - tests/conftest.py
    - .gitignore
    - uv.lock
  modified: []

key-decisions:
  - "Used BotSettings.from_toml() classmethod with dynamic subclass instead of mutating class-level model_config -- prevents test pollution across test runs"
  - "Used datetime.now(UTC) instead of deprecated datetime.utcnow() for FillEvent timestamp default"
  - "pydantic-settings TomlConfigSettingsSource handles TOML loading natively -- no custom TOML parsing needed"

patterns-established:
  - "Pydantic config: nested BaseModel sections under BaseSettings top-level, TOML source customization via settings_customise_sources"
  - "Event types: frozen dataclasses with slots=True for immutability and memory efficiency"
  - "Logging: structlog with contextvars for cross-module context propagation, dual ConsoleRenderer/JSONRenderer"
  - "Testing: pytest with tmp_path for isolated TOML file testing, monkeypatch for env var tests"

requirements-completed: [CONF-01, CONF-02]

# Metrics
duration: 8min
completed: 2026-03-27
---

# Phase 01 Plan 01: Project Scaffolding Summary

**Pydantic config with three-phase capital risk model, frozen dataclass events, and structlog dual-mode logging on a fully-installed Python 3.12 package**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-27T08:58:27Z
- **Completed:** 2026-03-27T09:06:42Z
- **Tasks:** 2
- **Files modified:** 20+

## Accomplishments
- Full Python package scaffolded with all Phase 1 dependencies installed via uv (46 packages)
- Pydantic config models validate three capital phases returning 0.10/0.05/0.02 risk per trade (D-03)
- TOML config files load into validated BotSettings with env var override support (FXBOT_ prefix)
- Frozen dataclass event types defined for tick, bar, DOM, fill, and 11 system event types
- structlog configured with dual rendering: Rich console (dev) and JSON (production)

## Task Commits

Each task was committed atomically:

1. **Task 1 (TDD RED): Failing config tests** - `680d081` (test)
2. **Task 1 (TDD GREEN): Config models, TOML loading, loader** - `7f043e8` (feat)
3. **Task 2: Event types and structured logging** - `755e05a` (feat)
4. **Housekeeping: .gitignore and uv.lock** - `9026419` (chore)

## Files Created/Modified
- `pyproject.toml` - Project metadata, dependencies (metatrader5, numpy, pandas, pydantic, structlog, etc.)
- `src/fxsoqqabot/config/models.py` - RiskConfig, ExecutionConfig, SessionConfig, DataConfig, LoggingConfig, BotSettings
- `src/fxsoqqabot/config/loader.py` - load_settings() with graceful missing-file handling
- `src/fxsoqqabot/config/__init__.py` - Exports BotSettings and load_settings
- `src/fxsoqqabot/core/events.py` - TickEvent, BarEvent, DOMEntry, DOMSnapshot, FillEvent, EventType enum
- `src/fxsoqqabot/logging/setup.py` - setup_logging() with structlog dual-mode configuration
- `src/fxsoqqabot/logging/__init__.py` - Exports setup_logging, get_logger
- `config/default.toml` - Full default configuration matching all Pydantic model defaults
- `config/paper.toml` - Paper mode override only
- `config/live.toml` - Live mode override only
- `tests/test_config/test_models.py` - 25 tests for all config models and TOML loading
- `tests/test_config/test_events.py` - 15 tests for events and logging
- `tests/conftest.py` - Shared fixtures (tmp_config_dir, default_settings)
- `.gitignore` - Excludes __pycache__, .venv, IDE, data/, test caches
- `uv.lock` - Pinned dependency versions

## Decisions Made
- Used `BotSettings.from_toml()` classmethod with dynamic subclass creation to override TOML file paths without mutating the class-level `model_config` dict -- prevents test pollution
- Used `datetime.now(UTC)` instead of deprecated `datetime.utcnow()` for FillEvent timestamp
- pydantic-settings TomlConfigSettingsSource handles TOML natively -- no manual TOML parsing

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed datetime.utcnow() deprecation**
- **Found during:** Task 2 (Event types)
- **Issue:** Plan specified `datetime.utcnow()` which is deprecated in Python 3.12+ and scheduled for removal
- **Fix:** Changed to `datetime.now(UTC)` using `from datetime import UTC`
- **Files modified:** src/fxsoqqabot/core/events.py
- **Verification:** All tests pass with zero warnings
- **Committed in:** 755e05a (Task 2 commit)

**2. [Rule 1 - Bug] Fixed class-level model_config mutation in BotSettings**
- **Found during:** Task 1 (Config models TDD GREEN)
- **Issue:** Using `_toml_file` param in `__init__` mutated the shared class dict, causing test pollution (mode leaked from 'live' override test to subsequent default test)
- **Fix:** Replaced `_toml_file` __init__ approach with `from_toml()` classmethod that creates a dynamic subclass, keeping class-level config immutable
- **Files modified:** src/fxsoqqabot/config/models.py, tests/test_config/test_models.py
- **Verification:** All 25 config tests pass in any order
- **Committed in:** 7f043e8 (Task 1 GREEN commit)

**3. [Rule 3 - Blocking] Added .gitignore for generated files**
- **Found during:** Post-Task 2 cleanup
- **Issue:** __pycache__ directories were untracked; uv.lock needed to be committed for reproducibility
- **Fix:** Created .gitignore excluding __pycache__, .venv, IDE files, data/, test caches
- **Files modified:** .gitignore (new)
- **Verification:** `git status --short` shows clean working directory
- **Committed in:** 9026419

---

**Total deviations:** 3 auto-fixed (2 bugs, 1 blocking)
**Impact on plan:** All auto-fixes necessary for correctness and clean repo state. No scope creep.

## Issues Encountered
None beyond the auto-fixed items above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Config models ready for import by all subsequent plans (01-02 through 01-07)
- Event types ready for data ingestion (01-02), execution (01-03), and risk management (01-04)
- Structured logging ready for all modules
- All dependencies installed and locked

## Self-Check: PASSED

All 12 created files verified present. All 4 commit hashes verified in git log.

---
*Phase: 01-trading-infrastructure*
*Completed: 2026-03-27*
