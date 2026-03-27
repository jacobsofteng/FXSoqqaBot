# Phase 3: Backtesting and Validation - Research

**Researched:** 2026-03-27
**Domain:** Backtesting engine, walk-forward validation, Monte Carlo simulation, regime-aware evaluation, historical data ingestion
**Confidence:** HIGH

## Summary

Phase 3 builds the scientific validation framework that replays 2015-present XAUUSD history through the exact same signal pipeline used in live trading. The critical architectural challenge is introducing a DataFeedProtocol and Clock abstraction that decouples the existing MarketDataFeed and TradingEngine from MT5 without breaking live trading. This is not a "separate backtesting engine" -- it is the same engine running against historical data via interface abstraction (TEST-07).

The existing codebase has strong foundations for this: SignalModule Protocol (structural typing), frozen dataclasses for events (TickEvent, BarEvent), numpy array interfaces (TickBuffer.as_arrays(), BarBuffer.as_arrays()), and PaperExecutor for fill simulation. The backtest engine feeds the identical dict shapes (tick_arrays, bar_arrays, dom) to the identical signal modules. The key new components are: (1) histdata.com CSV ingestion to Parquet, (2) DataFeedProtocol abstraction, (3) BacktestClock for deterministic time, (4) BacktestExecutor extending PaperExecutor with session-aware spread/slippage models, (5) walk-forward coordinator, (6) Monte Carlo trade shuffler, (7) regime-aware evaluation and Feigenbaum stress testing.

**Primary recommendation:** Build a custom backtesting engine on top of the existing signal pipeline rather than deeply integrating vectorbt. Use vectorbt only for portfolio-level analytics (Sharpe, drawdown, equity curves) on the output trade list, not for the simulation loop itself. The signal pipeline is too complex (3 async modules, chaos/flow/timing with numpy array inputs) for vectorbt's from_order_func callback model, which requires Numba-compatible functions.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Dual data source: histdata.com M1 bar CSVs for 2015-2024 bulk history, MT5 tick data for the most recent 1-2 years. Signal modules run on M1 bars for older data, full ticks for recent data.
- **D-02:** Graceful module degradation when only M1 bars are available. Chaos and order flow modules run in "bar-only" mode with reduced confidence -- similar to how order flow already degrades without DOM data (Phase 2 D-13). Modules adapt computations to bar OHLCV.
- **D-03:** Strict data validation with auto-repair. Validate timestamps are monotonic, detect/fill gaps (weekends, holidays, outages), flag suspicious bars (extreme range, zero volume), log quality report. Automatically interpolate small gaps (<5 bars) and filter extreme outliers.
- **D-04:** Convert CSVs to Parquet once, partitioned by year/month. DuckDB queries Parquet directly. Consistent with Phase 1's tick storage pattern. One-time conversion cost, fast repeated backtests.
- **D-05:** Walk-forward windows: 6 months training, 2 months validation, rolling forward by 2 months. ~50 windows from 2015-present.
- **D-06:** Dual walk-forward threshold -- BOTH must pass: (1) Strategy must be net profitable in at least 70% of walk-forward windows (2) Aggregate profit factor > 1.5 across all windows combined
- **D-07:** Monte Carlo dual threshold -- BOTH must pass: (1) 5th percentile of Monte Carlo equity curves (10,000+ runs) must be net positive (p < 0.05) (2) Median Monte Carlo run must be profitable AND 95th percentile max drawdown must stay below 40% of peak equity
- **D-08:** Regime-aware evaluation uses the 5 regimes from the chaos module: trending-up, trending-down, ranging, high-chaos, pre-bifurcation. Tag historical periods by running the chaos module over them and measure performance separately per regime.
- **D-09:** Session-aware dynamic spread model. Calibrate from recent MT5 tick data where real spreads are available. Model spread by time-of-day and volatility.
- **D-10:** Stochastic slippage drawn from a distribution calibrated to recent live fills.
- **D-11:** Configurable per-lot commission cost. Default to RoboForex ECN rates (~$5-7 per round-trip for gold).
- **D-12:** Reserve the most recent 6 months (~Oct 2025 - Mar 2026) as untouched holdout. Never used during development, walk-forward training, or parameter tuning.
- **D-13:** Hard fail on OOS divergence. If out-of-sample profit factor is less than 50% of in-sample, or max drawdown exceeds 2x in-sample, the strategy is flagged as overfit and rejected.

