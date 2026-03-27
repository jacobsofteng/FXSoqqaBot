# Phase 4: Observability and Self-Learning - Research

**Researched:** 2026-03-27
**Domain:** TUI/Web dashboard observability + evolutionary self-learning loop
**Confidence:** HIGH

## Summary

Phase 4 adds two major capabilities to FXSoqqaBot: (1) dual monitoring dashboards -- a Textual-based terminal TUI for real-time operational monitoring and a FastAPI-served web dashboard for historical analysis accessible from any local network device, and (2) a self-learning mutation loop using DEAP genetic algorithms and scikit-learn ML classifiers that evolves trading strategy parameters, validates improvements through walk-forward testing, and retires underperforming rules.

The codebase is well-prepared for this phase. The TradingEngine already runs concurrent async loops (tick, bar, health, signal) via asyncio.gather -- the TUI and web server integrate as additional parallel tasks. The PaperExecutor provides virtual fill infrastructure for shadow mode variants. The AdaptiveWeightTracker establishes the EMA performance tracking pattern that rule retirement mirrors. The WalkForwardValidator provides the scientific validation gate for variant promotion. DuckDB/Parquet storage and structlog context propagation are in place for trade logging.

The primary architectural challenge is coordinating the learning loop lifecycle -- GA evolution should not block the trading engine's main loop. Running DEAP evolution in asyncio.to_thread() (matching the existing Numba computation pattern) is the correct approach. Shadow mode variants need independent copies of the signal pipeline with mutated parameters, each receiving the same market data but producing independent virtual trades via separate PaperExecutor instances.

**Primary recommendation:** Build the observability layer first (TUI + web dashboard + trade logging), then layer the self-learning loop on top, since the learning loop depends on logged trade context data and the dashboards need to display learning loop events.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Single-screen panel layout for TUI -- all key info visible at once without navigation. Fixed panels for: regime status, signal confidences (per-module bar chart), open position with live P&L, risk/circuit breaker status, and recent trades log.
- **D-02:** Traffic-light regime color coding: green = trending (favorable), yellow = ranging (neutral), red = high-chaos/pre-bifurcation (danger).
- **D-03:** Mutation/adaptation events appear as highlighted rows inline in the recent trades/activity panel (OBS-03). No dedicated mutation panel.
- **D-04:** Kill switch button in TUI per Phase 1 D-09, plus compact order flow visualization: volume delta bar and bid-ask pressure indicator (OBS-02).
- **D-05:** 1-second refresh rate for regime, signals, P&L, and risk panels. Trades panel updates on events.
- **D-06:** Hybrid data delivery: WebSocket for live price/P&L/regime updates, REST endpoints for historical queries. FastAPI serves both.
- **D-07:** Four chart types: (1) equity curve with drawdown overlay, (2) XAUUSD candlestick chart with trade entry/exit markers (lightweight-charts), (3) color-coded regime timeline, (4) per-module accuracy/weight over time.
- **D-08:** Filterable trade history table with filters by date range, regime state, outcome (win/loss), and signal strength. DuckDB serves the queries.
- **D-09:** Web dashboard includes kill switch and pause/resume buttons for remote intervention. Read-only for everything else.
- **D-10:** Web dashboard binds to 0.0.0.0 on configurable port for local network access (OBS-05).
- **D-11:** Full snapshot logging per trade (~20-30 fields): every signal module's raw output + confidence, fused score, regime state + confidence, position size, spread at entry, slippage, ATR, all fusion weights, hold duration, entry/exit prices, outcome.
- **D-12:** Trade context stored in a new `trade_log` table in the existing DuckDB database. Parquet export for archival.
- **D-13:** Keep all trade logs forever. No automatic cleanup.
- **D-14:** Phase-aware fitness function mirroring three-phase risk model: Aggressive = profit factor, Selective = Sharpe ratio, Conservative = Sharpe + max drawdown penalty.
- **D-15:** GA runs one generation after every N trades (configurable, default 50-100). ~1-2 generations per week.
- **D-16:** GA evolves signal thresholds, SL/TP multipliers, regime behavior parameters, timeframe weights, initial fusion weight seeds. Module internals are fixed.
- **D-17:** 3-5 mutated variants run in paper mode alongside live strategy using PaperExecutor.
- **D-18:** Promotion requires p < 0.05 statistical significance on phase-aware fitness over 50+ virtual trades. Walk-forward validation must also pass.
- **D-19:** Gradual decay via EMA performance score (same pattern as AdaptiveWeightTracker). Below minimum threshold after 50+ trades, rule is retired to cooldown pool. Never permanently deleted.
- **D-20:** Signal combination analysis: tracks which combos win above 70%, which regimes favorable, which rules degrading. Auto-retires underperformers.

