# Project Research Summary

**Project:** FXSoqqaBot v1.1 Live Demo Launch
**Domain:** XAUUSD scalping bot — signal recalibration, paper-to-live transition, automated optimization, unattended demo operation
**Researched:** 2026-03-28
**Confidence:** HIGH

## Executive Summary

FXSoqqaBot v1.0 shipped a complete 14.8K LOC signal-to-execution pipeline with 772+ passing tests, but the bot generates approximately 20 trades per 3 months instead of the target 10-20 per day. Research across all four areas confirms this is a calibration problem, not an architectural one. Three compounding bugs in the signal pipeline — the chaos module returning `direction=0.0` for 60-80% of market time, timing urgency applied twice (once internally in `ou_model.py`, once externally in `module.py`), and fusion thresholds calibrated against the resulting broken signal math — combine to choke trade flow to near zero. The signal pipeline must be fixed before any other optimization or execution work can produce meaningful results.

The paper-to-live transition is largely already built. `OrderManager.place_market_order()` has a clean paper/live branch, `order_check()` pre-validation exists, and `MT5Bridge` wraps all blocking calls in a single-thread executor. The missing pieces are targeted: live position lifecycle management (no mechanism to detect when server-side SL/TP fires), position reconciliation on crash/restart, and the `modify_sl()` method whose call site exists but implementation does not. These are additions to existing components, not new architectural layers. The automated optimization pipeline is also architecturally complete but cannot run to completion because the backtest it invokes floods 57M+ potential debug log lines across 3.8M bars — a fix already implemented in the optimizer (cli.py:542-546) but not yet applied to the backtest runner.

The correct execution sequence for v1.1 is strict: fix signal pipeline bugs, then fix backtest performance, then run optimization to get data-driven parameters, then wire live execution against those parameters, then harden for a week-long unattended demo. Skipping ahead — most dangerously, lowering fusion thresholds before fixing chaos direction and timing urgency — will produce single-module-driven noise trades with sub-40% win rates and no genuine edge. The stack requires only two new packages (`optuna-dashboard` and `desktop-notifier`); everything else is already installed.

---

## Key Findings

### Recommended Stack

The v1.0 stack (Optuna 4.8, Numba 0.64, structlog 25.5, DuckDB 1.5, vectorbt 0.28, Textual 8.1, FastAPI) already provides every capability needed for v1.1. Research identified only two net-new dependencies:

**New for v1.1:**
- `optuna-dashboard` 0.20.x: Real-time web UI for trial inspection during optimization — reads any Optuna storage backend; dev-only tool, zero runtime cost
- `desktop-notifier` 6.2.0: Async-native (`await notifier.send()`) Windows toast notifications for critical trading events (kill switch, circuit breaker trip, MT5 disconnect >30s) — WinRT bridge on Windows, smaller and more focused than Apprise

**Configuration changes (no new packages):**
- `NUMBA_CACHE_DIR` env var to `.numba_cache/` — eliminates 5-10s JIT cold-start on optimization workers; cache survives venv rebuilds
- Optuna storage switched from in-memory to `JournalStorage(JournalFileBackend(...))` — enables multi-process parallel trials (multiprocessing.Pool, not `n_jobs`) and persists study for optuna-dashboard replay
- structlog dual output: Rich console for interactive sessions, `RotatingFileHandler` + JSON for demo week (10MB x 10 files = 100MB max disk usage bounded)

**What NOT to add:** ZeroMQ/MQL5 EA bridge (Python MT5 package handles order_send at 1-5ms, sufficient for scalping), aiomql (competes with existing MT5Bridge), Prometheus/Grafana (overkill for single-machine demo), Polars for optimization acceleration (bottleneck is signal computation per bar, not DataFrame I/O — profile first before switching).

See `.planning/research/STACK.md` for full version compatibility matrix and alternatives considered.

### Expected Features

Research identifies four priority tiers based on what blocks the demo launch vs what enhances it.

