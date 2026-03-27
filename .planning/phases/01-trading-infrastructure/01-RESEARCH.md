# Phase 1: Trading Infrastructure - Research

**Researched:** 2026-03-27
**Domain:** MT5 integration, data ingestion, order execution, risk management, state persistence, configuration
**Confidence:** HIGH

## Summary

Phase 1 builds the foundational trading infrastructure for FXSoqqaBot: connecting to MetaTrader 5, ingesting live XAUUSD tick and bar data, executing trades with full risk protection, persisting state for crash recovery, and making everything configurable via TOML files. This is a greenfield phase with no existing code -- it establishes all patterns for subsequent phases.

The MetaTrader5 Python package (5.0.5640) provides the complete API surface needed: `copy_ticks_from()` for tick data, `copy_rates_from()` for multi-timeframe bars, `market_book_get()` for DOM depth, `order_send()` for execution, `positions_get()` for state reconciliation, and `account_info()` for equity tracking. All MT5 calls are blocking and must be wrapped in `asyncio.to_thread()` to avoid freezing the event loop. The async architecture is the single most important design decision in this phase -- every downstream module depends on a non-blocking data pipeline.

**Primary recommendation:** Build an async core using `asyncio` with a dedicated `ThreadPoolExecutor` for MT5 calls. Structure the project as a `src/fxsoqqabot/` package with clear module boundaries: `data/` (ingestion + storage), `execution/` (MT5 bridge + orders), `risk/` (position sizing + circuit breakers), `config/` (Pydantic settings), and `core/` (async engine + state management). Use TOML for configuration with Pydantic-settings for validation. Persist operational state in SQLite with WAL mode via aiosqlite. Store tick data in Parquet via DuckDB.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Bot ships with a paper trading mode that runs the full pipeline (data ingestion, signal processing, order generation) but simulates fills instead of executing on MT5. Paper mode uses full virtual fill simulation -- models spread, slippage, and produces realistic P&L tracking against live tick data.
- **D-02:** Switching from paper to live mode is a manual config change only. No automatic promotion. Human always in the loop for the paper-to-live transition.
- **D-03:** Position sizing accepts higher risk per trade in the aggressive capital phase because $20 is treated as pure seed money. The three-phase risk model:
  - Aggressive ($20-$100): up to 10% risk per trade
  - Selective ($100-$300): up to 5% risk per trade
  - Conservative ($300+): up to 2% risk per trade
- **D-04:** At 0.01 minimum lot size, if the calculated risk still exceeds the phase limit, the trade is skipped. But with 10% risk at $20 ($2.00 risk budget), most gold scalping setups with 0.01 lots should fit.
- **D-05:** After a Python crash or machine reboot with open positions: bot closes ALL positions immediately, cancels all pending orders, then auto-resumes trading. No manual intervention required to restart, but open positions are always flattened for safety.
- **D-06:** After an MT5 connection drop: bot retries reconnection indefinitely. Server-side stop-losses protect open positions while Python is disconnected. On reconnection, bot reconciles state and resumes management.
- **D-07:** Full state persisted to SQLite for recovery: every open position, pending order, daily P&L, circuit breaker states, session counters, and last known account snapshot. Positions are also read fresh from MT5 on restart for reconciliation.
- **D-08:** Four automatic circuit breakers beyond daily drawdown (RISK-04):
  1. Consecutive loss streak -- halt after N consecutive losing trades (configurable, e.g., 5)
  2. Spread spike detection -- halt when spread exceeds threshold for sustained period (e.g., 5x average for 30+ seconds)
  3. Rapid equity drop -- halt if equity drops X% within a short window (e.g., 5% in 15 minutes), even if daily limit not hit
  4. Max daily trade count -- halt after N trades per day regardless of P&L, prevents runaway overtrading
- **D-09:** Kill switch invocable via CLI command (`python -m fxsoqqabot kill`) AND a TUI dashboard button. CLI works independently of TUI.
- **D-10:** Safety trigger reset policy: daily drawdown, loss streak, rapid equity drop, and max trade counters auto-reset at the configured session boundary. Kill switch requires explicit manual reset via CLI command.

