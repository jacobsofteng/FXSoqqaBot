# Stack Research

**Domain:** Python-first XAUUSD scalping bot with chaos theory, order flow analysis, and self-learning on MetaTrader 5
**Researched:** 2026-03-27
**Confidence:** HIGH (all core libraries verified via PyPI/official sources; versions confirmed current)

## Python Runtime

| Decision | Value | Rationale |
|----------|-------|-----------|
| **Python version** | 3.12.x | Best stability-compatibility balance. MT5 package supports 3.6-3.14, but 3.12 has mature ecosystem support across NumPy 2.4, SciPy 1.17, Numba 0.64, and scikit-learn 1.8. Python 3.13's free-threading is experimental and eats 15-20% more memory with no meaningful perf gain for scientific workloads. Stick with 3.12 until 3.13 ecosystem matures. |

---

## Recommended Stack

### MT5 Integration Layer

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| **MetaTrader5** (pip: `metatrader5`) | 5.0.5640 | Python-MT5 bridge: tick data, DOM, order execution, account info | Official MetaQuotes package. Provides `copy_ticks_from()` for tick data, `market_book_get()` for DOM depth, `order_send()` for execution. No alternative exists for direct MT5 integration. Released Feb 2026, actively maintained. | HIGH |
| **pyzmq** | 27.1.0 | ZeroMQ IPC between Python brain and MQL5 EA | The standard for Python-MQL5 bidirectional communication. The MT5 Python package handles data retrieval well, but for sub-100ms execution commands from Python to the EA, ZeroMQ named sockets on localhost are the proven pattern. Multiple open-source MT5-ZMQ bridges exist (Darwinex DWX connector, aminch8/MT5-ZeroMQ). | HIGH |
| **MQL5 EA** (thin) | MT5 native | Order execution, position management, heartbeat | The EA is a thin relay: receives JSON commands over ZMQ, executes `OrderSend()`, reports fills back. All logic stays in Python. Keep the EA under 500 lines. | HIGH |

**Architecture note:** Two communication channels run in parallel:
1. **MetaTrader5 Python package** -- for data retrieval (ticks, OHLCV, DOM snapshots, account state). This is a polling model.
2. **ZeroMQ (pyzmq)** -- for command/response execution. Python sends trade commands; EA responds with fill confirmations. This is a push/pull model with ~1-5ms localhost latency.

### Scientific Computing Core

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| **NumPy** | 2.4.3 | Array operations, linear algebra, FFT | Foundation of the entire scientific stack. Every other library depends on it. NumPy 2.x has significant performance improvements over 1.x. Released Mar 2026. | HIGH |
| **SciPy** | 1.17.1 | Signal processing, optimization, statistical distributions, ODE solvers | Essential for Feigenbaum bifurcation analysis (`scipy.integrate`), fractal spectrum computation (`scipy.signal`), Lyapunov exponent estimation support, and statistical testing for regime detection. Released Feb 2026. | HIGH |
| **Numba** | 0.64.0 | JIT compilation for hot numerical loops | Critical for real-time performance. Chaos theory computations (Lyapunov exponents, correlation dimension, fractal dimension) involve tight loops over time series that are 10-30x slower in pure Python/NumPy. Numba's `@njit` decorator compiles these to machine code. Released Feb 2026. | HIGH |
| **nolds** | 0.6.3 | Nonlinear dynamics measures: Hurst exponent, Lyapunov exponents, correlation dimension, DFA, sample entropy | Purpose-built for exactly our chaos/fractal analysis needs. Implements Rosenstein (lyap_r) and Eckmann (lyap_e) algorithms for Lyapunov exponents, plus Hurst exponent, fractal dimension, and DFA. Small, numpy-only dependency. Use as reference implementation, then re-implement hot paths with Numba for production speed. | HIGH |

