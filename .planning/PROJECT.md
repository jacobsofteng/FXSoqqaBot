# FXSoqqaBot

## What This Is

A self-learning, self-adapting Forex scalping bot for XAUUSD (Gold) on MetaTrader 5 via RoboForex ECN with 1:500 leverage. It reads the market's current state through chaos regime dynamics, order flow microstructure, and quantum-inspired timing, then fuses these signals into confidence-weighted trade decisions. Python-first architecture with a thin MQL5 execution layer, dual dashboards (TUI + web), and a hybrid genetic + ML evolution loop that promotes strategy improvements only after walk-forward validation.

## Core Value

The bot reads the market's true state through the fusion of all analysis modules and trades with the dominant forces. The edge is not in any single module but in the fusion. If everything else fails, the multi-module state reading must work.

## Current Milestone: v1.1 Live Demo Launch

**Goal:** Make the bot trade 10-20 times/day with optimized signals and run unattended on the RoboForex demo account for a 1-week observation period.

**Target features:**
- Signal pipeline overhaul (chaos direction, timing urgency, fusion thresholds, position sizing)
- Backtesting pipeline fix (performance, complete execution)
- Automated optimization (single command, no manual intervention)
- Live MT5 execution (real orders on demo account)
- Demo hardening (logging, recovery, monitoring)

## Current State

**Shipped:** v1.0 MVP (2026-03-28)
**Codebase:** 14,811 LOC Python source, 14,594 LOC tests (772+ tests passing)
**Status:** v1.1 Phase 8 complete — signal pipeline calibrated (chaos direction modes, timing fix, phase-aware risk). Next: backtest pipeline & automated optimization.

## Requirements

### Validated

- ✓ Market microstructure sensor ingesting tick-level data, DOM depth, volume delta from MT5/RoboForex ECN — v1.0
- ✓ Graceful degradation when DOM depth data is limited or unavailable — v1.0
- ✓ Three-phase growth model: aggressive/selective/conservative with adaptive behavior per capital phase — v1.0
- ✓ Institutional footprint detector (absorptions, iceberg patterns, DOM shifts, HFT signatures) — v1.0
- ✓ Quantum timing engine with OU mean-reversion and phase transition detection — v1.0
- ✓ Chaos/fractal/Feigenbaum regime classifier (Hurst, Lyapunov, fractal dimension, entropy, bifurcation) — v1.0
- ✓ Decision core fusing all upstream signals with confidence-weighted combination and adaptive EMA weights — v1.0
- ✓ Multi-tier risk management (5 circuit breakers + kill switch + session filter) — v1.0
- ✓ Self-learning mutation loop with GA evolution, shadow variants, ML regime classifier, walk-forward gate — v1.0
- ✓ Dual dashboard: rich TUI + lightweight web dashboard with live equity, signals, regime, positions — v1.0
- ✓ Backtesting framework with walk-forward, Monte Carlo, regime evaluation, Feigenbaum stress testing — v1.0
- ✓ Full cross-phase integration: all feedback loops wired, all 6 E2E flows verified — v1.0

### Active

**v1.1 — Live Demo Launch:**
- [ ] Signal pipeline overhaul — fix chaos direction, timing urgency, fusion thresholds for 10-20 trades/day
- [ ] Backtesting pipeline fix — performance optimization, complete 6-step pipeline
- [ ] Automated optimization — single command backtest → optimize → validate → write config
- [ ] Live MT5 execution — real order_send() on demo account, position tracking, reconnection
- [ ] Demo hardening — log levels, session management, crash recovery, monitoring

### Out of Scope

- Multi-asset trading (other pairs, indices, crypto) — XAUUSD mastery first
- Cloud deployment or distributed architecture — single Windows machine with MT5
- Mobile app — web dashboard accessible from any device is sufficient
- Social/copy trading — solo autonomous system
- News calendar as primary signal — bot reads market reaction through flow, not news
- Deep learning / neural networks — overfits on small datasets, prefer interpretable hybrid approach
- Real-time sub-second WebSocket updates — 1-5s polling sufficient, CPU reserved for trading logic

## Context

**Trading environment:**
- Broker: RoboForex ECN account
- Leverage: 1:500
- Platform: MetaTrader 5
- Instrument: XAUUSD (Gold) exclusively
- Starting capital: $20 (Phase 1 aggressive growth)

**Technical architecture (as shipped v1.0):**
- Python 3.12 with MetaTrader5 Python package for all logic and data
- Async engine with concurrent tick/bar/signal/health loops via asyncio.gather
- 3 signal modules (chaos, order flow, quantum timing) implementing SignalModule Protocol
- FusionCore with adaptive EMA weights persisted to SQLite
- Paper trading engine with spread/slippage simulation
- DuckDB/Parquet for analytical tick storage, SQLite for operational state
- Textual TUI + FastAPI web dashboard
- DEAP genetic algorithms + scikit-learn RandomForest for self-learning
- vectorbt-compatible backtesting with DataFeedProtocol abstraction

**Codebase structure:**
- `src/fxsoqqabot/` — 14,811 LOC across config, core, data, execution, risk, signals, backtest, dashboard, learning
- `tests/` — 14,594 LOC, 772+ tests, all passing
- `config/` — TOML configuration files (default, paper, live profiles)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Python-first architecture | Full scientific computing ecosystem, MT5 Python API, MQL5 too limited for chaos math/ML | ✓ Good — 14.8K LOC of clean Python, all 16 analysis algorithms in Python |
| Hybrid learning (rules + ML) | Pure ML is black-box; pure rules can't adapt. Hybrid gives interpretable core + adaptive layers | ✓ Good — GA evolves parameters, RandomForest improves regime detection |
| All modules simplified first | The edge is fusion, not any single module perfected in isolation | ✓ Good — full pipeline working end-to-end, all modules contribute to fusion |
| Same-machine deployment | Simplest setup, lowest latency for Python-MT5 communication | ✓ Good — no network issues, localhost sufficient |
| XAUUSD only | Gold mastery before diversification | — Pending (not yet live-tested) |
| Graceful DOM degradation | Broker DOM availability uncertain | ✓ Good — tick-only path works, DOM enhances when available |
| DataFeedProtocol abstraction | Share 100% analysis code between live and backtest | ✓ Good — zero separate backtest code paths |
| Learning disabled by default | Prevent accidental evolution before sufficient trade history at $20 | ✓ Good — safety-first for micro account |
| Synchronous is_killed property | Avoid async overhead for frequently-checked state | ✓ Good — fixed coroutine bug, clean sync reads |
| Walk-forward promotion gate | Prevent overfitting of evolved parameters | ✓ Good — callback injection pattern, fail-safe to rejection |

## Constraints

- **Platform**: MetaTrader 5 on Windows — MQL5 EA required for order execution, Python for everything else
- **Broker**: RoboForex ECN — data availability depends on what their feed exposes (DOM depth uncertain)
- **Capital**: Starting at $20 — position sizing and risk management must account for micro-account constraints
- **Leverage**: 1:500 — powerful but dangerous, bot must manage exposure intelligently per growth phase
- **Latency**: Same-machine localhost communication — acceptable for scalping
- **Backtesting**: Covers 2015-present XAUUSD history via histdata.com M1 bar data

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? Move to Out of Scope with reason
2. Requirements validated? Move to Validated with phase reference
3. New requirements emerged? Add to Active
4. Decisions to log? Add to Key Decisions
5. "What This Is" still accurate? Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-28 after Phase 8 signal & risk calibration complete*
