# Phase 2: Signal Pipeline and Decision Fusion - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Build all four analysis modules (chaos/fractal/Feigenbaum regime classifier, order flow & institutional footprint detector, quantum timing engine) in simplified form and fuse them into confidence-weighted trade decisions with phase-aware position sizing. The bot reads market state through the fusion of all modules and fires trades into MT5 via the Phase 1 infrastructure.

Requirements covered: CHAOS-01, CHAOS-02, CHAOS-03, CHAOS-04, CHAOS-05, CHAOS-06, FLOW-01, FLOW-02, FLOW-03, FLOW-04, FLOW-05, FLOW-06, QTIM-01, QTIM-02, QTIM-03, FUSE-01, FUSE-02, FUSE-03, FUSE-04, FUSE-05.

</domain>

<decisions>
## Implementation Decisions

### Signal Fusion Strategy
- **D-01:** Confidence-weighted blend for signal fusion. Each module outputs a score + confidence. Fusion multiplies score x confidence x adaptive weight. Highest composite wins direction. Transparent and debuggable.
- **D-02:** Adaptive weights use exponential moving average (EMA) of module accuracy over a rolling window (e.g., last 50 trades). Weights decay smoothly when a module is wrong, recover gradually when right. No sudden weight flips.
- **D-03:** Configurable minimum fused confidence threshold below which no trade fires, even if signals align. Prevents low-conviction trades.
- **D-04:** Confidence threshold varies by capital phase: aggressive ($20-$100) uses lower threshold (e.g., 0.5) for more trade frequency; conservative ($300+) uses higher threshold (e.g., 0.7) to protect capital. Aligns with three-phase risk model from Phase 1.
- **D-05:** Fusion weights adapt purely from accuracy (EMA), NOT from regime state. No hardcoded regime-to-weight mappings. If chaos is accurate during trends, its weight naturally rises. Regime is context for behavior, not for weight overrides.

### Regime-to-Behavior Mapping
- **D-06:** In high-chaos or pre-bifurcation regimes: reduce activity, don't stop. Raise the confidence threshold, widen SL distances, reduce position size. The bot still trades on very high-conviction signals.
- **D-07:** In ranging regimes: let fusion decide. No hardcoded ranging behavior (no forced mean-reversion or sitting out). If order flow and quantum timing produce high-confidence signals in a range, trade them. Regime is context, not a veto.
- **D-08:** On adverse regime transition with open position: tighten stops to lock in profit or reduce loss. Don't force-close -- let the tightened SL do its job.

### Entry/Exit Parameters
- **D-09:** Dynamic risk-reward ratio based on regime: trending = 3:1 RR (let profits run), ranging = 1.5:1 RR (quick scalp), high-chaos = 2:1 RR (balanced). SL distance from ATR x chaos-aware multiplier, TP = SL x RR ratio.
- **D-10:** Regime-aware trailing stops. In trending regime: activate trailing stop after price moves 1x SL distance in profit (trail at 0.5x ATR). In ranging: no trailing, use fixed TP. In high-chaos: aggressive trail (0.3x ATR) to lock in quickly.
- **D-11:** One position at a time. Simpler risk management, clearer P&L attribution, easier to debug. At $20 starting capital, multiple positions would over-leverage. Scale to multiple only after learning loop validates.
- **D-12:** Quantum timing has no veto or delay power over entry. Timing contributes to the confidence-weighted blend like any other module. Low timing confidence reduces overall score but doesn't delay or block entries.

### DOM vs Tick-Only Investment
- **D-13:** Tick-first, DOM as enhancement. Build order flow primarily on tick data (volume delta, bid-ask aggression, tick velocity). DOM analysis is an optional layer that activates when available and passes quality checks. ~80% tick / ~20% DOM effort split.
- **D-14:** Institutional footprint detection uses both statistical anomaly detection AND volume profile clustering from tick data. Statistical signatures: large volume without price movement (absorption), repeated volume at same price level (iceberg reload), volume spikes with spread widening (HFT). Volume-at-price profiles identify institutional levels as high-volume nodes.
- **D-15:** DOM quality auto-detection on startup. Sample DOM snapshots for ~60 seconds. If depth >= 5 levels on both sides and updates >= 1/sec, enable DOM analysis. Re-check periodically. Auto-disable if quality degrades, with logging.

### Claude's Discretion
- Signal module abstract interface design (ABC/Protocol patterns)
- New package structure under `src/fxsoqqabot/signals/`
- Chaos analysis algorithm selection (Rosenstein vs Eckmann for Lyapunov, etc.)
- Quantum timing simplified implementation approach
- Pydantic config model structure for signal modules
- SQLite schema extensions for signal state persistence
- Integration pattern into TradingEngine (new loop vs inline processing)
- ATR computation approach and lookback periods
- Feigenbaum bifurcation detection algorithm design
- Crowd entropy statistical mechanics implementation

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Architecture
- `CLAUDE.md` -- Full technology stack, version pinning, inter-module communication, "what NOT to use"
- `.planning/PROJECT.md` -- Core value (fusion is the edge), eight-module architecture, market philosophy
- `.planning/REQUIREMENTS.md` -- All 20 requirements for this phase (CHAOS-01-06, FLOW-01-06, QTIM-01-03, FUSE-01-05) with acceptance criteria