### Claude's Discretion
- DataFeedProtocol and Clock abstraction design (TEST-07 interface abstraction)
- How to retrofit the abstraction onto existing MarketDataFeed/TradingEngine without breaking live trading
- vectorbt integration approach vs custom engine architecture
- Feigenbaum stress testing implementation (synthetic regime transition injection)
- Backtest result storage schema and reporting format
- histdata.com CSV parsing specifics (format detection, encoding)
- Walk-forward optimizer coordination and parallelization strategy

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-04 | Bot loads and parses historical M1 bar data from histdata.com CSV files (2015-present) for backtesting | histdata.com CSV format specification (semicolon-delimited, no headers, EST timezone), Parquet conversion pattern matching Phase 1 TickStorage, `histdata` pip package for automated download |
| TEST-01 | Backtesting engine replays historical data with realistic spread simulation, slippage modeling, and commission costs | Custom engine replaying bars through existing signal pipeline, BacktestExecutor with session-aware spread model (D-09), stochastic slippage (D-10), configurable commission (D-11) |
| TEST-02 | Walk-forward validation trains on one period and validates on the next unseen period, rolling forward continuously | 6-month train / 2-month validation windows rolling by 2 months (D-05), dual threshold pass/fail (D-06), ~50 windows from 2015-present |
| TEST-03 | Monte Carlo simulation randomizes trade order sequences 10,000+ times, results statistically significant (p < 0.05) | NumPy-based trade shuffling (np.random.permutation), equity curve generation, 5th percentile positive + median profitable + bounded drawdown (D-07) |
| TEST-04 | Out-of-sample testing reserves recent history for final validation only | Most recent 6 months as untouched holdout (D-12), hard fail on OOS divergence (D-13) |
| TEST-05 | Regime-aware evaluation measures performance separately across market regimes | Run chaos module over historical data to tag periods, measure per-regime PF/drawdown/win-rate for all 5 RegimeState values (D-08) |
| TEST-06 | Feigenbaum stress testing injects simulated regime transitions into backtests | Synthetic price series with controlled bifurcation patterns, verify chaos module detects proximity, verify strategy adapts behavior at transitions |
| TEST-07 | Backtesting shares 100% of analysis code with live trading via interface abstraction | DataFeedProtocol (Protocol class), BacktestClock replacing real time, BacktestDataFeed producing identical dict shapes to MarketDataFeed |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Python 3.12.x** -- project targets 3.12 (venv confirmed at 3.12.13)
- **No Backtrader, no Zipline** -- CLAUDE.md explicitly forbids both
- **No TA-Lib** -- avoid C dependency; use NumPy/SciPy for custom indicators
- **vectorbt 0.28.x (open source)** -- CLAUDE.md recommends this + custom engine on top
- **DuckDB + Parquet** for analytical storage; SQLite for operational state
- **pandas 2.2.x** as primary DataFrame layer; Polars 1.x for bulk backtesting pipelines only
- **structlog** for structured logging with context binding (backtest run ID, window ID, regime)
- **Pydantic 2.12.5** for configuration validation
- **Protocol-based interfaces** -- use structural typing, not ABC inheritance
- **Frozen dataclasses with `__slots__`** for event types
- **uv** for package management
- **pytest** with pytest-asyncio for testing
- **ruff** for linting/formatting

## Standard Stack

### Core (already installed in project venv)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | 2.4.3 | Array operations for bar/tick data manipulation, Monte Carlo | Already installed, foundation of signal pipeline |
| scipy | 1.17.1 | Statistical testing (scipy.stats for p-values), signal processing | Already installed, used by chaos module |
| pandas | 2.3.3 | DataFrame operations for trade results, CSV parsing, resampling | Already installed, MT5 returns pandas natively |
| duckdb | 1.5.1 | Analytical queries on historical bar data and backtest results | Already installed, matches Phase 1 TickStorage pattern |
| pyarrow | 23.0.1 | Parquet read/write for historical data storage | Already installed, used for tick data storage |
| structlog | 25.5.0 | Structured logging with backtest context binding | Already installed |
| pydantic | 2.12.5 | BacktestConfig validation, result schemas | Already installed |
| numba | 0.64.0 | JIT compilation for hot Monte Carlo loops | Already installed, used by chaos computations |

### New Dependencies (need installation)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| vectorbt | 0.28.5 | Portfolio analytics: Sharpe, drawdown, equity curves, trade stats | Post-simulation analytics only -- NOT for the simulation loop itself |
| histdata | latest | Automated download of histdata.com M1 CSV files | One-time data ingestion; download then convert to Parquet |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| vectorbt for full simulation | Custom engine | Custom engine is necessary because signal pipeline has 3 async modules with complex numpy array inputs incompatible with vectorbt's Numba callback model. Use vectorbt only for post-hoc analytics. |
| histdata pip package | Manual download from histdata.com | Manual download is simpler but not automated. Use pip package for reproducibility. Either approach produces the same CSVs. |
| Polars for bulk processing | pandas throughout | Polars is 5-30x faster for analytical joins. Use for bulk backtest result analysis if pandas becomes a bottleneck. Not critical for v1. |

**Installation:**
```bash
uv pip install vectorbt histdata
```

**Version verification note:** vectorbt 0.28.5 (released 2026-03-26 per PyPI) requires numba and numpy, which are already in the project. Verify compatibility after install: `python -c "import vectorbt; print(vectorbt.__version__)"`. The main risk is vectorbt pulling conflicting dependency versions -- use `uv pip install --no-deps vectorbt` if needed, then install any missing sub-dependencies individually.

## Architecture Patterns

