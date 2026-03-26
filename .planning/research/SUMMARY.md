# Project Research Summary

**Project:** FXSoqqaBot
**Domain:** Autonomous XAUUSD (gold) scalping bot with chaos theory, order flow, quantum-inspired timing, and self-learning on MetaTrader 5
**Researched:** 2026-03-27
**Confidence:** HIGH (stack verified, architecture patterns mature, domain pitfalls well-documented; MEDIUM for experimental differentiators)

## Executive Summary

FXSoqqaBot is a Python-first autonomous trading bot that combines four orthogonal signal sources -- chaos/fractal regime detection, order flow microstructure, institutional footprint analysis, and quantum-inspired timing -- into a single decision fusion engine. The technology stack for building this in 2026 is mature and well-understood: Python 3.12, the official MetaTrader5 package for data retrieval, NumPy/SciPy/Numba for scientific computing, scikit-learn/Optuna/DEAP for the hybrid learning core, DuckDB+Parquet for analytics, and Textual/FastAPI for monitoring. Every core library has been verified on PyPI with confirmed cross-compatibility. The nolds library provides ready-made Hurst exponent, Lyapunov exponent, and fractal dimension implementations that serve as both reference and starting point. The critical architectural insight is that the MetaTrader5 Python package is fully synchronous -- every `mt5.*` call blocks -- so all MT5 interaction must be thread-isolated via `asyncio.to_thread()` from day one. This is non-negotiable and the most common source of architectural rewrites in Python-MT5 projects.

The recommended approach is a layered event-driven pipeline: Data Ingestion (MT5 Bridge) feeds a Microstructure Sensor, which publishes normalized MarketState to three parallel analysis modules (Chaos/Fractal Regime, Institutional Footprint, Quantum Timing), whose signals converge in a Decision Core that fuses them with confidence weighting and phase-aware risk management. Cross-cutting systems -- Self-Learning, Dashboard, and Backtesting -- observe the pipeline without interfering with it. The backtesting framework uses interface-swapping (replacing the MT5 Bridge with a HistoricalDataFeed) so all modules run identical code in both live and backtest modes. This architecture supports the project's core thesis: the competitive edge is not in any single module but in the fusion of orthogonal signal sources. Research confirms no commercial or open-source system combines chaos theory regime detection with order flow microstructure with quantum-inspired timing. The fusion is genuinely novel.

The three highest risks are: (1) the $20 starting capital makes proper risk management mathematically impossible at 0.01 minimum lot size -- a single 20-pip stop loss risks 10% of the account, so the aggressive growth phase must accept elevated risk with compensating trade selectivity; (2) chaos theory metrics (Hurst, Lyapunov, fractal dimension) produce unreliable results on noisy financial data and must be treated as qualitative regime indicators with confidence intervals, not precise measurements; and (3) backtesting overfitting across an 8-module system with dozens of parameters will produce strategies that look brilliant in-sample and fail live, so walk-forward validation and Monte Carlo testing must be embedded from the first backtest run, not bolted on later. The Feigenbaum bifurcation detector and quantum timing engine are the highest-risk, highest-reward features with no existing implementations to reference -- defer both to late phases.

## Key Findings

### Recommended Stack

Python 3.12 is the target runtime, chosen for ecosystem maturity over 3.13's experimental free-threading. The stack splits cleanly by responsibility.