### Claude's Discretion
- Textual widget selection and CSS styling for TUI panels
- FastAPI route structure and WebSocket message protocol
- lightweight-charts integration specifics for candlestick + trade markers
- DuckDB trade_log table schema design (column types, indexes)
- DEAP genetic programming configuration (population size, mutation rates, crossover operators)
- ML classifier choice for LEARN-03 (RandomForest vs XGBoost) and feature engineering
- Shadow mode resource management (CPU/memory budget for parallel variants)
- Walk-forward validation reuse pattern (import vs shared interface)
- Web dashboard frontend framework (vanilla JS, or minimal framework)
- Plotly vs lightweight-charts for non-candlestick charts (equity curve, regime timeline)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OBS-01 | Rich terminal TUI: regime (color-coded), signal confidences, open positions with live P&L, spread/slippage, circuit breaker status, daily stats | Textual 8.1.1 widgets (DataTable, Sparkline, Static, ProgressBar), reactive attributes, set_interval(1.0) for 1-second refresh per D-05 |
| OBS-02 | TUI order flow visualization: volume delta, bid-ask pressure, institutional flow direction | Sparkline widget for volume delta bar, Static with Rich Text for pressure indicators, compact inline rendering per D-04 |
| OBS-03 | TUI flags strategy mutation/adaptation events with what changed and why | Highlighted rows in DataTable activity panel per D-03, EventType enum extension for MUTATION/RULE_RETIRED/VARIANT_PROMOTED |
| OBS-04 | Web dashboard: equity curve, trade history filters, regime timeline, module performance | FastAPI + lightweight-charts-python for candlestick, Plotly for equity/regime/module charts, DuckDB queries for filtered trade history per D-07/D-08 |
| OBS-05 | Web dashboard accessible from any device on local network | FastAPI bind to 0.0.0.0 with configurable port per D-10, served by uvicorn |
| LEARN-01 | Full trade context logging: regime, signals, confidences, sizing, timing, outcome | New trade_log DuckDB table per D-12 with ~25 columns capturing full decision context per D-11 |
| LEARN-02 | GA evolves rule parameters using trade outcomes as fitness | DEAP 1.4.3 toolbox with phase-aware fitness (D-14), N-trade trigger (D-15), parameter bounds from D-16 |
| LEARN-03 | ML classifiers improve regime detection and win probability over time | scikit-learn 1.8.0 RandomForestClassifier trained on trade_log data, feature importance for signal combination analysis |
| LEARN-04 | Shadow mode: mutated variants run in parallel without risking capital | 3-5 ShadowVariant instances each with own PaperExecutor + signal pipeline copy per D-17, promotion via statistical test per D-18 |
| LEARN-05 | Learning loop identifies winning signal combos, favorable regimes, degrading rules -- auto-retires underperformers | EMA performance tracking per D-19/D-20, combination analysis from trade_log, automatic retirement with cooldown pool |
| LEARN-06 | Walk-forward validation prevents overfitting in evolved parameters | Reuse existing WalkForwardValidator from backtest/validation.py per D-18, apply to promoted variant parameters |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Python 3.12.x** -- not 3.13 or 3.15. pyproject.toml enforces `>=3.12,<3.13`.
- **Textual 8.1.1** for TUI, **Rich 13.x** for rendering, **FastAPI 0.115+** for web, **uvicorn 0.41.0** for ASGI server.
- **DEAP 1.4.3** for genetic algorithms, **scikit-learn 1.8.0** for ML classifiers, **Optuna 4.8.0** for hyperparameter optimization.
- **lightweight-charts-python 2.1** for TradingView-style financial charts, **Plotly 5.x** for analytical charts.
- **DuckDB 1.5.0 + Parquet** for analytics, **SQLite** for operational state -- already in codebase.
- **structlog 25.5.0** with contextvars for structured logging -- already configured.
- **Pydantic 2.12.5** for all configuration models -- existing pattern.
- **Frozen dataclasses with `__slots__`** for all data structures.
- **Protocol-based structural typing** for module interfaces (not ABC).
- **TYPE_CHECKING imports** to avoid circular dependencies.
- **asyncio.to_thread()** for blocking computations.
- **Module-level structlog logger** with `.bind(component="name")`.
- Do NOT use: TensorFlow, PyTorch, Streamlit, Redis, Celery, MongoDB.
- Do NOT use: Backtrader, TA-Lib.

## Standard Stack

### Core (New Dependencies for Phase 4)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **textual** | 8.1.1 | Rich terminal TUI with reactive widgets, CSS styling, async-first | Per CLAUDE.md. The dominant Python TUI framework. Supports DataTable, Sparkline, Static, RichLog, Button widgets. Reactive attributes auto-refresh on change. set_interval() for periodic updates. |
| **fastapi** | 0.115+ | WebSocket + REST API server for web dashboard | Per CLAUDE.md. Native WebSocket support via Starlette. Serves both real-time streams and historical query endpoints. |
| **uvicorn** | 0.41.0 | ASGI server for FastAPI | Per CLAUDE.md. Use `uvicorn[standard]` for performance. Single-worker sufficient for localhost. |
| **lightweight-charts** | 2.1 | TradingView-style candlestick charts with trade markers | Per CLAUDE.md. Python wrapper for Lightweight Charts JS. Supports live updates via `update()` and `update_from_tick()`. |
| **plotly** | 5.x | Equity curve, regime timeline, module performance charts | Per CLAUDE.md. Generates standalone HTML/JSON for web dashboard. Good for non-candlestick analytical visualizations. |
| **deap** | 1.4.3 | Genetic algorithm framework for strategy evolution | Per CLAUDE.md. Supports custom fitness functions, configurable operators (crossover, mutation, selection), multi-objective optimization via NSGA-II. |
| **scikit-learn** | 1.8.0 | RandomForest/GradientBoosting for regime classification improvement | Per CLAUDE.md. Feature importance for signal combination analysis. Robust cross-validation. |
| **optuna** | 4.8.0 | Bayesian hyperparameter optimization for GA meta-parameters | Per CLAUDE.md. TPE-based optimization with pruning. Complementary to DEAP -- Optuna tunes GA hyperparameters. |

