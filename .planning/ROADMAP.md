# Roadmap: FXSoqqaBot

## Overview

FXSoqqaBot goes from zero to autonomous XAUUSD scalping in four phases. First, we build the data pipeline, execution bridge, risk management, and configuration that keep a $20 account alive. Second, we build all eight analysis modules in simplified form and fuse them -- because the edge is the fusion, not any single module. Third, we scientifically validate the strategy through backtesting with walk-forward and Monte Carlo anti-overfitting. Fourth, we add observability dashboards and the self-learning evolution loop that lets the bot improve itself over time. Each phase delivers a complete, testable capability.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Trading Infrastructure** - Data pipeline, MT5 bridge, risk management, and configuration that keep a $20 account alive
- [ ] **Phase 2: Signal Pipeline and Decision Fusion** - All analysis modules (chaos, order flow, quantum timing) simplified and fused into trade decisions
- [ ] **Phase 3: Backtesting and Validation** - Scientific validation with walk-forward, Monte Carlo, and regime-aware evaluation on 2015-present XAUUSD data
- [ ] **Phase 4: Observability and Self-Learning** - Real-time dashboards (TUI + web) and self-learning mutation loop for continuous strategy evolution
- [ ] **Phase 5: Self-Learning Feedback Loop Wiring** - Wire disconnected learning/evolution components into engine runtime (gap closure)
- [ ] **Phase 6: Dashboard Live State Wiring** - Connect engine state to TUI/web dashboards and fix pause behavior (gap closure)
- [ ] **Phase 7: Validation Pipeline Entry Points** - Wire orphaned RegimeTagger and FeigenbaumStressTest into backtest CLI (gap closure)

## Phase Details

### Phase 1: Trading Infrastructure
**Goal**: The bot connects to MT5, ingests live market data, executes trades with full risk protection, and survives connection failures -- all configurable without code changes
**Depends on**: Nothing (first phase)
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-05, DATA-06, EXEC-01, EXEC-02, EXEC-03, EXEC-04, RISK-01, RISK-02, RISK-03, RISK-04, RISK-05, RISK-06, RISK-07, CONF-01, CONF-02
**Success Criteria** (what must be TRUE):
  1. Bot streams live XAUUSD tick data from MT5 and maintains rolling in-memory buffers across multiple timeframes (M1, M5, M15, H1, H4) without blocking the async event loop
  2. Bot places a market order on MT5 with server-side stop-loss and receives fill confirmation, and the kill switch can immediately flatten all positions and halt trading
  3. Position sizing engine correctly calculates lot size from equity, risk percentage, and SL distance for all three capital phases ($20-$100, $100-$300, $300+) and never exceeds safe exposure
  4. Daily drawdown circuit breaker halts trading when loss limit is hit, persists across restarts, and session time filter prevents trading outside configured hours
  5. Bot detects MT5 disconnection, automatically reconnects, and reconciles position state -- and recovers gracefully from a full Python restart with open positions
**Plans**: 7 plans

Plans:
- [x] 01-01-PLAN.md -- Project scaffolding, config models, event types, structured logging
- [x] 01-02-PLAN.md -- Async MT5 bridge and market data feed (ticks, bars, DOM)
- [x] 01-03-PLAN.md -- Rolling in-memory buffers and DuckDB/Parquet storage
- [x] 01-04-PLAN.md -- Order execution with server-side SL and paper trading engine
- [x] 01-05-PLAN.md -- Position sizing engine and session time filter
- [x] 01-06-PLAN.md -- Circuit breakers, kill switch, and SQLite state persistence
- [x] 01-07-PLAN.md -- Async engine orchestration, crash recovery, and CLI entry points

### Phase 2: Signal Pipeline and Decision Fusion
**Goal**: The bot reads the market's true state through simplified versions of all analysis modules -- chaos regime, order flow, institutional footprint, quantum timing -- and fuses them into confidence-weighted trade decisions with phase-aware position sizing
**Depends on**: Phase 1
**Requirements**: CHAOS-01, CHAOS-02, CHAOS-03, CHAOS-04, CHAOS-05, CHAOS-06, FLOW-01, FLOW-02, FLOW-03, FLOW-04, FLOW-05, FLOW-06, QTIM-01, QTIM-02, QTIM-03, FUSE-01, FUSE-02, FUSE-03, FUSE-04, FUSE-05
**Success Criteria** (what must be TRUE):
  1. Bot classifies the current XAUUSD market into discrete regime states (trending-up, trending-down, ranging, high-chaos, pre-bifurcation) using Hurst exponent, Lyapunov exponent, fractal dimension, and crowd entropy -- each with confidence levels
  2. Bot computes real-time order flow signals (volume delta, bid-ask aggression, institutional footprints) from tick data, with graceful degradation when DOM depth data is unavailable
  3. Bot outputs probability-weighted entry and exit timing windows based on price-time coupled state modeling
  4. Decision core fuses all upstream signals using confidence-weighted combination where fusion weights adapt based on recent module accuracy, and fires trades with precise entry/SL/TP into MT5
  5. Bot auto-transitions between capital phase behaviors (aggressive/selective/conservative) based on equity with smooth behavioral transitions