**Core technologies:**
- **MetaTrader5 5.0.5640** (Python package): sole interface to MT5 for tick data, DOM snapshots, bar data, and order execution -- no alternative exists for direct MT5 integration
- **NumPy 2.4 + SciPy 1.17 + Numba 0.64**: the scientific computing foundation; Numba JIT compiles hot chaos math loops for 10-30x speedup over pure Python
- **nolds 0.6.3**: reference implementations of Hurst exponent, Lyapunov exponents, fractal dimension, DFA, and sample entropy -- use as starting point, re-implement hot paths in Numba
- **scikit-learn 1.8 + Optuna 4.8 + DEAP 1.4**: hybrid learning core (ML classifiers for regime detection, Bayesian parameter optimization, genetic rule evolution) -- deliberately avoids TensorFlow/PyTorch
- **DuckDB 1.5 + Parquet + SQLite**: dual-database strategy -- SQLite for high-frequency transactional writes (ticks, trade journal), DuckDB for analytical queries over millions of rows (20-50x faster than SQLite for aggregations)
- **Pydantic 2.12**: type-safe configuration validation and data model schemas across all modules -- catches misconfigurations before they cause silent trading errors
- **Textual 8.1 + FastAPI + lightweight-charts-python 2.1**: TUI for primary monitoring, web dashboard for remote access with TradingView-style charting
- **vectorbt 0.28.4**: fastest open-source Python backtesting engine (vectorized, Numba-powered) -- replaces abandoned Backtrader
- **structlog 25.5**: structured logging with context propagation (trade ID, regime state, signal scores) essential for debugging "why did the bot take that trade?"

**Architecture note on MT5 execution path:** STACK.md recommends ZeroMQ (pyzmq) + thin MQL5 EA for order execution. ARCHITECTURE.md recommends using `mt5.order_send()` directly from Python for Phase 1, since the local API call is ~17 microseconds and the broker adds 60-200ms regardless. **Resolution: use the MetaTrader5 Python package directly for Phase 1. Add a watchdog MQL5 EA in Phase 2 as a safety net (independent stop-loss management if Python crashes), not as the primary execution path.** Revisit ZeroMQ only if measured round-trip latency exceeds 200ms in testing.

**Tools:** uv for package management, ruff for linting/formatting, pytest + mypy for testing and type checking, pre-commit for quality gates.

### Expected Features

**Must have (table stakes -- bot is dead without these):**
- Tick data ingestion pipeline (MT5 `copy_ticks_from()` and `symbol_info_tick()` polling)
- Order execution with server-side stop-loss on every trade
- Position sizing engine respecting 0.01 lot minimum and $20 capital constraints
- Spread and slippage awareness (block trades when spread > 2x session average)
- Daily drawdown circuit breaker and kill switch (hard stop, not advisory)
- Session/time filtering (trade only during London-NY overlap for gold)
- Trade logging with full signal context to SQLite
- Reconnection and state recovery (survive MT5 disconnects without orphaned positions)
- Configuration management (TOML-based, separate configs per growth phase)
- Multi-timeframe data access (M1 entries with M5/M15/H1 context)
- Basic backtesting on historical tick data with variable spread modeling

**Should have (differentiators -- the actual edge):**
- Chaos/Fractal Regime Classifier (Hurst + Lyapunov + Fractal Dimension, treated as qualitative indicators)
- Order Flow Microstructure Analysis (volume delta, bid-ask imbalance, tick-level clustering)
- Institutional Footprint Detection (absorption patterns, iceberg detection, large-lot flow)
- Multi-Module Signal Fusion (confidence-weighted combination of orthogonal signals)
- Phase-Aware Capital Management (three growth phases: $20-$100 aggressive, $100-$300 selective, $300+ conservative)
- Walk-Forward + Monte Carlo Validation (anti-overfitting is as important as the strategy)
- Regime-Aware Backtesting (per-regime performance attribution)
- Rich Terminal TUI Dashboard (regime display, signal strengths, P&L, risk exposure)

**Defer to v2+:**
- Self-Learning Mutation Loop -- needs 200+ trades minimum; genetic evolution and ML retraining meaningless without sufficient history
- Feigenbaum Bifurcation Detection -- no off-the-shelf implementation, academic theory only, requires proven regime classifier as foundation
- Advanced Quantum Timing -- single academic paper (Sarkissian), no trading implementations, start with simplified probability windows first
- Full Institutional Footprint (iceberg/HFT signature detection) -- requires high-quality DOM data that may not be available from RoboForex ECN
- Web Dashboard -- TUI is sufficient for single-user monitoring; web adds complexity for marginal benefit in early phases

