---
phase: 03-backtesting-and-validation
plan: 02
subsystem: backtesting
tags: [histdata, csv-ingestion, parquet, duckdb, data-validation, tdd]

# Dependency graph
requires:
  - phase: 03-backtesting-and-validation
    plan: 01
    provides: "BacktestConfig with histdata_dir and parquet_dir paths"
  - phase: 01-trading-infrastructure
    provides: "TickStorage DuckDB/Parquet partitioning pattern (PARTITION_BY year, month)"
provides:
  - "HistoricalDataLoader: full CSV-to-Parquet ingestion pipeline for histdata.com M1 bar data"
  - "parse_histdata_csv: semicolon-delimited no-header CSV parsing with EST-to-UTC conversion"
  - "validate_bar_data: auto-repair with dedup, sort, gap interpolation, extreme bar removal, quality report"
  - "convert_to_parquet: DuckDB PARTITION_BY (year, month) Parquet output"
  - "load_bars: DuckDB time-range query from Parquet with start-inclusive end-exclusive windows"
  - "get_time_range: min/max timestamp query from Parquet"
affects: [03-03, 03-04, 03-05, backtesting-engine, walk-forward-validation]

# Tech tracking
tech-stack:
  added: []
  patterns: [histdata.com EST+5h UTC conversion, median-based outlier detection for robust extreme bar filtering, forward-fill gap interpolation with synthetic zero-volume bars]

key-files:
  created:
    - src/fxsoqqabot/backtest/historical.py
    - tests/test_backtest/test_historical.py
  modified: []

key-decisions:
  - "Median-based extreme bar detection instead of mean -- mean is inflated by outliers making 10x threshold ineffective"
  - "Forward-fill interpolation creates synthetic bars with close=previous close and volume=0 for gap identification"
  - "DuckDB in-memory connection for queries, separate connection per convert_to_parquet call for isolation"
  - "Quality report tracks all categories: duplicates, gaps, extreme bars, zero-volume bars as dict"

patterns-established:
  - "histdata.com CSV ingestion: semicolon-delimited, no headers, EST+5h to UTC, YYYYMMDD HHMMSS format"
  - "Data validation pipeline: dedup -> sort -> gap-fill -> extreme-filter -> zero-volume-count"
  - "Parquet partitioning via DuckDB COPY TO with PARTITION_BY (year, month) matching Phase 1 TickStorage"

requirements-completed: [DATA-04]

# Metrics
duration: 5min
completed: 2026-03-27
---

# Phase 03 Plan 02: Historical Data Ingestion Pipeline Summary

**histdata.com CSV-to-Parquet pipeline with EST-to-UTC conversion, auto-repair validation (dedup/sort/gap-fill/extreme-filter), and DuckDB time-range queries**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-27T14:18:29Z
- **Completed:** 2026-03-27T14:23:42Z
- **Tasks:** 1 (TDD: test + implementation)
- **Files created:** 2

## Accomplishments
- HistoricalDataLoader parses histdata.com semicolon-delimited CSVs with correct no-header format and YYYYMMDD HHMMSS datetime
- EST-to-UTC conversion adds exactly 5 hours per histdata.com specification (no DST), with Unix timestamp and partition columns
- Data validation auto-repairs: removes duplicates (keep first), sorts non-monotonic timestamps, interpolates small gaps (<=5 bars) via forward-fill, removes extreme range bars (>10x median range)
- Parquet output partitioned by year/month via DuckDB COPY, directly queryable by DuckDB for time-range slicing
- Quality report provides full accounting of all data issues (duplicates, gaps, extreme bars, zero-volume bars)
- 12 TDD tests covering all validation paths, parsing, Parquet I/O, and DuckDB query correctness

## Task Commits

Each task was committed atomically (TDD: test then feat):

1. **Task 1: CSV parsing, data validation, and Parquet conversion pipeline** - `fbea97f` (test: failing tests) + `59f47fe` (feat: implementation)

_TDD tasks have paired commits: RED (failing test) then GREEN (passing implementation)_

## Files Created/Modified
- `src/fxsoqqabot/backtest/historical.py` - HistoricalDataLoader class with parse_histdata_csv, validate_bar_data, convert_to_parquet, ingest_all, load_bars, get_time_range
- `tests/test_backtest/test_historical.py` - 12 tests covering CSV parsing, EST-to-UTC, validation auto-repair, Parquet output, DuckDB loading, quality report

## Decisions Made
- Median-based extreme bar detection instead of mean -- mean gets inflated by the extreme bars themselves, making the 10x threshold ineffective at catching outliers
- Forward-fill interpolation creates synthetic bars with open=high=low=close=previous_close and volume=0, making interpolated bars easily identifiable
- DuckDB in-memory connection for load_bars/get_time_range queries; fresh connection per convert_to_parquet for isolation
- Quality report as dict with all tracking keys (original_rows, final_rows, issues list, date_range tuple, per-category counts)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed extreme bar detection using median instead of mean**
- **Found during:** Task 1 (GREEN phase - test_validate_removes_extreme_bars failing)
- **Issue:** Using mean range for 10x threshold was inflated by the extreme bars themselves, making the threshold too high to catch outliers. A bar with range 50x normal would push the mean up so that 10x mean exceeded the outlier's range.
- **Fix:** Changed to median-based threshold (`median_range * 10`). Median is robust to outliers and provides a stable reference for normal bar range.
- **Files modified:** src/fxsoqqabot/backtest/historical.py
- **Verification:** test_validate_removes_extreme_bars passes
- **Committed in:** 59f47fe (part of feat commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Bug fix necessary for correctness. Median is strictly more robust than mean for outlier detection. No scope creep.

## Issues Encountered
- Worktree import resolution: the editable install points to the main repo src directory, not the worktree. Resolved by running pytest with `--import-mode=importlib -o "pythonpath=src"` to ensure the worktree's source files take precedence.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None - all data paths are fully wired. No placeholder data or hardcoded empty values.

## Next Phase Readiness
- HistoricalDataLoader is ready for the backtesting engine (Plan 03) to call load_bars() for historical bar replay
- Parquet partitioning matches Phase 1 TickStorage pattern for consistent data layout
- ingest_all() provides the full end-to-end pipeline from CSV directory to queryable Parquet
- Quality reports enable data quality monitoring before backtesting runs

## Self-Check: PASSED

- All 2 created files exist on disk
- All 2 commits (fbea97f, 59f47fe) verified in git log
- 12/12 tests pass

---
*Phase: 03-backtesting-and-validation*
*Completed: 2026-03-27*
