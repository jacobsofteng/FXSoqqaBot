# Requirements: FXSoqqaBot

**Defined:** 2026-03-27
**Core Value:** The bot reads the market's true state through the fusion of all eight modules and trades with the dominant forces. The edge is the fusion.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Data Infrastructure

- [x] **DATA-01**: Bot ingests real-time tick-level data (bid, ask, last, volume, flags) from MT5/RoboForex ECN for XAUUSD with sub-second polling
- [x] **DATA-02**: Bot retrieves DOM depth snapshots from MT5 when available, with graceful degradation to tick-only mode when DOM is limited or unavailable
- [x] **DATA-03**: Bot accesses bar data across multiple timeframes (M1, M5, M15, H1, H4) with aligned timestamps and efficient caching
- [ ] **DATA-04**: Bot loads and parses historical M1 bar data from histdata.com CSV files (2015-present) for backtesting
- [x] **DATA-05**: Bot stores tick data and trade events in DuckDB/Parquet for analytical queries and backtesting
- [x] **DATA-06**: Bot maintains rolling in-memory buffers of recent ticks and bars for real-time signal computation

### MT5 Bridge & Execution

- [x] **EXEC-01**: Python communicates with MT5 via MetaTrader5 Python package with all blocking calls wrapped in asyncio.to_thread() to avoid freezing the event loop
- [x] **EXEC-02**: Thin MQL5 EA executes orders (market orders, pending orders, SL/TP modification, partial close) with target sub-100ms round-trip on localhost
- [x] **EXEC-03**: Bot detects MT5 connection drops and automatically reconnects, reconciling expected vs actual position state on recovery
- [ ] **EXEC-04**: Bot recovers gracefully from Python crashes or machine reboots — checks for open positions on startup and resumes or closes as appropriate

### Risk & Safety

- [x] **RISK-01**: Every trade has a server-side stop-loss set at order placement time (never after), with ATR-based dynamic SL distance
- [x] **RISK-02**: Position sizing engine calculates lot size from account equity, risk percentage (1-2%), SL distance, and current spread — never exceeding safe exposure for the current capital phase
- [x] **RISK-03**: Bot filters trades when spread exceeds a configurable threshold (default: 2x average spread) and logs actual fill price vs requested price for slippage tracking
- [x] **RISK-04**: Daily drawdown circuit breaker halts all trading when daily loss exceeds configurable limit (default: 3-5%), persists across bot restarts, resets at session boundary
- [x] **RISK-05**: Kill switch immediately closes all positions, cancels all pending orders, and halts new trading — accessible from terminal command and dashboard
- [x] **RISK-06**: Bot only trades during configurable session windows (default: London-NY overlap 13:00-17:00 UTC), auto-pauses outside liquid hours
- [x] **RISK-07**: Weekly drawdown limit and total max drawdown limit enforce multi-tier capital protection beyond daily limits

### Chaos & Regime Detection

- [ ] **CHAOS-01**: Bot computes rolling Hurst Exponent on price series to classify trending (H>0.5), mean-reverting (H<0.5), or random walk (H≈0.5) regimes
- [ ] **CHAOS-02**: Bot computes Lyapunov Exponent to measure dynamical stability/instability of current price regime
- [ ] **CHAOS-03**: Bot computes Fractal Dimension to measure complexity and self-similarity of price action across timeframes
- [ ] **CHAOS-04**: Bot detects Feigenbaum bifurcation proximity by measuring period-doubling ratios in price oscillations to anticipate regime transitions before they complete
- [ ] **CHAOS-05**: Bot models crowd entropy through statistical mechanics — detecting entropy spikes that signal crowd panic or euphoria tipping points
- [ ] **CHAOS-06**: Bot classifies the current market into discrete regime states (trending-up, trending-down, ranging, high-chaos, pre-bifurcation) and outputs confidence levels, not point estimates

### Order Flow & Institutional Detection

- [ ] **FLOW-01**: Bot computes cumulative volume delta (buying vs selling pressure) from tick-level trade data in real time
- [ ] **FLOW-02**: Bot analyzes bid-ask aggression imbalances — detecting when aggressive buyers or sellers dominate the tape
- [ ] **FLOW-03**: Bot processes DOM depth data (when available) to detect weight shifting to one side, large hidden orders, and liquidity absorption
- [ ] **FLOW-04**: Bot detects institutional footprints: large order absorptions without price movement, iceberg order reload patterns at same price level, and volume clusters at key price levels
- [ ] **FLOW-05**: Bot identifies HFT acceleration signatures and distinguishes institutional-directed flow from retail-driven noise
- [ ] **FLOW-06**: Bot degrades order flow analysis gracefully — full capability with DOM data, reduced but functional with tick-only data

### Quantum Timing

