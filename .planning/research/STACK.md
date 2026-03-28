# Stack Research: v1.1 Live Demo Launch

**Domain:** Forex scalping bot -- signal calibration, live execution reliability, optimization performance, demo monitoring
**Researched:** 2026-03-28
**Confidence:** HIGH (most recommendations leverage already-installed packages or stdlib)

## Context

v1.0 shipped with the full scientific/ML/execution stack already installed (see pyproject.toml). This research focuses ONLY on what v1.1 needs beyond the existing stack for four new capability areas:

1. **Signal calibration** -- threshold sensitivity analysis, parameter sweep visualization
2. **MT5 live execution reliability** -- reconnection hardening, heartbeat, position sync
3. **Automated optimization performance** -- parallel Optuna trials, Numba cache management
4. **Demo monitoring/alerting** -- log rotation, health alerting, crash detection

The key finding: **v1.1 needs almost no new dependencies.** The existing stack (Optuna 4.8, Plotly 5.x, structlog 25.5, Numba 0.64) already provides the building blocks. What is needed is configuration changes, patterns, and at most 2 small additions.

---

## Recommended Stack Additions

### Signal Calibration Tooling

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **optuna.visualization** (built-in) | 4.8.0 (already installed) | Parameter importance, contour plots, parallel coordinate for threshold sensitivity | Already bundled with Optuna. `plot_param_importances()`, `plot_contour()`, `plot_parallel_coordinate()` generate interactive Plotly figures directly from Optuna Study objects. Zero new code for sensitivity analysis visualization -- just call the functions after optimization completes. Uses Plotly + scikit-learn under the hood, both already installed. |
| **Plotly** (already installed) | 5.x | Heatmaps for parameter sweep results, threshold sensitivity surfaces | Already in pyproject.toml. Use `go.Heatmap()` for 2D parameter sweep results (e.g., confidence_threshold vs. trade_frequency). `plotly.io.write_html()` saves interactive reports to disk -- no server needed. |
| **optuna-dashboard** | 0.20.x | Real-time web UI for watching optimization trials, inspecting parameter relationships | **NEW dependency.** Lightweight web app that reads Optuna storage and shows live trial progress, hyperparameter importance, and optimization history. Install with `pip install optuna-dashboard`, run with `optuna-dashboard sqlite:///study.db`. Provides value during optimization runs without custom code. Can also run as VS Code extension. Only needed during development/tuning, not at runtime. |

**What NOT to add for calibration:**
- No Dash/Streamlit -- overkill for generating static analysis reports. Plotly + `write_html()` is sufficient.
- No custom visualization framework -- Optuna's built-in viz covers 90% of what is needed for parameter sensitivity.

### MT5 Live Execution Reliability

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **MetaTrader5** (already installed) | 5.0.5640 | `positions_get(symbol=, group=)`, `terminal_info()`, `account_info()` for position sync and health checks | No new package needed. The existing MT5Bridge already has `reconnect_loop()` with exponential backoff, `ensure_connected()` via `terminal_info()`, `get_positions()`, and `close_all_positions()`. What is needed is PATTERN changes, not library changes: (1) position reconciliation after reconnect using `magic_number` filtering, (2) heartbeat interval tightening from 10s to 5s in the health loop, (3) position state diffing between local tracked positions and MT5 server positions. |
| **asyncio** (stdlib) | 3.12 stdlib | Heartbeat task, watchdog timer, event loop health monitoring | No new package needed. Use `asyncio.wait_for()` for timeout-guarded MT5 calls. Track `time.monotonic()` of last successful MT5 response as a "last heartbeat" value. If stale beyond threshold (e.g., 30s), trigger reconnection. Measure event loop lag by timing `asyncio.sleep(0)` wake-up delay -- if consistently >100ms, the loop is overloaded. |
| **tomli-w** (already installed) | 1.x | Write position state snapshots to TOML for crash recovery | Already in pyproject.toml as a dependency. Use for writing position state on each fill event so crash recovery can reconcile on restart. |