### Recommended Project Structure
```
src/fxsoqqabot/
  backtest/
    __init__.py
    clock.py            # BacktestClock (deterministic time for replay)
    config.py           # BacktestConfig (Pydantic model for all backtest params)
    data_feed.py        # DataFeedProtocol + BacktestDataFeed
    engine.py           # BacktestEngine (replay loop using existing signal pipeline)
    executor.py         # BacktestExecutor (extends PaperExecutor with spread/slippage models)
    historical.py       # HistoricalDataLoader (histdata.com CSV -> Parquet)
    monte_carlo.py      # Monte Carlo trade sequence shuffler
    regime_tagger.py    # Tag historical periods with regime states
    results.py          # BacktestResult dataclass + DuckDB storage
    stress_test.py      # Feigenbaum stress testing (synthetic regime transitions)
    validation.py       # Walk-forward coordinator + OOS evaluation
  data/
    feed.py             # MarketDataFeed (modify to implement DataFeedProtocol)
    protocol.py         # DataFeedProtocol definition (or in backtest/data_feed.py)
  core/
    engine.py           # TradingEngine (modify to accept Clock + DataFeedProtocol)
```

### Pattern 1: DataFeedProtocol (TEST-07 Critical Path)

**What:** A Protocol class that both MarketDataFeed (live) and BacktestDataFeed (historical) implement. The TradingEngine depends only on the Protocol, not on the concrete class.

**When to use:** This is the architectural keystone of the phase. Every other component depends on this abstraction.

**Design:**
```python
# src/fxsoqqabot/data/protocol.py
from typing import Protocol, runtime_checkable
import numpy as np
from fxsoqqabot.core.events import DOMSnapshot

@runtime_checkable
class DataFeedProtocol(Protocol):
    """Protocol for market data sources -- live or historical replay.

    Both MarketDataFeed and BacktestDataFeed implement this.
    TradingEngine depends only on this Protocol.
    """

    async def get_tick_arrays(self, symbol: str) -> dict[str, np.ndarray]:
        """Return tick data as numpy arrays.

        Keys: time_msc, bid, ask, last, spread, volume_real.
        Matches TickBuffer.as_arrays() output format exactly.
        """
        ...

    async def get_bar_arrays(
        self, symbol: str
    ) -> dict[str, dict[str, np.ndarray]]:
        """Return multi-timeframe bar data as numpy arrays.

        Outer dict keyed by timeframe ("M1", "M5", etc).
        Inner dict keyed by field ("time", "open", "high", "low", "close", "tick_volume").
        Matches BarBufferSet[tf].as_arrays() output format exactly.
        """
        ...

    async def get_dom(self, symbol: str) -> DOMSnapshot | None:
        """Return DOM snapshot or None for degraded mode."""
        ...

    def check_tick_freshness(self, max_age_seconds: float = 10.0) -> bool:
        """Whether data is fresh. Always True in backtest mode."""
        ...
```

**Retrofit strategy:** The existing MarketDataFeed does not directly implement this Protocol shape -- it has `fetch_ticks()` returning `list[TickEvent]` and separate buffer management. Two options:

1. **Adapter pattern (recommended):** Create a `LiveDataFeedAdapter` that wraps MarketDataFeed + TickBuffer + BarBufferSet and implements DataFeedProtocol. The TradingEngine uses the adapter. Zero changes to MarketDataFeed internals.
2. **Direct modification:** Rename/add methods to MarketDataFeed. Riskier -- changes a working component.

The adapter approach keeps the existing live trading code untouched while the backtest feed implements the same Protocol directly.

### Pattern 2: BacktestClock (Deterministic Time)

**What:** A Clock Protocol that provides the current time. Live mode uses real UTC time. Backtest mode advances time bar-by-bar from historical data.

```python
# src/fxsoqqabot/backtest/clock.py
from typing import Protocol
from datetime import datetime

class Clock(Protocol):
    """Time source -- real or simulated."""
    def now(self) -> datetime: ...
    def now_msc(self) -> int: ...

class WallClock:
    """Real-time clock for live trading."""
    def now(self) -> datetime:
        return datetime.now(UTC)
    def now_msc(self) -> int:
        return int(datetime.now(UTC).timestamp() * 1000)

class BacktestClock:
    """Deterministic clock for backtesting. Time advances with each bar."""
    def __init__(self) -> None:
        self._current_time_msc: int = 0

    def advance(self, time_msc: int) -> None:
        """Advance clock to the timestamp of the current bar."""
        self._current_time_msc = time_msc

    def now(self) -> datetime:
        return datetime.fromtimestamp(self._current_time_msc / 1000, tz=UTC)

    def now_msc(self) -> int:
        return self._current_time_msc
```

**Impact on TradingEngine:** Currently `TradingEngine` uses `datetime.now(timezone.utc)` in multiple places (MarketDataFeed, events). The Clock must be injectable. Minimal change: add a `clock` parameter to engine constructor, default to `WallClock()`.

### Pattern 3: BacktestEngine (Synchronous Replay Loop)

**What:** Instead of modifying TradingEngine's async loops, build a synchronous replay engine that calls the same signal modules.

**Rationale:** The live TradingEngine runs 4 concurrent async loops (tick, bar, health, signal). In backtesting, there is no real-time polling -- we iterate bar-by-bar sequentially. Trying to shoehorn historical data into the async polling model adds complexity for zero benefit. Better to build a synchronous replay loop that calls the signal modules directly.