**Must have — P0 (bot cannot trade without these):**
- Chaos direction fix for non-trending regimes — `direction_map` in `chaos/module.py` lines 122-129 returns `0.0` for RANGING, HIGH_CHAOS, and PRE_BIFURCATION, covering 60-80% of gold's market time; fusion formula `direction * confidence * weight = 0` regardless of confidence when direction is zero
- Timing urgency double-application fix — urgency applied at `ou_model.py` line 127 (inside `window_conf`) AND again at `module.py` line 136 (outer multiplier); if urgency=0.5, effective scaling is 0.25, collapsing timing confidence to 0.15-0.25 range
- Fusion threshold reduction — `aggressive_confidence_threshold=0.50` was calibrated against broken signal math; correct value after fixing is data-driven, likely 0.25-0.35; do NOT set before measuring the new distribution
- Position sizing for $20 equity — XAUUSD M5 ATR $2-6 produces SL distances that make 0.01 minimum lot yield 15-25% actual risk, which the sizer correctly rejects; fix via ATR multiplier 1.0-1.5x + aggressive_risk_pct 15-20%
- Circuit breaker recalibration — 5% daily drawdown at $20 = $1.00 = less than one losing trade; must become phase-aware (15-20% for aggressive demo phase)

**Must have — P1 (required for demo launch):**
- Multiple concurrent positions (2-3) — single position limit forces average hold times under 48 minutes to hit 10-20 trades/day; 2-3 positions provide realistic flexibility with per-position + aggregate risk check
- Live MT5 execution on demo account — code path exists but untested; needs order_check retcode handling (10004=requote, 10013=invalid, 10014=invalid volume, 10015=invalid stops), live.toml credentials, `mt5.symbol_select("XAUUSD", True)` at startup
- Trailing stop implementation — `TradeManager.get_trailing_params()` exists but `modify_sl` call site in trade_manager.py lines 176-178 points to a method that does not exist on OrderManager; implement via `TRADE_ACTION_SLTP`
- Automated optimization with expanded search space — current 11-param Optuna search covers only FusionConfig; must add chaos thresholds, timing urgency exponent, sl_atr_multiplier, concurrent positions to find parameters that produce target trade frequency

**Should have — P2 (add during demo week once core is running):**
- Multi-objective optimization (profit factor + trade count Pareto front via NSGAIISampler)
- Position sync on startup after crash (query positions_get(), filter by magic_number, adopt orphaned positions)
- Trade journal logging `should_trade=False` decisions with reason codes (not just successful trades)

**Defer — v1.2+:**
- Self-learning loop activation — needs 1000+ trade history; 1-week demo at 10-20/day yields 70-140 trades, below the threshold where evolution is reliable
- ZeroMQ MQL5 execution bridge — only warranted if measured Python MT5 round-trip exceeds 200ms, which it does not on localhost
- VPS deployment, real-money transition (minimum 2 weeks profitable demo with 500+ trades)

**Never build for v1.1:** Standard TA indicators (RSI, MACD, Bollinger) as primary signals — dilutes the chaos/flow/timing fusion edge; deep learning for signal generation — opaque, GPU-dependent, catastrophic overfitter on small datasets.

See `.planning/research/FEATURES.md` for complete dependency graph, competitor analysis, and P0-P3 priority matrix with implementation math.

### Architecture Approach

The v1.0 architecture is well-structured and requires no structural changes for v1.1. The existing signal→fusion→trade manager→order manager→MT5Bridge pipeline is clean, the paper/live branch is a single conditional in `OrderManager.place_market_order()`, and the BacktestEngine uses the same signal pipeline as the live engine. All v1.1 changes are targeted modifications to existing components plus one new sub-component.

**Components and their v1.1 status:**