**Anti-features (deliberately NOT building):**
- Multi-pair trading (destroys XAUUSD focus)
- Grid/martingale strategies (guaranteed account destruction at $20 with 1:500 leverage)
- Deep learning price prediction (overfits catastrophically on small datasets, uninterpretable)
- News calendar as primary signal (institutions already positioned; read the reaction through flow instead)
- Cloud deployment (adds latency between Python and MT5, both must run on same machine)

### Architecture Approach

The system follows a 5-layer event-driven pipeline with 3 cross-cutting systems. All inter-module communication uses an in-process async event bus (`asyncio.Queue` per subscriber). Only the MT5 Bridge touches the MetaTrader5 package directly. The backtesting framework swaps the data source (HistoricalDataFeed replaces LiveDataFeed) while all analysis, decision, and execution logic runs identical code paths -- eliminating "backtest vs live" code divergence.

**Major components:**
1. **MT5 Bridge** -- sole owner of all `mt5.*` calls; wraps synchronous API in `asyncio.to_thread()`; produces RawTick, DOMSnapshot, BarData; consumes TradeRequest
2. **Microstructure Sensor (Module 1)** -- normalizes raw data into MarketState (volume delta, spread dynamics, DOM depth parsing); acts as the nervous system
3. **Institutional Footprint (Module 2)** -- classifies activity as institutional vs retail from flow patterns; produces InstitutionalSignal with direction and confidence
4. **Quantum Timing Engine (Module 3)** -- models price-time as coupled state variables; produces TimingSignal with probability-weighted entry/exit windows
5. **Chaos/Fractal Regime Classifier (Module 4)** -- detects dynamical market state via Hurst, Lyapunov, fractal dimension, bifurcation proximity; produces RegimeState
6. **Decision Core (Module 5)** -- fuses all upstream signals with confidence weighting; applies phase-aware position sizing and risk management; produces TradeRequest or NoAction
7. **Self-Learning Loop (Module 6)** -- journals trades, runs offline genetic optimization in ProcessPoolExecutor, trains shadow models, promotes improvements via versioned config swap; never runs synchronously in the trading loop
8. **Dashboard/Telemetry (Module 7)** -- read-only subscriber to all events; Textual TUI primary, FastAPI web secondary; never produces trading signals
9. **Backtesting Framework (Module 8)** -- replays historical ticks through the same pipeline; walk-forward, Monte Carlo, regime-aware evaluation

**Key patterns:**
- Event Bus (in-process pub/sub) for all inter-module communication
- Async polling loop with `asyncio.to_thread()` for synchronous MT5 calls
- Interface swap (Strategy pattern) for backtesting -- DataFeedProtocol abstraction
- Shadow Model Promotion for safe self-learning -- never modify live params directly
- ProcessPoolExecutor for CPU-intensive chaos math (avoids GIL contention)
- Dual-database (SQLite transactional writes, DuckDB analytical reads)
- Abstracted Clock (real vs simulated) enabling deterministic backtesting

**Key anti-patterns to avoid:**
- Direct MT5 calls from analysis modules (breaks backtesting, creates hidden coupling)
- Synchronous learning in the trading loop (blocks tick processing for seconds/minutes)
- God Object Decision Core (keep signal fusion separate from analysis logic)
- Storing config in the database (use TOML files with hot-reload via ConfigUpdate events)
- `if is_backtesting:` branches (use interface swap instead)

### Critical Pitfalls

1. **Python-MT5 IPC latency makes scalping unreliable** -- The MT5 Python API via `mt5.order_send()` can add 500-800ms total round-trip. Prevention: measure actual latency in Phase 1; if median exceeds 200ms, route execution through a thin MQL5 EA via ZeroMQ. The EA handles `OrderSend()` natively in microseconds. Design the execution layer to be swappable from day one.

2. **$20 micro-account position sizing is mathematically impossible for proper risk management** -- At 0.01 lot minimum, a 20-pip SL = $2 = 10% of account. Prevention: accept elevated risk in Phase 1 ($20-$100), compensate with extreme trade selectivity (1-2 trades/day max, tighter stops), implement fractional Kelly criterion to skip marginal trades, and consider starting on RoboForex ProCent (cent lots) for the $20 phase.

