# Phase 4: Observability and Self-Learning - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Build dual monitoring dashboards (rich terminal TUI + lightweight web) for real-time operator observability, and a self-learning mutation loop that evolves trading strategy parameters through genetic algorithms + ML, promoting improvements only after scientific walk-forward validation. The operator sees everything the bot does; the bot evolves what it does.

Requirements covered: OBS-01, OBS-02, OBS-03, OBS-04, OBS-05, LEARN-01, LEARN-02, LEARN-03, LEARN-04, LEARN-05, LEARN-06.

</domain>

<decisions>
## Implementation Decisions

### TUI Dashboard Design
- **D-01:** Single-screen panel layout — all key info visible at once without navigation. Fixed panels for: regime status, signal confidences (per-module bar chart), open position with live P&L, risk/circuit breaker status, and recent trades log. Like a trading terminal.
- **D-02:** Traffic-light regime color coding: green = trending (favorable), yellow = ranging (neutral), red = high-chaos/pre-bifurcation (danger). Aligns with D-06 from Phase 2 (reduced activity in danger zones).
- **D-03:** Mutation/adaptation events appear as highlighted rows inline in the recent trades/activity panel (OBS-03). No dedicated mutation panel — keeps layout compact.
- **D-04:** Kill switch button in TUI per Phase 1 D-09, plus compact order flow visualization: volume delta bar and bid-ask pressure indicator (OBS-02). Not a full order flow panel.
- **D-05:** 1-second refresh rate for regime, signals, P&L, and risk panels. Trades panel updates on events (trade open/close/mutation). Balances responsiveness with CPU usage.

### Web Dashboard
- **D-06:** Hybrid data delivery: WebSocket for live price/P&L/regime updates, REST endpoints for historical queries (trade history, equity curve data, configuration). FastAPI serves both.
- **D-07:** Four chart types: (1) equity curve with drawdown overlay, (2) XAUUSD candlestick chart with trade entry/exit markers (lightweight-charts), (3) color-coded regime timeline, (4) per-module accuracy/weight over time.
- **D-08:** Filterable trade history table with filters by date range, regime state, outcome (win/loss), and signal strength. Sortable columns. DuckDB serves the queries.
- **D-09:** Web dashboard includes kill switch and pause/resume buttons for remote intervention from any device on the local network. Read-only for everything else (no config editing from web).
- **D-10:** Web dashboard accessible from any device on the local network (OBS-05). FastAPI binds to 0.0.0.0 on a configurable port.

### Trade Context Logging
- **D-11:** Full snapshot logging per trade (LEARN-01): every signal module's raw output + confidence, fused score, regime state + confidence, position size, spread at entry, slippage, ATR, all fusion weights at decision time, hold duration, entry/exit prices, and outcome. ~20-30 fields per trade.
- **D-12:** Trade context stored in a new `trade_log` table in the existing DuckDB database. Consistent with tick storage pattern in `data/storage.py`. Analytical queries (regime performance, signal correlation) run natively. Parquet export for archival.
- **D-13:** Keep all trade logs forever. At scalping frequency (~5-20 trades/day), even years of data is <100MB in DuckDB. More data = better ML training. No automatic cleanup or retention window.

### Learning Loop Architecture
- **D-14:** Phase-aware fitness function mirroring the three-phase risk model:
  - Aggressive ($20-$100): Fitness = profit factor weighted higher. Reward growth, tolerate higher drawdown.
  - Selective ($100-$300): Fitness = Sharpe ratio. Balance growth with consistency, penalize variance.
  - Conservative ($300+): Fitness = Sharpe + max drawdown penalty combined. Capital preservation co-equal with returns.
- **D-15:** Genetic algorithm runs one evolution generation after every N trades (configurable, default 50-100). Ensures sufficient new data before evolving. ~1-2 generations per week at typical scalping frequency.
- **D-16:** GA evolves signal thresholds, SL/TP multipliers, regime behavior parameters, timeframe weights, and initial fusion weight seeds. Module internals (Hurst window, Lyapunov embedding dimension, fractal parameters) are fixed — those are physics, not strategy.

### Shadow Mode
- **D-17:** 3-5 mutated variants run in paper mode alongside the live strategy. Each variant processes the same market data, generates virtual trades with simulated fills. Reuses existing PaperExecutor from Phase 1.
- **D-18:** Promotion requires statistical significance: variant must outperform live on the phase-aware fitness metric over a minimum sample (50+ virtual trades) with p < 0.05. Walk-forward validation on recent windows must also pass (reuses Phase 3 validation). Prevents lucky streaks from promoting.