### Already Installed (Reused from Earlier Phases)
| Library | Version | Purpose |
|---------|---------|---------|
| **duckdb** | 1.5.0 | Trade_log table, analytical queries for dashboard and learning loop |
| **structlog** | 25.5.0 | Context-propagating structured logging for trade context capture |
| **pydantic** | 2.12.5 | Configuration models for TUI, web, and learning loop settings |
| **rich** | 13.x | Console rendering engine (Textual dependency), log formatting |
| **numpy** | 2.4.3 | Array operations for statistical tests in learning loop |
| **scipy** | 1.17.1 | Statistical tests (scipy.stats.ttest_ind, mannwhitneyu) for promotion criteria |
| **pandas** | 2.2.x | DataFrame operations for trade log analysis and chart data prep |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Plotly for equity/regime charts | lightweight-charts for everything | Plotly is better for non-candlestick charts (overlaid equity + drawdown, heatmaps). lightweight-charts excels at financial OHLC but is limited for arbitrary analytical charts. Use both per their strengths. |
| RandomForest (LEARN-03) | XGBoost | XGBoost may slightly outperform but adds a C++ dependency (xgboost package). RandomForest from scikit-learn is already in the stack, simpler, and sufficient for regime classification with ~25 features. Start with RF, upgrade to XGBoost only if RF accuracy plateaus. |
| Vanilla JS for web frontend | React, Vue, Alpine.js | Vanilla JS avoids a build step and npm dependency chain. The web dashboard is a single-page read-only monitoring tool with 4-5 chart panels. Alpine.js could simplify reactivity if vanilla JS becomes unwieldy, but start with vanilla. |
| DEAP alone | Optuna alone | DEAP handles rule structure evolution (which parameters to tune, custom crossover). Optuna handles hyperparameter optimization (what values those parameters should have). They complement each other -- DEAP for the GA loop, Optuna for tuning the GA's own meta-parameters. |

**Installation (additions to pyproject.toml dependencies):**
```toml
# Phase 4 additions
"textual>=8.1",
"fastapi[standard]>=0.115",
"uvicorn[standard]>=0.41",
"lightweight-charts>=2.1",
"plotly>=5.0",
"deap>=1.4",
"scikit-learn>=1.8",
"optuna>=4.8",
```

## Architecture Patterns

### Recommended Project Structure (New Modules)
```
src/fxsoqqabot/
+-- dashboard/
|   +-- __init__.py
|   +-- tui/
|   |   +-- __init__.py
|   |   +-- app.py              # Textual App class, panel layout, CSS
|   |   +-- widgets.py          # Custom widgets: RegimePanel, SignalBars, PositionPanel
|   |   +-- styles.tcss         # Textual CSS stylesheet
|   +-- web/
|       +-- __init__.py
|       +-- server.py           # FastAPI app, WebSocket endpoints, REST routes
|       +-- static/             # HTML, JS, CSS for web frontend
|       |   +-- index.html
|       |   +-- dashboard.js
|       |   +-- styles.css
|       +-- charts.py           # Plotly chart generation helpers
+-- learning/
|   +-- __init__.py
|   +-- trade_logger.py         # Full context trade logging to DuckDB (LEARN-01)
|   +-- evolution.py            # DEAP GA evolution loop (LEARN-02)
|   +-- classifier.py           # ML regime improvement (LEARN-03)
|   +-- shadow.py               # Shadow mode variant management (LEARN-04)
|   +-- analyzer.py             # Signal combination analysis (LEARN-05)
|   +-- retirement.py           # Rule EMA tracking and retirement (LEARN-05/D-19)
+-- config/
|   +-- models.py               # Extended with TUIConfig, WebConfig, LearningConfig
```

### Pattern 1: TUI Integration via Shared State Object
**What:** TUI reads from a shared TradingEngineState dataclass that the engine updates. TUI never calls engine methods directly.
**When to use:** Always for TUI-to-engine data flow.
**Example:**
```python
@dataclass
class TradingEngineState:
    """Shared state snapshot for TUI consumption. Updated by engine, read by TUI."""
    regime: RegimeState = RegimeState.RANGING
    regime_confidence: float = 0.0
    signal_confidences: dict[str, float] = field(default_factory=dict)
    fusion_score: float = 0.0
    open_position: dict | None = None
    current_price: float = 0.0
    spread: float = 0.0
    equity: float = 0.0
    daily_pnl: float = 0.0
    breaker_status: dict[str, str] = field(default_factory=dict)
    recent_trades: list[dict] = field(default_factory=list)
    last_mutation_event: str = ""
    volume_delta: float = 0.0
    bid_pressure: float = 0.0
    ask_pressure: float = 0.0

# In TUI app:
class FXSoqqaBotTUI(App):
    def __init__(self, state: TradingEngineState):
        super().__init__()
        self._state = state

    def on_mount(self):
        self.set_interval(1.0, self._refresh_panels)  # D-05: 1-second refresh

    def _refresh_panels(self):
        # Read from shared state, update widgets
        regime_panel = self.query_one("#regime", Static)
        regime_panel.update(self._format_regime(self._state.regime))
```

### Pattern 2: Web Dashboard WebSocket Protocol
**What:** FastAPI WebSocket pushes JSON state updates; REST serves historical queries.
**When to use:** For web dashboard real-time updates (D-06).
**Example:**
```python
from fastapi import FastAPI, WebSocket
import asyncio

app = FastAPI()

@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            state_snapshot = engine_state.to_dict()  # Read shared state
            await websocket.send_json(state_snapshot)
            await asyncio.sleep(1.0)  # Match TUI refresh rate
    except WebSocketDisconnect:
        pass

@app.get("/api/trades")
async def get_trades(
    regime: str | None = None,
    outcome: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    min_confidence: float | None = None,
):
    """Filtered trade history from DuckDB per D-08."""
    # Build DuckDB query with filters
    ...
```