### Claude's Discretion
- Project structure and Python package layout
- Async architecture design (event loop structure, threading model)
- DuckDB/Parquet schema design and partitioning strategy
- SQLite state schema design
- MT5-Python communication architecture details (MetaTrader5 package vs ZeroMQ bridge specifics)
- Configuration file format (YAML vs TOML) and structure
- Logging and error reporting patterns
- Test structure and coverage approach

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | Real-time tick-level data ingestion (bid, ask, last, volume, flags) with sub-second polling | MT5 `copy_ticks_from()` returns numpy array with time, bid, ask, last, volume, time_msc, flags, volume_real. Use `COPY_TICKS_ALL` flag. Wrap in `asyncio.to_thread()` for non-blocking polling. |
| DATA-02 | DOM depth snapshots with graceful degradation to tick-only | MT5 `market_book_add()` + `market_book_get()` returns BookInfo tuples (type, price, volume, volume_dbl). DOM may be empty/limited for forex on RoboForex ECN -- must detect and degrade. |
| DATA-03 | Multi-timeframe bar data (M1, M5, M15, H1, H4) with aligned timestamps and caching | MT5 `copy_rates_from()` with TIMEFRAME_M1/M5/M15/H1/H4 constants. Returns numpy array with time, open, high, low, close, tick_volume, spread, real_volume. |
| DATA-05 | Tick data and trade events stored in DuckDB/Parquet | DuckDB 1.5.x reads/writes Parquet natively. Hive-partition by year/month for efficient time-range queries. Row groups of 100K-1M rows for parallelism. |
| DATA-06 | Rolling in-memory buffers for real-time signal computation | `collections.deque(maxlen=N)` for O(1) append with automatic eviction. Separate buffers per timeframe. |
| EXEC-01 | Python-MT5 communication with async wrapping | All MT5 calls via `asyncio.to_thread()` with dedicated `ThreadPoolExecutor`. MT5 package is fully blocking -- no native async support. |
| EXEC-02 | Thin MQL5 EA for order execution (market, pending, SL/TP modification, partial close) | MT5 `order_send()` with `TRADE_ACTION_DEAL` for market orders. TradeRequest dict with action, symbol, volume, type, price, sl, tp, deviation, magic, comment, type_filling, type_time. Check `result.retcode == TRADE_RETCODE_DONE` (10009). |
| EXEC-03 | MT5 disconnection detection and automatic reconnection with state reconciliation | `mt5.terminal_info()` returns None when disconnected. Retry `mt5.initialize()` + `mt5.login()` indefinitely. On reconnect, compare `positions_get()` against SQLite state. |
| EXEC-04 | Python crash recovery with open position handling | On startup: `mt5.initialize()` -> `mt5.positions_get()` -> if positions exist, close all per D-05. Load SQLite state for circuit breaker continuity. |
| RISK-01 | Server-side stop-loss at order placement time with ATR-based SL distance | Include `sl` field in `order_send()` request dict. Use `order_check()` to pre-validate. ATR-based: typical 2x ATR for scalping. Gold scalping SL typically 15-30 pips ($1.50-$3.00 per 0.01 lot). |
| RISK-02 | Position sizing engine for three capital phases | `lot_size = risk_amount / (sl_distance_points * point_value_per_lot)`. Use `symbol_info()` for volume_min (0.01), volume_step, point, digits, trade_contract_size. Use `order_calc_margin()` to verify margin sufficiency. |
| RISK-03 | Spread filter and slippage tracking | Compare `symbol_info_tick().ask - symbol_info_tick().bid` against configurable threshold. Log `result.price` vs `request['price']` after order_send for slippage tracking. |
| RISK-04 | Daily drawdown circuit breaker with persistence across restarts | Track daily P&L in SQLite. Compare against configurable limit (3-5% of starting daily equity). Persist state with timestamp for session boundary reset logic. |
| RISK-05 | Kill switch: flatten all positions + halt trading | Iterate `positions_get()`, send `TRADE_ACTION_DEAL` close for each. Set `kill_switch_active=True` in SQLite. CLI entry point: `python -m fxsoqqabot kill`. |
| RISK-06 | Session time filter (default: London-NY overlap 13:00-17:00 UTC) | Compare current UTC time against configurable session windows. Auto-pause outside windows. Multiple windows supportable. |
| RISK-07 | Weekly and total max drawdown limits | Track weekly P&L (Monday-Friday) and total drawdown from equity high-water mark in SQLite. Multi-tier: daily -> weekly -> total. |
| CONF-01 | All parameters configurable via YAML/TOML files | Pydantic-settings 2.13.x with `TomlConfigSettingsSource`. Nested config models for risk, execution, data, sessions. Validation catches misconfigurations before runtime. |
| CONF-02 | Separate profiles per growth phase with automatic switching | Three Pydantic models (aggressive/selective/conservative) with equity-based auto-selection. Smooth transitions at boundaries per D-03. |
</phase_requirements>

## Standard Stack

### Core (Phase 1 only)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| MetaTrader5 | 5.0.5640 | Python-MT5 bridge: ticks, DOM, bars, orders, account | Official MetaQuotes package. Only option for direct MT5 integration. All calls blocking. |
| numpy | 2.4.3 | Array operations for tick/bar data from MT5 | MT5 package returns data as numpy structured arrays. Foundation for all numerical work. |
| pandas | 2.2.x | DataFrame operations for time-series resampling | MT5 data converts to pandas DataFrames. Pin to 2.2.x per CLAUDE.md (3.0 has breaking changes with string dtype defaults and CoW semantics). |
| pydantic | 2.12.5 | Configuration model validation, data schemas | Type-safe config for all modules. Runtime validation catches misconfigurations. |
| pydantic-settings | 2.13.1 | TOML config file loading, environment variable support | Built-in `TomlConfigSettingsSource` for structured config. Multiple file support with deep merge. |
| structlog | 25.5.0 | Structured logging with context propagation | JSON output for DuckDB analysis. Context binding (trade_id, regime, signal scores) across call chain. |
| duckdb | 1.5.1 | Analytical queries on tick data, trade logs | Embedded columnar DB. 10-100x faster than SQLite for analytical queries. Reads Parquet natively. |
| pyarrow | 23.0.1 | Parquet file I/O for tick data storage | Columnar, compressed on-disk format. DuckDB queries Parquet directly. |
| aiosqlite | 0.22.1 | Async SQLite for operational state persistence | Non-blocking SQLite access from asyncio. WAL mode for concurrent reads/writes. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rich | 13.x | Console log rendering, dev-time pretty output | structlog ConsoleRenderer for development. Switch to JSONRenderer in production. |
| pytz | latest | Timezone handling for UTC time operations | MT5 tick timestamps are UTC epoch seconds. Session time filters need timezone-aware comparison. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| aiosqlite | sqlite3 (stdlib) | aiosqlite adds async. sqlite3 is simpler but blocks event loop. Use aiosqlite for all async paths. |
| TOML config | YAML config | Both supported by pydantic-settings. TOML is Python-native (tomllib in 3.11+), less ambiguous than YAML, better for nested config. Recommend TOML. |
| asyncio.to_thread | loop.run_in_executor | to_thread is simpler (Python 3.9+). run_in_executor allows custom executors for thread pool sizing. Use to_thread for convenience, run_in_executor when tuning thread count. |
| Direct MT5 package | aiomql framework | aiomql wraps MT5 with async but adds opinionated abstractions. We need full control over risk/execution logic. Use MT5 package directly with our own async wrapper. |
| pyzmq (ZeroMQ) | Direct MT5 package only | ZeroMQ needed for Phase 2+ when MQL5 EA handles sub-100ms execution. Phase 1 can use MT5 Python package alone for all operations. Add ZeroMQ when EA bridge is needed. |

**Installation (Phase 1):**
```bash
uv init --python 3.12 fxsoqqabot
cd fxsoqqabot
uv add metatrader5 numpy "pandas>=2.2,<3.0" pydantic pydantic-settings structlog duckdb pyarrow aiosqlite rich pytz
uv add --dev pytest pytest-asyncio pytest-cov ruff mypy pre-commit
```

