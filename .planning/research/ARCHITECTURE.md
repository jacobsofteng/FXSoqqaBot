# Architecture Research

**Domain:** Python-first XAUUSD scalping bot with 8 interconnected modules on MetaTrader 5
**Researched:** 2026-03-27
**Confidence:** HIGH (MT5 Python API is well-documented; event-driven trading architectures are a mature pattern)

## System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         LAYER 0: DATA INGESTION                          │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │              MT5 Bridge (polling loop, ~100ms cycle)               │  │
│  │  symbol_info_tick() | market_book_get() | copy_ticks_from()       │  │
│  └──────────────────────────────┬─────────────────────────────────────┘  │
│                                 │ raw ticks, DOM snapshots, bars         │
├─────────────────────────────────┼────────────────────────────────────────┤
│                         LAYER 1: SENSING                                 │
│                                 │                                        │
│  ┌──────────────────────────────▼─────────────────────────────────────┐  │
│  │              [1] Market Microstructure Sensor                      │  │
│  │  tick normalization, volume delta, bid-ask spread, DOM parsing    │  │
│  └──┬───────────────────────┬──────────────────────┬──────────────────┘  │
│     │ normalized ticks      │ volume profile        │ DOM state          │
├─────┼───────────────────────┼──────────────────────┼─────────────────────┤
│                         LAYER 2: ANALYSIS                                │
│     │                       │                      │                     │
│  ┌──▼───────────────┐  ┌───▼──────────────┐  ┌────▼─────────────────┐   │
│  │ [2] Institutional │  │ [4] Chaos/Fractal│  │ [3] Quantum Timing  │   │
│  │ Footprint Detector│  │ Regime Classifier│  │     Engine          │   │
│  │                   │  │                  │  │                     │   │
│  │ absorption,       │  │ fractal dim,     │  │ price-time states,  │   │
│  │ iceberg detect,   │  │ Lyapunov exp,    │  │ probability windows,│   │
│  │ flow imbalance    │  │ bifurcation prox │  │ entry/exit timing   │   │
│  └────────┬──────────┘  └────────┬─────────┘  └──────────┬──────────┘   │
│           │ inst_signal          │ regime_state           │ timing_signal│
├───────────┼──────────────────────┼────────────────────────┼──────────────┤
│                         LAYER 3: DECISION                                │
│           │                      │                        │              │
│  ┌────────▼──────────────────────▼────────────────────────▼──────────┐   │
│  │              [5] Decision and Execution Core                      │   │
│  │  signal fusion | confidence weighting | position sizing           │   │
│  │  phase-aware risk (aggressive/selective/conservative)             │   │
│  └──────────────────────────────┬────────────────────────────────────┘   │
│                                 │ trade_request                          │
├─────────────────────────────────┼────────────────────────────────────────┤
│                         LAYER 4: EXECUTION                               │
│                                 │                                        │
│  ┌──────────────────────────────▼────────────────────────────────────┐   │
│  │              MT5 Bridge (order_send / order_check)                 │   │
│  │  order validation | slippage guard | execution confirmation       │   │
│  └──────────────────────────────┬────────────────────────────────────┘   │
│                                 │ trade_result                           │
├═════════════════════════════════╪════════════════════════════════════════╡
│                     CROSS-CUTTING SYSTEMS                                │
│                                 │                                        │
│  ┌──────────────────────────────▼────────────────────────────────────┐   │
│  │              [6] Self-Learning Mutation Loop                       │   │
│  │  trade journal | forward labeling | genetic param evolution       │   │
│  │  regime-aware performance attribution | shadow model training     │   │
│  └───────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐   │
│  │              [7] Dashboard and Telemetry                           │   │
│  │  Textual TUI (primary) | FastAPI web dashboard (secondary)        │   │
│  │  subscribes to all layers via event bus                           │   │
│  └───────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐   │
│  │              [8] Backtesting and Anti-Overfitting Framework        │   │
│  │  replays historical ticks through same pipeline                   │   │
│  │  walk-forward | Monte Carlo | regime-aware evaluation             │   │
│  └───────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Boundary |
|-----------|----------------|----------|
| **MT5 Bridge** | All communication with MetaTrader 5 terminal. Wraps the synchronous `MetaTrader5` Python package. Sole owner of `mt5.initialize()`, `mt5.shutdown()`, and all `mt5.*` calls. No other module touches MT5 directly. | Ingestion + Execution boundaries. Produces `RawTick`, `DOMSnapshot`, `BarData`. Consumes `TradeRequest`. |
| **[1] Microstructure Sensor** | Normalizes raw ticks into usable market state: volume delta, bid-ask spread dynamics, tick intensity, DOM depth parsing (when available), order flow imbalance. Acts as the nervous system. | Consumes raw data from MT5 Bridge. Produces `MarketState` dataclass consumed by all Layer 2 modules. |
| **[2] Institutional Footprint** | Classifies activity as institutional vs. retail: absorption detection, iceberg pattern recognition, large-lot flow imbalance, HFT signature detection. | Consumes `MarketState`. Produces `InstitutionalSignal` with flow direction, confidence, magnitude. |
| **[3] Quantum Timing** | Models price-time as coupled state variables. Calculates probability-weighted entry/exit windows using wave-function-inspired modeling. | Consumes `MarketState`. Produces `TimingSignal` with entry/exit probability distributions. |
| **[4] Chaos/Fractal Regime** | Detects dynamical market state: fractal dimension, Lyapunov exponents, Hurst exponent, bifurcation proximity, crowd entropy estimation. | Consumes `MarketState`. Produces `RegimeState` classifying market as trending/mean-reverting/chaotic/bifurcating. |
| **[5] Decision Core** | Fuses upstream signals into trade decisions. Weights signals by regime context. Applies phase-aware position sizing ($20/$100/$300 thresholds). Manages open positions. | Consumes all Layer 2 outputs. Produces `TradeRequest` or `NoAction`. Owns risk management logic. |
| **[6] Self-Learning Loop** | Logs complete trade context (all signals at entry/exit). Forward-labels outcomes. Runs offline genetic optimization of module parameters. Trains shadow models. Promotes improvements via versioned config swap. | Reads trade journal + historical `MarketState` sequences. Writes updated parameter configs. Runs asynchronously from the trading loop. |
| **[7] Dashboard/Telemetry** | Displays real-time system state. Textual TUI for primary monitoring. Optional FastAPI web dashboard. Read-only subscriber to all events. | Subscribes to event bus. Never produces trading signals. Pure observation layer. |
| **[8] Backtesting** | Replays historical tick data through the same module pipeline. Walk-forward validation, Monte Carlo simulation, out-of-sample testing. | Replaces MT5 Bridge with a `HistoricalDataFeed` that emits the same `RawTick`/`DOMSnapshot` interfaces. All other modules are unaware they are in backtest mode. |