### Pattern 3: GA Evolution in Background Thread
**What:** DEAP evolution runs in asyncio.to_thread() to avoid blocking the trading loop.
**When to use:** When GA generation is triggered after N trades (D-15).
**Example:**
```python
import asyncio
from deap import base, creator, tools, algorithms

class EvolutionManager:
    def __init__(self, config: LearningConfig):
        self._trade_count_since_evolve = 0
        self._evolve_threshold = config.evolve_every_n_trades  # D-15: 50-100

    async def on_trade_closed(self, trade_context: dict):
        self._trade_count_since_evolve += 1
        if self._trade_count_since_evolve >= self._evolve_threshold:
            # Run GA in thread to avoid blocking (same pattern as Numba computations)
            await asyncio.to_thread(self._run_generation)
            self._trade_count_since_evolve = 0

    def _run_generation(self):
        """Blocking DEAP evolution -- runs in thread."""
        offspring = algorithms.varAnd(self._population, self._toolbox, cxpb=0.5, mutpb=0.2)
        fitnesses = map(self._toolbox.evaluate, offspring)
        for ind, fit in zip(offspring, fitnesses):
            ind.fitness.values = fit
        self._population = self._toolbox.select(offspring, k=len(self._population))
```

### Pattern 4: Shadow Mode Variant Architecture
**What:** Each shadow variant gets independent signal pipeline copies with mutated parameters, sharing the same market data feed.
**When to use:** For LEARN-04 shadow mode (D-17).
**Example:**
```python
@dataclass
class ShadowVariant:
    """A mutated strategy variant running in paper mode alongside live."""
    variant_id: str
    mutated_params: dict[str, float]  # Parameter overrides
    paper_executor: PaperExecutor      # Own PaperExecutor instance
    trade_count: int = 0
    fitness_score: float = 0.0

class ShadowManager:
    def __init__(self, n_variants: int = 5):
        self._variants: list[ShadowVariant] = []
        # Each variant gets its own PaperExecutor and mutated config
        for i in range(n_variants):
            variant = ShadowVariant(
                variant_id=f"shadow_{i}",
                mutated_params=self._generate_mutations(),
                paper_executor=PaperExecutor(starting_balance=20.0),
            )
            self._variants.append(variant)

    async def process_market_data(self, tick_arrays, bar_arrays):
        """Feed same market data to all variants for virtual trade decisions."""
        for variant in self._variants:
            # Each variant runs its own signal pipeline with mutated parameters
            await self._evaluate_variant(variant, tick_arrays, bar_arrays)
```

### Pattern 5: Trade Context Logger Interceptor
**What:** Intercept TradeDecision + FillEvent in TradeManager to log full context to DuckDB.
**When to use:** For LEARN-01 (D-11/D-12).
**Example:**
```python
class TradeContextLogger:
    """Captures full trade context for DuckDB trade_log table per D-11."""

    def __init__(self, storage: TickStorage):
        self._db = storage  # Reuse existing DuckDB connection

    def log_trade(
        self,
        decision: TradeDecision,
        fill: FillEvent,
        signals: list[SignalOutput],
        fusion_result: FusionResult,
        weights: dict[str, float],
        equity: float,
        atr: float,
    ) -> None:
        """Log full snapshot: ~25 columns per D-11."""
        record = {
            "timestamp": fill.timestamp.isoformat(),
            "ticket": fill.ticket,
            "action": decision.action,
            "regime": decision.regime.value,
            "regime_confidence": ...,  # From chaos module signal
            "fused_confidence": fusion_result.fused_confidence,
            "composite_score": fusion_result.composite_score,
            # Per-module signals
            "chaos_direction": ...,
            "chaos_confidence": ...,
            "flow_direction": ...,
            "flow_confidence": ...,
            "timing_direction": ...,
            "timing_confidence": ...,
            # Weights at decision time
            "weight_chaos": weights.get("chaos", 0),
            "weight_flow": weights.get("flow", 0),
            "weight_timing": weights.get("timing", 0),
            # Execution details
            "lot_size": decision.lot_size,
            "sl_distance": decision.sl_distance,
            "tp_distance": decision.tp_distance,
            "entry_price": fill.fill_price,
            "spread_at_entry": fill.fill_price - fill.requested_price,
            "slippage": fill.slippage,
            "atr": atr,
            "equity": equity,
            # Outcome (filled on close)
            "exit_price": None,
            "pnl": None,
            "hold_duration_s": None,
        }
        self._db.execute("INSERT INTO trade_log ...")
```

### Anti-Patterns to Avoid
- **Direct engine calls from TUI/web:** Never call engine methods from dashboard code. Use a shared state object that the engine writes and dashboards read. This avoids threading issues and keeps concerns separated.
- **Blocking GA in the event loop:** DEAP's evolution loop is CPU-intensive. Always run in asyncio.to_thread(). The codebase already uses this pattern for Numba computations and MT5 calls.
- **Shared PaperExecutor between shadow variants:** Each variant MUST have its own PaperExecutor instance. Shared state would corrupt virtual trade tracking.
- **Evolving module internals:** Per D-16, only evolve strategy parameters (thresholds, multipliers, weights). Module internals (Hurst window, Lyapunov embedding, fractal parameters) are physics -- fixed.
- **Promoting without statistical significance:** Per D-18, variant promotion requires p < 0.05 over 50+ virtual trades AND walk-forward validation pass. Lucky streaks must not cause promotion.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Genetic algorithm framework | Custom crossover/mutation/selection | DEAP 1.4.3 | Mature toolbox pattern with pluggable operators. Custom GA implementations miss edge cases (elitism, bloat control, fitness sharing). DEAP handles all of these. |
| Terminal UI framework | Manual curses/ANSI | Textual 8.1.1 | CSS-like styling, reactive attributes, widget library, async-first. Building a multi-panel dashboard with curses would be 10x more code. |
| Financial candlestick charts | Custom canvas rendering | lightweight-charts-python 2.1 | TradingView's chart library handles zoom, crosshair, OHLC rendering, trade markers. Custom canvas charting is thousands of lines for inferior results. |
| Analytical charts | Custom SVG/matplotlib | Plotly 5.x | Interactive charts with hover, zoom, overlays. Equity curves with drawdown overlay would be painful with matplotlib for web embedding. |
| WebSocket server | Raw asyncio sockets | FastAPI WebSocket | Connection management, JSON serialization, route dispatching, error handling all built-in. Raw sockets require all of this manually. |
| Statistical significance tests | Custom p-value computation | scipy.stats.mannwhitneyu | Mann-Whitney U test is the correct non-parametric test for comparing two strategy fitness distributions. Custom implementations risk mathematical errors. |
| Walk-forward validation | New validation system | Existing WalkForwardValidator | Per D-18: reuse the Phase 3 validation infrastructure. Building a parallel system contradicts the principle of shared code paths (TEST-07). |