3. **Backtesting overfitting across an 8-module, 40+ parameter system** -- Some parameter combination will always look good on historical data by chance. Prevention: strict temporal separation (train 2015-2020, validate 2021-2023, holdout 2024-2026), walk-forward with rolling windows requiring consistent profitability across ALL windows, Monte Carlo randomization, statistical significance testing (Sharpe > 2.0, minimum 100 out-of-sample trades).

4. **Chaos theory metrics produce numerically meaningless results on noisy financial data** -- Lyapunov exponents are dominated by market microstructure noise; Hurst requires thousands of data points but regimes change faster; finite sample bias makes random walks appear trending. Prevention: use chaos metrics as qualitative regime indicators (rising/falling/stable) not precise numbers; apply noise-robust methods (DFA for Hurst, PCA-based Lyapunov, wavelet fractal dimension); require minimum 500 ticks for Hurst, 1000+ for Lyapunov; validate against null hypothesis (synthetic random data with matched statistical properties).

5. **Self-learning system diverges into self-destruction** -- Positive feedback loops (losing streak triggers aggressive mutation), catastrophic forgetting (overwrites working parameters when regime changes), reward hacking (maximizes position size on high-probability setups). Prevention: hard guardrails the GA cannot override (max position, max daily loss, max drawdown), population diversity enforcement, regime-tagged parameter memory, mandatory walk-forward validation gate before any mutated strategy goes live, human-in-the-loop halt at 20% drawdown.

6. **MT5 connection drops silently during live trading** -- Named pipes break without TCP-style state management; Python continues running with stale data while open positions go unmanaged. Prevention: heartbeat loop every 5-10 seconds checking tick freshness; wrap all MT5 calls in connection-aware wrapper; MQL5 watchdog EA tightens stops to breakeven if Python goes silent; monitor MT5 process via psutil.

7. **XAUUSD spread widening destroys scalping edge during news** -- ECN spreads spike 50-200% during high-impact events; positions opened minutes before news get stopped out by spread alone. Prevention: real-time spread monitor feeding decision engine; block entries when spread > 2x average; 15-minute news blackout; variable spread modeling in backtests (3x perturbation on 5% of ticks).

## Implications for Roadmap

Based on combined research, suggested phase structure:

### Phase 1: Foundation and MT5 Bridge
**Rationale:** Everything depends on reliable data flow and order execution. The synchronous MT5 API must be thread-isolated from day one -- retrofitting this is a near-complete rewrite.
**Delivers:** Live tick data streaming, bar data for multiple timeframes, DOM subscription, order execution path, connection health monitoring with auto-reconnection.
**Addresses features:** Tick data ingestion, Python-MT5 communication bridge, basic order execution, reconnection/state recovery, configuration management (TOML + Pydantic).
**Avoids pitfalls:** MT5 IPC latency (measure round-trip on 100 test orders, median must be <100ms), silent connection drops (heartbeat loop, tick freshness validation), credential exposure (env vars, .gitignore from first commit).
**Stack elements:** MetaTrader5 5.0.5640, asyncio, Pydantic 2.12, structlog, SQLite (tick store).

### Phase 2: Risk Management and Trade Infrastructure
**Rationale:** With $20 at 1:500 leverage, a single unprotected trade can wipe the account. All safety systems must exist before any strategy logic runs. This is survival, not strategy.
**Delivers:** Position sizing engine, stop-loss enforcement, circuit breakers, kill switch, session filtering, trade journal, spread monitoring.
**Addresses features:** Stop-loss on every trade, position sizing for micro accounts, daily drawdown limit, kill switch, session/time filtering, spread/slippage awareness, trade logging to SQLite.
**Avoids pitfalls:** $20 position sizing impossibility (phased risk model, capital adequacy check, fractional Kelly), spread widening destruction (real-time spread monitor, news blackout schedule), order size validation (both Python and EA must reject oversized orders).
**Stack elements:** SQLite (trade journal), Pydantic (risk parameter validation).