1. **ChaosRegimeModule** (`signals/chaos/module.py`) — MODIFY: recalibrate `direction` computation from binary +1/-1/0 to a continuous [-1,1] value derived from Hurst+price momentum; the `direction_map` returning 0 for 3 of 5 regimes is the root cause of zero trades
2. **QuantumTimingModule** (`signals/timing/module.py`) — MODIFY: remove outer `* urgency` on line 136; urgency already incorporated in `window_conf` via `ou_model.py` line 127; one-line fix
3. **BacktestEngine + Runner** (`backtest/engine.py`, `backtest/runner.py`) — MODIFY: apply `structlog.make_filtering_bound_logger(logging.WARNING)` (model: cli.py lines 542-546 which the optimizer already uses); pre-warm Numba JIT once before walk-forward loop, not per window
4. **OrderManager** (`execution/orders.py`) — MODIFY: add `modify_sl()` using `TRADE_ACTION_SLTP` action; add retcode handling for requotes and invalid stops
5. **MT5Bridge** (`execution/mt5_bridge.py`) — MODIFY: add `get_deal_history(ticket)` for live close detection; tighten health_loop interval from 10s to 5s; add monotonic `last_mt5_response_time` tracking; expand reconnect_loop to infinite retry with capped backoff for week-long unattended operation
6. **TradingEngine** (`core/engine.py`) — MODIFY: add `_check_live_positions()` to detect server-side SL/TP fires; add heartbeat log entry in health_loop; fix Windows SIGINT handling (add_signal_handler fails on Windows, use `signal.signal()` instead)
7. **Optimizer** (`optimization/optimizer.py`) — EXPAND: switch to JournalStorage; expand search space from 11 to ~20 params; add NSGAIISampler for multi-objective

**New sub-component required (one):** A position monitor within `_tick_loop` or `_health_loop` that polls `bridge.get_positions()`, detects when a tracked position disappears (server SL/TP fired), fetches deal history for actual PnL, and routes through a `_handle_live_close()` method mirroring the existing `_handle_paper_close()` path to update weight tracker and learning loop. This is the single genuinely new component.

**Key patterns confirmed as correct (do not change):**
- Paper/live branch at execution point only — signal pipeline is 100% shared between modes
- TOML config layering: `default.toml` ← `optimized.toml` ← `live.toml` — no manual parameter copying needed for live deployment
- Implicit position state machine (NO_POSITION → POSITION_OPEN → closed) — extend to explicit (add ORDER_PENDING, DETECTING_CLOSE states) for live mode

See `.planning/research/ARCHITECTURE.md` for full integration diagrams, suggested implementation patterns, and recommended project structure changes.

### Critical Pitfalls

1. **Chaos direction=0 starves the entire fusion pipeline** — The most critical bug. With `direction=0`, the fusion formula produces `0 * confidence * weight = 0` contribution regardless of signal quality. Fixing all other issues while leaving this unaddressed still produces near-zero trades. Prevention: fix before touching any thresholds. Validate fix by running 1000 bars and confirming chaos direction != 0 on >30% of bars.

2. **Timing urgency double-applied compresses confidence to 0.15-0.25** — One-line fix (`module.py` line 136, remove `* urgency`), but if left in place, timing's contribution to fusion is negligible even with perfect OU model fit. Validate fix by confirming timing confidence spans 0.1-0.8 across representative test data.

3. **Lowering fusion threshold before signal fixes creates noise trades** — The tempting shortcut: reduce `aggressive_confidence_threshold` to 0.20 to force more trades. With broken signals, this produces trades driven almost entirely by the flow module (the only one contributing nonzero direction reliably), bypassing the entire multi-module fusion rationale. Win rate drops below 40%. Prevention: fix signals first, measure the new confidence distribution, set threshold from the 40th-percentile value.

4. **Position sizer rejects every trade at $20 equity** — XAUUSD M5 ATR of $2-6 means any SL distance above $2 produces >10% actual risk at minimum 0.01 lot, which the sizer correctly rejects. This produces zero live trades even when fusion generates valid signals. Prevention: ATR multiplier 1.0-1.5x for aggressive phase + 15-20% risk_pct; mark this as demo-mode math explicitly with a `# DEMO_ONLY` code comment so it cannot carry forward to real-money phase.