**Key insight:** Phase 4's value is in the integration architecture, not in reimplementing components. Every major capability has a mature library. The complexity is in wiring them together correctly: shared state for dashboards, thread-safe GA evolution, clean variant lifecycle management, and statistical rigor in the promotion pipeline.

## Common Pitfalls

### Pitfall 1: TUI Blocking the Event Loop
**What goes wrong:** Textual App.run() blocks the main thread, preventing the trading engine from running.
**Why it happens:** Textual needs its own event loop management. Running both Textual and asyncio.gather() for engine loops naively will conflict.
**How to avoid:** Run the TUI and engine in separate asyncio tasks within the same event loop. Textual supports `run_async()` which returns a coroutine. Include the TUI coroutine in the engine's `asyncio.gather()`. Alternatively, run the Textual app as the main loop and start the engine as a worker.
**Warning signs:** TUI appears but engine loops never start, or engine runs but TUI is frozen.

### Pitfall 2: Race Conditions in Shared State
**What goes wrong:** TUI reads partially-updated state while engine is writing, causing garbled display or crashes.
**Why it happens:** The TradingEngineState dataclass is written by the engine loop and read by TUI at 1-second intervals. Without synchronization, reads and writes can interleave.
**How to avoid:** Use a simple pattern: engine writes a complete new snapshot atomically (replace the reference, not mutate fields individually). Python's GIL makes reference assignment atomic. Alternatively, use asyncio.Lock for fine-grained field updates. Given 1-second refresh and single writer, atomic snapshot replacement is sufficient and simpler.
**Warning signs:** Occasionally seeing stale or inconsistent data combinations (e.g., new regime with old confidence).

### Pitfall 3: GA Overfitting to Recent Trades
**What goes wrong:** Evolved parameters work well on the last 50-100 trades but fail on different market conditions.
**Why it happens:** GA fitness computed only on recent trade outcomes. If the recent window was trending, evolved parameters optimize for trending. When market switches to ranging, they fail.
**How to avoid:** D-18's walk-forward validation is the key defense. Also: D-14's phase-aware fitness includes Sharpe ratio (not just profit factor), which penalizes inconsistency. The promotion gate requires both statistical significance AND walk-forward pass. Additionally, D-19's gradual EMA retirement will catch parameters that worked temporarily.
**Warning signs:** Promoted variants degrade within 1-2 weeks. High promotion rate followed by high retirement rate.

### Pitfall 4: Shadow Mode Memory/CPU Explosion
**What goes wrong:** Running 5 shadow variants each with full signal pipeline copies exhausts memory or slows the main trading loop.
**Why it happens:** Each variant needs ChaosRegimeModule, OrderFlowModule, QuantumTimingModule instances (Numba JIT caches, numpy arrays). 5 copies multiply memory usage.
**How to avoid:** Share immutable market data (tick_arrays, bar_arrays are numpy arrays, not copied). Only duplicate the signal processing and fusion layers with different parameters. Limit variant count to 3-5 (D-17). Run variant evaluation in a single asyncio.to_thread() call, not 5 separate threads. Profile memory: each variant should add <50MB.
**Warning signs:** System memory usage growing linearly with variant count. Main loop tick processing slowing down.

### Pitfall 5: DuckDB Write Contention
**What goes wrong:** Concurrent writes to DuckDB from trade logger, dashboard queries, and tick storage cause lock timeouts.
**Why it happens:** DuckDB supports multiple concurrent readers but only one writer at a time. If tick storage, trade context logging, and web dashboard queries all hit the same database, writes may contend.
**How to avoid:** Use separate DuckDB connections for read-only dashboard queries (DuckDB supports this). Batch trade log writes (one INSERT per trade, not per tick). Consider a separate DuckDB file for trade_log if contention is observed. The existing analytics.duckdb handles tick storage; adding trade_log to the same file is fine given low write frequency (~5-20 trades/day).
**Warning signs:** DuckDB "database is locked" errors in logs. Dashboard queries timing out.

### Pitfall 6: Textual Widget Update from Non-Main Thread
**What goes wrong:** Updating Textual widgets from a worker thread causes crashes or silent failures.
**Why it happens:** Textual widgets must be updated from the main thread (same as most GUI frameworks). If the engine runs in a different thread and tries to update widgets directly, it will fail.
**How to avoid:** Use Textual's `App.call_from_thread()` for thread-safe updates, or better yet, use the shared state pattern (Pattern 1) where the TUI reads state via set_interval() on the main thread. The engine writes state; the TUI polls it.
**Warning signs:** "RuntimeError: widget update outside main thread" or similar. Widgets not updating despite state changes.