## Recommended Project Structure

```
fxsoqqabot/
├── core/                       # Shared infrastructure
│   ├── __init__.py
│   ├── event_bus.py            # In-process pub/sub event system
│   ├── types.py                # All shared dataclasses and type definitions
│   ├── config.py               # Configuration loading (TOML-based)
│   ├── clock.py                # Abstracted clock (real or simulated for backtest)
│   └── logging.py              # Structured logging setup
│
├── bridge/                     # MT5 communication boundary
│   ├── __init__.py
│   ├── mt5_client.py           # Wraps all mt5.* calls, async via to_thread
│   ├── data_feed.py            # Polling loop: ticks, DOM, bars
│   └── order_executor.py       # order_send, order_check, position management
│
├── sensor/                     # Module 1: Market Microstructure Sensor
│   ├── __init__.py
│   ├── tick_processor.py       # Tick normalization, volume delta
│   ├── spread_analyzer.py      # Bid-ask spread dynamics
│   ├── dom_parser.py           # DOM depth parsing (graceful degradation)
│   └── market_state.py         # Assembles MarketState from all sub-signals
│
├── institutional/              # Module 2: Institutional Footprint Detector
│   ├── __init__.py
│   ├── flow_classifier.py      # Retail vs. institutional classification
│   ├── absorption_detector.py  # Absorption/iceberg pattern detection
│   └── footprint.py            # Produces InstitutionalSignal
│
├── quantum/                    # Module 3: Quantum Timing Engine
│   ├── __init__.py
│   ├── state_model.py          # Price-time coupled state variables
│   ├── probability_windows.py  # Entry/exit probability calculation
│   └── timing.py               # Produces TimingSignal
│
├── chaos/                      # Module 4: Chaos/Fractal/Feigenbaum Regime
│   ├── __init__.py
│   ├── fractal_dimension.py    # Fractal dimension calculation
│   ├── lyapunov.py             # Lyapunov exponent estimation
│   ├── hurst.py                # Hurst exponent (R/S analysis)
│   ├── bifurcation.py          # Feigenbaum bifurcation proximity
│   └── regime.py               # Produces RegimeState
│
├── decision/                   # Module 5: Decision and Execution Core
│   ├── __init__.py
│   ├── signal_fusion.py        # Weighted combination of all upstream signals
│   ├── risk_manager.py         # Phase-aware position sizing, drawdown limits
│   ├── position_tracker.py     # Open position state management
│   └── execution.py            # Trade decision logic, produces TradeRequest
│
├── learning/                   # Module 6: Self-Learning Mutation Loop
│   ├── __init__.py
│   ├── trade_journal.py        # Full-context trade logging
│   ├── forward_labeler.py      # Outcome labeling after trade closes
│   ├── genetic_optimizer.py    # Genetic algorithm for parameter evolution
│   ├── shadow_trainer.py       # ML model training (runs offline)
│   └── config_promoter.py      # Versioned config swap mechanism
│
├── dashboard/                  # Module 7: Dashboard and Telemetry
│   ├── __init__.py
│   ├── tui/                    # Textual TUI application
│   │   ├── app.py              # Main Textual app
│   │   ├── widgets/            # Custom widgets (regime display, signal panel, etc.)
│   │   └── screens/            # TUI screen definitions
│   └── web/                    # FastAPI web dashboard (optional, later phase)
│       ├── app.py              # FastAPI application
│       └── routes/             # API endpoints + SSE streams
│
├── backtest/                   # Module 8: Backtesting Framework
│   ├── __init__.py
│   ├── historical_feed.py      # Replays historical data as RawTick stream
│   ├── simulator.py            # Simulated order execution with slippage model
│   ├── walk_forward.py         # Walk-forward validation engine
│   ├── monte_carlo.py          # Monte Carlo simulation
│   └── evaluator.py            # Performance metrics, regime-aware scoring
│
├── storage/                    # Persistence layer
│   ├── __init__.py
│   ├── tick_store.py           # SQLite for tick/trade writes
│   ├── analytics_store.py      # DuckDB for analytical queries
│   └── migrations/             # Schema versioning
│
├── main.py                     # Entry point: live trading mode
├── backtest_runner.py          # Entry point: backtesting mode
└── config/
    ├── default.toml            # Default configuration
    ├── live.toml               # Live trading overrides
    └── backtest.toml           # Backtest-specific config
```