```python
class BacktestEngine:
    """Synchronous replay engine using the same signal pipeline."""

    def __init__(
        self,
        settings: BotSettings,
        backtest_config: BacktestConfig,
        data_feed: BacktestDataFeed,
        clock: BacktestClock,
        executor: BacktestExecutor,
    ) -> None:
        # Initialize same signal modules as TradingEngine
        self._chaos = ChaosRegimeModule(settings.signals.chaos)
        self._flow = OrderFlowModule(settings.signals.flow)
        self._timing = QuantumTimingModule(settings.signals.timing)
        self._fusion = FusionCore(settings.signals.fusion)
        # ... same components as TradingEngine._initialize_components()

    async def run(self, start_time: int, end_time: int) -> BacktestResult:
        """Replay historical data bar-by-bar through signal pipeline."""
        for bar_time, tick_arrays, bar_arrays in self._data_feed.iterate(start_time, end_time):
            self._clock.advance(bar_time)

            # Run same signal modules with same inputs
            signals = []
            for module in [self._chaos, self._flow, self._timing]:
                signal = await module.update(tick_arrays, bar_arrays, None)
                signals.append(signal)

            # Same fusion
            fusion_result = self._fusion.fuse(signals, weights, threshold)

            # Same trade evaluation (via BacktestExecutor)
            if fusion_result.should_trade:
                decision = self._executor.evaluate_and_execute(...)
                # Record trade with regime tag

        return self._build_result()
```

**Key insight:** The signal modules are already Protocol-based and receive dict[str, np.ndarray] inputs. They do not care if the arrays come from live MT5 polling or historical Parquet files. TEST-07 is satisfied because the exact same module code runs in both contexts.

### Pattern 4: Historical Data Pipeline (DATA-04)

**What:** Download histdata.com CSVs, validate, convert to Parquet partitioned by year/month.

```
histdata.com CSVs -> parse (semicolon-delimited, no headers, EST tz)
    -> validate (monotonic timestamps, gap detection, outlier filtering)
    -> convert to Parquet (partitioned year/month)
    -> DuckDB queries Parquet directly for backtest windows
```

**CSV format (from official histdata.com specification):**
- Delimiter: semicolon (`;`)
- Columns: DateTime; Open; High; Low; Close; Volume
- DateTime format: `YYYYMMDD HHMMSS` (e.g., `20150102 170000`)
- Timezone: Eastern Standard Time (EST) -- NO daylight saving adjustments
- No headers in file
- All prices are bid quotes
- Volume is tick count (not lot volume)

**Timezone conversion:** EST is UTC-5 fixed (no DST). Convert to UTC immediately during parsing: `timestamp_utc = timestamp_est + timedelta(hours=5)`.

### Pattern 5: Session-Aware Spread Model (D-09)

```python
@dataclass(frozen=True, slots=True)
class SpreadModel:
    """Session-aware dynamic spread simulation per D-09."""
    london_ny_overlap_pips: tuple[float, float] = (2.0, 3.0)  # tight
    london_session_pips: tuple[float, float] = (3.0, 5.0)
    asian_session_pips: tuple[float, float] = (4.0, 6.0)
    low_liquidity_pips: tuple[float, float] = (6.0, 10.0)

    def sample_spread(self, hour_utc: int, volatility_factor: float = 1.0) -> float:
        """Sample spread from session-appropriate distribution."""
        if 13 <= hour_utc <= 17:  # London-NY overlap
            low, high = self.london_ny_overlap_pips
        elif 8 <= hour_utc <= 12:  # London morning
            low, high = self.london_session_pips
        elif 0 <= hour_utc <= 7:  # Asian session
            low, high = self.asian_session_pips
        else:
            low, high = self.low_liquidity_pips
        base = np.random.uniform(low, high)
        return base * volatility_factor * 0.01  # Convert pips to price units for gold
```

### Anti-Patterns to Avoid

- **Separate backtest code paths:** The entire point of TEST-07 is that signal modules run identically in live and backtest. Never create parallel implementations of signal logic.
- **Lookahead bias:** The backtest engine must only see data up to the "current" bar. Never pass future bars into signal module computations. The BarBuffer pattern (rolling window) naturally prevents this -- populate buffers bar-by-bar.
- **Survivorship bias in walk-forward:** Each walk-forward window must be completely independent. Do not carry learned weights or state from one window to the next.
- **Using vectorbt's simulation loop for complex signals:** vectorbt's `from_order_func` requires Numba-compatible callbacks. Our signal modules use scipy, nolds, and complex numpy operations that cannot be JIT-compiled. Use vectorbt only for post-hoc analytics.
- **Modifying PaperExecutor for backtest needs:** Extend it (BacktestExecutor inherits from PaperExecutor or shares interface), do not modify it. PaperExecutor serves live paper trading.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Trade-level analytics (Sharpe, Sortino, Calmar, max drawdown, win rate) | Custom metric calculators | vectorbt's `Portfolio.from_orders()` on the trade list | vectorbt has battle-tested implementations of 40+ portfolio metrics, handles edge cases (zero trades, single trade, all losses) |
| Equity curve visualization | Custom matplotlib plotting | vectorbt + plotly for equity curves, drawdown charts | Consistent with CLAUDE.md stack; vectorbt wraps plotly |
| Statistical significance testing | Custom p-value calculation | scipy.stats.percentileofscore, scipy.stats.ttest_1samp | Well-tested statistical functions; Monte Carlo p-value is just percentile rank of zero in the distribution |
| Parquet I/O with partitioning | Custom file management | DuckDB `read_parquet()` + `COPY TO ... PARTITION_BY` | Matches Phase 1 TickStorage pattern exactly; DuckDB handles partition pruning automatically |
| CSV parsing with validation | Manual string splitting | pandas.read_csv with dtype enforcement | pandas handles encoding issues, missing data, and type coercion robustly |
| Random number generation for Monte Carlo | Custom RNG | numpy.random.Generator (PCG64) | Statistically sound, reproducible with seed, fast vectorized operations |