### Machine Learning and Optimization

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| **scikit-learn** | 1.8.0 | Regime classification, feature engineering, model evaluation | The hybrid learning core needs classifiers (Random Forest, Gradient Boosting) for market regime detection, plus robust cross-validation and pipeline utilities. scikit-learn is the standard -- no need for deep learning frameworks for regime classification. Released Dec 2025. | HIGH |
| **Optuna** | 4.8.0 | Bayesian hyperparameter optimization for strategy parameters | Superior to grid search or random search for optimizing trading strategy parameters. Uses Tree-structured Parzen Estimators (TPE) by default, supports pruning of bad trials early, has built-in visualization dashboard. Replaces the need for hand-rolled genetic algorithms for parameter tuning. Released Mar 2026. | HIGH |
| **DEAP** | 1.4.3 | Genetic algorithms for evolving trading rules | Optuna handles parameter optimization; DEAP handles rule structure evolution. DEAP supports strongly-typed genetic programming, multi-objective optimization (NSGA-II), and custom mutation operators. Essential for the self-learning mutation loop that evolves rule-based strategies. Released May 2025. | HIGH |

**Why not TensorFlow/PyTorch?** The project uses hybrid learning (rule-based core + ML layers), not deep learning. scikit-learn classifiers are sufficient for regime detection and far simpler to debug, explain, and maintain. If LSTM or attention models are needed later for sequence modeling, add PyTorch then -- but start without it.

### Data Storage and Management

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| **DuckDB** | 1.5.0 | Analytical queries on historical tick data, backtest results, trade logs | Embedded (no server), columnar storage, 10-100x faster than SQLite for analytical queries (aggregations, window functions, time-series slicing). Reads Parquet files directly. Perfect for "give me all ticks where spread > X during London session 2015-2024" queries. Released Mar 2026. | HIGH |
| **Parquet** (via `pyarrow`) | pyarrow 19.x | On-disk storage format for historical tick data | Columnar, compressed, splittable. A year of XAUUSD tick data (~50M+ ticks) fits in ~2-3 GB as Parquet vs 15+ GB as CSV. DuckDB queries Parquet directly without loading into memory. Partition by year/month for efficient access. | HIGH |
| **SQLite** | stdlib | Lightweight transactional storage for trade journal, config, state | For things that need ACID transactions: active trade state, configuration, mutation loop history. SQLite is in Python's stdlib, zero setup, battle-tested. Use DuckDB for analytics, SQLite for operational state. | HIGH |
| **Pydantic** | 2.12.5 | Configuration validation, data model schemas, settings management | Type-safe configuration for all 8 modules. `pydantic-settings` handles env vars and YAML/TOML config files. Validates trade signals, regime states, and module interfaces at runtime. Catches misconfigurations before they cause silent trading errors. | HIGH |

### DataFrame Processing

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| **pandas** | 2.2.x | DataFrame operations, time-series resampling, indicator computation | MetaTrader5 Python package returns data as pandas DataFrames natively. scikit-learn expects pandas input. The entire Python trading ecosystem is built on pandas. Use it as the primary data manipulation layer. | HIGH |
| **Polars** | 1.x | High-performance batch processing for backtesting data pipelines | 5-30x faster than pandas for large aggregations and joins. Use Polars specifically in the backtesting pipeline where you process millions of ticks across years of data. Keep pandas for real-time operations where MT5 returns pandas natively. Do not try to replace all pandas with Polars -- the two coexist well. | MEDIUM |

**Why not replace pandas entirely with Polars?** The MT5 package returns pandas DataFrames. scikit-learn expects pandas. Converting back and forth negates the performance gain. Use Polars only where it matters: bulk backtesting data pipelines processing millions of rows.