### Structure Rationale

- **`core/`:** Shared infrastructure that every module depends on. The event bus, type definitions, and clock abstraction live here. This is the foundation that must be built first.
- **`bridge/`:** Hard boundary around all MT5 communication. No module except `bridge/` imports `MetaTrader5`. This makes the backtesting swap trivial -- replace `bridge/data_feed.py` with `backtest/historical_feed.py` and everything else works identically.
- **One folder per module (sensor/, institutional/, quantum/, chaos/, decision/):** Each analysis module is a self-contained package. They share no internal state. They receive `MarketState` via the event bus and publish their signal type. This makes modules independently testable and replaceable.
- **`learning/`:** Deliberately separated from the trading pipeline. It reads trade results and historical data but never injects into the live decision path synchronously. Its output is configuration updates, not trading signals.
- **`storage/`:** Dual-database strategy (detailed below). Centralized persistence so modules write through a clean API, not directly to files.
- **`config/`:** TOML-based configuration with layered overrides. The learning module's output is a new TOML parameter set that gets promoted to the active config.

## Architectural Patterns

### Pattern 1: Event Bus (In-Process Pub/Sub)

**What:** A lightweight in-process publish/subscribe system using `asyncio.Queue` per subscriber. Producers publish typed events; consumers subscribe by event type. No external message broker needed.

**When to use:** All inter-module communication in the live trading pipeline. The Sensor publishes `MarketState`; all Layer 2 modules subscribe. Layer 2 modules publish their signals; the Decision Core subscribes to all of them.

**Trade-offs:**
- Pro: Zero serialization overhead, type-safe, easy to debug, no external dependencies
- Pro: Dashboard subscribes to everything without coupling to any module
- Pro: Backtesting framework subscribes to the same events for replay validation
- Con: Single-process only (fine for our same-machine deployment)
- Con: Backpressure must be handled manually (bounded queues)

**Example:**
```python
from dataclasses import dataclass
from typing import TypeVar, Type, Callable, Awaitable
from collections import defaultdict
import asyncio

T = TypeVar("T")

@dataclass(frozen=True, slots=True)
class MarketState:
    timestamp: float
    bid: float
    ask: float
    volume_delta: float
    spread: float
    dom_depth: list | None  # None when DOM unavailable

@dataclass(frozen=True, slots=True)
class RegimeState:
    timestamp: float
    regime: str  # "trending" | "mean_reverting" | "chaotic" | "bifurcating"
    fractal_dim: float
    hurst: float
    confidence: float

class EventBus:
    def __init__(self):
        self._subscribers: dict[Type, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, event_type: Type[T], maxsize: int = 100) -> asyncio.Queue[T]:
        queue: asyncio.Queue[T] = asyncio.Queue(maxsize=maxsize)
        self._subscribers[event_type].append(queue)
        return queue

    async def publish(self, event: object) -> None:
        for queue in self._subscribers[type(event)]:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest event (backpressure strategy for non-critical consumers)
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(event)
```

