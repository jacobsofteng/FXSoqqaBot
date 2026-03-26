# FXSoqqaBot

## What This Is

A self-learning, self-adapting Forex scalping bot for XAUUSD (Gold) on MetaTrader 5 via RoboForex ECN with 1:500 leverage. It reads the market's current state — institutional flow, order flow microstructure, chaos regime dynamics, and quantum-inspired timing — and positions itself in harmony with the dominant forces. Python-first architecture with a thin MQL5 execution layer, designed to evolve its own strategy through a hybrid rule-based + ML mutation loop.

## Core Value

The bot reads the market's true state through the fusion of all eight modules — institutional flow, order flow, chaos dynamics, quantum timing — and trades with the dominant forces. The edge is not in any single module but in the fusion. If everything else fails, the multi-module state reading must work.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Market microstructure sensor ingesting tick-level data, DOM depth, volume delta, and bid-ask flow in real time from MT5/RoboForex ECN
- [ ] Institutional footprint detector classifying activity as retail noise vs. institutional flow (absorptions, iceberg patterns, DOM shifts, HFT signatures)
- [ ] Quantum timing engine treating price-time as coupled state variables with probability-weighted entry/exit windows
- [ ] Chaos/fractal/Feigenbaum regime classifier detecting market dynamical state (fractal dimension, strange attractors, bifurcation proximity, crowd entropy)
- [ ] Decision and execution core fusing all upstream signals into trade decisions with phase-aware position sizing
- [ ] Self-learning mutation loop logging full trade context and evolving rules via hybrid genetic + ML optimization
- [ ] Dual dashboard: rich terminal TUI for real-time monitoring + lightweight web dashboard for charts, stats, regime visualization
- [ ] Backtesting framework with walk-forward validation, Monte Carlo simulation, out-of-sample testing, regime-aware evaluation, and Feigenbaum stress testing across XAUUSD 2015-present
- [ ] Three-phase growth model: aggressive ($20-$100), selective ($100-$300), conservative ($300+) with adaptive behavior per capital phase
- [ ] Graceful degradation when DOM depth data is limited or unavailable from broker feed

### Out of Scope

- Multi-asset trading (other pairs, indices, crypto) — focus entirely on XAUUSD mastery first
- Cloud deployment or distributed architecture — runs on single Windows machine with MT5
- Mobile app or mobile dashboard — web dashboard accessible from any device is sufficient
- Social/copy trading features — this is a solo autonomous system
- Fundamental news calendar integration as a primary signal — the bot reads the market's reaction through flow, not the news itself

## Context

**Trading environment:**
- Broker: RoboForex ECN account
- Leverage: 1:500
- Platform: MetaTrader 5
- Instrument: XAUUSD (Gold) exclusively
- Starting capital: $20 (Phase 1 aggressive growth)

**Technical architecture:**
- Python-first via MetaTrader5 Python package — Python controls all logic
- Thin MQL5 Expert Advisor for order execution only
- Same-machine deployment: Python brain + MT5 on one Windows box, localhost communication
- Full scientific computing stack: NumPy, SciPy, scikit-learn, and domain-specific libraries
- Hybrid learning: rule-based trading core with ML layers for regime detection and parameter optimization
- Genetic algorithms for evolving rule parameters, ML classifiers for market state

**Data access strategy:**
- Design for best-case: full DOM depth snapshots + tick-level bid/ask data
- Degrade gracefully if RoboForex ECN limits DOM exposure
- Tick data is the minimum viable feed; DOM is the ideal

**Market philosophy:**
- Gold is volatile, institutionally dominated, geopolitically sensitive
- The market is a complex adaptive system — part deterministic, part chaotic
- The bot does not predict the market — it reads the market's current state
- Standard technical analysis is table stakes that every trader knows; the edge comes from deeper physics-inspired market reading
- Institutional flow alignment is survival, not strategy

**The eight modules (interconnected, not siloed):**
1. Market Microstructure Sensor — raw data nervous system
2. Institutional Footprint Detector — smart money tracker
3. Quantum Timing Engine — price-time coupled state modeling
4. Chaos/Fractal/Feigenbaum Regime Classifier — dynamical state detection
5. Decision and Execution Core — signal fusion + trade firing
6. Self-Learning Mutation Loop — continuous strategy evolution
7. Dashboard and Telemetry — TUI + web observability
8. Backtesting and Anti-Overfitting Framework — scientific validation

**Build approach:** All eight modules in simplified form from the start — the power is in the fusion, not individual modules in isolation. Each module starts simple and deepens over iterations.

## Constraints

- **Platform**: MetaTrader 5 on Windows — MQL5 EA required for order execution, Python for everything else
- **Broker**: RoboForex ECN — data availability depends on what their feed exposes (DOM depth uncertain)
- **Capital**: Starting at $20 — position sizing and risk management must account for micro-account constraints
- **Leverage**: 1:500 — powerful but dangerous, bot must manage exposure intelligently per growth phase
- **Latency**: Same-machine localhost communication — acceptable for scalping but Python-MT5 bridge latency must be minimized
- **Backtesting**: Must cover 2015-present XAUUSD history — need reliable historical tick data source

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Python-first architecture | Full scientific computing ecosystem (NumPy, SciPy, ML), MT5 Python API available, MQL5 too limited for chaos math and ML | — Pending |
| Hybrid learning (rules + ML) | Pure ML is black-box and hard to debug in trading; pure rules can't adapt. Hybrid gives interpretable core with adaptive layers | — Pending |
| All modules simplified first | The edge is fusion of all signals, not any single module perfected in isolation. Simplified full pipeline beats one perfect component | — Pending |
| Same-machine deployment | Simplest setup, lowest latency for Python-MT5 communication, no network overhead | — Pending |
| XAUUSD only | Gold mastery before diversification — one instrument deeply understood beats many instruments superficially | — Pending |
| Graceful DOM degradation | Broker DOM data availability is uncertain — design for best case but ensure system works with tick-only data | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-27 after initialization*