### TUI Dashboard (Terminal)

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| **Textual** | 8.1.1 | Rich terminal UI for real-time monitoring | The dominant Python TUI framework in 2026. CSS-like styling, reactive widgets, async-first, can run in browser via `textual-web`. Supports live-updating tables, charts, sparklines, logs. Production/Stable status. MIT licensed. Released Mar 2026. | HIGH |
| **Rich** | 13.x | Console rendering engine (Textual dependency), standalone logging formatting | Textual is built on Rich. Also use Rich directly for structured log output (`rich.logging`) and console rendering outside the TUI app. Same author (Will McGugan / Textualize). | HIGH |

### Web Dashboard

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| **FastAPI** | 0.115.x+ | WebSocket API server for real-time data streaming to web dashboard | Native WebSocket support via Starlette. Async-first. Serves both REST endpoints (historical data, configuration) and WebSocket streams (live ticks, regime state, trade events). Lighter than Dash for our use case since we need a data API, not a full dashboard framework. | HIGH |
| **uvicorn** | 0.41.0 | ASGI server for FastAPI | The standard ASGI server. Use `uvicorn[standard]` for uvloop + httptools performance. Single-worker is fine since this runs on localhost for one user. | HIGH |
| **lightweight-charts-python** | 2.1 | TradingView-style candlestick/tick charts in the web UI | Python wrapper for TradingView's Lightweight Charts JS library. Supports live data updates, multi-pane charts, drawing tools. Purpose-built for financial charting. Can embed in a simple HTML page served by FastAPI. | MEDIUM |
| **Plotly** | 5.x | Interactive analytical charts (equity curves, regime heatmaps, drawdown) | For non-candlestick visualizations: equity curves, regime classification heatmaps, Monte Carlo simulation fans, drawdown charts. Plotly's Python API generates standalone HTML or JSON for the web dashboard. | HIGH |

**Why FastAPI + lightweight-charts instead of Dash?** Dash is heavier than needed. We need a lightweight web dashboard for one user on localhost, not an enterprise analytics platform. FastAPI + WebSocket + lightweight-charts gives us real-time streaming with TradingView-quality charts and full control over the frontend. Dash's callback model adds complexity for real-time data that WebSockets handle natively.

### Backtesting Framework

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| **vectorbt** (open source) | 0.28.4 | High-speed vectorized backtesting, parameter sweeps, Monte Carlo | Fastest open-source Python backtesting engine. Built on pandas/NumPy + Numba. Vectorized execution means testing thousands of parameter combinations in seconds. Supports walk-forward optimization, Monte Carlo simulation, and portfolio-level analysis. | HIGH |
| **Custom engine** (on top of vectorbt) | -- | Regime-aware evaluation, Feigenbaum stress testing, anti-overfitting | vectorbt handles the fast vectorized execution. Build custom layers on top for: regime-tagged performance attribution, out-of-sample regime stress tests, combinatorial purged cross-validation (to prevent lookahead bias). | HIGH |

**Why not Backtrader?** Backtrader's last meaningful release was years ago. It struggles with Python 3.10+ and modern dependencies. The community has moved to vectorbt for research and NautilusTrader for production-grade event-driven backtesting. vectorbt's vectorized approach is 10-100x faster for parameter sweeps.

**Why not vectorbt PRO?** PRO is $20/month with a proprietary license. The open-source version (0.28.4) provides everything we need: vectorized backtesting, Monte Carlo, walk-forward. If features like advanced portfolio optimization or live trading integration are needed later, PRO is a reasonable upgrade path.

### Logging and Observability

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| **structlog** | 25.5.0 | Structured logging with context propagation | Every trade decision flows through 8 modules. structlog binds context (regime state, signal scores, trade ID) that propagates through the entire call chain. JSON output feeds into DuckDB for post-hoc analysis. Critical for debugging "why did it take that trade?" | HIGH |
| **Rich** (logging handler) | 13.x | Pretty console log output during development | Rich's logging handler makes structured logs readable during development. In production, switch to JSON output for machine parsing. | HIGH |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **uv** | Package management and virtual environments | 10-100x faster than pip. Handles venv creation, dependency resolution, and lockfiles. The standard Python package manager in 2026. |
| **ruff** | Linting and formatting | Replaces flake8, isort, black in a single Rust-based tool. Near-instant on large codebases. |
| **pytest** | Testing framework | With `pytest-asyncio` for async tests, `pytest-cov` for coverage. |
| **mypy** | Static type checking | Essential for a complex 8-module system. Catches interface mismatches between modules at dev time, not runtime. |
| **pre-commit** | Git hooks for quality gates | Runs ruff, mypy, and tests before each commit. |