### Pattern 2: Async Polling Loop with `asyncio.to_thread`

**What:** The MT5 Python package is entirely synchronous. Every `mt5.*` call blocks. We wrap each call in `asyncio.to_thread()` to keep the main event loop responsive. A dedicated polling coroutine calls `symbol_info_tick()` and `market_book_get()` at a configurable interval (default ~100ms for scalping).

**When to use:** All MT5 Bridge operations -- data ingestion and order execution.

**Trade-offs:**
- Pro: Non-blocking; analysis modules run concurrently with data polling
- Pro: `symbol_info_tick()` roundtrip is ~17 microseconds on same machine, so 100ms polling wastes no meaningful time
- Pro: Proven pattern used by `aiomql` framework in production
- Con: GIL means true parallelism requires `ProcessPoolExecutor` for CPU-heavy work
- Con: Polling introduces up to one polling-interval of latency (100ms worst case)

**Example:**
```python
import MetaTrader5 as mt5
import asyncio

class MT5DataFeed:
    def __init__(self, event_bus: EventBus, symbol: str = "XAUUSD",
                 poll_interval: float = 0.1):
        self._bus = event_bus
        self._symbol = symbol
        self._interval = poll_interval
        self._running = False

    async def start(self):
        self._running = True
        # Subscribe to DOM updates
        await asyncio.to_thread(mt5.market_book_add, self._symbol)
        while self._running:
            tick = await asyncio.to_thread(mt5.symbol_info_tick, self._symbol)
            dom = await asyncio.to_thread(mt5.market_book_get, self._symbol)
            if tick is not None:
                await self._bus.publish(RawTick(
                    timestamp=tick.time_msc / 1000.0,
                    bid=tick.bid, ask=tick.ask,
                    volume=tick.volume, flags=tick.flags
                ))
            if dom is not None:
                await self._bus.publish(DOMSnapshot(
                    timestamp=tick.time_msc / 1000.0 if tick else time.time(),
                    entries=[(e.type, e.price, e.volume_dbl) for e in dom]
                ))
            await asyncio.sleep(self._interval)

    async def stop(self):
        self._running = False
        await asyncio.to_thread(mt5.market_book_release, self._symbol)
```

### Pattern 3: Interface Swap for Backtesting (Strategy Pattern)

**What:** The backtesting framework works by replacing the MT5 Bridge's `DataFeed` with a `HistoricalDataFeed` that replays stored tick data through the same event bus. All downstream modules (Sensor, Institutional, Chaos, Quantum, Decision) are completely unaware whether they are processing live or historical data.

**When to use:** Backtesting mode. Also used for replay-debugging of live trading sessions.

**Trade-offs:**
- Pro: Guarantees backtest fidelity -- same code path as live
- Pro: No "backtest-only" code branches that diverge from production
- Pro: An abstracted `Clock` provides simulated time so time-dependent calculations (e.g., tick intensity per second) work correctly
- Con: Requires discipline to never call `time.time()` directly in modules -- always use `Clock`

**Example:**
```python
from abc import ABC, abstractmethod

class DataFeedProtocol(ABC):
    @abstractmethod
    async def start(self) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...

class LiveDataFeed(DataFeedProtocol):
    """Wraps MT5 Bridge -- used in production."""
    async def start(self):
        # polls mt5.symbol_info_tick() in a loop
        ...

class HistoricalDataFeed(DataFeedProtocol):
    """Replays stored tick data -- used in backtesting."""
    def __init__(self, tick_store, event_bus, clock, speed: float = 0.0):
        self._store = tick_store
        self._bus = event_bus
        self._clock = clock
        self._speed = speed  # 0.0 = as fast as possible

    async def start(self):
        for tick in self._store.iter_ticks():
            self._clock.advance_to(tick.timestamp)
            await self._bus.publish(tick)
            if self._speed > 0:
                await asyncio.sleep(self._speed)
```

### Pattern 4: Shadow Model Promotion (Safe Self-Learning)

**What:** The self-learning loop never modifies live trading parameters directly. It trains "shadow" parameter sets, evaluates them against recent out-of-sample data, and only promotes a new parameter set when it meets strict improvement thresholds. Promotion is an atomic config file swap.