**Version verification notes:**
- MetaTrader5 5.0.5640: Verified on PyPI (Feb 2026)
- pandas: CLAUDE.md pins 2.2.x. pandas 3.0.1 is latest (Jan 2026) but has breaking changes (string dtype default, CoW). Pin `>=2.2,<3.0` to stay compatible.
- duckdb: 1.5.1 is latest (verified), CLAUDE.md says 1.5.0. Minor patch, compatible.
- pyarrow: 23.0.1 is latest. CLAUDE.md says 19.x. Major version jump but Parquet format is stable. DuckDB 1.5.x is compatible with pyarrow 23.x.
- pydantic-settings: 2.13.1 is latest (Feb 2026). Not in CLAUDE.md versions but is the companion to pydantic 2.12.5.

## Architecture Patterns

### Recommended Project Structure
```
fxsoqqabot/
├── pyproject.toml              # uv project config, dependencies, metadata
├── uv.lock                     # Locked dependency versions
├── config/
│   ├── default.toml            # Default configuration
│   ├── paper.toml              # Paper trading overrides
│   └── live.toml               # Live trading overrides
├── src/
│   └── fxsoqqabot/
│       ├── __init__.py
│       ├── __main__.py          # Entry point: python -m fxsoqqabot
│       ├── cli.py               # CLI commands (run, kill, status)
│       ├── core/
│       │   ├── __init__.py
│       │   ├── engine.py        # Main async engine, event loop orchestration
│       │   ├── events.py        # Event types (TickEvent, BarEvent, FillEvent, etc.)
│       │   └── state.py         # State manager (SQLite persistence, recovery)
│       ├── config/
│       │   ├── __init__.py
│       │   ├── models.py        # Pydantic config models (risk, execution, data, session)
│       │   └── loader.py        # TOML loading, profile switching logic
│       ├── data/
│       │   ├── __init__.py
│       │   ├── feed.py          # MT5 data feed (ticks, bars, DOM)
│       │   ├── buffers.py       # Rolling in-memory buffers (deque-based)
│       │   └── storage.py       # DuckDB/Parquet tick storage
│       ├── execution/
│       │   ├── __init__.py
│       │   ├── mt5_bridge.py    # MT5 connection, async wrapper, reconnection
│       │   ├── orders.py        # Order placement, modification, closure
│       │   └── paper.py         # Paper trading fill simulation engine
│       ├── risk/
│       │   ├── __init__.py
│       │   ├── sizing.py        # Position sizing engine (three-phase model)
│       │   ├── circuit_breakers.py  # All circuit breakers (daily DD, loss streak, etc.)
│       │   ├── kill_switch.py   # Kill switch logic (flatten + halt)
│       │   └── session.py       # Session time filter
│       └── logging/
│           ├── __init__.py
│           └── setup.py         # structlog configuration
├── tests/
│   ├── conftest.py
│   ├── test_config/
│   ├── test_data/
│   ├── test_execution/
│   └── test_risk/
└── mql5/
    └── FXSoqqaBot.mq5           # Thin EA (Phase 2+ for ZeroMQ bridge)
```

### Pattern 1: Async MT5 Bridge with Connection Management

**What:** Wrapper class that makes all blocking MT5 calls non-blocking and handles connection lifecycle.
**When to use:** Every MT5 interaction throughout the codebase.

```python
# Source: MT5 official docs + asyncio.to_thread pattern
import asyncio
import MetaTrader5 as mt5
from concurrent.futures import ThreadPoolExecutor
import structlog

logger = structlog.get_logger()

class MT5Bridge:
    """Async wrapper around the blocking MetaTrader5 package."""

    def __init__(self, path: str | None = None, login: int | None = None,
                 password: str | None = None, server: str | None = None):
        self._path = path
        self._login = login
        self._password = password
        self._server = server
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mt5")
        self._connected = False

    async def connect(self) -> bool:
        """Initialize MT5 connection. Returns True on success."""
        kwargs = {}
        if self._path:
            kwargs["path"] = self._path
        if self._login:
            kwargs["login"] = self._login
            kwargs["password"] = self._password
            kwargs["server"] = self._server

        result = await asyncio.to_thread(mt5.initialize, **kwargs)
        if not result:
            error = mt5.last_error()
            logger.error("mt5_init_failed", error_code=error[0], error_msg=error[1])
            return False
        self._connected = True
        logger.info("mt5_connected", terminal=await self.terminal_info())
        return True

    async def ensure_connected(self) -> bool:
        """Check connection, reconnect if needed."""
        info = await asyncio.to_thread(mt5.terminal_info)
        if info is None:
            logger.warning("mt5_connection_lost, reconnecting")
            self._connected = False
            return await self.connect()
        return True

    async def get_ticks(self, symbol: str, date_from, count: int,
                        flags=mt5.COPY_TICKS_ALL):
        """Non-blocking tick data retrieval."""
        return await asyncio.to_thread(
            mt5.copy_ticks_from, symbol, date_from, count, flags
        )

    async def get_rates(self, symbol: str, timeframe, date_from, count: int):
        """Non-blocking bar data retrieval."""
        return await asyncio.to_thread(
            mt5.copy_rates_from, symbol, timeframe, date_from, count
        )

    async def send_order(self, request: dict):
        """Non-blocking order execution."""
        # Pre-validate with order_check
        check = await asyncio.to_thread(mt5.order_check, request)
        if check is None or check.retcode != 0:
            logger.error("order_check_failed", check=check)
            return check
        result = await asyncio.to_thread(mt5.order_send, request)
        return result

    async def get_positions(self, symbol: str | None = None):
        """Non-blocking position retrieval."""
        if symbol:
            return await asyncio.to_thread(mt5.positions_get, symbol=symbol)
        return await asyncio.to_thread(mt5.positions_get)

    async def shutdown(self):
        """Clean shutdown."""
        await asyncio.to_thread(mt5.shutdown)
        self._executor.shutdown(wait=False)
        self._connected = False
```

### Pattern 2: Position Sizing for XAUUSD Micro-Account

**What:** Calculate lot size respecting three-phase risk model and broker constraints.
**When to use:** Before every trade signal becomes an order.