### Phase 3: Simplified Signal Pipeline (All Analysis Modules)
**Rationale:** The project's core thesis is that fusion of orthogonal signals creates the edge. Building one perfect module in isolation misses the point. Start all modules in simplified form, then deepen iteratively.
**Delivers:** Basic regime classification (Hurst exponent only), basic order flow (volume delta, bid-ask imbalance), basic timing windows, signal fusion with confidence weighting.
**Addresses features:** Chaos/Fractal Regime Classifier (basic), Order Flow Microstructure (basic), Multi-timeframe context, Multi-Module Signal Fusion (basic weighted average).
**Avoids pitfalls:** Chaos metrics producing garbage (start with single metric -- Hurst -- validate against known market events before adding Lyapunov/fractal dimension), DOM dependency (degrade gracefully to tick-only analysis).
**Stack elements:** nolds (reference), SciPy, Numba (JIT for hot loops), ProcessPoolExecutor (GIL avoidance).
**Architecture:** Each module is an independent package publishing typed signals to the event bus. Decision Core only performs fusion, never duplicates analysis.

### Phase 4: Backtesting and Validation Framework
**Rationale:** Untested strategies are gambling. Walk-forward and Monte Carlo must be embedded from the first backtest run, not added later. The backtesting framework also validates the signal pipeline built in Phase 3.
**Delivers:** Historical tick replay through the same pipeline (interface swap), walk-forward validation with rolling windows, Monte Carlo simulation (10,000+ shuffles), regime-aware performance attribution, variable spread modeling.
**Addresses features:** Basic backtesting, Walk-Forward + Monte Carlo Validation, Regime-Aware Backtesting.
**Avoids pitfalls:** Overfitting (strict temporal separation, walk-forward across ALL windows, statistical significance testing), fixed spread in backtesting (use tick-level bid/ask with perturbation), look-ahead bias (audit all data access patterns, abstracted Clock prevents `time.time()` calls).
**Stack elements:** vectorbt 0.28.4, DuckDB 1.5 + Parquet (analytical queries over historical data), Polars (bulk data pipelines).

### Phase 5: Dashboard and Observability
**Rationale:** Observability enables debugging the signal pipeline. Build after signals exist so there is something to observe. The TUI must not compete with trading logic for CPU.
**Delivers:** Textual TUI showing regime state, signal confidence, open positions, P&L, spread metrics, circuit breaker status. Structured logging to JSON for post-hoc analysis in DuckDB.
**Addresses features:** Rich Terminal TUI Dashboard.
**Avoids pitfalls:** TUI CPU consumption (update at 1-2 second intervals, not every tick), showing chaos metrics as precise numbers (use color-coded ranges and confidence bands instead), P&L updating every tick causing emotional interference (cap at 5-second updates).
**Stack elements:** Textual 8.1, Rich 13.x, structlog (JSON output for DuckDB ingestion).

### Phase 6: Self-Learning and Evolution
**Rationale:** Requires 200+ trades minimum for meaningful evolution. The genetic algorithm needs sufficient trade history to distinguish signal from noise. Cannot meaningfully run until the bot has traded for weeks or completed extensive backtesting.
**Delivers:** Trade outcome forward-labeling, genetic parameter evolution (DEAP), Bayesian hyperparameter optimization (Optuna), shadow model training, versioned config promotion with rollback.
**Addresses features:** Self-Learning Mutation Loop, Phase-Aware Capital Management auto-transitions.
**Avoids pitfalls:** Self-learning divergence (hard guardrails GA cannot override, population diversity enforcement, regime-tagged memory, validation gates before promotion), catastrophic forgetting (retain per-regime parameter sets), survivorship bias in gene pool (force-inject crisis period data into every generation).
**Stack elements:** DEAP 1.4, Optuna 4.8, scikit-learn 1.8 (regime classifiers), ProcessPoolExecutor (offline training).