- [ ] **QTIM-01**: Bot models price-time as coupled state variables and outputs probability-weighted entry windows (when to enter) and exit windows (when to exit)
- [ ] **QTIM-02**: Bot estimates not just where price will move but when the move will begin and end, using phase transition modeling and energy representations of volatility
- [ ] **QTIM-03**: Entry and exit windows include associated probability weights and confidence intervals — the bot acts on high-probability timing zones, not point predictions

### Signal Fusion & Decision

- [ ] **FUSE-01**: Decision core fuses signals from all upstream modules (chaos regime, order flow, institutional, quantum timing) into a single trade decision using confidence-weighted combination
- [ ] **FUSE-02**: Each module produces a signal with a confidence score; fusion weights adapt based on which modules have been accurate in the recent rolling window
- [ ] **FUSE-03**: Bot applies phase-aware position sizing: aggressive leverage utilization ($20-$100), selective with tighter risk ($100-$300), conservative capital preservation ($300+)
- [ ] **FUSE-04**: Bot auto-transitions between capital phases based on equity, with smooth behavioral transitions (no sudden strategy flip at exact threshold)
- [ ] **FUSE-05**: Decision core fires trades into MT5 with precise entry, SL, and TP parameters and manages open positions in real time, exiting when conditions reverse

### Self-Learning & Evolution

- [ ] **LEARN-01**: Bot logs every trade with full context: regime state, order flow conditions, signal combination and individual confidences, position size, entry/exit timing, win/loss, hold duration, spread at entry, slippage
- [ ] **LEARN-02**: Genetic algorithm evolves rule parameters (SL distance, entry thresholds, timeframe weights, signal fusion weights) using trade outcomes as fitness function
- [ ] **LEARN-03**: ML classifiers (RandomForest/XGBoost) trained on trade context data to improve regime detection and win probability prediction over time
- [ ] **LEARN-04**: Shadow mode tests strategy variants in parallel — mutated parameter sets run alongside live strategy without risking capital, promoted to live when they outperform
- [ ] **LEARN-05**: Learning loop identifies which signal combinations win above 70%, which regimes are most favorable, and which rules are degrading — retires underperforming rules automatically
- [ ] **LEARN-06**: Walk-forward validation of evolved parameters prevents the learning loop from overfitting to recent market conditions

### Backtesting & Validation

- [ ] **TEST-01**: Backtesting engine replays historical data (histdata.com M1 bars 2015-present + MT5 tick data for recent periods) with realistic spread simulation, slippage modeling, and commission costs
- [ ] **TEST-02**: Walk-forward validation trains on one period and validates on the next unseen period, rolling forward continuously — strategy must generalize, not memorize
- [ ] **TEST-03**: Monte Carlo simulation randomizes trade order sequences and entry timing 10,000+ times to verify robustness — results must be statistically significant (p < 0.05)
- [ ] **TEST-04**: Out-of-sample testing reserves a portion of recent history (never touched during development) for final validation only
- [ ] **TEST-05**: Regime-aware evaluation measures performance separately across trending, ranging, high-volatility, low-volatility, and news-driven market regimes
- [ ] **TEST-06**: Feigenbaum stress testing injects simulated regime transitions into backtests to verify the chaos module correctly anticipates and adapts to bifurcation events
- [ ] **TEST-07**: Backtesting shares 100% of analysis code with live trading via interface abstraction (DataFeedProtocol + Clock) — no separate backtest-only code paths

### Observability

- [ ] **OBS-01**: Rich terminal TUI dashboard shows in real time: current regime (color-coded), signal confidence per module, open positions with live P&L, spread/slippage metrics, circuit breaker status, daily stats
- [ ] **OBS-02**: TUI displays order flow visualization — volume delta, bid-ask pressure, institutional flow direction estimate
- [ ] **OBS-03**: TUI flags moments where the strategy mutated or adapted, showing what changed and why
- [ ] **OBS-04**: Lightweight web dashboard shows historical equity curve, trade history with filters, regime timeline, module performance comparison, and cumulative win rate
- [ ] **OBS-05**: Web dashboard is accessible from any device on the local network for remote monitoring

### Configuration

- [x] **CONF-01**: All risk parameters, signal thresholds, trading hours, position sizes, and module weights are configurable via YAML/TOML files without code changes
- [x] **CONF-02**: Separate configuration profiles for each growth phase ($20-$100, $100-$300, $300+) with automatic profile switching based on equity

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Quantum Timing

- **QTIM-04**: Full Hamiltonian energy representation of market volatility for state transition probability modeling
- **QTIM-05**: Quantum price level detection — identifying discrete energy levels where price preferentially settles

### Advanced Institutional Detection

- **FLOW-07**: Full iceberg order lifecycle tracking with reload prediction
- **FLOW-08**: Dark pool activity inference from tape anomalies

### Extended Validation