**Plans**: 6 plans

Plans:
- [x] 02-01-PLAN.md -- Signal pipeline foundation: dependencies, Protocol/dataclass types, config models
- [x] 02-02-PLAN.md -- Chaos/regime module: Hurst, Lyapunov, fractal, Feigenbaum, entropy, regime classifier
- [x] 02-03-PLAN.md -- Order flow module: volume delta, aggression, DOM analysis, institutional footprints, HFT detection
- [x] 02-04-PLAN.md -- Quantum timing module: OU mean-reversion timing, phase transition detection
- [x] 02-05-PLAN.md -- Fusion core: confidence-weighted blend, adaptive weights, phase behavior, trade manager
- [x] 02-06-PLAN.md -- Engine integration: signal loop wiring, weight persistence, end-to-end pipeline

### Phase 3: Backtesting and Validation
**Goal**: The strategy is scientifically validated on 2015-present XAUUSD history with anti-overfitting guarantees -- walk-forward, Monte Carlo, and regime-aware evaluation confirm the signal fusion generalizes to unseen data
**Depends on**: Phase 2
**Requirements**: DATA-04, TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, TEST-06, TEST-07
**Success Criteria** (what must be TRUE):
  1. Backtesting engine replays historical M1 bar data (2015-present) and recent MT5 tick data through the exact same signal pipeline used in live trading (no separate backtest code paths) with realistic spread simulation and slippage modeling
  2. Walk-forward validation trains on one period and validates on the next unseen period with rolling windows, and the strategy must be profitable across ALL windows -- not just aggregate
  3. Monte Carlo simulation randomizes trade sequences 10,000+ times and results are statistically significant (p < 0.05)
  4. Performance is measured separately across trending, ranging, high-volatility, and low-volatility regimes, and Feigenbaum stress testing verifies chaos module behavior during simulated regime transitions
  5. Out-of-sample holdout period (never touched during development) produces results consistent with in-sample performance
**Plans**: 5 plans

Plans:
- [x] 03-01-PLAN.md -- Interface abstraction: DataFeedProtocol, Clock Protocol, BacktestConfig, LiveDataFeedAdapter
- [x] 03-02-PLAN.md -- Historical data pipeline: histdata.com CSV parsing, validation, Parquet conversion
- [x] 03-03-PLAN.md -- Backtest engine: BacktestDataFeed, BacktestExecutor (spread/slippage/commission), BacktestEngine replay loop
- [x] 03-04-PLAN.md -- Walk-forward validation and out-of-sample holdout evaluation
- [x] 03-05-PLAN.md -- Monte Carlo simulation, regime-aware evaluation, and Feigenbaum stress testing

### Phase 4: Observability and Self-Learning
**Goal**: The operator can monitor every aspect of the bot's behavior in real time through dashboards, and the bot evolves its own strategy through a hybrid genetic + ML learning loop that promotes improvements only after scientific validation
**Depends on**: Phase 3
**Requirements**: OBS-01, OBS-02, OBS-03, OBS-04, OBS-05, LEARN-01, LEARN-02, LEARN-03, LEARN-04, LEARN-05, LEARN-06
**Success Criteria** (what must be TRUE):
  1. Rich terminal TUI displays in real time: current regime (color-coded), signal confidence per module, open positions with live P&L, spread/slippage metrics, circuit breaker status, and flags when the strategy mutates
  2. Lightweight web dashboard accessible from any device on the local network shows historical equity curve, trade history with filters, regime timeline, and module performance comparison
  3. Bot logs every trade with full context (regime state, all signal confidences, position size, timing, outcome) and the genetic algorithm evolves rule parameters using trade outcomes as fitness
  4. Shadow mode tests mutated strategy variants alongside the live strategy without risking capital, and variants are promoted to live only after walk-forward validation confirms they outperform
  5. Learning loop identifies which signal combinations, regimes, and rules are performing or degrading -- and automatically retires underperforming rules
**Plans**: 8 plans
**UI hint**: yes