### Rule Retirement
- **D-19:** Gradual decay via EMA performance score (same pattern as AdaptiveWeightTracker in `signals/fusion/weights.py`). Below a minimum threshold after 50+ trades, rule is retired. Retired rules enter a cooldown pool — can be re-evolved with mutations later. Never permanently deleted.
- **D-20:** LEARN-05 signal combination analysis: learning loop tracks which signal combinations win above 70%, which regimes are most favorable, and which rules are degrading. Auto-retires underperformers per D-19.

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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Architecture
- `CLAUDE.md` — Full technology stack with version pins: Textual 8.1.1 for TUI, FastAPI 0.115+ for web, Rich 13.x for rendering, DEAP 1.4.3 for GA, scikit-learn 1.8.0 for ML, Optuna 4.8.0 for hyperparameter optimization, lightweight-charts-python 2.1 for financial charts, Plotly 5.x for analytical charts
- `.planning/PROJECT.md` — Eight module architecture, build approach, constraints
- `.planning/REQUIREMENTS.md` — OBS-01 through OBS-05, LEARN-01 through LEARN-06 requirement definitions

### Prior Phase Context
- `.planning/phases/01-trading-infrastructure/01-CONTEXT.md` — D-01 paper trading mode (reused by shadow mode), D-03 three-phase risk model (mirrored by D-14 fitness function), D-09 kill switch CLI + TUI, D-10 safety reset policy
- `.planning/phases/02-signal-pipeline-and-decision-fusion/02-CONTEXT.md` — D-01/D-02 confidence-weighted fusion and EMA weights (learning loop extends this), D-05 weights adapt from accuracy only, D-06 regime behavior mapping
- `.planning/phases/03-backtesting-and-validation/03-CONTEXT.md` — D-05/D-06 walk-forward validation windows and pass/fail criteria (LEARN-06 reuses this), D-07 Monte Carlo thresholds

### Existing Code
- `src/fxsoqqabot/logging/setup.py` — structlog configuration with contextvars, dual-mode rendering
- `src/fxsoqqabot/core/engine.py` — TradingEngine async architecture, component orchestration
- `src/fxsoqqabot/core/events.py` — EventType enum, frozen dataclass event types
- `src/fxsoqqabot/signals/fusion/weights.py` — AdaptiveWeightTracker EMA pattern (D-19 reuses this)
- `src/fxsoqqabot/signals/fusion/trade_manager.py` — TradeDecision dataclass, regime-aware execution
- `src/fxsoqqabot/execution/paper.py` — PaperExecutor for virtual fills (D-17 shadow mode reuses)
- `src/fxsoqqabot/data/storage.py` — DuckDB/Parquet tick storage pattern (D-12 extends)
- `src/fxsoqqabot/config/models.py` — Pydantic BotSettings, all configurable parameters
- `src/fxsoqqabot/cli.py` — argparse CLI with run/kill/status/reset subcommands
- `src/fxsoqqabot/backtest/validation.py` — Walk-forward validation (D-18 reuses)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **PaperExecutor** (`execution/paper.py`): Virtual fill simulation — shadow mode variants can each get their own PaperExecutor instance
- **AdaptiveWeightTracker** (`signals/fusion/weights.py`): EMA-based performance tracking pattern — rule retirement (D-19) mirrors this exact approach
- **structlog + contextvars** (`logging/setup.py`): Context propagation already configured — trade_id, regime_state can be bound once and flow through all modules
- **DuckDB storage** (`data/storage.py`): Parquet-backed analytical storage — trade_log table follows the same pattern
- **Walk-forward validation** (`backtest/validation.py`): Scientific validation infrastructure — promotion criteria (D-18) reuses this directly
- **EventType enum** (`core/events.py`): Extensible for learning events (MUTATION, RULE_RETIRED, VARIANT_PROMOTED)

### Established Patterns
- Frozen dataclasses with `__slots__` for all data structures (events, decisions, sizing results)
- Protocol-based structural typing for module interfaces (SignalModule, DataFeedProtocol)
- TYPE_CHECKING imports to avoid circular dependencies between modules
- asyncio.to_thread() for blocking computations (MT5 calls, numerical computation)
- Pydantic v2 models for all configuration with TOML loader
- Module-level structlog logger with `.bind(component="name")` for context

### Integration Points
- TUI hooks into TradingEngine's existing tick/bar/health loops for live data
- Web dashboard's FastAPI server runs as a parallel asyncio task alongside TradingEngine
- Trade context logger intercepts TradeDecision + fill result in TradeManager
- GA evolution triggered by trade_count threshold in the learning loop manager
- Shadow variants instantiate their own signal pipeline copies with mutated parameters

</code_context>

<specifics>
## Specific Ideas

- Phase-aware fitness function explicitly mirrors the three-phase risk model ($20-$100, $100-$300, $300+) — same phase boundaries, different optimization targets
- Shadow variants reuse the existing PaperExecutor infrastructure from Phase 1
- Rule retirement follows the same EMA decay pattern as AdaptiveWeightTracker
- Walk-forward validation from Phase 3 is the gatekeeper for variant promotion — no separate validation system

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-observability-and-self-learning*
*Context gathered: 2026-03-27*