**Key insight:** The custom part is the replay loop and interface abstraction. Everything before (data loading) and after (analytics) should use existing libraries.

## Common Pitfalls

### Pitfall 1: Lookahead Bias in Bar Data
**What goes wrong:** Accidentally including future bars in signal computation windows, especially when constructing multi-timeframe bar arrays.
**Why it happens:** When building bar arrays from Parquet, it is tempting to query a wide time range and let signal modules self-select. But if the query includes bars beyond the "current" time, higher timeframes (H1, H4) may leak future information.
**How to avoid:** For each M1 bar being replayed, construct bar arrays for all timeframes using only data up to and including that bar's timestamp. Use DuckDB `WHERE time <= current_bar_time` for all queries.
**Warning signs:** Suspiciously high backtest performance (>90% win rate), H1/H4 signals that seem prescient.

### Pitfall 2: EST to UTC Timezone Conversion
**What goes wrong:** histdata.com uses EST (UTC-5 fixed, no DST). If not converted to UTC, all session-based logic (London-NY overlap, spread model, session filter) produces wrong results.
**Why it happens:** EST without DST is unusual -- most US timezone code assumes EDT/EST switching. The histdata.com spec explicitly says "WITHOUT Day Light Savings adjustments."
**How to avoid:** Convert timestamps to UTC during CSV parsing: add 5 hours. Verify by checking that the first bar on a Monday should be around 22:00 UTC Sunday (Sydney open) or 00:00 UTC Monday.
**Warning signs:** Spread model applying Asian session spreads during London hours, session filter blocking trades during active hours.

### Pitfall 3: Bar-Only Mode Degradation for Order Flow Module
**What goes wrong:** The OrderFlowModule expects tick_arrays with bid, ask, last, volume_real, spread, time_msc. With only M1 bars, there are no ticks.
**Why it happens:** 2015-2024 data from histdata.com is M1 bars only. No tick-level data exists.
**How to avoid:** Per D-02, implement bar-only mode: synthesize approximate tick_arrays from bar OHLCV. For each M1 bar, create a single "synthetic tick" with bid=close, ask=close+estimated_spread, last=close, volume_real=tick_volume. Set a "bar_only" flag that reduces confidence by 50% (matching Phase 2 DOM degradation pattern).
**Warning signs:** OrderFlowModule crashing with empty arrays, or producing nonsensical signals on synthetic ticks.

### Pitfall 4: Walk-Forward Window Boundary Alignment
**What goes wrong:** Training/validation windows not aligned to market hours, causing weekends or holidays to fall partially in one window.
**Why it happens:** Naive date arithmetic (e.g., "6 months from Jan 1") does not account for trading calendar.
**How to avoid:** Define windows by actual bar count or trading days, not calendar months. Alternatively, snap window boundaries to the first/last trading bar within each calendar period.
**Warning signs:** Extremely short validation windows near holidays, training windows with large gaps.

### Pitfall 5: Monte Carlo Destroys Trade Dependencies
**What goes wrong:** Shuffling trade sequences breaks temporal dependencies. If trades have autocorrelated outcomes (e.g., losing streaks during high-chaos regime), shuffling underestimates drawdown risk during those regimes.
**Why it happens:** Monte Carlo trade shuffling assumes independence between trades.
**How to avoid:** This is a known limitation, not a bug. Acknowledge it in results reporting. Complement trade shuffling with regime-stratified Monte Carlo (shuffle within each regime independently).
**Warning signs:** Monte Carlo drawdowns are much smaller than actual backtest drawdowns.

### Pitfall 6: Overfitting via Hyperparameter Tuning During Walk-Forward
**What goes wrong:** If you tune signal module parameters during each walk-forward training window, you are optimizing parameters 50 times on different data slices. The "best parameters per window" approach overfits to each window.
**How to avoid:** For Phase 3 v1, use FIXED parameters across all walk-forward windows. Walk-forward validates the strategy with fixed parameters -- it does NOT optimize parameters per window. Parameter optimization is Phase 4 (LEARN-02 with Optuna/DEAP). Walk-forward here proves the existing fusion logic generalizes.
**Warning signs:** Different optimal parameters per window with no convergence.

