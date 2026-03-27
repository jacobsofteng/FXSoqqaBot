# Phase 4: Observability and Self-Learning - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 04-observability-and-self-learning
**Areas discussed:** TUI Dashboard Design, Web Dashboard Scope, Trade Context Logging, Learning Loop Design

---

## TUI Dashboard Design

### Layout Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Single-screen panels | All key info visible at once in fixed panels — like a trading terminal | :heavy_check_mark: |
| Tabbed views | Separate tabs for Overview, Signals, Trades, Risk, Logs | |
| Scrollable single page | Vertically scrollable with all sections stacked | |

**User's choice:** Single-screen panels
**Notes:** ASCII mockup provided showing regime, signals, position, risk, and recent trades panels.

### Regime Color Coding

| Option | Description | Selected |
|--------|-------------|----------|
| Traffic-light scheme | Green=trending, Yellow=ranging, Red=high-chaos/pre-bifurcation | :heavy_check_mark: |
| Spectrum scheme | Unique color per regime (blue, cyan, yellow, magenta, red) | |
| You decide | Claude picks based on Textual capabilities | |

**User's choice:** Traffic-light scheme
**Notes:** None

### Mutation Log Display (OBS-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Inline alerts in trades panel | Mutation events as highlighted rows in activity panel | :heavy_check_mark: |
| Dedicated mutation panel | Separate panel with mutation history | |
| Status bar notifications | Brief flash in status bar | |

**User's choice:** Inline alerts in trades panel
**Notes:** None

### TUI Extras

| Option | Description | Selected |
|--------|-------------|----------|
| Kill switch + basic flow viz | Kill button + compact volume delta bar and bid-ask pressure | :heavy_check_mark: |
| Full order flow panel | Dedicated panel with volume delta chart and heatmap | |
| Kill switch only | Kill button, no flow viz in TUI | |

**User's choice:** Kill switch + basic flow viz
**Notes:** None

### Refresh Rate

| Option | Description | Selected |
|--------|-------------|----------|
| 1-second updates | Regime, signals, P&L, risk update every 1s; trades on events | :heavy_check_mark: |
| Sub-second (250ms) | Quarter-second updates for near-real-time feel | |
| You decide | Claude picks per-panel refresh intervals | |

**User's choice:** 1-second updates
**Notes:** None

---

## Web Dashboard Scope

### Data Delivery

| Option | Description | Selected |
|--------|-------------|----------|
| WebSocket streaming | Pure WebSocket push for all live data | |
| Auto-refresh polling | REST endpoints polled every 5-10 seconds | |
| Hybrid | WebSocket for live price/P&L, REST for historical queries | :heavy_check_mark: |

**User's choice:** Hybrid
**Notes:** None

### Charts (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| Equity curve | Running equity over time with drawdown overlay | :heavy_check_mark: |
| Candlestick with trades | XAUUSD price chart with entry/exit markers | :heavy_check_mark: |
| Regime timeline | Color-coded bar showing regime state over time | :heavy_check_mark: |
| Module performance | Per-module accuracy/weight over time | :heavy_check_mark: |

**User's choice:** All four charts
**Notes:** None

### Trade Filtering

| Option | Description | Selected |
|--------|-------------|----------|
| Filterable table | Filters by date, regime, outcome, signal strength; sortable | :heavy_check_mark: |
| Simple chronological list | Reverse chronological, no filtering | |
| You decide | Claude designs based on DuckDB capabilities | |

**User's choice:** Filterable table
**Notes:** None

### Interactive Controls

| Option | Description | Selected |
|--------|-------------|----------|
| Read-only monitoring | Pure observation, all control in CLI/TUI | |
| Kill switch + pause | Emergency kill and pause/resume from web | :heavy_check_mark: |
| Full control panel | Config editing + kill + pause from web | |

**User's choice:** Kill switch + pause
**Notes:** None

---

## Trade Context Logging