### Phase 7: Advanced Differentiators and Web Dashboard
**Rationale:** These are the highest-risk, highest-reward features with no existing implementations. They must build on a proven foundation. The web dashboard is deferred here because the TUI is sufficient for single-user monitoring.
**Delivers:** Feigenbaum bifurcation proximity detection, advanced quantum timing (coupled-wave model), full institutional footprint (iceberg reloads, HFT signatures), FastAPI web dashboard with TradingView charts.
**Addresses features:** Feigenbaum Bifurcation Detection, Advanced Quantum Timing, Full Institutional Footprint, Web Dashboard.
**Avoids pitfalls:** Building experimental features before the foundation works. These phases must demonstrate value incrementally -- if bifurcation detection does not improve regime classification measurably, deprioritize it.
**Stack elements:** FastAPI + uvicorn + lightweight-charts-python (web), custom implementations for Feigenbaum/quantum (no off-the-shelf libraries exist).

### Phase Ordering Rationale

- Data and execution (Phase 1) are root dependencies -- nothing works without them
- Risk management (Phase 2) before strategy because $20 accounts die fast without protection; the position sizing module must exist before any live trade
- All modules simplified together (Phase 3) because the project's edge is fusion, not any single module in isolation; each starts as a minimal signal producer
- Backtesting (Phase 4) validates Phases 1-3 before risking real money; embeds anti-overfitting from the first run
- Dashboard (Phase 5) enables debugging but is not on the critical path for trading
- Self-learning (Phase 6) requires trade history that only exists after weeks of Phase 3 trading or extensive Phase 4 backtesting
- Advanced differentiators (Phase 7) are experimental with no reference implementations -- build on proven foundations or not at all

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (Signal Pipeline):** Chaos metrics on financial data require noise-robust estimation methods (DFA, wavelet-based, PCA Lyapunov). Quantum timing has one academic paper. Start minimal and validate empirically.
- **Phase 4 (Backtesting):** Historical tick data quality for XAUUSD pre-2020 from RoboForex is unknown. Combinatorial purged cross-validation for multi-module systems has limited documentation.
- **Phase 6 (Self-Learning):** Regime-aware genetic optimization is novel. No established pattern for genetic population management across regime changes.
- **Phase 7 (Advanced Differentiators):** Feigenbaum bifurcation detection for trading has zero reference implementations. Will require translating academic theory (Batunin, dynamic bifurcations papers) to code from scratch. Quantum-inspired timing based on single paper (Sarkissian).

Phases with standard patterns (skip research-phase):
- **Phase 1 (Foundation):** MT5 Python API is thoroughly documented. Async-first architecture with `asyncio.to_thread()` is a proven pattern (aiomql reference implementation exists).
- **Phase 2 (Risk Management):** Position sizing, circuit breakers, and kill switches are well-documented trading system patterns.
- **Phase 5 (Dashboard):** Textual TUI framework is mature with extensive documentation and examples.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All 25+ packages verified on PyPI with version compatibility confirmed. Python 3.12 ecosystem fully mature. |
| Features (table stakes) | HIGH | Standard trading bot requirements well-understood from multiple sources. |
| Features (chaos/fractal) | MEDIUM | nolds library exists but applying chaos theory to financial data requires careful noise handling. Theoretical basis sound, practical results uncertain. |
| Features (Feigenbaum/quantum) | LOW | No commercial or open-source implementations. Academic papers only. |
| Architecture | HIGH | Event-driven trading systems are mature patterns. Dual-database strategy well-documented. MT5 bridge architecture has multiple reference implementations. |
| Pitfalls | HIGH | 7 critical pitfalls identified with multiple corroborating sources. Python-MT5 latency and overfitting risks especially well-documented. |

**Overall confidence:** HIGH for infrastructure and architecture, MEDIUM for the core trading strategy, LOW for experimental differentiators (Feigenbaum, quantum timing).

### Gaps to Address