5. **Backtest log flood blocks optimization** — 57M potential debug log lines for 3.8M bars causes the backtest to appear stuck. Optimization cannot run because it invokes the backtest. The fix already exists in the codebase: the optimizer suppresses logging at cli.py lines 542-546. Apply the same `make_filtering_bound_logger(logging.WARNING)` pattern to the backtest runner.

6. **Paper-to-live switch without order_check dry-run validation** — Paper mode never exercises filling mode, stops level minimum, volume step, or Market Watch availability. First live trade may fail silently. Prevention: run `order_check()` on a sample request (no `order_send`) before enabling live trading; call `mt5.symbol_select("XAUUSD", True)` unconditionally at startup.

7. **Orphaned positions after Python crash** — `TradeManager._open_position_ticket` is in-memory only. On crash + restart, the bot starts fresh while the position remains on MT5 server with a fixed SL and no monitoring. The bot may open a second position on the same signal. Prevention: persist open position ticket + entry price to SQLite on every fill; on startup, query `positions_get(symbol="XAUUSD")`, filter by magic_number, adopt into TradeManager state.

8. **MT5 terminal crashes during unattended week-long operation** — Windows Update restarts, MT5 auto-updates, screen lock freezing the terminal UI, AutoTrading getting disabled after an update. The existing `reconnect_loop` only handles broker disconnection, not terminal process death. Prevention: check if `terminal64.exe` is running before reconnection attempts; use infinite retry with capped backoff (not max_retries=3); add a heartbeat file polled by a Task Scheduler watchdog.

---

## Implications for Roadmap

The dependency structure from research is unambiguous and strict: signal correctness is the prerequisite for everything else. No amount of threshold tuning, optimization, or live execution wiring produces meaningful results until all three signal modules contribute nonzero directional output to the fusion. The suggested phases follow the dependency chain with no shortcuts.

### Phase 1: Signal Pipeline Overhaul

**Rationale:** Three compounding signal bugs combine to choke trade flow to near zero. All other phases depend on the pipeline generating meaningful signals. This is the root cause of the gap between v1.0's theoretical capability and its actual trade frequency.

**Delivers:** Signal pipeline that generates 5-15+ trades/day on backtested data; corrected signal math with measured confidence distributions; calibrated fusion threshold derived from actual data; position sizing that clears the $20 micro-account constraint; circuit breakers tuned for micro-account reality.

**Addresses (from FEATURES.md):** All five P0 features — chaos direction fix, timing urgency fix, fusion threshold reduction (after measurement), position sizing for $20, circuit breaker recalibration.

**Avoids (from PITFALLS.md):** Pitfalls 1-4. Strict order within phase: (1) fix chaos direction, (2) fix timing urgency, (3) measure new confidence distribution, (4) set threshold from measured data, (5) fix position sizing. Do NOT change the threshold until step 3 is complete.

**Research flag:** No phase research needed — bugs are identified with exact file/line locations in PITFALLS.md. Standard mathematical calibration work.

### Phase 2: Backtest Pipeline Performance

**Rationale:** Automated optimization runs the backtest dozens of times per session. The backtest cannot complete a single walk-forward window due to log flooding. Until this is fixed, Phase 3 optimization cannot produce results.

**Delivers:** Full 3.8M bar backtest completing in under 30 minutes with WARNING log level; walk-forward validation operating without performance degradation across all windows; Numba JIT compiled once per process not per walk-forward window.

**Addresses (from FEATURES.md):** Unblocks "automated optimization with expanded search space" (P1).

**Avoids (from PITFALLS.md):** Pitfall 5 (backtest log flood). After applying WARNING level, verify actual errors (exceptions, order failures) still surface — do not accidentally silence real failures.

**Uses (from STACK.md):** `structlog.make_filtering_bound_logger(logging.WARNING)` — already used by optimizer at cli.py:542-546, apply same pattern to backtest runner; `NUMBA_CACHE_DIR` env var for persistent cross-run JIT cache.