**When to use:** Module 6 (Self-Learning Mutation Loop) when updating any tunable parameter across modules.

**Trade-offs:**
- Pro: Live trading is never disrupted by a learning cycle
- Pro: Rollback is trivial -- revert to previous config version
- Pro: Full audit trail of every parameter change with associated performance metrics
- Con: Learning improvements are delayed (batch promotion, not real-time adaptation)
- Con: Requires careful versioning of config files

## Data Flow

### Primary Trading Flow (Live Mode)

```
MT5 Terminal
    |
    | mt5.symbol_info_tick(), mt5.market_book_get()
    | (polled every ~100ms via asyncio.to_thread)
    v
MT5 Bridge  ──publishes──>  EventBus [RawTick, DOMSnapshot]
                                |
                                v
                    [1] Microstructure Sensor
                    (subscribes to RawTick, DOMSnapshot)
                    (computes volume delta, spread, DOM features)
                                |
                    ──publishes──>  EventBus [MarketState]
                                |
                 ┌──────────────┼──────────────┐
                 v              v              v
        [2] Institutional  [4] Chaos/    [3] Quantum
         Footprint          Fractal       Timing
         Detector           Regime        Engine
                 |              |              |
          publishes        publishes       publishes
      [InstSignal]    [RegimeState]   [TimingSignal]
                 |              |              |
                 └──────────────┼──────────────┘
                                v
                    [5] Decision and Execution Core
                    (subscribes to all three signal types)
                    (fuses signals, applies risk rules)
                                |
                    ──publishes──>  EventBus [TradeRequest | NoAction]
                                |
                                v
                        MT5 Bridge (order_send)
                                |
                    ──publishes──>  EventBus [TradeResult]
                                |
                                v
                    [6] Self-Learning Loop (journals everything)
                    [7] Dashboard (displays everything)
```

### Self-Learning Data Flow (Offline/Background)

```
Trade Journal (SQLite)
    |
    | query: recent closed trades + full signal context
    v
Forward Labeler
    |
    | annotates: entry quality, exit quality, regime accuracy
    v
Genetic Optimizer
    |
    | evolves: parameter sets for each module
    | evaluates: on walk-forward windows
    v
Shadow Trainer
    |
    | trains: ML classifiers on labeled regime data
    | validates: out-of-sample performance
    v
Config Promoter
    |
    | if improvement > threshold:
    |   write new config/params_v{N+1}.toml
    |   signal main loop to reload
    v
Main Trading Loop (picks up new config on next cycle)
```

### Key Data Flows

1. **Tick-to-Trade (critical path):** `RawTick` -> `MarketState` -> `[InstSignal, RegimeState, TimingSignal]` -> `TradeRequest` -> `TradeResult`. This is the latency-sensitive path. Target: under 50ms from tick arrival to trade decision (excluding broker execution time). All processing is in-memory via the event bus.

2. **Trade-to-Journal (logging path):** Every `TradeRequest` and `TradeResult` is written to the trade journal with the full signal snapshot at time of decision. This is append-only and must never block the critical path. Use `asyncio.create_task` for fire-and-forget writes.

3. **Journal-to-Learning (background path):** The learning loop reads from the trade journal periodically (e.g., after every N closed trades or on a timer). It runs CPU-intensive optimization in a `ProcessPoolExecutor` to avoid blocking the event loop and GIL contention with the trading path.

4. **Config-to-Modules (promotion path):** When the learning loop promotes a new parameter set, it writes a versioned TOML file and publishes a `ConfigUpdate` event. Each module watches for `ConfigUpdate` events relevant to its namespace and hot-reloads its parameters on the next processing cycle. No restart required.

## Storage Strategy

### Dual-Database Architecture

Use **SQLite** for transactional writes and **DuckDB** for analytical reads. Both are embedded, zero-dependency, file-based databases that require no server process.

| Store | Engine | Purpose | Access Pattern |
|-------|--------|---------|----------------|
| Tick store | SQLite | Raw tick archival, write-heavy | Append-only, sequential writes at tick rate |
| Trade journal | SQLite | Trade logs with full signal context | Append on trade open/close, read by learning loop |
| Config history | SQLite | Versioned parameter sets | Write on promotion, read on startup |
| Analytics cache | DuckDB | Historical analysis, backtest queries | Bulk reads, columnar aggregations, regime statistics |
| Backtest results | DuckDB | Walk-forward results, Monte Carlo output | Write after backtest run, read for dashboard/analysis |