### Technology Decisions
- `CLAUDE.md` §Recommended Stack §Scientific Computing Core -- NumPy 2.4.3, SciPy 1.17.1, Numba 0.64.0 for chaos computations
- `CLAUDE.md` §Recommended Stack §Machine Learning -- scikit-learn 1.8.0 for regime classification
- `CLAUDE.md` §What NOT to Use -- No TensorFlow, no PyTorch for v1, no indicator soup
- `CLAUDE.md` §Alternatives Considered -- nolds 0.6.3 for reference Lyapunov/Hurst/fractal implementations

### Phase 1 Infrastructure (integration points)
- `src/fxsoqqabot/core/events.py` -- Frozen dataclass event pattern to follow for signal events
- `src/fxsoqqabot/core/engine.py` -- TradingEngine with three async loops; signal modules plug in here
- `src/fxsoqqabot/data/buffers.py` -- TickBuffer.as_arrays() and BarBufferSet for numpy data access
- `src/fxsoqqabot/data/feed.py` -- MarketDataFeed with fetch_ticks(), fetch_dom(), fetch_multi_timeframe_bars()
- `src/fxsoqqabot/config/models.py` -- Pydantic config hierarchy to extend with signal configs
- `src/fxsoqqabot/execution/orders.py` -- OrderManager.place_market_order() for trade execution
- `src/fxsoqqabot/risk/sizing.py` -- PositionSizer.calculate_lot_size() with three-phase model
- `src/fxsoqqabot/risk/circuit_breakers.py` -- CircuitBreakerManager gates all trade execution
- `src/fxsoqqabot/core/state.py` -- StateManager (SQLite) for persisting signal states

### Prior Phase Context
- `.planning/phases/01-trading-infrastructure/01-CONTEXT.md` -- Phase 1 decisions (D-01 through D-10)

### Broker & Platform
- `CLAUDE.md` §Constraints -- RoboForex ECN, DOM uncertainty, localhost deployment
- `.planning/STATE.md` §Blockers/Concerns -- DOM quality unknown, Feigenbaum has no reference implementations

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TickBuffer.as_arrays()` -- Returns numpy arrays (bid, ask, last, spread, volume_real, time_msc) for vectorized computation in chaos/order flow modules
- `BarBufferSet` -- Multi-timeframe bar access (M1/M5/M15/H1/H4) with `.as_arrays()` for regime detection
- `DOMSnapshot` -- Frozen dataclass with graceful degradation (empty tuple when unavailable)
- `OrderManager` -- Routes trades through paper/live mode transparently; fusion core calls `place_market_order()`
- `PositionSizer` -- Three-phase capital model already implements D-03/D-04 from Phase 1
- `CircuitBreakerManager` -- Five automatic breakers gate trade execution
- `StateManager` -- SQLite persistence with WAL mode; extend with signal state tables
- `BotSettings.from_toml()` -- Pydantic config with TOML loading + env var overrides

### Established Patterns
- **Events:** Frozen dataclasses with `__slots__` for memory efficiency -- signal modules should follow this
- **Async:** All blocking MT5 calls wrapped in `asyncio.to_thread()` -- Numba-JIT chaos computations should use same pattern
- **Config:** Pydantic BaseModel hierarchy loaded from TOML -- signal configs extend this
- **Buffers:** `collections.deque(maxlen=N)` for O(1) fixed-size rolling data
- **Logging:** structlog with context binding -- signal modules bind regime state and scores

### Integration Points
- `TradingEngine._tick_loop()` -- Signal modules consume tick data after buffer update
- `TradingEngine._bar_loop()` -- Regime detection updates after bar refresh
- `TradingEngine._initialize_components()` -- Signal modules instantiated here with dependency injection
- `TradingEngine.start()` -- Add signal analysis loop(s) to `asyncio.gather()`
- `config/models.py:BotSettings` -- Add `signals: SignalModulesConfig` field

</code_context>

<specifics>
## Specific Ideas

- Institutional footprint detection should combine BOTH statistical anomaly detection AND volume profile clustering -- not one or the other. Statistical signatures catch real-time anomalies; volume profiles provide structural context.
- The fusion edge comes from all modules contributing, not from any module having veto power. Quantum timing, chaos regime, and order flow all feed the weighted blend equally. The adaptive EMA mechanism rewards accuracy, not module type.
- High-chaos doesn't mean "don't trade" -- it means "trade only with very high conviction." The bot reads market state, including chaotic state, and positions accordingly.
- $20 aggressive phase needs trade frequency. Lower confidence thresholds let more trades through to maximize growth opportunities with seed money.

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 02-signal-pipeline-and-decision-fusion*
*Context gathered: 2026-03-27*