---

## Installation

```bash
# Create virtual environment with uv
uv venv --python 3.12
source .venv/Scripts/activate  # Windows Git Bash

# Core MT5 integration
uv pip install MetaTrader5==5.0.5640 pyzmq==27.1.0

# Scientific computing
uv pip install numpy==2.4.3 scipy==1.17.1 numba==0.64.0 nolds==0.6.3

# Data processing
uv pip install pandas==2.2.3 polars pyarrow duckdb==1.5.0

# ML and optimization
uv pip install scikit-learn==1.8.0 optuna==4.8.0 deap==1.4.3

# Configuration and validation
uv pip install pydantic==2.12.5 pydantic-settings

# TUI dashboard
uv pip install textual==8.1.1 rich

# Web dashboard
uv pip install "fastapi[standard]" uvicorn==0.41.0 plotly lightweight-charts==2.1

# Backtesting
uv pip install vectorbt==0.28.4

# Logging
uv pip install structlog

# Dev dependencies
uv pip install pytest pytest-asyncio pytest-cov mypy ruff pre-commit
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|------------------------|
| **MetaTrader5 (official)** | mt5linux, pymt5 | Only if running on Linux (mt5linux wraps MT5 via Wine). We're on Windows -- use the official package. |
| **pyzmq (ZeroMQ)** | Named Pipes (Win32) | Named pipes are faster (~0.1ms vs ~1ms) but harder to debug and Windows-only. ZeroMQ is cross-platform, well-documented, and 1-5ms is fine for scalping (we're not HFT). |
| **DuckDB + Parquet** | TimescaleDB, InfluxDB | If running a server-based architecture with multiple clients. We're single-machine, embedded -- DuckDB is simpler and faster for our use case. |
| **Optuna** | Hyperopt, Bayesian Optimization | If you need a simpler API. Optuna is more feature-rich (pruning, multi-objective, dashboard) and more actively maintained than hyperopt. |
| **vectorbt (open source)** | vectorbt PRO ($20/mo) | If you need advanced portfolio optimization, live trading integration, or premium support. Open source covers our backtesting needs. |
| **vectorbt** | Backtrader | Never -- Backtrader is effectively abandoned. Use vectorbt for speed or NautilusTrader for event-driven simulation. |
| **Textual** | curses, urwid, prompt-toolkit | If you need something lower-level. Textual is higher-level, more productive, and actively maintained. No reason to go lower-level. |
| **FastAPI + lightweight-charts** | Plotly Dash | If you want an all-in-one dashboard framework with less custom code. Dash is heavier and its callback model is awkward for real-time WebSocket streams. |
| **structlog** | loguru | If you prefer simplicity over structured context propagation. Loguru is great for simple apps; structlog is better for complex multi-module systems where you need context binding (trade ID, regime state, signal scores). |
| **DEAP** | PyGAD, pymoo | If you want a simpler GA library (PyGAD) or pure multi-objective optimization (pymoo). DEAP is more flexible for custom genetic operators needed for rule evolution. |
| **pandas** | Polars (full replacement) | Not recommended yet. MT5 returns pandas natively, scikit-learn expects pandas. Use Polars only for bulk backtesting pipelines. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Backtrader** | Effectively abandoned. No releases in years. Breaks on Python 3.10+. Community has migrated away. | vectorbt for vectorized backtesting |
| **TA-Lib** | C dependency is painful to install on Windows. We're building custom indicators from chaos theory, not standard TA. If needed, pandas-ta is a pure-Python alternative. | NumPy/SciPy for custom indicators, pandas-ta if standard TA needed |
| **TensorFlow** | Massive dependency, GPU-focused, overkill for regime classification. Adds 1+ GB to install and massive startup time. | scikit-learn for regime classification |
| **PyTorch** (at launch) | Same as TensorFlow. If LSTM/attention needed later for sequence modeling, add then. Not for v1. | scikit-learn for v1, add PyTorch only if needed later |
| **Zipline / Zipline-Reloaded** | Designed for equity markets with daily bars. Does not support forex tick data, custom instruments, or the execution model we need. | vectorbt for backtesting |
| **Streamlit** | Script-reruns-on-every-interaction model is wrong for a real-time trading dashboard. Memory grows linearly per connection. No WebSocket support without hacks. | FastAPI + lightweight-charts for web dashboard |
| **MongoDB** | Server-based, document-oriented -- wrong model for time-series tick data analytics. Adds deployment complexity for zero benefit. | DuckDB + Parquet for analytics, SQLite for operational state |
| **Redis** | We're single-machine, single-user. No need for a message broker or cache server. Python's built-in `asyncio.Queue` and in-memory dicts handle inter-module communication. | asyncio.Queue for internal pub/sub |
| **Celery** | Distributed task queue for multi-server architectures. We're single-machine. Use `asyncio` and `concurrent.futures` for parallelism. | asyncio + ThreadPoolExecutor/ProcessPoolExecutor |
| **ccxt** | Crypto exchange library. Does not support MetaTrader 5 or forex brokers. | MetaTrader5 official package |

---

## Stack Patterns by Variant

**If DOM depth data is available from RoboForex ECN:**
- Use `market_book_add()` / `market_book_get()` for real-time DOM snapshots
- Process order book imbalance, absorption detection, iceberg pattern recognition
- Full institutional footprint detection enabled

**If DOM depth data is limited or unavailable:**
- Fall back to tick-level bid/ask spread analysis via `copy_ticks_from()`
- Infer institutional activity from volume spikes, spread widening, and tick velocity
- Disable DOM-dependent signals in the decision fusion layer
- This is the minimum viable data feed

**If backtesting needs to scale beyond single-machine:**
- vectorbt PRO ($20/mo) adds distributed parameter sweeps
- DuckDB can query remote Parquet files on S3
- But this is out of scope for v1 -- single machine is sufficient

**If real-time web dashboard needs to serve multiple users:**
- Add Redis pub/sub for WebSocket fan-out (FastAPI + python-socketio + Redis adapter)
- But this is out of scope -- single localhost user for v1

---

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| MetaTrader5 5.0.5640 | Python 3.6-3.14 | Wide Python version support. Pin to 3.12 for ecosystem compatibility. |
| NumPy 2.4.3 | Numba 0.64.0 | Numba 0.64 explicitly supports NumPy 2.x. Verify with `numba -s` after install. |
| NumPy 2.4.3 | scikit-learn 1.8.0 | scikit-learn 1.8 supports NumPy 2.x. |
| NumPy 2.4.3 | pandas 2.2.x | pandas 2.2 supports NumPy 2.x via pyarrow backend. |
| vectorbt 0.28.4 | NumPy 2.x, Numba 0.64 | vectorbt depends on both. Ensure compatible versions via lockfile. |
| DuckDB 1.5.0 | Python 3.10+ | DuckDB 1.5 dropped Python 3.9 support. Fine with our 3.12 target. |
| Textual 8.1.1 | Python 3.9-3.13 | Wide compatibility. No issues with 3.12. |
| FastAPI 0.115+ | uvicorn 0.41.0 | FastAPI + uvicorn are tightly coupled. Install via `fastapi[standard]`. |
| Pydantic 2.12.5 | FastAPI 0.115+ | FastAPI requires Pydantic v2. Included automatically. |

---

## Inter-Module Communication Architecture

The 8-module system needs a clean internal communication pattern:

```
Module Communication (all in-process, same Python runtime):

  MT5 Data  -->  [asyncio.Queue]  -->  Microstructure Sensor
                                           |
                                    [shared state dict]
                                           |
              +----+----+----+----+--------+
              v    v    v    v    v
           Inst  Quant Chaos  ...  (analysis modules)
              |    |    |    |
              v    v    v    v
           [signal bus: asyncio.Queue or dataclass events]
              |
              v
         Decision Core  -->  [ZeroMQ]  -->  MQL5 EA  -->  MT5
              |
              v
         Trade Journal  -->  [DuckDB/SQLite]
              |
              v
         Self-Learning Loop  -->  [Optuna/DEAP]