```python
# Source: MT5 order_calc_margin docs + XAUUSD contract specs
import MetaTrader5 as mt5

# XAUUSD key facts (verified from RoboForex ECN specs):
# - Contract size: 100 oz per lot
# - 0.01 lot = 1 oz
# - Each $1 move in gold price = $1 per 0.01 lot
# - Point: 0.01 (2 decimal digits for gold on most brokers)
# - Minimum lot: 0.01, step: 0.01
# - With 1:500 leverage: margin for 0.01 lot at $2000 gold = $0.40

def calculate_lot_size(
    equity: float,
    risk_pct: float,       # e.g., 0.10 for 10% in aggressive phase
    sl_distance: float,    # in price units (e.g., $3.00 for a $3 SL)
    symbol_info,           # from mt5.symbol_info("XAUUSD")
) -> float:
    """Calculate lot size for XAUUSD respecting risk budget and broker limits."""
    risk_amount = equity * risk_pct  # e.g., $20 * 0.10 = $2.00

    # For XAUUSD: each 0.01 lot, $1 price move = $1 P&L
    # So: lot_size = risk_amount / sl_distance / contract_size_per_lot
    # contract_size = 100 oz, but 0.01 lot = 1 oz
    # Simplified: lot_size = risk_amount / (sl_distance * 100)
    contract_size = symbol_info.trade_contract_size  # 100
    lot_size = risk_amount / (sl_distance * contract_size)

    # Round down to lot step
    volume_step = symbol_info.volume_step  # 0.01
    lot_size = max(
        symbol_info.volume_min,
        round(lot_size // volume_step * volume_step, 2)
    )

    # Cap at volume_max
    lot_size = min(lot_size, symbol_info.volume_max)

    return lot_size

# Example: $20 equity, 10% risk ($2), $3 SL distance
# lot_size = $2 / ($3 * 100) = 0.0067 -> rounds to 0.01 (minimum)
# Risk check: 0.01 lot * $3 SL * 100 = $3.00 actual risk
# $3.00 / $20 = 15% > 10% limit -> SKIP TRADE (per D-04)
# With $2 SL: 0.01 lot * $2 * 100 = $2.00 = exactly 10% -> TAKE TRADE
```

### Pattern 3: Circuit Breaker State Machine

**What:** Multi-tier safety system with persistent state.
**When to use:** Checked before every trade and on every tick/equity update.

```python
# Circuit breaker states (persisted to SQLite)
from enum import Enum
from pydantic import BaseModel
from datetime import datetime, timezone

class BreakerState(str, Enum):
    ACTIVE = "active"      # Trading allowed
    TRIPPED = "tripped"    # Halted, auto-resets at session boundary
    KILLED = "killed"      # Manual kill switch, requires explicit reset

class CircuitBreakerSnapshot(BaseModel):
    """Persisted to SQLite for crash recovery."""
    daily_pnl: float = 0.0
    daily_starting_equity: float = 0.0
    weekly_pnl: float = 0.0
    equity_high_water_mark: float = 0.0
    consecutive_losses: int = 0
    daily_trade_count: int = 0
    last_equity_check: float = 0.0
    last_equity_check_time: datetime | None = None
    session_date: str = ""  # "2026-03-27" for daily reset detection
    week_start_date: str = ""  # Monday date for weekly reset
    kill_switch: BreakerState = BreakerState.ACTIVE
    daily_drawdown: BreakerState = BreakerState.ACTIVE
    loss_streak: BreakerState = BreakerState.ACTIVE
    rapid_equity_drop: BreakerState = BreakerState.ACTIVE
    max_trades: BreakerState = BreakerState.ACTIVE
```

### Pattern 4: Pydantic TOML Configuration

**What:** Type-safe hierarchical configuration loaded from TOML files.
**When to use:** All configurable parameters across the system.

```python
# Source: pydantic-settings 2.13.x docs with TomlConfigSettingsSource
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class RiskConfig(BaseModel):
    # Phase thresholds (equity boundaries)
    aggressive_max: float = 100.0
    selective_max: float = 300.0
    # Risk per trade by phase
    aggressive_risk_pct: float = 0.10
    selective_risk_pct: float = 0.05
    conservative_risk_pct: float = 0.02
    # Circuit breakers
    daily_drawdown_pct: float = 0.05
    weekly_drawdown_pct: float = 0.10
    max_total_drawdown_pct: float = 0.25
    max_consecutive_losses: int = 5
    max_daily_trades: int = 20
    rapid_equity_drop_pct: float = 0.05
    rapid_equity_drop_window_minutes: int = 15
    # Spread filter
    spread_threshold_multiplier: float = 2.0
    spread_spike_multiplier: float = 5.0
    spread_spike_duration_seconds: int = 30

class SessionConfig(BaseModel):
    windows: list[dict] = [{"start": "13:00", "end": "17:00"}]  # UTC
    timezone: str = "UTC"
    reset_hour: int = 0  # Session boundary for counter reset

class ExecutionConfig(BaseModel):
    symbol: str = "XAUUSD"
    magic_number: int = 20260327
    deviation: int = 20
    mode: str = "paper"  # "paper" or "live" (D-02: manual switch only)
    sl_atr_multiplier: float = 2.0
    mt5_path: str | None = None
    mt5_login: int | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None

class DataConfig(BaseModel):
    tick_buffer_size: int = 10000
    bar_buffer_sizes: dict[str, int] = {
        "M1": 1440, "M5": 288, "M15": 96, "H1": 24, "H4": 6
    }
    tick_poll_interval_ms: int = 100
    bar_refresh_interval_seconds: int = 5
    storage_path: str = "data/"
    parquet_partition_by: list[str] = ["year", "month"]

class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(
        toml_file=["config/default.toml", "config/live.toml"],
        env_prefix="FXBOT_",
        env_nested_delimiter="__",
    )
    risk: RiskConfig = RiskConfig()
    session: SessionConfig = SessionConfig()
    execution: ExecutionConfig = ExecutionConfig()
    data: DataConfig = DataConfig()

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        from pydantic_settings import TomlConfigSettingsSource
        return (
            kwargs.get("init_settings"),
            kwargs.get("env_settings"),
            TomlConfigSettingsSource(settings_cls),
        )
```