### Pitfall 7: Web Dashboard Security on Local Network
**What goes wrong:** Binding to 0.0.0.0 exposes the dashboard (including kill switch) to anyone on the local network.
**Why it happens:** D-09 requires kill switch and pause/resume in the web dashboard. D-10 requires 0.0.0.0 binding for local network access.
**How to avoid:** Add a simple bearer token or API key for write operations (kill, pause, resume). Read-only dashboard access can remain unauthenticated since it's local network only. Store the API key in the TOML config per CONF-01 pattern. Log all kill switch activations.
**Warning signs:** Unauthorized kill switch activations. Any device on the network can halt trading.

### Pitfall 8: DEAP Fitness Function Must Return Tuple
**What goes wrong:** Fitness function returns a float instead of a tuple, causing cryptic DEAP errors.
**Why it happens:** DEAP requires fitness values as tuples (even for single-objective optimization) to support multi-objective. `weights=(1.0,)` means maximizing a single-element tuple.
**How to avoid:** Always return a tuple from the fitness function: `return (sharpe_ratio,)` not `return sharpe_ratio`. This is a well-known DEAP gotcha.
**Warning signs:** "TypeError: iteration over a 0-d array" or "fitness must be a sequence" errors from DEAP.

## Code Examples

### TUI App Layout with Textual
```python
# Source: Textual official docs pattern + project conventions
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, DataTable, Sparkline, Button, RichLog

class FXSoqqaBotTUI(App):
    """Single-screen dashboard per D-01."""

    CSS_PATH = "styles.tcss"  # Textual CSS file

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="left-panel"):
                yield Static(id="regime-panel", classes="panel")        # D-02 color-coded regime
                yield Static(id="signals-panel", classes="panel")       # Per-module confidences
                yield Static(id="order-flow-panel", classes="panel")    # D-04 volume delta + pressure
            with Vertical(id="center-panel"):
                yield Static(id="position-panel", classes="panel")      # Open position + P&L
                yield Static(id="risk-panel", classes="panel")          # Circuit breaker status
                yield DataTable(id="trades-table", classes="panel")     # Recent trades + mutations
            with Vertical(id="right-panel"):
                yield Static(id="stats-panel", classes="panel")         # Daily stats
                yield Sparkline(id="equity-spark", classes="panel")     # Mini equity sparkline
                yield Button("KILL", id="kill-btn", variant="error")    # D-04 kill switch
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(1.0, self._refresh_all)  # D-05: 1-second refresh

    def _refresh_all(self) -> None:
        """Read from shared TradingEngineState and update all panels."""
        state = self._engine_state

        # Regime panel with traffic-light colors (D-02)
        regime_colors = {
            "trending_up": "green", "trending_down": "green",
            "ranging": "yellow",
            "high_chaos": "red", "pre_bifurcation": "red",
        }
        color = regime_colors.get(state.regime.value, "white")
        self.query_one("#regime-panel", Static).update(
            f"[bold {color}]Regime: {state.regime.value}[/] ({state.regime_confidence:.0%})"
        )
```

### Textual CSS Stylesheet
```css
/* styles.tcss -- Textual CSS for TUI layout */
Screen {
    layout: horizontal;
}

#left-panel, #center-panel, #right-panel {
    width: 1fr;
    height: 100%;
}

.panel {
    border: solid $accent;
    margin: 1;
    padding: 1;
}

#regime-panel {
    height: 3;
}

#kill-btn {
    dock: bottom;
    width: 100%;
}

#trades-table {
    height: 1fr;
}
```

### DuckDB Trade Log Schema
```python
# Source: Existing data/storage.py pattern extended for LEARN-01 / D-11/D-12
def _init_trade_log_table(self) -> None:
    """Create trade_log table with full context per D-11."""
    self._db.execute("""
        CREATE TABLE IF NOT EXISTS trade_log (
            -- Identity
            trade_id INTEGER PRIMARY KEY,
            ticket BIGINT,
            timestamp TIMESTAMP,

            -- Trade action
            action VARCHAR,             -- buy/sell
            entry_price DOUBLE,
            exit_price DOUBLE,
            lot_size DOUBLE,
            sl_distance DOUBLE,
            tp_distance DOUBLE,

            -- Regime state
            regime VARCHAR,
            regime_confidence DOUBLE,

            -- Per-module signals (raw)
            chaos_direction DOUBLE,
            chaos_confidence DOUBLE,
            flow_direction DOUBLE,
            flow_confidence DOUBLE,
            timing_direction DOUBLE,
            timing_confidence DOUBLE,

            -- Fusion output
            composite_score DOUBLE,
            fused_confidence DOUBLE,
            confidence_threshold DOUBLE,

            -- Weights at decision time
            weight_chaos DOUBLE,
            weight_flow DOUBLE,
            weight_timing DOUBLE,

            -- Market conditions
            atr DOUBLE,
            spread_at_entry DOUBLE,
            slippage DOUBLE,
            equity_at_trade DOUBLE,

            -- Outcome (updated on close)
            pnl DOUBLE,
            hold_duration_seconds DOUBLE,
            exit_regime VARCHAR,
            is_paper BOOLEAN DEFAULT FALSE,

            -- Variant tracking (shadow mode)
            variant_id VARCHAR DEFAULT 'live'
        )
    """)
```