- **TEST-08**: Live A/B testing framework — run competing strategies on separate sub-accounts simultaneously
- **TEST-09**: Real-time strategy degradation detection with automatic fallback to safer parameters

## Out of Scope

| Feature | Reason |
|---------|--------|
| Multi-asset trading (other pairs, crypto, indices) | XAUUSD mastery first — all models tuned for gold's specific dynamics |
| Grid/martingale position management | Guaranteed eventual account destruction, especially at $20 with 1:500 leverage |
| News calendar as primary signal | Bot reads market reaction through flow, not the news itself — calendar trading is chasing |
| Indicator soup (RSI + MACD + Stochastic + Bollinger) | Correlated price-derived indicators create conflicting signals; using orthogonal sources instead |
| Deep learning / neural network price prediction | Overfits on small datasets, black-box, undebuggable; hybrid interpretable approach instead |
| Cloud deployment / distributed architecture | Adds network latency and failure modes; single Windows machine is simpler and faster |
| Mobile app | Web dashboard accessible from any device is sufficient |
| Social/copy trading | Solo autonomous system |
| Real-time WebSocket dashboard updates | Sub-second dashboard updates waste CPU that should go to trading logic; 1-5 second polling is sufficient |
| Direct institutional strategy replication | Cannot replicate co-located, dark-pool-access strategies; align with flow direction instead |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 1: Trading Infrastructure | Complete |
| DATA-02 | Phase 1: Trading Infrastructure | Complete |
| DATA-03 | Phase 1: Trading Infrastructure | Complete |
| DATA-04 | Phase 3: Backtesting and Validation | Pending |
| DATA-05 | Phase 1: Trading Infrastructure | Complete |
| DATA-06 | Phase 1: Trading Infrastructure | Complete |
| EXEC-01 | Phase 1: Trading Infrastructure | Complete |
| EXEC-02 | Phase 1: Trading Infrastructure | Complete |
| EXEC-03 | Phase 1: Trading Infrastructure | Complete |
| EXEC-04 | Phase 1: Trading Infrastructure | Pending |
| RISK-01 | Phase 1: Trading Infrastructure | Complete |
| RISK-02 | Phase 1: Trading Infrastructure | Complete |
| RISK-03 | Phase 1: Trading Infrastructure | Complete |
| RISK-04 | Phase 1: Trading Infrastructure | Complete |
| RISK-05 | Phase 1: Trading Infrastructure | Complete |
| RISK-06 | Phase 1: Trading Infrastructure | Complete |
| RISK-07 | Phase 1: Trading Infrastructure | Complete |
| CHAOS-01 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| CHAOS-02 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| CHAOS-03 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| CHAOS-04 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| CHAOS-05 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| CHAOS-06 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| FLOW-01 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| FLOW-02 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| FLOW-03 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| FLOW-04 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| FLOW-05 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| FLOW-06 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| QTIM-01 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| QTIM-02 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| QTIM-03 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| FUSE-01 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| FUSE-02 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| FUSE-03 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| FUSE-04 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| FUSE-05 | Phase 2: Signal Pipeline and Decision Fusion | Pending |
| TEST-01 | Phase 3: Backtesting and Validation | Pending |
| TEST-02 | Phase 3: Backtesting and Validation | Pending |
| TEST-03 | Phase 3: Backtesting and Validation | Pending |
| TEST-04 | Phase 3: Backtesting and Validation | Pending |
| TEST-05 | Phase 3: Backtesting and Validation | Pending |
| TEST-06 | Phase 3: Backtesting and Validation | Pending |
| TEST-07 | Phase 3: Backtesting and Validation | Pending |
| OBS-01 | Phase 4: Observability and Self-Learning | Pending |
| OBS-02 | Phase 4: Observability and Self-Learning | Pending |
| OBS-03 | Phase 4: Observability and Self-Learning | Pending |
| OBS-04 | Phase 4: Observability and Self-Learning | Pending |
| OBS-05 | Phase 4: Observability and Self-Learning | Pending |
| LEARN-01 | Phase 4: Observability and Self-Learning | Pending |
| LEARN-02 | Phase 4: Observability and Self-Learning | Pending |
| LEARN-03 | Phase 4: Observability and Self-Learning | Pending |
| LEARN-04 | Phase 4: Observability and Self-Learning | Pending |
| LEARN-05 | Phase 4: Observability and Self-Learning | Pending |
| LEARN-06 | Phase 4: Observability and Self-Learning | Pending |
| CONF-01 | Phase 1: Trading Infrastructure | Complete |
| CONF-02 | Phase 1: Trading Infrastructure | Complete |

**Coverage:**
- v1 requirements: 47 total
- Mapped to phases: 47
- Unmapped: 0

---
*Requirements defined: 2026-03-27*
*Last updated: 2026-03-27 after roadmap creation*