### Pitfall 7: vectorbt Dependency Conflicts
**What goes wrong:** vectorbt 0.28.x pulls in many dependencies (matplotlib, plotly, scikit-learn, scipy, requests, schedule, etc.) that may conflict with the project's pinned versions.
**Why it happens:** vectorbt is a large library with broad dependency requirements.
**How to avoid:** Install with `uv pip install vectorbt` and let uv's resolver handle conflicts. If conflicts arise, use `--no-deps` and install missing pieces individually. Alternatively, use vectorbt only in analysis scripts (not in core backtest engine code), so it is a dev dependency, not a runtime requirement.
**Warning signs:** Import errors, version downgrades of numpy/pandas/scipy after installing vectorbt.

## Code Examples

### histdata.com CSV Parsing

```python
# Source: histdata.com specification + pandas documentation
import pandas as pd
from datetime import timedelta
from pathlib import Path

def parse_histdata_csv(filepath: Path) -> pd.DataFrame:
    """Parse a histdata.com Generic ASCII M1 CSV file.

    Format: YYYYMMDD HHMMSS;Open;High;Low;Close;Volume
    No headers, semicolon-delimited, EST timezone (UTC-5 fixed, no DST).
    """
    df = pd.read_csv(
        filepath,
        sep=";",
        header=None,
        names=["datetime_str", "open", "high", "low", "close", "volume"],
        dtype={
            "open": "float64",
            "high": "float64",
            "low": "float64",
            "close": "float64",
            "volume": "int64",
        },
    )
    # Parse datetime: "YYYYMMDD HHMMSS" format
    df["datetime_est"] = pd.to_datetime(df["datetime_str"], format="%Y%m%d %H%M%S")

    # Convert EST to UTC (add 5 hours, no DST per histdata.com spec)
    df["datetime_utc"] = df["datetime_est"] + timedelta(hours=5)

    # Convert to unix timestamp (seconds) for consistency with BarEvent.time
    df["time"] = (df["datetime_utc"].astype("int64") // 10**9).astype("int64")

    # Add partition columns for Parquet
    df["year"] = df["datetime_utc"].dt.year
    df["month"] = df["datetime_utc"].dt.month

    # Drop intermediate columns
    df = df.drop(columns=["datetime_str", "datetime_est"])

    return df
```

### Data Validation

```python
# Source: Project decision D-03
import numpy as np

def validate_bar_data(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Validate and auto-repair M1 bar data per D-03.

    Returns (cleaned_df, quality_report).
    """
    report = {"original_rows": len(df), "issues": []}

    # 1. Monotonic timestamps
    if not df["time"].is_monotonic_increasing:
        dups = df["time"].duplicated(keep="first").sum()
        report["issues"].append(f"Non-monotonic: {dups} duplicate timestamps removed")
        df = df.drop_duplicates(subset=["time"], keep="first").sort_values("time")

    # 2. Detect gaps (expected 60-second intervals for M1)
    time_diffs = np.diff(df["time"].values)
    expected_interval = 60  # 60 seconds for M1
    gap_mask = time_diffs > expected_interval * 5  # >5 bars missing
    small_gap_mask = (time_diffs > expected_interval * 1.5) & (time_diffs <= expected_interval * 5)

    # 3. Auto-interpolate small gaps (<5 bars)
    small_gap_count = small_gap_mask.sum()
    if small_gap_count > 0:
        report["issues"].append(f"Small gaps interpolated: {small_gap_count}")
        # Forward-fill small gaps

    # 4. Flag suspicious bars (extreme range, zero volume)
    bar_range = df["high"] - df["low"]
    mean_range = bar_range.mean()
    extreme = bar_range > mean_range * 10
    if extreme.any():
        report["issues"].append(f"Extreme range bars: {extreme.sum()}")
        df = df[~extreme]

    zero_vol = df["volume"] == 0
    if zero_vol.any():
        report["issues"].append(f"Zero volume bars: {zero_vol.sum()}")
        # Keep but flag -- zero volume M1 bars are common during low liquidity

    report["final_rows"] = len(df)
    report["date_range"] = (df["datetime_utc"].min(), df["datetime_utc"].max())
    return df, report
```

### Monte Carlo Trade Shuffling