### Log Depth (LEARN-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Full snapshot | ~20-30 fields: all module outputs, fusion weights, regime, sizing, timing, outcome | :heavy_check_mark: |
| Summary only | ~10 fields: fused direction, confidence, regime, prices, P&L | |
| Full + tick context | Full snapshot + raw tick window around entry/exit | |

**User's choice:** Full snapshot
**Notes:** None

### Storage

| Option | Description | Selected |
|--------|-------------|----------|
| DuckDB trade_log table | New table in existing DuckDB, consistent with tick storage | :heavy_check_mark: |
| Separate SQLite database | Dedicated trade journal DB | |
| You decide | Claude picks based on existing patterns | |

**User's choice:** DuckDB trade_log table
**Notes:** None

### Retention

| Option | Description | Selected |
|--------|-------------|----------|
| Keep everything | Never delete; <100MB for years of data | :heavy_check_mark: |
| Rolling window | Keep 6-12 months, archive older to Parquet | |
| You decide | Claude determines based on data volumes | |

**User's choice:** Keep everything
**Notes:** None

---

## Learning Loop Design

### Fitness Function (LEARN-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Risk-adjusted return | Sharpe ratio or profit factor as primary fitness | :heavy_check_mark: (modified) |
| Pure P&L | Net profit as fitness | |
| Multi-objective (NSGA-II) | Pareto frontier optimization | |
| You decide | Claude designs based on backtest metrics | |

**User's choice:** Risk-adjusted return — but PHASE-AWARE:
- Aggressive ($20-$100): profit factor weighted higher, tolerate higher drawdown
- Selective ($100-$300): Sharpe ratio, penalize variance
- Conservative ($300+): Sharpe + max drawdown penalty, capital preservation co-equal
**Notes:** User explicitly requested mirroring the three-phase risk model from Phase 1 D-03.

### GA Timing (LEARN-02)

| Option | Description | Selected |
|--------|-------------|----------|
| After N trades | One generation per 50-100 trades, configurable | :heavy_check_mark: |
| Daily end-of-session | Once daily after session ends | |
| Continuous background | Continuous evolution in background thread | |

**User's choice:** After N trades
**Notes:** None

### Shadow Mode (LEARN-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Paper-trade variants | 3-5 variants in paper mode alongside live, using PaperExecutor | :heavy_check_mark: |
| Backtest-only validation | Validate via backtesting recent data only | |
| Single challenger | One variant at a time | |

**User's choice:** Paper-trade variants
**Notes:** None

### Promotion Criteria (LEARN-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Statistical significance | Outperform on fitness with p < 0.05 over 50+ trades + walk-forward | :heavy_check_mark: |
| Simple threshold | Exceed live fitness by configurable margin | |
| You decide | Claude designs using Phase 3 validation | |

**User's choice:** Statistical significance
**Notes:** None

### Rule Retirement (LEARN-05)

| Option | Description | Selected |
|--------|-------------|----------|
| Gradual decay + threshold | EMA performance score, retire below threshold after 50+ trades, cooldown pool | :heavy_check_mark: |
| Hard cutoff | Immediate retirement below win rate/profit factor threshold after N trades | |
| You decide | Claude designs consistent with EMA weight tracking | |

**User's choice:** Gradual decay + threshold
**Notes:** None

### GA Parameter Scope (LEARN-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Signal thresholds + fusion weights | Evolve strategy params, keep module physics fixed | :heavy_check_mark: |
| Everything configurable | Evolve all params including module internals | |
| Fusion weights only | Only evolve the fusion layer | |

**User's choice:** Signal thresholds + fusion weights
**Notes:** Module internals (Hurst window, Lyapunov embedding) are physics — not strategy parameters.

---

## Claude's Discretion

- Textual widget selection and CSS styling
- FastAPI route structure and WebSocket protocol
- lightweight-charts integration specifics
- DuckDB trade_log schema design
- DEAP GA configuration (population, mutation rates, crossover)
- ML classifier choice (RandomForest vs XGBoost)
- Shadow mode resource management
- Web dashboard frontend framework choice
- Plotly vs lightweight-charts for non-candlestick charts

## Deferred Ideas

None — discussion stayed within phase scope