### DEAP GA Setup for Strategy Evolution
```python
# Source: DEAP official docs pattern adapted for D-14/D-15/D-16
from deap import base, creator, tools, algorithms
import random

# D-14: Fitness maximizes phase-aware metric (Sharpe for selective phase)
creator.create("FitnessMax", base.Fitness, weights=(1.0,))
creator.create("Individual", list, fitness=creator.FitnessMax)

# D-16: Define parameter bounds (what GA evolves)
PARAM_BOUNDS = {
    "aggressive_confidence_threshold": (0.3, 0.7),
    "selective_confidence_threshold":  (0.4, 0.8),
    "conservative_confidence_threshold": (0.5, 0.9),
    "sl_atr_base_multiplier": (1.0, 4.0),
    "trending_rr_ratio": (1.5, 5.0),
    "ranging_rr_ratio": (1.0, 3.0),
    "high_chaos_size_reduction": (0.2, 0.8),
    "weight_chaos_seed": (0.1, 0.5),
    "weight_flow_seed": (0.1, 0.5),
    "weight_timing_seed": (0.1, 0.5),
}

toolbox = base.Toolbox()
toolbox.register("individual", _create_individual)  # Random within bounds
toolbox.register("population", tools.initRepeat, list, toolbox.individual)
toolbox.register("evaluate", _phase_aware_fitness)   # D-14 fitness function
toolbox.register("mate", tools.cxBlend, alpha=0.5)   # Blend crossover for float params
toolbox.register("mutate", tools.mutGaussian, mu=0, sigma=0.1, indpb=0.2)
toolbox.register("select", tools.selTournament, tournsize=3)

def _phase_aware_fitness(individual: list, trade_log: list[dict], equity: float) -> tuple[float]:
    """D-14: Fitness depends on capital phase."""
    # Apply individual's parameters to compute virtual trades
    if equity < 100:  # Aggressive
        return (compute_profit_factor(trade_log),)
    elif equity < 300:  # Selective
        return (compute_sharpe_ratio(trade_log),)
    else:  # Conservative
        sharpe = compute_sharpe_ratio(trade_log)
        dd_penalty = compute_max_drawdown_penalty(trade_log)
        return (sharpe - dd_penalty,)
```

### Shadow Mode Promotion with Statistical Test
```python
# Source: scipy.stats for D-18 statistical significance
from scipy import stats

def evaluate_promotion(
    live_trades: list[dict],
    variant_trades: list[dict],
    fitness_fn: callable,
    alpha: float = 0.05,    # D-18: p < 0.05
    min_trades: int = 50,   # D-18: minimum 50 virtual trades
) -> bool:
    """D-18: Test if variant significantly outperforms live."""
    if len(variant_trades) < min_trades:
        return False

    live_fitness = [fitness_fn(t) for t in live_trades]
    variant_fitness = [fitness_fn(t) for t in variant_trades]

    # Mann-Whitney U test (non-parametric, no normality assumption)
    statistic, p_value = stats.mannwhitneyu(
        variant_fitness, live_fitness, alternative="greater"
    )

    return p_value < alpha
```