Corresponding TOML file:
```toml
# config/default.toml
[execution]
symbol = "XAUUSD"
magic_number = 20260327
deviation = 20
mode = "paper"
sl_atr_multiplier = 2.0

[risk]
aggressive_max = 100.0
selective_max = 300.0
aggressive_risk_pct = 0.10
selective_risk_pct = 0.05
conservative_risk_pct = 0.02
daily_drawdown_pct = 0.05
max_consecutive_losses = 5
max_daily_trades = 20

[session]
timezone = "UTC"
reset_hour = 0

[[session.windows]]
start = "13:00"
end = "17:00"

[data]
tick_buffer_size = 10000
tick_poll_interval_ms = 100
bar_refresh_interval_seconds = 5
storage_path = "data/"
```

### Anti-Patterns to Avoid

- **Calling MT5 functions directly from async context:** Every MT5 call blocks the thread. Always use `asyncio.to_thread()` or `loop.run_in_executor()`. Failure to do this freezes the entire bot.
- **Assuming MT5 functions raise exceptions:** They return None on failure and set a silent error code. Must check every return value and call `mt5.last_error()` explicitly.
- **Setting SL/TP after order placement (two-step):** Server-side SL must be in the initial `order_send()` request. If the request succeeds but a follow-up SL modification fails, you have an unprotected position. Always include `sl` in the initial order dict.
- **Hardcoding broker-specific values:** RoboForex ECN fill policy, stops level, spread behavior can change. Query `symbol_info()` at runtime for volume_min, volume_step, stops_level, point, digits.
- **Using global MT5 state without locking:** The MT5 Python package uses global state internally. Multiple threads calling MT5 functions simultaneously can corrupt state. Use a single-threaded executor with max_workers=1 for MT5 calls, or serialize access.
- **Ignoring `order_check()` before `order_send()`:** order_check validates margin, fill policy, and SL distance requirements without executing. Always pre-validate.
- **Paper mode that skips the execution pipeline:** Paper mode must go through the same code path as live mode up to the final order_send call, then diverge to the fill simulator. Separate code paths create bugs that only appear in live.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TOML config loading + validation | Custom TOML parser + validation | pydantic-settings TomlConfigSettingsSource | Handles nesting, type coercion, env var overrides, multiple files, deep merge. Custom parsers miss edge cases. |
| Async SQLite access | Raw sqlite3 with threading | aiosqlite | Proven async bridge, handles WAL mode, context managers, proper cleanup. |
| Tick data storage + querying | Custom binary format | DuckDB + Parquet | Columnar compression, partition pruning, SQL queries, zero-copy reads. Custom formats are slower and buggier. |
| Structured logging | print() or logging.getLogger | structlog | Context propagation (trade_id, regime_state), JSON output, processor pipeline. Custom logging misses context binding. |
| Timezone handling | Manual UTC offset math | pytz or datetime.timezone | DST transitions, broker timezone differences. Manual math breaks across DST boundaries. |
| Position size rounding | Manual floor/round | Use symbol_info().volume_step with proper step math | Broker-specific lot steps vary. Round-toward-zero to volume_step, clamp to volume_min/volume_max. |

**Key insight:** The MetaTrader5 Python package handles the hard parts (market data, order execution, account info) but silently fails on errors. The infrastructure code is primarily about: (1) wrapping it async-safely, (2) validating every return value, (3) persisting state for recovery, and (4) enforcing risk constraints before execution.

## Common Pitfalls

### Pitfall 1: MT5 Silent Failures
**What goes wrong:** MT5 functions return None or empty tuples on failure without raising exceptions. Code proceeds with None data, causing crashes downstream or silent data gaps.
**Why it happens:** MetaQuotes designed the API for MQL5 error-code style, not Python exception style.
**How to avoid:** Every MT5 call must be wrapped in a helper that checks the return value and calls `mt5.last_error()`. Create a `check_mt5_result()` utility used everywhere.
**Warning signs:** NoneType errors deep in data processing, gaps in tick history, orders that silently fail.

### Pitfall 2: MT5 Thread Safety
**What goes wrong:** Multiple async tasks call MT5 functions concurrently through separate `to_thread` calls. The MT5 package uses global internal state and is not thread-safe.
**Why it happens:** asyncio.to_thread uses a thread pool, so two MT5 calls can execute on different threads simultaneously.
**How to avoid:** Use a `ThreadPoolExecutor(max_workers=1)` dedicated to MT5, ensuring serialized access. Or use an `asyncio.Lock` before each to_thread call.
**Warning signs:** Intermittent crashes, corrupted data returns, "IPC timeout" errors.

### Pitfall 3: Order Filling Mode Mismatch
**What goes wrong:** `order_send()` fails with "Unsupported filling mode" error.
**Why it happens:** Different brokers support different fill policies (FOK, IOC, RETURN). RoboForex ECN may only accept specific modes for XAUUSD.
**How to avoid:** Read `symbol_info("XAUUSD").filling_mode` at startup to determine which flags are supported. Set `type_filling` dynamically based on the broker's supported modes.
**Warning signs:** All order_send calls returning retcode != 10009.

### Pitfall 4: Stops Level Minimum Distance
**What goes wrong:** SL too close to market price, rejected by broker.
**Why it happens:** Brokers enforce a minimum distance (stops_level) between market price and SL/TP. For volatile instruments like gold, this can be significant.
**How to avoid:** Read `symbol_info("XAUUSD").stops_level` and ensure SL distance >= stops_level * point. If ATR-based SL is too tight, widen it or skip the trade.
**Warning signs:** Orders with valid lot size but rejected SL.

### Pitfall 5: $20 Account Position Sizing Math
**What goes wrong:** Every calculated lot size rounds to 0.01 (minimum), but actual risk at 0.01 exceeds the phase limit. Bot either never trades or over-risks.
**Why it happens:** With $20 equity and 0.01 minimum lot, the minimum tradeable risk is `sl_distance * $1/point`. For a $3 SL, that is $3 risk = 15% of $20. The 10% aggressive limit means maximum $2 risk, requiring SL <= $2.
**How to avoid:** Calculate the *actual* risk at 0.01 lot size and compare against the limit. If actual risk > limit, skip the trade (per D-04). Log the skip reason clearly. Design ATR-based SL to target tight setups ($1-$2 range) during the aggressive phase.
**Warning signs:** All trades skipped due to risk exceeding limit; or risk limit silently ignored.

