# Phase 3: Backtesting and Validation - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Scientifically validate the signal fusion strategy on 2015-present XAUUSD history with anti-overfitting guarantees. This phase delivers: historical data ingestion (histdata.com M1 bars + MT5 tick data), a backtesting engine that replays data through the exact same signal pipeline used in live trading (via DataFeedProtocol + Clock abstraction), walk-forward validation, Monte Carlo simulation, regime-aware evaluation, Feigenbaum stress testing, and out-of-sample holdout testing.

Requirements covered: DATA-04, TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, TEST-06, TEST-07.

</domain>

<decisions>
## Implementation Decisions

### Historical Data Strategy
- **D-01:** Dual data source: histdata.com M1 bar CSVs for 2015-2024 bulk history, MT5 tick data for the most recent 1-2 years. Signal modules run on M1 bars for older data, full ticks for recent data.
- **D-02:** Graceful module degradation when only M1 bars are available. Chaos and order flow modules run in "bar-only" mode with reduced confidence — similar to how order flow already degrades without DOM data (Phase 2 D-13). Modules adapt computations to bar OHLCV.
- **D-03:** Strict data validation with auto-repair. Validate timestamps are monotonic, detect/fill gaps (weekends, holidays, outages), flag suspicious bars (extreme range, zero volume), log quality report. Automatically interpolate small gaps (<5 bars) and filter extreme outliers.
- **D-04:** Convert CSVs to Parquet once, partitioned by year/month. DuckDB queries Parquet directly. Consistent with Phase 1's tick storage pattern. One-time conversion cost, fast repeated backtests.
- **D-04a:** Raw histdata.com CSV files are stored in `data/histdata/` relative to the project root. The historical data loader reads from this directory.

### Validation Pass/Fail Criteria
- **D-05:** Walk-forward windows: 6 months training, 2 months validation, rolling forward by 2 months. ~50 windows from 2015-present.
- **D-06:** Dual walk-forward threshold — BOTH must pass:
  1. Strategy must be net profitable in at least 70% of walk-forward windows
  2. Aggregate profit factor > 1.5 across all windows combined
- **D-07:** Monte Carlo dual threshold — BOTH must pass:
  1. 5th percentile of Monte Carlo equity curves (10,000+ runs) must be net positive (p < 0.05)
  2. Median Monte Carlo run must be profitable AND 95th percentile max drawdown must stay below 40% of peak equity
- **D-08:** Regime-aware evaluation uses the 5 regimes from the chaos module: trending-up, trending-down, ranging, high-chaos, pre-bifurcation. Tag historical periods by running the chaos module over them and measure performance separately per regime.

### Spread & Slippage Realism
- **D-09:** Session-aware dynamic spread model. Calibrate from recent MT5 tick data where real spreads are available. Model spread by time-of-day and volatility: tight during London-NY overlap (~2-3 pips), wider during Asian session (~4-6 pips), widest during low-liquidity hours (~6-10 pips).
- **D-10:** Stochastic slippage drawn from a distribution calibrated to recent live fills: ~80% no slippage, ~15% 1-pip adverse, ~4% 2-pip adverse, ~1% 3+ pip adverse. Varies by session volatility.
- **D-11:** Configurable per-lot commission cost. Default to RoboForex ECN rates (~$5-7 per round-trip for gold). Adjustable if broker or account type changes.

### Out-of-Sample Holdout
- **D-12:** Reserve the most recent 6 months (~Oct 2025 - Mar 2026) as untouched holdout. Never used during development, walk-forward training, or parameter tuning.
- **D-13:** Hard fail on OOS divergence. If out-of-sample profit factor is less than 50% of in-sample, or max drawdown exceeds 2x in-sample, the strategy is flagged as overfit and rejected. Must re-tune and re-validate.

### Claude's Discretion
- DataFeedProtocol and Clock abstraction design (TEST-07 interface abstraction)
- How to retrofit the abstraction onto existing MarketDataFeed/TradingEngine without breaking live trading
- vectorbt integration approach vs custom engine architecture
- Feigenbaum stress testing implementation (synthetic regime transition injection)
- Backtest result storage schema and reporting format
- histdata.com CSV parsing specifics (format detection, encoding)
- Walk-forward optimizer coordination and parallelization strategy

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Architecture
- `CLAUDE.md` -- Full technology stack, version pinning, inter-module communication, "what NOT to use"
- `.planning/PROJECT.md` -- Core value (fusion is the edge), eight-module architecture, constraints
- `.planning/REQUIREMENTS.md` -- All 8 requirements for this phase (DATA-04, TEST-01 through TEST-07) with acceptance criteria