**Why this split:** SQLite handles high-frequency small writes (ticks arrive every 100ms) with sub-millisecond insert latency. DuckDB handles analytical queries over millions of rows 20-50x faster than SQLite due to columnar storage. The learning loop and backtesting framework query DuckDB. The live trading pipeline writes to SQLite. A periodic sync task copies closed data from SQLite to DuckDB for analysis.

### File-Based Storage (Supplementary)

| Data | Format | Purpose |
|------|--------|---------|
| Parameter configs | TOML | Human-readable, version-controlled module parameters |
| Mutation history | JSON lines | Append-only log of every genetic algorithm generation |
| Model artifacts | pickle/joblib | Trained ML models (regime classifier, etc.) |

### Schema Boundaries

Each module owns its own tables/schemas. The trade journal schema is owned by the learning module. The tick store schema is owned by the bridge. No cross-module direct table access -- all inter-module data sharing goes through the event bus or explicit query APIs in the storage layer.

## Python-MT5 Communication Deep Dive

### The MetaTrader5 Python Package

The official `MetaTrader5` package (PyPI: `MetaTrader5`, version 5.0.5430 as of Jan 2026) communicates with the MT5 terminal via an internal IPC mechanism on the same machine. Key characteristics:

| Property | Detail |
|----------|--------|
| All calls synchronous | Every function blocks until the terminal responds |
| Single-threaded access | Only one thread should call `mt5.*` functions at a time |
| `symbol_info_tick()` latency | ~17 microseconds average on same machine |
| `order_send()` local latency | ~15-24 microseconds (local API call only; broker execution adds 60-200ms) |
| `market_book_get()` | Requires prior `market_book_add()` subscription; returns current DOM snapshot |
| No callback/event API | No way to register for tick callbacks; must poll |
| No async variant | Must use `asyncio.to_thread()` or thread pool wrappers |

### Why NOT a Thin MQL5 EA with Socket/Pipe Communication

The PROJECT.md mentions a "thin MQL5 EA for execution only." After research, the recommended approach is simpler: **use the Python `MetaTrader5` package directly for both data and execution.** Rationale:

1. `mt5.order_send()` from Python has ~17 microsecond local latency. The broker adds 60-200ms regardless. A socket/pipe hop through an MQL5 EA adds complexity with zero latency benefit.
2. `mt5.symbol_info_tick()` and `mt5.market_book_get()` give Python direct access to all market data. No need for an MQL5 EA to relay data.
3. A thin MQL5 EA is only needed if you want the EA to act as a safety net (e.g., trailing stop management if Python crashes). This is a valid use case for a later phase -- a watchdog EA that monitors positions and enforces hard stop-losses independently of Python.

**Recommendation:** Phase 1 uses Python `MetaTrader5` package exclusively. Phase 2+ adds a watchdog MQL5 EA for safety, not for primary execution.

### Handling the GIL for CPU-Intensive Analysis

The chaos/fractal calculations (Lyapunov exponents, fractal dimension, Hurst exponent) are CPU-intensive. Running them in the main asyncio event loop would block tick processing.

**Solution:** Use `ProcessPoolExecutor` for CPU-heavy analysis modules. The event bus delivers `MarketState` to each analysis module's async handler. Modules that need heavy computation offload to a process pool:

```python
import asyncio
from concurrent.futures import ProcessPoolExecutor

# Module-level process pool (shared across CPU-intensive modules)
_cpu_pool = ProcessPoolExecutor(max_workers=3)

class ChaosRegimeClassifier:
    async def on_market_state(self, state: MarketState):
        loop = asyncio.get_event_loop()
        regime = await loop.run_in_executor(
            _cpu_pool,
            self._compute_regime,  # Pure function, no shared state
            state
        )
        await self._bus.publish(regime)

    @staticmethod
    def _compute_regime(state: MarketState) -> RegimeState:
        # CPU-intensive: fractal dim, Lyapunov, Hurst
        # Runs in separate process -- no GIL contention
        ...
```

**Critical constraint:** Functions sent to `ProcessPoolExecutor` must be picklable. Use `@staticmethod` or module-level functions, not bound methods. Dataclasses with `slots=True` pickle efficiently.

## Build Order (Dependency-Driven)

The modules have clear dependency ordering. Build bottom-up:

```
Phase 1 (Foundation):
  core/event_bus.py + core/types.py + core/config.py + core/clock.py
  bridge/mt5_client.py + bridge/data_feed.py
  storage/tick_store.py
  sensor/ (simplified: tick normalization + spread only)

Phase 2 (Minimal Trading Loop):
  decision/ (simplified: single-signal threshold trading)
  bridge/order_executor.py
  storage/ (trade journal tables)

Phase 3 (Analysis Modules):
  chaos/ (start with Hurst exponent only)
  institutional/ (start with volume imbalance only)
  quantum/ (start with basic timing windows)

Phase 4 (Feedback Systems):
  learning/ (trade journal + basic parameter logging)
  dashboard/tui/ (basic Textual app showing state)

Phase 5 (Validation):
  backtest/ (historical feed + walk-forward)

Phase 6 (Deepening):
  All modules gain depth (fractal dim, Lyapunov, absorption, etc.)
  learning/ gains genetic optimizer + shadow training
  dashboard/ gains web interface
```

**Rationale for this order:**
- You cannot test anything without the bridge and event bus (Phase 1).
- A minimal trading loop (Phases 1-2) proves the architecture end-to-end before investing in complex analysis.
- Analysis modules (Phase 3) are independent of each other and can be built in parallel.
- The learning loop (Phase 4) needs trade history to learn from, so it follows trading.
- Backtesting (Phase 5) validates everything built so far.
- Deepening (Phase 6) is iterative and ongoing.

## Scaling Considerations

This is a single-machine, single-instrument system. "Scaling" means handling increasing computational complexity, not distributed deployment.

| Concern | At Launch (simplified modules) | At Full Depth (all modules active) | If Multi-Instrument (future) |
|---------|-------------------------------|-------------------------------------|------------------------------|
| CPU load | Minimal -- simple math on 10 ticks/sec | Moderate -- fractal/chaos math in process pool | Need dedicated process per instrument |
| Memory | < 100MB -- small tick buffer | ~500MB -- rolling windows for fractal analysis | Linear growth per instrument |
| Storage | ~50MB/day tick data | Same tick rate, more metadata per trade | Multiply by instrument count |
| Latency | < 10ms tick-to-decision | < 50ms with process pool offloading | Process pool contention risk |

### Scaling Priorities

1. **First bottleneck: CPU-intensive chaos math.** Fractal dimension and Lyapunov exponent calculations on rolling windows are O(n*log(n)) to O(n^2). Mitigation: `ProcessPoolExecutor`, pre-computed rolling windows, caching regime state (regime changes slowly -- no need to recompute every tick).

2. **Second bottleneck: Tick storage I/O.** At ~10 ticks/second for XAUUSD, SQLite handles this trivially. But backtest replay of years of tick data at maximum speed can bottleneck on reads. Mitigation: DuckDB for bulk historical reads, batch tick loading into memory before backtest runs.

3. **Third bottleneck: Event bus queue depth.** If a slow subscriber (like the dashboard) cannot keep up, its queue fills. Mitigation: Bounded queues with drop-oldest policy for non-critical subscribers (dashboard), and backpressure for critical subscribers (decision core).

## Anti-Patterns

### Anti-Pattern 1: Direct MT5 Calls from Analysis Modules

**What people do:** Import `MetaTrader5` in the chaos or institutional module to fetch additional data mid-calculation.
**Why it is wrong:** Creates hidden coupling, breaks backtesting (MT5 is not available in backtest mode), causes thread-safety issues with concurrent `mt5.*` calls, and makes modules impossible to unit test.
**Do this instead:** All market data flows through the event bus. If a module needs data it does not currently receive, extend the `MarketState` dataclass or create a new event type published by the Sensor.

### Anti-Pattern 2: Synchronous Learning in the Trading Loop

**What people do:** Run genetic optimization or model training synchronously after each trade closes, blocking the main loop.
**Why it is wrong:** A single genetic optimization run can take seconds to minutes. During that time, the bot misses ticks, cannot manage open positions, and might miss stop-loss adjustments.
**Do this instead:** The learning loop runs in a separate `asyncio.Task` (or process). It reads from the trade journal database, not from live events. It publishes `ConfigUpdate` events when new parameters are ready.

### Anti-Pattern 3: God Object Decision Core

**What people do:** Put all analysis logic inside the decision module -- "it needs to see everything anyway."
**Why it is wrong:** The decision core becomes an untestable monolith. Every change to any analysis algorithm requires modifying the decision module. Backtesting requires running the entire monolith.
**Do this instead:** Each analysis module is independent. The decision core only performs signal fusion (weighted combination) and risk management. It receives pre-computed signals and never duplicates analysis logic.

### Anti-Pattern 4: Storing Config in the Database

**What people do:** Put module parameters in SQLite rows, query on every tick.
**Why it is wrong:** Adds unnecessary I/O to the critical path. Config changes are rare (maybe once per day from the learning loop). Reading from the DB on every tick is wasteful.
**Do this instead:** Config is loaded into memory at startup from TOML files. The learning loop writes new TOML files and publishes a `ConfigUpdate` event. Modules hot-reload from the event, not from the database.