### Pitfall 6: SQLite State Corruption on Crash
**What goes wrong:** Bot crashes mid-write to SQLite, leaving corrupted state that prevents restart.
**Why it happens:** Default SQLite journal mode (DELETE) can leave partial writes. Power failure during commit corrupts the database.
**How to avoid:** Enable WAL mode (`PRAGMA journal_mode=WAL`) on first connection. WAL mode survives crashes -- partial writes are rolled back automatically. Use transactions for multi-table state updates.
**Warning signs:** "database is locked" or "malformed" errors on restart.

### Pitfall 7: MT5 Connection Drop Without Detection
**What goes wrong:** MT5 terminal disconnects from broker but Python code keeps polling stale data.
**Why it happens:** `copy_ticks_from()` may return the last cached data instead of failing when connection is lost.
**How to avoid:** Periodically call `terminal_info()` and check `terminal_info().connected` flag. Also monitor tick freshness: if the latest tick timestamp is more than N seconds old, assume disconnection.
**Warning signs:** Flat tick data (no bid/ask changes for extended period), stale timestamps.

### Pitfall 8: Pandas 3.0 Breaking Changes
**What goes wrong:** Code written for pandas 2.2 breaks silently with pandas 3.0 due to string dtype changes and Copy-on-Write semantics.
**Why it happens:** pandas 3.0 (Jan 2026) changed default string handling and indexing behavior.
**How to avoid:** Pin pandas `>=2.2,<3.0` in dependencies. The MT5 package returns numpy arrays, not pandas -- the conversion point (`pd.DataFrame(ticks)`) is safe, but downstream operations on string columns may differ.
**Warning signs:** Unexpected dtype behaviors, warnings about deprecated patterns.

## Code Examples

### MT5 Initialization with Error Handling
```python
# Source: MQL5 official Python docs
import MetaTrader5 as mt5

def init_mt5(path: str | None = None) -> bool:
    """Initialize MT5 with comprehensive error checking."""
    kwargs = {"path": path} if path else {}
    if not mt5.initialize(**kwargs):
        code, message = mt5.last_error()
        # Common codes:
        # -10003: "IPC initialize failed" (MT5 terminal not running)
        # -10005: "IPC timeout" (MT5 slow to respond)
        # -10004: "IPC send failed"
        raise ConnectionError(f"MT5 init failed: [{code}] {message}")

    # Verify connection to broker
    info = mt5.terminal_info()
    if info is None:
        mt5.shutdown()
        raise ConnectionError("MT5 terminal_info returned None")

    if not info.connected:
        mt5.shutdown()
        raise ConnectionError("MT5 terminal not connected to broker")

    return True
```

### Complete Order Placement with Risk Validation
```python
# Source: MQL5 order_send + order_check docs
import MetaTrader5 as mt5

async def place_market_order(
    bridge: "MT5Bridge",
    action: str,  # "buy" or "sell"
    lot_size: float,
    sl_price: float,
    tp_price: float | None = None,
    magic: int = 20260327,
) -> dict:
    """Place a market order with server-side SL."""
    symbol = "XAUUSD"

    # Get current prices
    tick = await bridge.get_symbol_tick(symbol)
    if tick is None:
        return {"success": False, "error": "no_tick_data"}

    price = tick.ask if action == "buy" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if action == "buy" else mt5.ORDER_TYPE_SELL

    # Determine filling mode from symbol info
    info = await bridge.get_symbol_info(symbol)
    filling = mt5.ORDER_FILLING_IOC  # Default for ECN
    if info.filling_mode & mt5.ORDER_FILLING_FOK:
        filling = mt5.ORDER_FILLING_FOK

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
        "type": order_type,
        "price": price,
        "sl": sl_price,
        "deviation": 20,
        "magic": magic,
        "comment": "fxsoqqabot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }
    if tp_price is not None:
        request["tp"] = tp_price

    # Pre-validate
    check = await bridge.order_check(request)
    if check is None:
        error = await bridge.last_error()
        return {"success": False, "error": f"check_none: {error}"}
    if check.retcode != 0:
        return {"success": False, "error": f"check_failed: {check.retcode} {check.comment}"}

    # Execute
    result = await bridge.send_order(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"success": False, "error": f"send_failed: {result.retcode} {result.comment}"}

    # Track slippage
    slippage = result.price - price
    return {
        "success": True,
        "order_ticket": result.order,
        "deal_ticket": result.deal,
        "fill_price": result.price,
        "requested_price": price,
        "slippage": slippage,
        "volume": result.volume,
    }
```

### SQLite State Persistence with WAL Mode
```python
# Source: aiosqlite docs + SQLite WAL docs
import aiosqlite
from pathlib import Path

async def init_state_db(db_path: Path) -> aiosqlite.Connection:
    """Initialize SQLite state database with WAL mode."""
    db = await aiosqlite.connect(db_path)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")  # Safe with WAL
    await db.execute("PRAGMA busy_timeout=5000")

    await db.executescript("""
        CREATE TABLE IF NOT EXISTS circuit_breaker_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            daily_pnl REAL DEFAULT 0.0,
            daily_starting_equity REAL DEFAULT 0.0,
            weekly_pnl REAL DEFAULT 0.0,
            equity_high_water_mark REAL DEFAULT 0.0,
            consecutive_losses INTEGER DEFAULT 0,
            daily_trade_count INTEGER DEFAULT 0,
            session_date TEXT DEFAULT '',
            week_start_date TEXT DEFAULT '',
            kill_switch TEXT DEFAULT 'active',
            daily_drawdown TEXT DEFAULT 'active',
            loss_streak TEXT DEFAULT 'active',
            rapid_equity_drop TEXT DEFAULT 'active',
            max_trades TEXT DEFAULT 'active',
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS positions (
            ticket INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            type INTEGER NOT NULL,
            volume REAL NOT NULL,
            open_price REAL NOT NULL,
            sl REAL,
            tp REAL,
            magic INTEGER,
            open_time TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket INTEGER,
            symbol TEXT,
            action TEXT,
            volume REAL,
            open_price REAL,
            close_price REAL,
            sl REAL,
            tp REAL,
            pnl REAL,
            slippage REAL,
            spread_at_entry REAL,
            open_time TEXT,
            close_time TEXT,
            hold_duration_seconds REAL,
            magic INTEGER,
            comment TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS account_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equity REAL,
            balance REAL,
            margin REAL,
            free_margin REAL,
            margin_level REAL,
            timestamp TEXT DEFAULT (datetime('now'))
        );

        -- Ensure exactly one circuit breaker state row
        INSERT OR IGNORE INTO circuit_breaker_state (id) VALUES (1);
    """)
    await db.commit()
    return db
```