**Research flag:** No phase research needed. The fix is a 5-line change with a direct model already in the codebase.

### Phase 3: Automated Optimization

**Rationale:** With working signals (Phase 1) and a fast backtest (Phase 2), optimization can run end-to-end. Manual threshold tuning is guesswork — Optuna TPE over an expanded 20-parameter search space produces walk-forward-validated parameters that actually achieve the target trade frequency.

**Delivers:** `config/optimized.toml` with chaos thresholds, timing urgency exponent, SL ATR multiplier, concurrent positions count, and fusion thresholds all Optuna-tuned; multi-objective Pareto front balancing profit factor against trade frequency (NSGAIISampler); optuna-dashboard for real-time trial inspection; ~3-4x speedup from multiprocessing.Pool + JournalStorage parallel workers.

**Addresses (from FEATURES.md):** "Automated optimization with expanded search space" (P1), "multi-objective optimization" (P2), "optimization warm-start from previous run" (P2), "config diff visualization" (P3).

**Avoids (from PITFALLS.md):** Optimization overfitting — use walk-forward + OOS gate as Optuna's objective function, not raw in-sample profit. Add per-trial timeout to prevent a single trial from running indefinitely.

**Uses (from STACK.md):** Optuna JournalStorage + multiprocessing.Pool (official single-machine parallel pattern); optuna-dashboard 0.20.x (new dep); NUMBA_CACHE_DIR warmup in each worker process before trials begin.

**Research flag:** No phase research needed. Optuna multi-process and multi-objective are well-documented with official examples.

### Phase 4: Live MT5 Execution

**Rationale:** Paper mode is validated; optimization has produced calibrated parameters; this phase wires the existing live execution code path, fills the identified gaps, and validates the full stack against a real demo account before the monitored demo week.

**Delivers:** Bot executing on demo account with order_check pre-validation, retcode handling for all common broker errors, trailing stop modification via TRADE_ACTION_SLTP, position sync on startup (crash recovery), live position close detection, and full trade logging for live fills.

**Addresses (from FEATURES.md):** "Live MT5 execution on demo" (P1), "trailing stop implementation" (P1), "position sync on startup" (P2).

**Avoids (from PITFALLS.md):** Pitfall 6 (paper-to-live validation gap) — run order_check dry-run before first order_send, verify symbol_select at startup, test retcode 10004 (requote). Pitfall 8 (orphaned positions) — persist position ticket to SQLite on every fill; reconcile on startup. Must fill the `modify_sl()` gap in OrderManager before trailing stops can work.

**Uses (from ARCHITECTURE.md):** New `_check_live_positions()` method; `get_deal_history()` on MT5Bridge; `modify_sl()` on OrderManager; explicit position state machine (NO_POSITION → ORDER_PENDING → POSITION_OPEN → DETECTING_CLOSE → NO_POSITION).

**Research flag:** Likely needs phase research for RoboForex ECN filling mode specifics, MT5 deal history API edge cases, and retcode completeness. Integration-heavy phase with broker-specific behavior.

### Phase 5: Demo Hardening (Unattended Operation)

**Rationale:** A week-long unattended demo exposes failure modes invisible in interactive sessions. This phase makes the bot survivable across Windows events, MT5 process crashes, market closes, and disk exhaustion without human intervention.

**Delivers:** Infinite reconnection with capped exponential backoff; MT5 terminal process monitoring with subprocess restart capability; heartbeat file for external Task Scheduler watchdog; rotating log files (100MB total max); weekend market-close detection (XAUUSD closes Fri 22:00, reopens Sun 23:00 UTC); Windows toast alerts for kill switch / circuit breaker / MT5 disconnect via desktop-notifier; alert if no trade evaluation occurs for 30+ minutes during active session hours.

**Addresses (from FEATURES.md):** Demo monitoring, "graceful degradation metrics" dashboard display (P2).