### Anti-Pattern 5: Tight Coupling Between Backtest and Live Code

**What people do:** Use `if is_backtesting:` branches throughout the codebase to switch between live and simulated behavior.
**Why it is wrong:** Backtest behavior diverges from live over time. Bugs hide in branch differences. Every new feature needs both branches.
**Do this instead:** Use the interface swap pattern. The `DataFeedProtocol` and `Clock` abstractions are the only things that differ. All analysis, decision, and execution logic is identical in both modes.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| MetaTrader 5 Terminal | `MetaTrader5` Python package via `asyncio.to_thread()` | Must be running on same machine. `mt5.initialize()` connects. Only one Python process should connect at a time. |
| RoboForex ECN | Via MT5 Terminal (transparent) | Broker execution latency (60-200ms) is out of our control. DOM depth availability depends on broker feed. |
| Filesystem | TOML configs, SQLite/DuckDB files | All storage is local. No network dependencies. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| MT5 Bridge <-> Sensor | EventBus: `RawTick`, `DOMSnapshot` | Bridge publishes; Sensor subscribes. One-way data flow. |
| Sensor <-> Analysis Modules | EventBus: `MarketState` | Sensor publishes; Modules 2, 3, 4 subscribe. Fan-out pattern. |
| Analysis Modules <-> Decision Core | EventBus: `InstSignal`, `RegimeState`, `TimingSignal` | Each module publishes its signal type. Decision Core subscribes to all three. Fan-in pattern. |
| Decision Core <-> MT5 Bridge | EventBus: `TradeRequest` -> Bridge; `TradeResult` -> EventBus | Two-step: Decision publishes request, Bridge executes and publishes result. |
| All Modules <-> Dashboard | EventBus: all event types | Dashboard subscribes to everything. Read-only. Never publishes. |
| Trading Pipeline <-> Learning Loop | SQLite trade journal (async read) + EventBus `ConfigUpdate` | Learning reads from DB (decoupled). Publishes config changes via event bus. |
| Live Mode <-> Backtest Mode | `DataFeedProtocol` interface swap + `Clock` abstraction | Only the data source and clock differ. All other code is shared. |

## Sources

- [MetaTrader5 Python Integration Official Docs](https://www.mql5.com/en/docs/python_metatrader5) -- Complete API reference, function signatures, return types (HIGH confidence)
- [market_book_get Documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5marketbookget_py) -- DOM access API specifics (HIGH confidence)
- [MetaTrader5 on PyPI](https://pypi.org/project/metatrader5/) -- Package version 5.0.5430, Jan 2026 (HIGH confidence)
- [aiomql Framework](https://github.com/Ichinga-Samuel/aiomql) -- Async MT5 wrapper architecture using `asyncio.to_thread()` pattern (HIGH confidence)
- [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) -- Deterministic event-driven trading engine architecture reference (MEDIUM confidence, different platform but validated patterns)
- [aiopubsub](https://pypi.org/project/aiopubsub/) -- Trading-specific async pub/sub library by Quantlane (MEDIUM confidence)
- [Event-Driven Architecture in Python for Trading](https://www.pyquantnews.com/free-python-resources/event-driven-architecture-in-python-for-trading) -- Event-driven trading engine patterns (MEDIUM confidence)
- [DuckDB vs SQLite Comparison](https://betterstack.com/community/guides/scaling-python/duckdb-vs-sqlite/) -- Dual-database strategy rationale (HIGH confidence)
- [MT5 Build 2815 Release Notes](https://www.metatrader5.com/en/releasenotes/terminal/2186) -- DOM access from Python added in this build (HIGH confidence)
- [MQL5 Named Pipe Communication](https://www.mql5.com/en/articles/503) -- DLL-free inter-process communication for watchdog EA (MEDIUM confidence)
- [Textual TUI Framework](https://textual.textualize.io/) -- Modern Python TUI with reactive widgets, suitable for real-time dashboard (HIGH confidence)
- [MQL5 Forum: MT5 Python Latency](https://www.mql5.com/en/forum/465784) -- Measured latency: ~17us for symbol_info_tick, 60-200ms for broker execution (MEDIUM confidence, community benchmarks)
- [MetaTrader-Python-Tick-Acquisition](https://github.com/UmaisZahid/MetaTrader-Python-Tick-Acquisition) -- Millisecond-precision tick bridge architecture reference (LOW confidence, single project)

---
*Architecture research for: Python-first XAUUSD scalping bot with 8 interconnected modules*
*Researched: 2026-03-27*