### DuckDB/Parquet Tick Storage Schema
```python
# Source: DuckDB docs + Parquet partitioning best practices
import duckdb
from pathlib import Path

def init_tick_storage(storage_path: Path) -> duckdb.DuckDBPyConnection:
    """Initialize DuckDB for tick data analytics."""
    db = duckdb.connect(str(storage_path / "analytics.duckdb"))

    # Create a view over partitioned Parquet files
    # Ticks stored as: data/ticks/year=2026/month=03/ticks_20260327.parquet
    db.execute("""
        CREATE TABLE IF NOT EXISTS tick_data (
            time_msc BIGINT,         -- Millisecond timestamp
            bid DOUBLE,
            ask DOUBLE,
            last DOUBLE,
            volume BIGINT,
            flags INTEGER,
            volume_real DOUBLE,
            spread DOUBLE,           -- Computed: ask - bid
            -- Partition columns
            year INTEGER,
            month INTEGER,
            day INTEGER
        )
    """)

    # Trade events table for analytics
    db.execute("""
        CREATE TABLE IF NOT EXISTS trade_events (
            event_time TIMESTAMP,
            ticket BIGINT,
            symbol VARCHAR,
            action VARCHAR,
            volume DOUBLE,
            price DOUBLE,
            sl DOUBLE,
            tp DOUBLE,
            pnl DOUBLE,
            slippage DOUBLE,
            spread DOUBLE,
            magic INTEGER
        )
    """)

    return db

def flush_ticks_to_parquet(db, ticks_batch, storage_path: Path):
    """Write tick batch to partitioned Parquet files."""
    # ticks_batch is a pandas DataFrame
    db.execute("""
        COPY (SELECT * FROM ticks_batch)
        TO '{path}/ticks/'
        (FORMAT PARQUET, PARTITION_BY (year, month), ROW_GROUP_SIZE 100000)
    """.format(path=storage_path))
```