### FastAPI Web Server with WebSocket + REST
```python
# Source: FastAPI official docs pattern adapted for D-06/D-07/D-08/D-09/D-10
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import asyncio

app = FastAPI(title="FXSoqqaBot Dashboard")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    """D-06: WebSocket for live price/P&L/regime updates."""
    await websocket.accept()
    try:
        while True:
            snapshot = engine_state.to_dict()
            await websocket.send_json(snapshot)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass

@app.get("/api/trades")
async def get_trades(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    regime: str | None = Query(None),
    outcome: str | None = Query(None),
    min_confidence: float | None = Query(None),
    limit: int = Query(100),
):
    """D-08: Filterable trade history from DuckDB."""
    conditions = ["1=1"]
    params = []
    if regime:
        conditions.append("regime = ?")
        params.append(regime)
    if outcome == "win":
        conditions.append("pnl > 0")
    elif outcome == "loss":
        conditions.append("pnl < 0")
    # ... more filters
    query = f"SELECT * FROM trade_log WHERE {' AND '.join(conditions)} ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    return db.execute(query, params).fetchdf().to_dict(orient="records")

@app.post("/api/kill")
async def kill_switch(api_key: str = Query(...)):
    """D-09: Remote kill switch with API key auth."""
    if api_key != config.web_api_key:
        raise HTTPException(403, "Invalid API key")
    await engine.kill_switch.activate()
    return {"status": "killed"}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| curses/urwid for TUI | Textual with CSS-like styling | 2023-2024 | 5-10x less code for equivalent dashboard. Reactive attributes, async-first. |
| Backtrader for backtesting | vectorbt + custom (already done) | 2023 | Backtrader abandoned. Already addressed in Phase 3. |
| Manual parameter tuning | DEAP GA + Optuna Bayesian | Mature | Automated exploration of parameter space with scientific validation gates. |
| Flask/Django for API | FastAPI async-first | 2020+ | Native WebSocket, async, type hints, auto-docs. Standard for Python APIs in 2026. |
| matplotlib for web charts | Plotly + lightweight-charts | 2022+ | Interactive, embeddable HTML. No backend rendering needed. |

**Deprecated/outdated:**
- **curses**: Low-level, painful for complex layouts. Textual is the standard replacement.
- **Flask-SocketIO**: Flask is sync-first. FastAPI with native WebSocket is simpler and faster.
- **Backtrader**: Effectively abandoned. Already replaced in Phase 3.

## Open Questions

1. **lightweight-charts-python web serving model**
   - What we know: The library can generate chart HTML/JS. There's a `lightweight-charts-server` package for server integration.
   - What's unclear: The exact pattern for embedding lightweight-charts in a FastAPI-served page with WebSocket live updates. The library's native `show()` opens a browser window, which is not what we want for a web dashboard.
   - Recommendation: Generate the chart configuration as JSON from Python. Serve a static HTML page that includes the TradingView Lightweight Charts JS library directly (CDN or bundled). FastAPI serves the page + WebSocket data. The JS frontend creates the chart and updates it from WebSocket data. This bypasses the Python wrapper's display model entirely for the web dashboard.

2. **Textual + TradingEngine coexistence in one process**
   - What we know: Textual has `run_async()` and worker support. TradingEngine uses asyncio.gather() for its loops.
   - What's unclear: Whether Textual's event loop management conflicts with the engine's asyncio.gather().
   - Recommendation: Two options: (a) Textual App as the main loop with engine started as a Textual worker, or (b) engine as the main loop with TUI launched via separate `asyncio.create_task()`. Option (a) is cleaner since Textual manages the event loop and the engine just needs its coroutines scheduled.

3. **Shadow variant signal pipeline weight**
   - What we know: Each variant needs independent signal processing with mutated parameters. D-17 specifies 3-5 variants.
   - What's unclear: Whether creating 3-5 full ChaosRegimeModule copies (with Numba JIT) will cause excessive memory usage.
   - Recommendation: Share the raw computation results (Hurst, Lyapunov, etc. are physics -- same across variants per D-16) and only duplicate the fusion/decision layer with different parameters. This reduces per-variant overhead from ~100MB to ~10MB.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12.x | All | NOT DETECTED (3.15.0a1 found) | 3.15.0a1 | Must install Python 3.12 per pyproject.toml constraint |
| textual | TUI dashboard | Not installed | -- | Must install via uv |
| fastapi | Web dashboard | Not installed | -- | Must install via uv |
| uvicorn | Web dashboard | Not installed | -- | Must install via uv |
| lightweight-charts | Web candlestick | Not installed | -- | Must install via uv |
| plotly | Web analytical charts | Not installed | -- | Must install via uv |
| deap | GA evolution | Not installed | -- | Must install via uv |
| scikit-learn | ML classifiers | Not installed | -- | Must install via uv |
| optuna | Hyperparameter tuning | Not installed | -- | Must install via uv |
| duckdb | Trade logging | In pyproject.toml | 1.5.0 | Already a dependency |
| structlog | Context logging | In pyproject.toml | 25.5.0 | Already a dependency |
| scipy | Statistical tests | In pyproject.toml | 1.17.1 | Already a dependency |
| rich | TUI rendering base | In pyproject.toml | 13.x | Already a dependency |

**Missing dependencies with no fallback:**
- Python 3.12.x runtime (system has 3.15.0a1 -- the .venv likely has 3.12 per pyproject.toml, but system Python does not match)

**Missing dependencies with fallback:**
- All Phase 4 packages (textual, fastapi, deap, etc.) need to be added to pyproject.toml and installed. This is expected -- they are new for this phase.

**Note:** The project uses `uv` for package management with a lockfile. Phase 4's first task should add the new dependencies to pyproject.toml and run `uv sync`.

## Sources

### Primary (HIGH confidence)
- [Textual official docs](https://textual.textualize.io/) -- Widget library, reactive system, CSS styling, workers, set_interval
- [Textual DataTable](https://textual.textualize.io/widgets/data_table/) -- update_cell, add_row, cursor modes
- [Textual Sparkline](https://textual.textualize.io/widgets/sparkline/) -- Reactive data attribute, min/max colors
- [Textual Workers](https://textual.textualize.io/guide/workers/) -- Thread workers, call_from_thread, run_async
- [FastAPI WebSocket docs](https://fastapi.tiangolo.com/advanced/websockets/) -- WebSocket endpoint pattern
- [DEAP GitHub](https://github.com/DEAP/deap) -- creator/base/tools/algorithms pattern, fitness tuples
- [lightweight-charts-python GitHub](https://github.com/louisnw01/lightweight-charts-python) -- Chart creation, live updates, multi-pane, asyncio support
- [scikit-learn feature importance](https://scikit-learn.org/stable/auto_examples/ensemble/plot_forest_importances.html) -- RandomForest feature_importances_, permutation importance

### Secondary (MEDIUM confidence)
- [FastAPI real-time dashboard patterns](https://testdriven.io/blog/fastapi-postgres-websockets/) -- WebSocket fan-out, heartbeat, backpressure recipes
- [DEAP GA for trading optimization](https://medium.com/towards-artificial-intelligence/genetic-algorithm-for-trading-strategy-optimization-in-python-614eb660990d) -- Fitness function patterns for trading strategy parameters
- [MarkTechPost Textual dashboard](https://www.marktechpost.com/2025/11/15/how-to-design-a-fully-interactive-reactive-and-dynamic-terminal-based-data-dashboard-using-textual/) -- Reactive StatsCard pattern, set_interval for live updates

### Tertiary (LOW confidence)
- [lightweight-charts-server PyPI](https://pypi.org/project/lightweight-charts-server/) -- Server integration for lightweight-charts (View + Stream modes). Needs validation for FastAPI integration pattern.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries are locked in CLAUDE.md with specific versions. No decision needed, only research integration patterns.
- Architecture: HIGH -- codebase patterns are well-established (frozen dataclasses, Protocol typing, asyncio.to_thread, structlog context). Phase 4 extends these patterns to new modules.
- Pitfalls: HIGH -- identified from direct codebase analysis (threading model, DuckDB concurrency, Textual event loop, DEAP fitness tuples) and cross-verified with official docs.
- Integration points: HIGH -- all reusable assets (PaperExecutor, AdaptiveWeightTracker, WalkForwardValidator, TickStorage, StateManager) were read and interface contracts are documented.

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable libraries, locked versions)