**Avoids (from PITFALLS.md):** Pitfall 7 (MT5 terminal crashes undetected); weekend handling gap; log disk exhaustion; bot appearing idle with no diagnosis. Post-hardening verification: simulate MT5 terminal kill and confirm reconnection within 2 minutes; run bot across Friday 21:00 UTC through Monday 01:00 UTC, verify no errors; confirm log rotation after 24-hour run.

**Uses (from STACK.md):** `desktop-notifier` 6.2.0 (new dep); RotatingFileHandler + structlog dual output; DuckDB reading JSON logs for post-hoc session analysis.

**Research flag:** Likely needs phase research for Windows-specific `signal.signal()` SIGINT behavior and `subprocess.Popen` path to restart MT5 terminal on Windows.

### Phase Ordering Rationale

- **Phase 1 is unconditionally first** — signal bugs produce zero trades; running optimization or live execution against a zero-trade pipeline is meaningless and misleading
- **Phase 2 must precede Phase 3** — optimization calls the backtest; the backtest must complete reliably for optimization to converge
- **Phase 3 must precede Phase 4** — live execution should use Optuna-validated parameters, not arbitrary defaults or manually-guessed thresholds
- **Phase 4 must precede Phase 5** — hardening failure modes are only reachable after live execution is functional; hardening a broken pipeline wastes effort
- **Within Phase 1:** chaos direction fix → timing urgency fix → run 1000 bars → measure confidence distribution → set threshold from data. The threshold is the last thing changed, not the first.

### Research Flags

Phases likely needing `/gsd:research-phase` during planning:
- **Phase 4 (Live MT5 Execution):** RoboForex ECN filling mode specifics (IOC vs FOK vs RETURN), complete order retcode taxonomy, MT5 deal history API for position close PnL retrieval — broker-specific behavior may have surprises not covered by official docs
- **Phase 5 (Demo Hardening):** Windows `signal.signal()` vs `add_signal_handler()` behavior differences, reliable path to `terminal64.exe` for subprocess restart on typical Windows MT5 install locations

Phases with standard patterns (can skip research-phase):
- **Phase 1 (Signal Overhaul):** All bugs identified with exact file/line citations; fixes are mathematical corrections to existing formulas
- **Phase 2 (Backtest Performance):** Single known fix already implemented in the codebase for the optimizer; apply same pattern to the backtest runner
- **Phase 3 (Optimization):** Optuna JournalStorage + multiprocessing.Pool is the officially documented single-machine parallel pattern with examples

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Only 2 new packages; all others already installed with verified compatibility; version matrix confirmed against existing pyproject.toml |
| Features | HIGH | Root causes identified through codebase analysis with exact file/line citations; priority assignments grounded in dependency math from FEATURES.md |
| Architecture | HIGH | All integration points traced through actual source code; no speculative changes; component boundaries verified by reading the codebase |
| Pitfalls | HIGH | Critical pitfalls verified against actual codebase (specific line numbers cited in PITFALLS.md sources); recovery strategies grounded in existing code patterns |

**Overall confidence: HIGH**

### Gaps to Address

- **Actual fused_confidence distribution is unknown until Phase 1 signals are fixed** — threshold recommendations (0.25-0.35 for aggressive) are based on signal math modeling, not measured data. After fixing chaos direction and timing urgency, run 1000+ bars, log all fused_confidence values, and set the final threshold from the 40th-percentile value. Do not hard-code a threshold before measuring.

- **RoboForex ECN filling mode behavior must be confirmed live** — research recommends IOC filling for XAUUSD on RoboForex ECN. The existing `_determine_filling_mode()` method handles this dynamically via `symbol_info().filling_mode` bitmask. Verify it runs and caches the result during Phase 4 connection setup, not at first trade time.

- **Optimization convergence time is uncertain** — with ~20 parameters and walk-forward objective, 100-200 Optuna trials on a 4-core machine may take 2-4 hours. Monitor the first Phase 3 run to establish actual duration before scheduling automated overnight optimization.