```

**Internal pub/sub:** Use `asyncio.Queue` instances for inter-module communication. No external message broker needed for single-process architecture.

**Shared state:** Use Pydantic models as immutable snapshots of module state. Modules publish state updates; consumers read the latest snapshot.

**External communication:** Only ZeroMQ crosses process boundaries (Python <-> MQL5 EA).

---

## Sources

- [MetaTrader5 on PyPI](https://pypi.org/project/metatrader5/) -- version 5.0.5640, Feb 2026
- [MQL5 Python Integration docs](https://www.mql5.com/en/docs/python_metatrader5) -- copy_ticks_from, market_book_get API
- [NumPy releases](https://numpy.org/doc/stable/release.html) -- v2.4.3, Mar 2026
- [SciPy news](https://scipy.org/news/) -- v1.17.1, Feb 2026
- [scikit-learn releases](https://scikit-learn.org/stable/whats_new.html) -- v1.8.0, Dec 2025
- [Numba release notes](https://numba.readthedocs.io/en/stable/release-notes-overview.html) -- v0.64.0, Feb 2026
- [Optuna docs](https://optuna.readthedocs.io/) -- v4.8.0, Mar 2026
- [DEAP on PyPI](https://pypi.org/project/deap/) -- v1.4.3, May 2025
- [nolds on PyPI](https://pypi.org/project/nolds/) -- v0.6.3
- [nolds documentation](https://cschoel.github.io/nolds/) -- Hurst, Lyapunov, fractal dimension algorithms
- [DuckDB releases](https://github.com/duckdb/duckdb/releases) -- v1.5.0, Mar 2026
- [vectorbt on PyPI](https://pypi.org/project/vectorbt/) -- v0.28.4
- [Textual on PyPI](https://pypi.org/project/textual/) -- v8.1.1, Mar 2026
- [FastAPI releases](https://github.com/fastapi/fastapi/releases) -- v0.115+
- [uvicorn on PyPI](https://pypi.org/project/uvicorn/) -- v0.41.0, Feb 2026
- [pyzmq on PyPI](https://pypi.org/project/pyzmq/) -- v27.1.0, Sep 2025
- [lightweight-charts-python on PyPI](https://pypi.org/project/lightweight-charts/) -- v2.1, Sep 2024
- [Pydantic on PyPI](https://pypi.org/project/pydantic/) -- v2.12.5, Nov 2025
- [structlog docs](https://www.structlog.org/) -- v25.5.0
- [Darwinex DWX ZeroMQ connector](https://github.com/darwinex/dwx-zeromq-connector) -- MT5-ZMQ bridge reference
- [Polars vs Pandas benchmarks (2026)](https://docs.kanaries.net/articles/polars-vs-pandas) -- 5-30x faster for analytical workloads
- [Python backtesting landscape (2026)](https://python.financial/) -- vectorbt vs backtrader comparison
- [MQL5 named pipes article](https://www.mql5.com/en/articles/115) -- IPC alternatives for MT5

---
*Stack research for: Python-first XAUUSD scalping bot with chaos theory on MetaTrader 5*
*Researched: 2026-03-27*