**What NOT to add for execution reliability:**
- No ZeroMQ (pyzmq) yet -- the MT5 Python package handles all data retrieval and `order_send()` directly. ZeroMQ is only needed if we move to a separate MQL5 EA execution layer, which is out of scope for v1.1 demo.
- No aiomql -- while it wraps MT5 in async, our MT5Bridge already does this correctly with `ThreadPoolExecutor(max_workers=1)`. Adding aiomql would create two competing MT5 wrappers. Stick with our bridge.
- No watchdog (filesystem monitor) -- unnecessary complexity. The health loop already monitors connection state. Add a monotonic heartbeat timestamp instead.

### Automated Optimization Performance

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Optuna JournalStorage** (built-in) | 4.8.0 (already installed) | File-based storage backend for multi-process parallel optimization on single machine | Already part of Optuna -- `from optuna.storages import JournalStorage` and `from optuna.storages.journal import JournalFileBackend`. Current optimizer uses in-memory storage and `asyncio.run()` per trial in a single process. To parallelize, switch to `JournalStorage(JournalFileBackend("./optuna_journal.log"))` and use `multiprocessing.Pool` to run N workers sharing the same study via the journal file. This is the officially recommended approach for single-machine multi-process optimization -- no database server needed, no SQLite locking issues. |
| **multiprocessing** (stdlib) | 3.12 stdlib | Spawn parallel optimization workers | Use `multiprocessing.Pool(processes=N)` where N = CPU cores - 1 (leave one core for system). Each worker calls `study.optimize(objective, n_trials=trials_per_worker)` against the shared JournalStorage. The TPE sampler handles concurrent trial suggestions correctly. |
| **Numba cache** (already installed, needs configuration) | 0.64.0 | Persistent JIT compilation cache to eliminate cold-start penalty | All `@njit(cache=True)` decorators are already in `_numba_core.py`. Two changes needed: (1) Set `NUMBA_CACHE_DIR` environment variable to a stable project-local path (e.g., `.numba_cache/`) so cache persists across venv rebuilds, and (2) call `warmup_jit()` once at process start in the optimizer workers before trials begin. First run compiles ~8 JIT functions (~5-10s), subsequent runs load from `.nbi/.nbc` cache files instantly. |

**What NOT to add for optimization performance:**
- No Dask -- overkill for single-machine parallelism. `multiprocessing.Pool` + JournalStorage achieves the same result with zero infrastructure.
- No joblib -- while Optuna historically considered joblib integration, `multiprocessing.Pool` with JournalStorage is the current officially documented approach. Joblib adds a dependency for no additional benefit here.
- No Redis/PostgreSQL for Optuna storage -- JournalFileBackend is purpose-built for this exact scenario (multi-process, single machine, file-based, no server).
- No Polars for backtest acceleration yet -- the optimization bottleneck is the signal pipeline computation per bar, not DataFrame operations. Profile first before switching the backtest data path.

### Demo Monitoring and Alerting

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **structlog + stdlib logging handlers** (already installed) | structlog 25.5.0 + Python 3.12 stdlib | JSON log rotation for production demo runs | structlog's `ProcessorFormatter` integrates with any stdlib `logging.Handler`. Use `logging.handlers.RotatingFileHandler(maxBytes=10_485_760, backupCount=10)` for 10MB rotating log files. Keep console output (Rich renderer) for interactive sessions, add file handler with JSON renderer for demo runs. Both handlers can coexist through structlog's standard library integration. Zero new dependencies. |
| **desktop-notifier** | 6.2.0 | **NEW dependency.** Windows toast notifications for critical alerts (kill switch, circuit breaker, crash recovery) | Async-native (`await notifier.send()`), integrates cleanly with the existing asyncio event loop. Supports clickable notifications with action buttons. Pure Python on Linux/macOS, uses WinRT bridge on Windows. Lightweight alternative to Apprise (which adds 130+ service integrations we do not need). Only fires for critical events: kill switch activation, circuit breaker trips, MT5 disconnection, crash recovery completion. |
| **DuckDB** (already installed) | 1.5.0 | Query JSON log files for post-hoc analysis, aggregate trade performance metrics | Already installed. structlog JSON output can be loaded directly: `SELECT * FROM read_json_auto('logs/*.json')`. Enables queries like "show me all trades where fusion_confidence < 0.5" or "average signal latency by regime" without custom parsing. This is the existing analytics stack, just pointed at log files. |