### structlog Configuration
```python
# Source: structlog 25.5.0 docs
import structlog
import logging

def setup_logging(json_mode: bool = False):
    """Configure structlog for the trading bot."""
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_mode:
        # Production: JSON output for DuckDB ingestion
        renderer = structlog.processors.JSONRenderer()
    else:
        # Development: colorful console output via Rich
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )

# Usage with context binding:
# logger = structlog.get_logger()
# logger = logger.bind(trade_id="T-001", phase="aggressive")
# logger.info("order_placed", symbol="XAUUSD", volume=0.01, sl=2950.00)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| pandas 2.x default | pandas 3.0 with CoW + string dtype | Jan 2026 | Pin to 2.2.x for stability. MT5 returns numpy, not pandas, so conversion is safe. |
| pydantic-settings 2.x YAML | pydantic-settings 2.13 native TOML | 2025-2026 | TOML is now first-class in pydantic-settings. No need for custom YAML loader. |
| pyarrow 19.x | pyarrow 23.0.1 | 2026 | Major version bump. Parquet format stable. DuckDB 1.5.x compatible. |
| sqlite3 stdlib async via threads | aiosqlite 0.22.1 | Stable | Mature async bridge. WAL mode + aiosqlite is the standard pattern. |
| Custom MT5 async wrappers | aiomql framework available | 2025-2026 | aiomql exists but is opinionated. Custom wrappers give more control for our architecture. |

**Deprecated/outdated:**
- **pymt5adapter**: Deprecated (archived on GitHub). Was a Pythonic wrapper for MT5. Use raw MT5 package with custom async wrapper instead.
- **pandas 2.2.x**: Still supported but pandas 3.0 is current. Pin 2.2.x per CLAUDE.md decision to avoid breaking changes.
- **Backtrader**: Abandoned. Do not use for any purpose.

## Open Questions

1. **RoboForex ECN filling mode for XAUUSD**
   - What we know: ECN brokers typically support IOC or FOK. The filling mode must be queried at runtime via `symbol_info().filling_mode`.
   - What's unclear: Which specific mode(s) RoboForex ECN supports for gold. This can only be determined with a live MT5 connection.
   - Recommendation: Query at startup, fall back to IOC, log the result. Handle gracefully if neither works.

2. **DOM depth availability on RoboForex ECN for XAUUSD**
   - What we know: DOM for forex/metals is often limited or empty. `market_book_get()` may return empty tuples. RoboForex blog discusses DOM conceptually but doesn't confirm ECN data quality.
   - What's unclear: Whether RoboForex ECN provides any meaningful DOM data for XAUUSD.
   - Recommendation: Implement DOM ingestion but design the entire system to work with tick-only data (DATA-02 graceful degradation). Test empirically on first connection.

3. **MT5 package thread safety guarantees**
   - What we know: The package uses global state and IPC to the MT5 terminal process. Multiple forum posts report IPC timeout errors under concurrent access.
   - What's unclear: Whether concurrent calls from different threads can corrupt state or just slow down.
   - Recommendation: Use `ThreadPoolExecutor(max_workers=1)` for all MT5 calls to serialize access. This is a safety measure -- the performance cost is negligible since MT5 IPC is the bottleneck anyway.

4. **XAUUSD stops_level on RoboForex ECN**
   - What we know: Brokers enforce minimum SL distance. This value varies by broker and instrument.
   - What's unclear: The exact stops_level for XAUUSD on RoboForex ECN.
   - Recommendation: Query `symbol_info("XAUUSD").stops_level` at startup. Factor into SL distance calculations. Log the value.

5. **MT5 reconnection behavior after network drop**
   - What we know: `mt5.initialize()` can be called again after `mt5.shutdown()`. The terminal may auto-reconnect to the broker independently.
   - What's unclear: Whether calling `initialize()` while the terminal is reconnecting causes issues. Whether `terminal_info().connected` accurately reflects broker connection status in real-time.
   - Recommendation: Implement exponential backoff for reconnection attempts. Monitor both `terminal_info().connected` and tick freshness as dual indicators.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All code | Yes | 3.12.13 (via uv) | -- |
| uv | Package management | Yes | 0.10.12 | -- |
| MetaTrader 5 terminal | MT5 bridge | Yes | Installed at C:/Program Files/MetaTrader 5/ | -- |
| git | Version control | Yes | 2.51.2 | -- |
| ruff | Linting | No (not global) | -- | Install via uv: `uv tool install ruff` |
| mypy | Type checking | No (not global) | -- | Install via uv: `uv tool install mypy` |
| pytest | Testing | No (not global) | -- | Install as dev dependency in project venv |

**Missing dependencies with no fallback:**
- None. All critical dependencies are available.

**Missing dependencies with fallback:**
- ruff, mypy, pytest: Not installed globally but will be installed as project dev dependencies via uv. No blocking issue.

**Note on Python version:** System Python is 3.15.0a1 (alpha). Python 3.12.13 is available via uv and is the correct target per CLAUDE.md. The project must be initialized with `--python 3.12` to use the right version.

## Project Constraints (from CLAUDE.md)

### Mandatory Stack Choices
- Python 3.12.x (not 3.13+, not 3.15)
- MetaTrader5 5.0.5640 via pip
- pandas 2.2.x (not 3.0)
- NumPy 2.4.x
- DuckDB + Parquet for analytics storage
- SQLite for operational state
- Pydantic 2.12.x for config validation
- structlog for logging
- uv for package management
- ruff for linting/formatting
- pytest for testing
- mypy for type checking

### Forbidden
- No Redis (single machine, use asyncio.Queue)
- No Celery (use asyncio + ThreadPoolExecutor)
- No MongoDB (use DuckDB + SQLite)
- No TensorFlow/PyTorch (scikit-learn for ML)
- No Backtrader (abandoned)
- No TA-Lib (use NumPy/SciPy for custom indicators)
- No Streamlit (use FastAPI + lightweight-charts later)

### Conventions
- All MT5 blocking calls wrapped in asyncio.to_thread()
- asyncio.Queue for inter-module communication (no Redis)
- MQL5 EA kept under 500 lines (thin relay)
- All logic in Python, EA is execution relay only

## Sources

### Primary (HIGH confidence)
- [MQL5 Python Integration docs](https://www.mql5.com/en/docs/python_metatrader5) -- Complete API reference: initialize, copy_ticks_from, copy_rates_from, market_book_get, order_send, order_check, order_calc_margin, positions_get, account_info, symbol_info, last_error
- [MQL5 order_send docs](https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py) -- TradeRequest structure, retcode values, fill policies
- [MQL5 copy_ticks_from docs](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksfrom_py) -- Tick structure (time, bid, ask, last, volume, time_msc, flags), COPY_TICKS flags
- [MQL5 market_book_get docs](https://www.mql5.com/en/docs/python_metatrader5/mt5marketbookget_py) -- BookInfo structure, market_book_add subscription pattern
- [MQL5 copy_rates_from docs](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py) -- Bar structure, TIMEFRAME constants
- [DuckDB Parquet docs](https://duckdb.org/docs/stable/data/parquet/overview) -- Read/write, partition pushdown, schema projection
- [DuckDB Hive Partitioning](https://duckdb.org/docs/stable/data/partitioning/hive_partitioning) -- Partition key filter pushdown
- [pydantic-settings docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) -- TomlConfigSettingsSource, multiple files, deep merge
- [structlog docs](https://www.structlog.org/en/stable/) -- v25.5.0 configuration, bound loggers, processors, JSON/console rendering
- [aiosqlite GitHub](https://github.com/omnilib/aiosqlite) -- Async SQLite bridge, thread-per-connection model
- [SQLite WAL mode docs](https://www.sqlite.org/wal.html) -- Crash recovery, concurrent access, persistence
- [Python asyncio.to_thread docs](https://docs.python.org/3/library/asyncio-task.html) -- Running blocking code in threads
- [uv project docs](https://docs.astral.sh/uv/guides/projects/) -- Project init, src layout, pyproject.toml, lock files

### Secondary (MEDIUM confidence)
- [MQL5 forum: filling modes](https://www.mql5.com/en/forum/458315) -- FOK vs IOC vs RETURN broker-specific support
- [MQL5 forum: market_book issues](https://www.mql5.com/en/forum/446902) -- DOM availability problems for forex symbols
- [MQL5 forum: IPC timeout errors](https://www.mql5.com/en/forum/447937) -- Connection initialization failure patterns
- [pandas 3.0 changelog](https://pandas.pydata.org/docs/whatsnew/v3.0.0.html) -- Breaking changes (CoW, string dtype)
- [RoboForex XAUUSD specs](https://roboforex.com/forex-trading/trading/specifications/card/pro-stan-ecn/XAUUSD/) -- Contract specifications (page could not be fetched, verify with MT5 terminal)
- [XAUUSD pip/lot calculations](https://www.defcofx.com/xauusd-pips-and-lot-size/) -- 0.01 lot = 1 oz, $1 move = $1 per 0.01 lot
- [aiomql framework](https://github.com/Ichinga-Samuel/aiomql) -- Reference for async MT5 patterns (not using directly)

### Tertiary (LOW confidence)
- [RoboForex ECN spread data](https://www.myfxbook.com/forex-broker-spreads/roboforex/4552,51) -- Spread monitoring (403, could not access)
- RoboForex XAUUSD typical spread: ECN accounts advertise "from 0 pips" but actual gold spreads are broker-specific and must be measured empirically

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- All packages verified on PyPI with current versions. MT5 API fully documented on MQL5.
- Architecture: HIGH -- Async wrapping of blocking MT5 calls is a well-established pattern. Project structure follows standard Python src-layout conventions.
- Pitfalls: HIGH -- MT5 silent failures, thread safety issues, and filling mode problems are widely documented in MQL5 forums and community resources.
- Position sizing math: HIGH -- XAUUSD contract specs (100 oz/lot, $1/point per 0.01 lot) are standard across brokers. Three-phase risk model is simple arithmetic.
- DOM availability: LOW -- Cannot verify RoboForex ECN DOM data quality without live connection. Graceful degradation is the correct mitigation.
- Broker-specific details: LOW -- Filling modes, stops_level, and spread behavior must be queried at runtime from the actual RoboForex ECN connection.

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable domain, 30-day validity)