- **DOM data quality from RoboForex ECN:** The entire order flow pipeline's effectiveness depends on DOM depth. RoboForex ECN likely provides only 5-10 aggregated levels, not a full institutional order book. Must be tested in Phase 1 and the order flow module designed to degrade gracefully to tick-only analysis.
- **MT5 execution path decision:** STACK.md and ARCHITECTURE.md provide conflicting recommendations (ZeroMQ EA vs direct Python API). Resolution provided above (direct API Phase 1, watchdog EA Phase 2), but actual latency measurement in the target environment must confirm this.
- **Historical tick data quality for XAUUSD 2015-2020:** Pre-2020 data from MT5 may have lower fidelity, gaps, and missing bid/ask spreads. Assess quality in Phase 4 before relying on it for strategy validation.
- **RoboForex ECN execution latency tail distribution:** Average ~45ms is documented, but 99th percentile during news events is unknown. Profile in Phase 1.
- **ProCent vs ECN account decision for $20 phase:** ProCent allows cent-lot sizing (0.001 effective) which solves the position sizing problem but may have different execution quality. Must decide before live trading begins.
- **vectorbt 0.28.4 + NumPy 2.4 edge cases:** Core compatibility confirmed, but exotic simulation scenarios may hit NumPy 2.x API changes. Test thoroughly during Phase 4.
- **Swap costs for overnight XAUUSD positions:** XAUUSD carries significant negative swap. Scalping bot should close all positions before rollover or account for swap in P&L. Must be factored into trade management logic.

## Sources

### Primary (HIGH confidence)
- [MetaTrader5 on PyPI](https://pypi.org/project/metatrader5/) -- v5.0.5640, all API function verification
- [MQL5 Python Integration Docs](https://www.mql5.com/en/docs/python_metatrader5) -- complete API reference
- [MT5 Build 2815 Release Notes](https://www.metatrader5.com/en/releasenotes/terminal/2186) -- DOM access from Python
- [NumPy](https://numpy.org/doc/stable/release.html), [SciPy](https://scipy.org/news/), [Numba](https://numba.readthedocs.io/) -- version and compatibility verification
- [scikit-learn](https://scikit-learn.org/), [Optuna](https://optuna.readthedocs.io/), [DEAP](https://pypi.org/project/deap/) -- ML/optimization stack verification
- [DuckDB](https://github.com/duckdb/duckdb/releases), [Textual](https://textual.textualize.io/), [FastAPI](https://github.com/fastapi/fastapi) -- dashboard and storage verification
- [nolds documentation](https://cschoel.github.io/nolds/) -- chaos/fractal algorithms
- [aiomql Framework](https://github.com/Ichinga-Samuel/aiomql) -- async MT5 architecture reference
- [FIA Best Practices for Automated Trading Risk Controls](https://www.fia.org/sites/default/files/2024-07/FIA_WP_AUTOMATED%20TRADING%20RISK%20CONTROLS_FINAL_0.pdf) -- risk management standards

### Secondary (MEDIUM confidence)
- [Feigenbaum Universality in Stock Indices (Batunin)](https://www.chesler.us/resources/academia/artBatunin.pdf) -- chaos theory application to markets
- [Quantum Coupled-Wave Theory of Price Formation (Sarkissian)](https://www.sciencedirect.com/science/article/abs/pii/S0378437120300911) -- quantum timing theoretical basis
- [Dynamic Bifurcations on Financial Markets](https://www.sciencedirect.com/science/article/abs/pii/S0960077916300844) -- bifurcation detection theory
- [MQL5 Forum: Latency Discussion](https://www.mql5.com/en/forum/465784) -- community benchmark measurements
- [Hurst Exponent Estimation Challenges](https://link.springer.com/article/10.1186/s40854-022-00394-x) -- financial time series estimation limitations
- [Lyapunov Exponent Estimation in Noisy Environments](https://www.sciencedirect.com/science/article/abs/pii/S0096300322005720) -- noise contamination analysis

### Tertiary (LOW confidence, needs validation)
- [lightweight-charts-python](https://pypi.org/project/lightweight-charts/) -- v2.1, last release Sep 2024 (potentially stale)
- [MetaTrader-Python-Tick-Acquisition](https://github.com/UmaisZahid/MetaTrader-Python-Tick-Acquisition) -- single-project tick bridge reference

---
*Research completed: 2026-03-27*
*Ready for roadmap: yes*