**What NOT to add for monitoring:**
- No Prometheus/Grafana -- server-based monitoring is overkill for a single-machine demo. DuckDB queries on JSON logs provide equivalent analytical capability without infrastructure.
- No Apprise -- supports 130+ notification services. We need exactly one: Windows toast notifications. desktop-notifier is smaller, async-native, and purpose-built.
- No plyer -- older library, synchronous API, broader scope than needed. desktop-notifier is modern, async, and focused on notifications.
- No Sentry/error tracking -- for a demo running on the developer's machine, structlog JSON + DuckDB queries are sufficient for debugging. Add Sentry only if the bot runs unattended for weeks.

---

## Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **optuna-dashboard** | 0.20.x | Web UI for inspecting optimization studies | During parameter tuning sessions. Run `optuna-dashboard sqlite:///study.db` after converting journal to SQLite, or use JournalStorage directly. Dev-only tool, not needed at runtime. |
| **desktop-notifier** | 6.2.0 | Windows toast notifications for critical trading alerts | In live/demo mode only. Silent in paper mode. Fire on: kill switch, circuit breaker trip, MT5 disconnect >60s, crash recovery. |

---

## Development Tools

No new development tools needed. Existing ruff, mypy, pytest, pre-commit cover v1.1 requirements.

| Tool | v1.1 Usage Notes |
|------|-----------------|
| **pytest** | Add integration tests for MT5 position reconciliation (mock MT5 responses). Test optimization parallelization with 2 workers on small datasets. |
| **mypy** | Type-check new position sync dataclasses and notification interfaces. |

---

## Installation

```bash
# NEW dependencies for v1.1 (only 2 packages)
uv pip install optuna-dashboard desktop-notifier

# Everything else is already installed from v1.0
# Verify with: uv pip list | grep -E "optuna|desktop"
```

Add to `pyproject.toml` dependencies:

```toml
# In [project] dependencies, add:
"optuna-dashboard>=0.20",
"desktop-notifier>=6.0",
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|------------------------|
| **optuna.visualization (built-in)** | Custom Plotly dashboards | Only if Optuna's built-in plots lack specific chart types needed. For v1.1, the built-in plots cover threshold sensitivity, parameter importance, and contour analysis. |
| **optuna-dashboard** | Optuna + Plotly static reports | If you want zero new dependencies. Generate HTML reports with `plotly.io.write_html()` after each optimization run instead of running a dashboard server. Loses real-time trial monitoring. |
| **JournalStorage (file-based)** | RDBStorage (SQLite/PostgreSQL) | If you need complex queries on trial data or long-term study persistence. SQLite RDBStorage works but has concurrency limitations with multi-process. JournalStorage is explicitly designed for multi-process on single machine. |
| **multiprocessing.Pool** | concurrent.futures.ProcessPoolExecutor | Equivalent functionality. ProcessPoolExecutor is slightly more modern API but Pool has more documentation for Optuna patterns. Either works. |
| **desktop-notifier** | Apprise | If you want multi-channel alerting (Telegram, Discord, Slack, email) in addition to Windows toast. Apprise supports 130+ services. Add it later if the demo graduates to unattended multi-day runs where you need remote alerting. |
| **desktop-notifier** | plyer | Never. plyer is synchronous, bloated (GPS, accelerometer, Bluetooth APIs we do not need), and does not integrate with asyncio. desktop-notifier is async-native and focused. |
| **RotatingFileHandler (stdlib)** | loguru with rotation | If you want simpler log rotation syntax. But structlog is already deeply integrated (contextvars, JSON renderer, component binding). Adding loguru creates two logging systems. Stick with structlog + stdlib handlers. |
| **NUMBA_CACHE_DIR env var** | Numba AOT compilation | If startup time is critical (sub-second). AOT compiles to a .pyd/.so that loads instantly. But AOT requires specifying exact function signatures upfront and does not support all Numba features. JIT cache with `cache=True` is simpler and already works. Use AOT only if cache warm-up remains a problem after NUMBA_CACHE_DIR is set. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **pyzmq / ZeroMQ** (for v1.1) | The MT5 Python package handles all needed communication. ZeroMQ is for a separate MQL5 EA execution layer, which is out of scope until the bot needs sub-10ms execution or runs logic the Python package cannot access. | MetaTrader5 Python package directly via MT5Bridge |
| **aiomql** | Competes with our existing MT5Bridge. Would require rewriting all execution code to use a different API surface. Our bridge already handles async correctly via ThreadPoolExecutor(1). | Existing MT5Bridge with pattern improvements |
| **Dask / Ray** | Distributed computing frameworks for multi-machine optimization. We are single-machine. Adds massive dependency tree for zero benefit. | multiprocessing.Pool + Optuna JournalStorage |
| **Celery** | Task queue for distributed systems. We are single-process with multiprocessing for optimization only. | multiprocessing.Pool |
| **Prometheus + Grafana** | Server-based monitoring stack. Requires running two additional services. Overkill for single-developer demo monitoring. | structlog JSON + DuckDB queries + desktop-notifier for alerts |
| **Sentry** | Cloud error tracking. For a demo on the developer's machine, local JSON logs are sufficient. Add only if the bot runs unattended for weeks remotely. | structlog JSON logs analyzed with DuckDB |
| **Streamlit** | Considered for calibration UI. Wrong architecture -- script reruns on every interaction, no persistent state, growing memory per session. | Optuna built-in visualization + optuna-dashboard |
| **Polars** (for optimization acceleration) | The optimization bottleneck is signal pipeline computation per bar, not DataFrame I/O. Switching pandas to Polars in the backtest engine would not improve trial speed. Profile first. | Focus on Numba cache and parallel trials |

---

## Stack Patterns by Variant

**If optimization is the bottleneck (most likely):**
- Use JournalStorage + multiprocessing.Pool for N parallel trials
- Set NUMBA_CACHE_DIR for persistent JIT compilation cache
- Each worker process gets its own event loop for async backtest engine
- Expected speedup: ~3-4x on 4-core machine (limited by CPU, not I/O)

**If MT5 reconnection is unstable:**
- Tighten health_loop interval from 10s to 5s
- Add monotonic heartbeat tracking (last_mt5_response_time)
- Position reconciliation on reconnect: query positions_get(symbol="XAUUSD"), filter by magic_number, diff against local state
- desktop-notifier fires on disconnect >30s and on reconnect

**If signal calibration needs interactive exploration:**
- optuna-dashboard provides real-time trial inspection during optimization
- After optimization, generate static HTML reports with optuna.visualization + plotly.io.write_html()
- For custom sweep analysis not covered by Optuna, use Plotly go.Heatmap() with pandas pivot tables

**If demo runs need post-hoc analysis:**
- structlog JSON mode writes machine-parseable logs
- RotatingFileHandler keeps disk usage bounded (10 files x 10MB = 100MB max)
- DuckDB reads JSON logs directly: `SELECT * FROM read_json_auto('logs/trading_*.json')`
- Query patterns: trades by regime, signal latency distribution, fusion confidence histogram

---

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| optuna-dashboard 0.20.x | Optuna 4.8.0 | optuna-dashboard tracks Optuna releases. v0.20 works with Optuna 3.x and 4.x. Reads any Optuna storage backend. |
| optuna-dashboard 0.20.x | Plotly 5.x | Uses Plotly for chart rendering. Already installed. |
| desktop-notifier 6.2.0 | Python 3.9+ | Requires `winrt-Windows.UI.Notifications` on Windows (installed automatically as dependency). Async-native, requires running event loop. |
| desktop-notifier 6.2.0 | asyncio (stdlib) | Uses `async/await` API. Call `await notifier.send()` from within the existing asyncio engine loops. |
| Optuna JournalStorage | multiprocessing (stdlib) | File-based locking ensures safe concurrent access. No special configuration needed beyond file path. |
| Numba 0.64 cache | NUMBA_CACHE_DIR env var | Set before any Numba import. Cache files are CPU-architecture-specific -- not portable between machines but persist across Python/venv rebuilds if Numba version matches. |
| RotatingFileHandler | structlog 25.5.0 | Use structlog's `ProcessorFormatter` as the formatter for the stdlib handler. Documented integration pattern. |

---

## Configuration Changes (No New Packages)

These improvements need code/config changes only -- no new dependencies:

| Change | What | Why |
|--------|------|-----|
| **NUMBA_CACHE_DIR** | Set env var to `.numba_cache/` in project root | Persistent JIT cache survives venv rebuilds. Eliminates 5-10s cold start on optimization workers. |
| **Health loop interval** | Reduce from 10s to 5s | Faster detection of MT5 disconnection during live demo. |
| **Heartbeat tracking** | Add `last_mt5_response_time = time.monotonic()` | Detect stale connections where `terminal_info()` returns True but data has stopped flowing. |
| **Position reconciliation** | On reconnect, diff `positions_get()` against local state | Catch positions that were opened/closed while disconnected. Filter by `magic_number=20260327`. |
| **Log file handler** | Add RotatingFileHandler alongside console | JSON logs to `logs/trading_YYYYMMDD.json` for post-hoc analysis. Keep console output for interactive use. |
| **structlog dual output** | Console (Rich) + File (JSON) simultaneously | Development sees pretty output, production gets machine-parseable JSON on disk. |
| **Optimization storage** | Switch from in-memory to JournalStorage | Enables multi-process parallelism AND persists study results for later analysis with optuna-dashboard. |

---

## Sources

- [Optuna 4.8.0 Easy Parallelization docs](https://optuna.readthedocs.io/en/stable/tutorial/10_key_features/004_distributed.html) -- JournalStorage, multi-process patterns
- [Optuna 4.8.0 Visualization docs](https://optuna.readthedocs.io/en/stable/reference/visualization/index.html) -- built-in plot functions
- [Optuna JournalStorage stabilization (Optuna blog)](https://medium.com/optuna/introducing-the-stabilized-journalstorage-in-optuna-4-0-from-mechanism-to-use-case-e320795ffb61) -- JournalFileBackend design rationale
- [optuna-dashboard on PyPI](https://pypi.org/project/optuna-dashboard/) -- v0.20.x, real-time web UI
- [optuna-dashboard on GitHub](https://github.com/optuna/optuna-dashboard) -- VS Code extension, JupyterLab support
- [desktop-notifier on PyPI](https://pypi.org/project/desktop-notifier/) -- v6.2.0, async Windows notifications
- [desktop-notifier on GitHub](https://github.com/samschott/desktop-notifier) -- async API, WinRT bridge
- [Numba caching docs](https://numba.readthedocs.io/en/stable/developer/caching.html) -- cache=True, NUMBA_CACHE_DIR, .nbi/.nbc files
- [Numba environment variables](https://numba.readthedocs.io/en/stable/reference/envvars.html) -- NUMBA_CACHE_DIR configuration
- [structlog standard library integration](https://www.structlog.org/en/stable/standard-library.html) -- ProcessorFormatter with stdlib handlers
- [Python logging.handlers](https://docs.python.org/3/library/logging.handlers.html) -- RotatingFileHandler
- [MQL5 positions_get() docs](https://www.mql5.com/en/docs/python_metatrader5/mt5positionsget_py) -- magic number filtering, position attributes
- [MQL5 Python Integration docs](https://www.mql5.com/en/docs/python_metatrader5) -- terminal_info, order_send, reconnection
- [Optuna SQLite locking issue #820](https://github.com/optuna/optuna/issues/820) -- why JournalStorage over SQLite for parallel
- [Optuna n_jobs threading limitation #1480](https://github.com/optuna/optuna/issues/1480) -- why multiprocessing.Pool over n_jobs

---
*Stack research for: FXSoqqaBot v1.1 Live Demo Launch*
*Researched: 2026-03-28*