```python
# Source: Standard Monte Carlo methodology for trading strategy validation
import numpy as np
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    """Result of Monte Carlo simulation per D-07."""
    n_simulations: int
    pct_5_equity: float       # 5th percentile final equity
    median_equity: float       # 50th percentile final equity
    pct_95_max_dd: float      # 95th percentile of max drawdowns
    p_value: float            # Fraction of runs that are net negative
    passes_threshold: bool     # Both D-07 criteria met

def run_monte_carlo(
    trade_pnls: np.ndarray,
    starting_equity: float,
    n_simulations: int = 10_000,
    seed: int = 42,
) -> MonteCarloResult:
    """Monte Carlo trade sequence shuffling per D-07.

    Shuffles the order of trade P&Ls and builds equity curves
    for each permutation. Measures tail risk and statistical significance.
    """
    rng = np.random.default_rng(seed)
    n_trades = len(trade_pnls)

    final_equities = np.zeros(n_simulations)
    max_drawdowns = np.zeros(n_simulations)

    for i in range(n_simulations):
        shuffled = rng.permutation(trade_pnls)
        equity_curve = starting_equity + np.cumsum(shuffled)

        final_equities[i] = equity_curve[-1]

        # Max drawdown
        running_max = np.maximum.accumulate(equity_curve)
        drawdowns = (running_max - equity_curve) / running_max
        max_drawdowns[i] = drawdowns.max()

    pct_5_equity = float(np.percentile(final_equities, 5))
    median_equity = float(np.percentile(final_equities, 50))
    pct_95_dd = float(np.percentile(max_drawdowns, 95))

    # p-value: fraction of runs with net negative P&L
    p_value = float(np.mean(final_equities < starting_equity))

    # D-07 dual threshold
    criterion_1 = pct_5_equity > starting_equity  # 5th pct net positive
    criterion_2 = median_equity > starting_equity and pct_95_dd < 0.40
    passes = criterion_1 and criterion_2

    return MonteCarloResult(
        n_simulations=n_simulations,
        pct_5_equity=pct_5_equity,
        median_equity=median_equity,
        pct_95_max_dd=pct_95_dd,
        p_value=p_value,
        passes_threshold=passes,
    )
```

### Feigenbaum Stress Test