- **$20 position sizing override must not carry forward to real-money** — the 15-20% risk_pct for aggressive phase is explicitly a demo-mode accommodation. Add a `# DEMO_ONLY` comment and a `demo_mode_risk_override: bool` config flag so this cannot silently carry forward when real capital is used in v1.2.

- **MT5 deal history retrieval edge cases** — the `history_deals_get(position=ticket)` pattern for retrieving live close PnL is referenced in research but not yet implemented. Verify the API returns accurate data for SL-hit closes vs TP-hit closes vs manual closes during Phase 4 validation.

---

## Sources

### Primary (HIGH confidence — codebase analysis or official docs)

- Codebase: `src/fxsoqqabot/signals/chaos/module.py` lines 122-129 — direction_map returning 0.0 for 3 of 5 regimes
- Codebase: `src/fxsoqqabot/signals/timing/module.py` line 136 vs `ou_model.py` line 127 — double urgency application
- Codebase: `src/fxsoqqabot/signals/fusion/core.py` lines 96-108 — fusion formula; `src/fxsoqqabot/execution/orders.py` lines 184-228 — live order path; lines 178-182 — paper bypass
- Codebase: `src/fxsoqqabot/risk/sizing.py` lines 117-132 — position sizing math and rejection logic
- Codebase: `src/fxsoqqabot/cli.py` lines 542-546 — optimizer WARNING log suppression (model for backtest fix)
- [Optuna JournalStorage docs](https://optuna.readthedocs.io/en/stable/tutorial/10_key_features/004_distributed.html) — multi-process parallel optimization on single machine
- [Optuna visualization docs](https://optuna.readthedocs.io/en/stable/reference/visualization/index.html) — built-in plot_param_importances, plot_contour, plot_parallel_coordinate
- [structlog performance docs](https://www.structlog.org/en/stable/performance.html) — `make_filtering_bound_logger`, zero-overhead filtering pattern
- [desktop-notifier GitHub](https://github.com/samschott/desktop-notifier) — async API, WinRT bridge for Windows toast notifications
- [Numba caching docs](https://numba.readthedocs.io/en/stable/developer/caching.html) — NUMBA_CACHE_DIR, `.nbi/.nbc` cache files
- [MQL5 Python order_send docs](https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py) — return codes, request structure, TRADE_ACTION_SLTP
- [MQL5 positions_get docs](https://www.mql5.com/en/docs/python_metatrader5/mt5positionsget_py) — magic number filtering, position attributes

### Secondary (MEDIUM confidence — community consensus, multiple sources)

- [Gold Scalping Strategy on MT5 2026](https://xmsignal.com/en/blog/gold-scalping-strategy-mt5/) — M5 timeframe ATR ranges ($1.50-$3.00 during London), 10-20 trade/day benchmark
- [XAUUSD Lot Size and Risk Management](https://www.defcofx.com/xauusd-pips-and-lot-size/) — pip value $0.01 per 0.01 lot, micro-account constraints
- [MT5 Python trailing stop pattern](https://appnologyjames.medium.com/metatrader-5-python-trailing-stop-2c562a541b48) — TRADE_ACTION_SLTP polling implementation
- [Paper vs Live Execution Differences](https://markrbest.github.io/paper-vs-live/) — 15-20% reality discount on demo fill quality vs live ECN
- [Optuna multi-objective NSGAIISampler](https://optuna.org/) — Pareto-optimal parameter sets for competing objectives
- [How to fix MT5 accidental disconnection](https://medium.com/the-trading-scientist/how-to-fix-accidental-disconnection-of-metatrader-2365ea899c3f) — terminal monitoring patterns

### Tertiary (LOW confidence — single source or inference)

- $20 positioning math estimates (ATR $2-6 range at M5) — valid for typical conditions but actual ATR varies with volatility regime; validate against live data during Phase 1 calibration

---

*Research completed: 2026-03-28*
*Ready for roadmap: yes*