Plans:
- [x] 04-01-PLAN.md -- Foundation: dependencies, config models, event types, shared state, trade context logger
- [x] 04-02-PLAN.md -- TUI dashboard: Textual app with regime, signals, position, risk, trades, order flow panels
- [x] 04-03-PLAN.md -- Web dashboard: FastAPI server, WebSocket/REST API, static HTML/JS/CSS frontend
- [x] 04-04-PLAN.md -- GA evolution engine, signal combination analyzer, EMA rule retirement tracker
- [x] 04-05-PLAN.md -- Shadow mode variant management, ML regime classifier, statistical promotion
- [x] 04-06-PLAN.md -- Engine integration: wire TUI, web, trade logger, and learning loop into TradingEngine
- [x] 04-07-PLAN.md -- Gap closure: fix trade logging pipeline (FillEvent return, close logging, learning loop wiring)
- [x] 04-08-PLAN.md -- Gap closure: add walk-forward validation gate to shadow variant promotion

### Phase 5: Self-Learning Feedback Loop Wiring
**Goal**: All learning and evolution feedback loops are connected at runtime — trade outcomes flow into adaptive weights, shadow variants accumulate trade data, promoted variants apply to the live engine, and walk-forward validation gates promotions
**Depends on**: Phase 4
**Requirements**: FUSE-02, LEARN-04, LEARN-05, LEARN-06
**Gap Closure**: Closes gaps from v1.0 milestone audit
**Success Criteria** (what must be TRUE):
  1. AdaptiveWeightTracker.record_outcome() is called after every trade close, and fusion weights evolve from warmup values based on module accuracy
  2. ShadowManager.record_variant_trade() is called for every trade, shadow variants accumulate trade history, and evaluate_promotion() returns meaningful results
  3. LearningLoopManager holds an engine reference and promote_variant() applies promoted parameters to the live trading strategy
  4. set_walk_forward_validator() is called during engine startup and the walk-forward gate blocks promotions that fail validation
**Plans**: 2 plans

Plans:
- [x] 05-01-PLAN.md -- Wire adaptive weights, shadow trade recording, and promote callback in engine and learning loop
- [x] 05-02-PLAN.md -- Integration tests for all four feedback loop wiring points

### Phase 6: Dashboard Live State Wiring
**Goal**: TUI and web dashboards display accurate live data — equity, connection status, kill state, module weights, regime timeline — and the pause command actually stops trading
**Depends on**: Phase 4
**Requirements**: OBS-01, OBS-04
**Gap Closure**: Closes gaps from v1.0 milestone audit
**Success Criteria** (what must be TRUE):
  1. _current_equity and _connected are assigned on the engine instance from MT5 account info, and dashboards display real equity values
  2. is_killed reads a boolean value (not a coroutine object) and displays correctly in TUI/web
  3. equity_history is populated over time, /api/equity returns real data, /api/module-weights returns current fusion weights, and regime timeline data flows to the web dashboard
  4. When is_paused is set via TUI/web, _signal_loop, _tick_loop, and _bar_loop skip evaluation until unpaused
**Plans**: 2 plans

Plans:
- [x] 06-01-PLAN.md -- Fix all 4 dashboard wiring bugs in engine, state snapshot, circuit breakers, and web server
- [x] 06-02-PLAN.md -- Unit tests for all 4 success criteria (equity, is_killed, history/weights, pause)

### Phase 7: Validation Pipeline Entry Points
**Goal**: RegimeTagger and FeigenbaumStressTest are callable from the backtest CLI and runner — completing the validation pipeline with regime-aware evaluation and chaos stress testing
**Depends on**: Phase 3
**Requirements**: TEST-05, TEST-06
**Gap Closure**: Closes gaps from v1.0 milestone audit
**Success Criteria** (what must be TRUE):
  1. CLI command exists to run regime-aware evaluation (RegimeTagger) on backtest results, producing per-regime performance breakdown
  2. CLI command exists to run Feigenbaum stress testing on backtest data, verifying chaos module behavior during simulated regime transitions
  3. Both tools are integrated into the backtest runner so they can be invoked as part of a standard validation pipeline
**Plans**: 2 plans

Plans:
- [x] 07-01-PLAN.md -- CLI subcommands (validate-regimes, stress-test) and runner extension to 6 steps
- [x] 07-02-PLAN.md -- Integration tests for CLI wiring and runner pipeline

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Trading Infrastructure | 7/7 | Complete | 2026-03-27 |
| 2. Signal Pipeline and Decision Fusion | 6/6 | Complete | 2026-03-27 |
| 3. Backtesting and Validation | 0/5 | Not started | - |
| 4. Observability and Self-Learning | 8/8 | Complete | 2026-03-28 |
| 5. Self-Learning Feedback Loop Wiring | 0/2 | Not started | - |
| 6. Dashboard Live State Wiring | 0/2 | Not started | - |
| 7. Validation Pipeline Entry Points | 0/2 | Not started | - |