```python
# Source: Custom implementation based on existing feigenbaum.py
import numpy as np

def generate_bifurcation_price_series(
    n_bars: int = 500,
    base_price: float = 2000.0,
    pre_transition_bars: int = 200,
    transition_bars: int = 100,
    post_transition_bars: int = 200,
    seed: int = 42,
) -> np.ndarray:
    """Generate synthetic price series with controlled period-doubling bifurcation.

    Creates a price series that transitions from stable oscillation
    to period-doubling, allowing verification that the chaos module
    detects the approach to bifurcation.

    Phase 1 (pre_transition_bars): Regular oscillation (single period)
    Phase 2 (transition_bars): Period doubling (approaching Feigenbaum delta)
    Phase 3 (post_transition_bars): Chaotic regime
    """
    rng = np.random.default_rng(seed)
    prices = np.zeros(n_bars)
    prices[0] = base_price

    for i in range(1, pre_transition_bars):
        # Stable single-period oscillation
        prices[i] = base_price + 5.0 * np.sin(2 * np.pi * i / 20) + rng.normal(0, 0.5)

    for i in range(pre_transition_bars, pre_transition_bars + transition_bars):
        # Period doubling: two nested oscillations
        progress = (i - pre_transition_bars) / transition_bars
        amplitude_1 = 5.0 * (1 - progress)
        amplitude_2 = 3.0 * progress
        prices[i] = (
            base_price
            + amplitude_1 * np.sin(2 * np.pi * i / 20)
            + amplitude_2 * np.sin(2 * np.pi * i / 10)
            + rng.normal(0, 0.5 + progress * 2)
        )

    for i in range(pre_transition_bars + transition_bars, n_bars):
        # Chaotic regime: high entropy, no clear period
        prices[i] = prices[i-1] + rng.normal(0, 3.0) + 0.5 * np.sin(rng.uniform(0, 2*np.pi))

    return prices
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single train/test split | Walk-forward with rolling windows | Established practice 2020+ | Prevents overfitting to a single split point |
| Fixed spread in backtesting | Session-aware dynamic spread model | Industry standard 2023+ | Backtests using tight fixed spreads massively overestimate profitability |
| Aggregate performance only | Regime-tagged performance attribution | Growing practice 2024+ | Reveals strategy only works in specific regimes |
| Simple random trade shuffling | Regime-stratified Monte Carlo | Emerging practice | Better preserves temporal structure while testing robustness |
| vectorbt for full simulation | vectorbt for analytics only | Project-specific decision | Complex signal pipelines need custom engines; vectorbt excels at post-hoc analysis |

**Deprecated/outdated:**
- **Backtrader:** Effectively abandoned, breaks on Python 3.10+. CLAUDE.md explicitly forbids.
- **Zipline/Zipline-Reloaded:** Designed for equities with daily bars, not forex ticks. Forbidden by CLAUDE.md.
- **Fixed slippage models:** Using a constant slippage ignores session volatility effects. Use stochastic model.

## Open Questions

1. **histdata.com XAUUSD data availability for 2015-2024**
   - What we know: histdata.com has XAUUSD M1 data. The `histdata` pip package supports automated download.
   - What's unclear: Exact years available, any gaps in coverage, file sizes.
   - Recommendation: Attempt download during data ingestion task. If gaps exist, log them and handle gracefully. Worst case, download manually from histdata.com website.

2. **vectorbt 0.28.5 compatibility with NumPy 2.4.3**
   - What we know: vectorbt 0.28.5 released 2026-03-26. It requires numba and numpy but PyPI page does not specify version ceilings. Numba 0.64 supports NumPy 2.x.
   - What's unclear: Whether vectorbt's internal code uses deprecated NumPy 2.x APIs.
   - Recommendation: Install in project venv and run `import vectorbt` as smoke test. If incompatible, use vectorbt in a separate analysis script with its own venv, or compute metrics manually using numpy.

3. **Signal module async vs sync execution in backtest**
   - What we know: Signal modules use `async def update()` and wrap blocking computations in `asyncio.to_thread()`. In backtest mode, there is no event loop latency concern.
   - What's unclear: Whether running the full async pipeline per bar is too slow for 500K+ M1 bars.
   - Recommendation: Run the backtest with `asyncio.run()` wrapping the replay loop. If too slow, create synchronous wrappers for signal modules (call the underlying functions directly without `to_thread`). Profile after first implementation.

4. **How many M1 bars from 2015-present?**
   - What we know: ~365 days/year * ~1440 M1 bars/day * ~5 trading days/week * ~52 weeks = ~374,400 bars/year * 10 years = ~3.7M bars total. But actual trading hours are roughly 5 days * 24 hours * 60 = 7,200 bars/week * 52 * 10 = ~3.74M.
   - What's unclear: Exact count after filtering weekends/holidays.
   - Recommendation: This is tractable. At ~100ms per bar (signal computation), full backtest takes ~100 hours. For walk-forward, each window is much smaller. Optimize hot paths if needed.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All code | Yes | 3.12.13 (venv) | -- |
| numpy | Data processing, signals | Yes | 2.4.3 | -- |
| scipy | Statistical testing, chaos module | Yes | 1.17.1 | -- |
| pandas | CSV parsing, DataFrames | Yes | 2.3.3 | -- |
| duckdb | Parquet queries, result storage | Yes | 1.5.1 | -- |
| pyarrow | Parquet I/O | Yes | 23.0.1 | -- |
| numba | JIT for Monte Carlo | Yes | 0.64.0 | -- |
| structlog | Logging | Yes | 25.5.0 | -- |
| pydantic | Config validation | Yes | 2.12.5 | -- |
| nolds | Chaos metrics (used by chaos module) | Yes | 0.6.3 | -- |
| vectorbt | Post-hoc portfolio analytics | No | -- | Install: `uv pip install vectorbt`; fallback: compute metrics manually with numpy |
| histdata (pip) | Automated CSV download | No | -- | Install: `uv pip install histdata`; fallback: manual download from histdata.com |
| uv | Package management | Yes | 0.10.12 | -- |
| pytest | Testing | Yes | 9.0.2 | -- |

**Missing dependencies with no fallback:**
- None -- all critical dependencies are installed. vectorbt and histdata are nice-to-have with manual fallbacks.

**Missing dependencies with fallback:**
- vectorbt: Can compute Sharpe/drawdown/win-rate manually with numpy if install fails
- histdata pip package: Can download CSVs manually from histdata.com website

## Sources

### Primary (HIGH confidence)
- histdata.com Data Files Detailed Specification -- CSV format, timezone, column layout
- Existing codebase: `src/fxsoqqabot/signals/base.py` (SignalModule Protocol), `data/buffers.py` (array shapes), `data/feed.py` (MarketDataFeed), `core/engine.py` (TradingEngine), `execution/paper.py` (PaperExecutor), `config/models.py` (BotSettings)
- Phase 3 CONTEXT.md -- All locked decisions D-01 through D-13

### Secondary (MEDIUM confidence)
- [vectorbt PyPI](https://pypi.org/project/vectorbt/) -- v0.28.5, March 2026
- [philipperemy/FX-1-Minute-Data](https://github.com/philipperemy/FX-1-Minute-Data) -- histdata.com Python downloader
- [histdata pip package](https://pypi.org/project/histdata/) -- automated download API
- [Walk-Forward Optimization (QuantInsti)](https://blog.quantinsti.com/walk-forward-optimization-introduction/) -- WFO methodology
- [Monte Carlo in Trading (Aron Groups)](https://arongroups.co/forex-articles/monte-carlo-simulation-in-python-for-trading/) -- trade shuffling approach
- [vectorbt Portfolio API](https://vectorbt.dev/api/portfolio/base/) -- from_orders, from_signals documentation

### Tertiary (LOW confidence)
- vectorbt + NumPy 2.4.3 compatibility -- not verified directly, based on dependency chain analysis
- Exact histdata.com XAUUSD coverage years -- needs runtime verification during data download

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all core libraries already installed and verified in project venv
- Architecture: HIGH -- interface abstraction pattern follows existing Protocol patterns in codebase; backtest replay loop is straightforward
- Data ingestion: HIGH -- histdata.com format is well-documented; Parquet conversion matches Phase 1 patterns
- Walk-forward: HIGH -- methodology is standard; implementation is straightforward rolling windows
- Monte Carlo: HIGH -- numpy-based trade shuffling is simple and well-established
- Feigenbaum stress testing: MEDIUM -- novel territory, no reference implementations, but approach (synthetic data) is sound
- vectorbt compatibility: LOW -- not tested with project's NumPy 2.4.3; may need workaround

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable domain, 30 days)