### Technology Decisions
- `CLAUDE.md` §Recommended Stack §Backtesting Framework -- vectorbt 0.28.4 for vectorized backtesting, custom engine on top
- `CLAUDE.md` §Recommended Stack §Scientific Computing Core -- NumPy 2.4.3, SciPy 1.17.1, Numba 0.64.0
- `CLAUDE.md` §Recommended Stack §Data Storage -- DuckDB 1.5.0, Parquet via pyarrow 19.x, SQLite for state
- `CLAUDE.md` §Recommended Stack §DataFrame Processing -- pandas 2.2.x primary, Polars 1.x for bulk batch processing
- `CLAUDE.md` §What NOT to Use -- No Backtrader, no Zipline, no TA-Lib

### Prior Phase Context
- `.planning/phases/01-trading-infrastructure/01-CONTEXT.md` -- Phase 1 decisions (paper trading D-01/D-02, risk model D-03/D-04, recovery D-05/D-07)
- `.planning/phases/02-signal-pipeline-and-decision-fusion/02-CONTEXT.md` -- Phase 2 decisions (fusion D-01/D-05, regime behavior D-06/D-08, DOM degradation D-13/D-15)

### Signal Pipeline (integration points for TEST-07)
- `src/fxsoqqabot/signals/base.py` -- SignalModule Protocol, SignalOutput dataclass, RegimeState enum
- `src/fxsoqqabot/data/feed.py` -- MarketDataFeed (currently coupled to MT5Bridge; needs DataFeedProtocol abstraction)
- `src/fxsoqqabot/core/engine.py` -- TradingEngine orchestrating all loops (needs Clock abstraction for replay)
- `src/fxsoqqabot/data/buffers.py` -- TickBuffer.as_arrays() and BarBufferSet for numpy data access
- `src/fxsoqqabot/data/storage.py` -- TickStorage (DuckDB/Parquet pattern to reuse for historical data)
- `src/fxsoqqabot/signals/fusion/core.py` -- FusionCore for confidence-weighted signal combination
- `src/fxsoqqabot/signals/fusion/trade_manager.py` -- TradeManager for position management
- `src/fxsoqqabot/risk/sizing.py` -- PositionSizer with three-phase capital model
- `src/fxsoqqabot/execution/paper.py` -- PaperExecutor (existing fill simulation to build on)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SignalModule` Protocol with `update(tick_arrays, bar_arrays, dom)` -- backtest engine feeds the same interface
- `TickBuffer.as_arrays()` / `BarBufferSet.as_arrays()` -- numpy array format modules expect; backtest data feed must produce identical format
- `PaperExecutor` -- already simulates fills against live data; backtest executor extends this pattern with spread/slippage models
- `FusionCore` -- confidence-weighted signal combination runs identically in backtest and live
- `PositionSizer` -- three-phase sizing used as-is in backtesting to match live behavior
- `TickStorage` (DuckDB/Parquet) -- same pattern for storing and querying historical bar/tick data
- `StateManager` (SQLite WAL) -- extend for backtest result persistence

### Established Patterns
- **Protocol-based interfaces:** SignalModule uses structural typing; DataFeedProtocol should follow same pattern
- **Frozen dataclasses with `__slots__`:** TickEvent, BarEvent, SignalOutput -- backtest events follow this
- **Async with `asyncio.to_thread()`:** Blocking computations wrapped for async; backtest may run synchronously for speed
- **structlog context binding:** Bind backtest run ID, window ID, regime for traceable results
- **Parquet partitioned by year/month:** Same scheme for historical M1 bar storage
- **Graceful degradation:** Order flow degrades without DOM; same pattern for bar-only mode in backtesting

### Integration Points
- `MarketDataFeed.__init__` takes `MT5Bridge` -- needs abstraction to accept backtest data source
- `TradingEngine` directly imports and instantiates `MT5Bridge` -- needs Clock injection for replay timing
- `config/models.py:BotSettings` -- extend with BacktestConfig (windows, spread model, slippage params, commission)
- Signal modules consume `tick_arrays`/`bar_arrays`/`dom` -- backtest feed must produce these exact dict shapes

</code_context>

<specifics>
## Specific Ideas

- Dual data source strategy mirrors the dual degradation philosophy: full fidelity when tick data available (recent), graceful bar-only mode for older history -- same principle as DOM degradation in Phase 2
- Validation is a dual-threshold gate at every level: walk-forward (70% windows profitable AND aggregate PF > 1.5), Monte Carlo (5th percentile positive AND median profitable with bounded drawdown), OOS (hard fail on divergence). Strategy must pass ALL gates.
- Spread model calibrated from real MT5 data bridges the gap between backtesting and live -- the same broker's actual spreads inform the simulation
- Commission is configurable because the user may change brokers or account types -- don't hardcode RoboForex rates

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 03-backtesting-and-validation*
*Context gathered: 2026-03-27*
