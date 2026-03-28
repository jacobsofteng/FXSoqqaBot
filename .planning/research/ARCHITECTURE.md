# Architecture Research: v1.1 Live Demo Launch

**Domain:** Signal recalibration, live execution, and automated optimization for XAUUSD scalping bot
**Researched:** 2026-03-28
**Confidence:** HIGH (codebase fully analyzed, all integration points traced through source)

## Executive Summary

The v1.0 architecture is well-structured with clean separation between signal modules, fusion, execution, and persistence. The v1.1 changes required to reach live demo trading do NOT require new architectural layers or fundamental restructuring. Instead, they require targeted modifications across five areas: (1) signal module recalibration parameters, (2) backtest pipeline performance, (3) optimization pipeline completion, (4) live execution wiring, and (5) unattended operation hardening.

The critical architectural insight is that the paper-to-live transition is already designed into the system. The `OrderManager.place_market_order()` method (orders.py:110-228) has a clean branch: `if self._config.mode == "paper"` routes to `PaperExecutor`, else executes real orders via `MT5Bridge.order_send()`. The live path already handles `order_check()` pre-validation, slippage tracking, and filling mode detection. The gap is not in the order flow -- it is in position lifecycle management, crash recovery for live positions, and the absence of a position monitoring loop for live mode.

## Current Architecture (as-built v1.0)

```
                          ┌─────────────────────────────┐
                          │          CLI Layer           │
                          │ run | backtest | optimize    │
                          │ kill | status | reset        │
                          └─────────┬───────────────────┘
                                    │
                          ┌─────────▼───────────────────┐
                          │      TradingEngine          │
                          │  asyncio.gather(4 loops)    │
                          └──┬────┬────┬────┬───────────┘
                             │    │    │    │
                ┌────────────┘    │    │    └────────────────┐
                │                 │    │                     │
         ┌──────▼──────┐  ┌──────▼────▼──┐  ┌──────────────▼─┐
         │  tick_loop   │  │  bar_loop    │  │  health_loop   │
         │  100ms poll  │  │  5s refresh  │  │  10s equity/   │
         │  ticks+DOM   │  │  M1-H4 bars  │  │  breakers      │
         └──────────────┘  └──────────────┘  └────────────────┘
                                    │
                          ┌─────────▼───────────────────┐
                          │      signal_loop (5s)       │
                          │                             │
                          │  ┌───────┐ ┌─────┐ ┌──────┐│
                          │  │Chaos  │ │Flow │ │Timing││
                          │  │Module │ │Mod  │ │Module││
                          │  └───┬───┘ └──┬──┘ └──┬───┘│
                          │      │        │       │    │
                          │  ┌───▼────────▼───────▼──┐ │
                          │  │      FusionCore       │ │
                          │  │ weighted_score fusion  │ │
                          │  └──────────┬────────────┘ │
                          │             │              │
                          │  ┌──────────▼────────────┐ │
                          │  │    TradeManager       │ │
                          │  │ SL/TP + sizing + exec │ │
                          │  └──────────┬────────────┘ │
                          └─────────────┼──────────────┘
                                        │
                          ┌─────────────▼──────────────┐
                          │      OrderManager          │
                          │  mode=="paper" → Paper     │
                          │  mode=="live"  → MT5Bridge │
                          └────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Key File |
|-----------|----------------|----------|
| **TradingEngine** | Lifecycle orchestration, loop management, component wiring | `core/engine.py` (1090 lines) |
| **ChaosRegimeModule** | Hurst + Lyapunov + fractal + Feigenbaum + entropy -> RegimeState | `signals/chaos/module.py` |
| **OrderFlowModule** | Volume delta + aggression + institutional + HFT -> flow direction | `signals/flow/module.py` |
| **QuantumTimingModule** | OU mean-reversion + ATR phase transition -> timing urgency | `signals/timing/module.py` |
| **FusionCore** | Confidence-weighted signal fusion -> composite direction + should_trade | `signals/fusion/core.py` |
| **AdaptiveWeightTracker** | EMA accuracy tracking -> normalized module weights | `signals/fusion/weights.py` |
| **PhaseBehavior** | Capital phase -> confidence threshold + regime RR adjustments | `signals/fusion/phase_behavior.py` |
| **TradeManager** | ATR SL/TP + regime adjustments + sizing + single-position limit | `signals/fusion/trade_manager.py` |
| **OrderManager** | Paper/live branch, order_check, order_send, filling mode, close | `execution/orders.py` |
| **PaperExecutor** | Paper fills, slippage simulation, virtual balance, SL/TP checks | `execution/paper.py` |
| **MT5Bridge** | Async wrapper around blocking MT5 package, single-thread executor | `execution/mt5_bridge.py` |
| **PositionSizer** | Three-phase risk model -> lot size from equity + SL distance | `risk/sizing.py` |
| **CircuitBreakerManager** | 5 breakers + kill switch + session filter | `risk/circuit_breakers.py` |
| **BacktestEngine** | Synchronous bar replay using same signal pipeline as live | `backtest/engine.py` |
| **Optimizer** | Optuna TPE (11 params) + DEAP GA (3 weights) + final validation | `optimization/optimizer.py` |

## v1.1 Integration Analysis

### Area 1: Signal Recalibration

**Problem:** Chaos module produces direction=0 too often; timing module urgency is not calibrated; fusion thresholds reject too many signals. Result: 0-1 trades/day instead of target 10-20.

**What needs to change:**

| Component | Current State | Required Change | Type |
|-----------|--------------|-----------------|------|
| `classify_regime()` in `signals/chaos/regime.py` | Returns regime but direction comes from price_direction parameter only, no chaos-driven directional bias | Chaos module must contribute a meaningful `direction` value, not just regime classification. Direction should derive from Hurst+price combined with regime strength | **Modify** |
| `ChaosRegimeModule.update()` | Produces `direction` from a simple price delta sign (+/-1 or 0) | Needs calibrated direction signal: weighted sum of Hurst trend persistence, volume momentum, regime confidence. Currently direction is binary/neutral, needs to be continuous [-1,1] | **Modify** |
| `QuantumTimingModule.update()` | Produces `direction` from OU displacement and `confidence` from fit quality | Timing urgency needs recalibration. Current compression/expansion thresholds (0.5/2.0) may be too extreme for XAUUSD M5. Needs parameter sweep or heuristic tuning | **Modify** |
| `FusionConfig` confidence thresholds | aggressive=0.5, selective=0.6, conservative=0.7 | These may be too high given that fused_confidence = sum(conf * weight) and with 3 modules the theoretical max is ~0.33 per module contribution. Need to understand actual distribution from backtests | **Tune** |
| `FusionCore.fuse()` | `fused_confidence = total_confidence_weight` where total is `sum(conf * weight)` | Need to verify math: with 3 equal-weight modules at 0.33 each, even perfect confidence signals produce fused_confidence = 0.33 + 0.33 + 0.33 = 1.0 max. But individual module confidence is rarely 1.0. Need data on actual distributions | **Analyze** |

**Integration points affected:**

```
classify_regime()
    └→ ChaosRegimeModule.update()  [SignalOutput: direction, confidence, regime]
         └→ signal_loop() collects signals
              └→ FusionCore.fuse(signals, weights, threshold)
                   └→ FusionResult.should_trade = abs(composite) > 0 AND fused_confidence >= threshold
                        └→ TradeManager.evaluate_and_execute()
```

**Key architectural insight:** The signal recalibration does NOT change any interfaces. `SignalOutput` is frozen with `direction: float`, `confidence: float`, `regime: RegimeState`. All changes are INTERNAL to individual signal module `update()` methods and to FusionConfig parameter values. This is the cleanest possible change.

**Suggested build order for recalibration:**
1. Add backtest instrumentation to log actual direction/confidence distributions from each module
2. Use these distributions to set realistic fusion thresholds
3. Tune chaos direction computation for continuous [-1,1] output
4. Tune timing urgency thresholds for XAUUSD M5 characteristics
5. Run optimization pipeline to find optimal parameters

### Area 2: Backtest Pipeline Performance

**Problem:** Backtest runner was stuck on the first walk-forward window with 147K+ debug log entries. The pipeline needs to complete end-to-end efficiently.

**What needs to change:**

| Component | Current State | Required Change | Type |
|-----------|--------------|-----------------|------|
| `run_full_backtest()` in `backtest/runner.py` | Runs 6-step pipeline sequentially but floods with debug logs | Force WARNING-level logging during backtest (like optimizer does) and profile bottlenecks | **Modify** |
| `BacktestEngine.run()` in `backtest/engine.py` | Creates fresh signal modules per run including Numba JIT warmup | JIT warmup should happen ONCE before walk-forward loop, not per window. Cache initialized modules or pre-warm | **Modify** |
| `cmd_backtest()` in `cli.py` | Uses default logging setup | Add `structlog.make_filtering_bound_logger(logging.WARNING)` like `cmd_optimize()` already does (line 544) | **Modify** |
| `WalkForwardValidator.run_walk_forward()` | Iterates windows, creates BacktestEngine per window | Pass pre-warmed module instances or pre-compile Numba cache before loop | **Modify** |

**Integration points affected:**

```
cmd_backtest()
    └→ run_full_backtest()
         └→ WalkForwardValidator.run_walk_forward()
              └→ [for each window]
                   └→ BacktestEngine(settings, config)  ← fresh instance
                        └→ engine.run(bars_df)
                             └→ chaos_module.initialize()  ← redundant JIT warmup
                                  └→ warmup_jit()  ← expensive first time only
```

**Key optimization:** Numba JIT compilation is expensive on first call (seconds) but cached on disk after that. The real performance issue is likely the log volume, not the computation. The optimizer already solved this (line 542-546 in cli.py) by forcing WARNING level. Apply the same pattern to backtest.

### Area 3: Optimization Pipeline Completion

**Problem:** Optimization needs to run end-to-end and write `config/optimized.toml` that the bot can load on next start.

**What needs to change:**

| Component | Current State | Required Change | Type |
|-----------|--------------|-----------------|------|
| `run_optimization()` | Writes `config/optimized.toml` with `[signals.fusion]` section | Works as designed. Need to verify it runs end-to-end with performance fix | **Verify** |
| `config/optimized.toml` | Written by optimizer but not auto-loaded | CLI needs `--config config/optimized.toml config/live.toml` to load both. Config merge is TOML-layered via `BotSettings.from_toml([files])`. Already supported. | **Documented** |
| Config loading chain | `load_settings(config_files)` -> `BotSettings.from_toml(config_files)` | Need to verify TOML layering: optimized.toml provides `[signals.fusion]` params, live.toml provides `[execution] mode="live"`. Default.toml fills everything else. | **Verify** |

**Data flow for optimization -> live deployment:**

```
optimize command
    └→ run_optimization()
         └→ Phase A: Optuna TPE (50 trials) -> best 11 fusion params
         └→ Phase B: DEAP GA (10 gens) -> best 3 weight seeds
         └→ Validation: walk-forward + OOS + Monte Carlo
         └→ Write config/optimized.toml
              └→ [signals.fusion]
                   aggressive_confidence_threshold = X
                   selective_confidence_threshold = Y
                   ... (14 params total)

run command with --config config/optimized.toml config/live.toml
    └→ load_settings(["config/optimized.toml", "config/live.toml"])
         └→ BotSettings.from_toml(files)  # layers: default <- optimized <- live
              └→ signals.fusion.* from optimized.toml
              └→ execution.mode = "live" from live.toml
              └→ everything else from defaults
```

**Key insight:** The optimization pipeline is architecturally complete. The issue is operational -- it needs to actually run to completion (blocked by backtest performance) and the output needs to be loadable by the run command. Both paths already exist in code.

### Area 4: Live Execution

**Problem:** Paper mode tracks positions internally via `PaperExecutor._positions`. Live mode sends orders via MT5 but has gaps in position lifecycle management.

**What currently works in live mode:**

1. `OrderManager.place_market_order()` with `mode="live"` correctly calls `order_check()` then `order_send()` (orders.py:184-228)
2. `OrderManager.close_position()` handles opposite-order closing (orders.py:230-300)
3. `OrderManager.close_all_positions()` iterates `bridge.get_positions()` (orders.py:302-321)
4. `MT5Bridge` wraps all blocking MT5 calls in single-thread executor (mt5_bridge.py:59-66)
5. `TradeManager` tracks `_open_position_ticket` for single-position limit (trade_manager.py:85-87)

**What is MISSING for live mode:**

| Gap | Description | Impact | Required Component |
|-----|-------------|--------|-------------------|
| **Live position monitoring** | Paper mode checks SL/TP via `PaperExecutor.check_sl_tp()` in tick_loop. Live mode relies on server-side SL/TP (set in order request). But `TradeManager._open_position_ticket` is never cleared in live mode when MT5 server closes a position | TradeManager thinks position is still open indefinitely, blocks new trades | **New: Position sync loop** |
| **Position reconciliation** | No mechanism to detect when MT5 server-side SL/TP fires. `bridge.get_positions()` exists but is not polled in live mode | Stale position state causes missed trades or doubled positions | **New: Position sync in health_loop or tick_loop** |
| **Live trade logging** | `_handle_paper_close()` handles paper position closes with full logging/learning. No equivalent for live closes | Trade history, weight adaptation, and learning loop miss live trade outcomes | **New: Live close handler** |
| **Crash recovery for live** | Current crash recovery closes ALL open positions on restart (engine.py:429-441). This is aggressive for live | Could close profitable positions unnecessarily on restart | **Modify: Optional preserve-positions flag** |
| **OrderManager.modify_sl** | Referenced in TradeManager.evaluate_and_execute() line 176-178 but NOT implemented on OrderManager | Adverse regime SL tightening silently fails | **New: Add modify_sl method** |

**New component: Position Monitor**

This is the single genuinely new component needed. It must:
1. Poll `bridge.get_positions(symbol)` on each tick loop cycle (or dedicated loop)
2. Compare against `TradeManager._open_position_ticket`
3. When position disappears from MT5 (server closed by SL/TP/margin), detect it
4. Compute PnL from position history or deal history
5. Call equivalent pipeline to `_handle_paper_close()`: trade logging, weight update, learning loop

**Suggested implementation pattern:**

```python
# In engine.py, within _tick_loop or as separate _position_sync_loop:

async def _check_live_positions(self) -> None:
    """Detect server-side position closures in live mode."""
    if self._settings.execution.mode != "live":
        return
    if self._trade_manager._open_position_ticket is None:
        return

    # Check if our tracked position still exists
    positions = await self._bridge.get_positions(
        symbol=self._settings.execution.symbol
    )
    open_tickets = {p.ticket for p in (positions or [])}

    tracked = self._trade_manager._open_position_ticket
    if tracked not in open_tickets:
        # Position was closed server-side (SL/TP hit or manual close)
        # Fetch deal history to get close price and PnL
        await self._handle_live_close(tracked)
```

**MT5 deal history retrieval:**

```python
# New method on MT5Bridge:
async def get_deal_history(self, ticket: int) -> Any:
    """Fetch deal history for a position ticket."""
    return await self._run_mt5(mt5.history_deals_get, position=ticket)
```

**Integration into existing architecture:**

```
_tick_loop() or _health_loop()
    └→ _check_live_positions()
         └→ bridge.get_positions(symbol)  [check if tracked ticket still open]
              └→ if missing: bridge.get_deal_history(ticket)  [get close details]
                   └→ _handle_live_close(ticket)  [mirrors _handle_paper_close]
                        ├→ trade_logger.log_trade_close()
                        ├→ weight_tracker.record_outcome()
                        ├→ learning_loop.on_trade_closed()
                        └→ trade_manager.record_position_closed()
```

**OrderManager.modify_sl implementation:**

```python
# New method on OrderManager:
async def modify_sl(self, ticket: int, new_sl: float) -> bool:
    """Modify stop-loss of an open position."""
    if self._config.mode == "paper":
        # Update paper position SL
        if self._paper_executor and ticket in self._paper_executor._positions:
            self._paper_executor._positions[ticket].sl = new_sl
            return True
        return False

    # Live mode: MT5 position modification
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": self._config.symbol,
        "sl": new_sl,
    }
    result = await self._bridge.order_send(request)
    return result is not None and result.retcode == TRADE_RETCODE_DONE
```

### Area 5: Demo Hardening (Unattended Operation)

**Problem:** Bot needs to run unattended for 1 week on demo account without crashing, hanging, or silently stopping.

**What needs to change:**

| Component | Current State | Required Change | Type |
|-----------|--------------|-----------------|------|
| **Logging levels** | Default `INFO` level floods with tick data every 100ms | Production logging: WARNING for tick/bar loops, INFO for trades/decisions, DEBUG only on explicit flag | **Modify** |
| **Session management** | Single window `13:00-17:00 UTC` | May need multiple windows (London + NY overlap is prime XAUUSD time, but Asian session gold moves matter). Session filter already supports multiple windows in config | **Tune** |
| **Reconnection** | `reconnect_loop(max_retries=5)` on startup, `reconnect_loop(max_retries=3)` in tick_loop | 5 retries = 63 seconds max before giving up forever. For unattended week-long operation, needs infinite retry (max_retries=0) with capped backoff | **Modify** |
| **Heartbeat/watchdog** | None | Need a periodic "I am alive" log entry + optional watchdog mechanism to detect if engine is stuck | **New: simple** |
| **State persistence frequency** | Signal weights saved on every trade, breaker state saved on every check | Adequate. Consider adding periodic state dump (every 5 min) as crash recovery checkpoint | **Minor enhance** |
| **Graceful shutdown on Windows** | `add_signal_handler` may fail on Windows (engine.py catches NotImplementedError) | Windows SIGINT handling is limited. Consider using `signal.signal(signal.SIGINT, handler)` which works on Windows, or a file-based kill mechanism | **Modify** |

**New component: Watchdog heartbeat (lightweight)**

```python
# In engine.py, add to health_loop or as simple addition:
async def _health_loop(self):
    # ... existing checks ...

    # Periodic heartbeat for monitoring
    self._logger.info(
        "heartbeat",
        uptime_minutes=(time.time() - self._start_time) / 60,
        trades_today=self._engine_state.breaker_status.get("daily_trade_count", 0),
        equity=self._current_equity,
        mode=self._settings.execution.mode,
    )
```

This is trivially added to the existing health_loop's 10-second cycle but should be throttled to once per minute or once per 5 minutes.

## Recommended Project Structure Changes

```
src/fxsoqqabot/
├── config/
│   ├── loader.py          # No changes needed
│   └── models.py          # Possible: add production logging profile
├── core/
│   ├── engine.py          # MODIFY: add _check_live_positions(), heartbeat, reconnect fixes
│   ├── events.py          # No changes needed
│   ├── state.py           # No changes needed
│   └── state_snapshot.py  # No changes needed
├── execution/
│   ├── mt5_bridge.py      # MODIFY: add get_deal_history()
│   ├── orders.py          # MODIFY: add modify_sl()
│   └── paper.py           # No changes needed (paper mode already works)
├── signals/
│   ├── base.py            # No changes needed (SignalOutput is stable)
│   ├── chaos/
│   │   ├── module.py      # MODIFY: recalibrate direction computation
│   │   └── regime.py      # REVIEW: threshold tuning
│   ├── flow/
│   │   └── module.py      # REVIEW: direction/confidence calibration
│   ├── timing/
│   │   └── module.py      # MODIFY: urgency calibration thresholds
│   └── fusion/
│       ├── core.py        # No changes needed (fusion math is correct)
│       ├── trade_manager.py # No changes needed (modify_sl already expected)
│       └── weights.py     # No changes needed
├── backtest/
│   ├── runner.py          # MODIFY: add production log level suppression
│   └── engine.py          # MODIFY: optimize JIT warmup, reduce per-bar logging
├── optimization/
│   └── optimizer.py       # VERIFY: run end-to-end
├── risk/                  # No changes needed
├── cli.py                 # MODIFY: backtest logging, config loading docs
└── logging/
    └── setup.py           # MODIFY: add production log profiles
config/
├── default.toml           # No changes needed
├── paper.toml             # No changes needed
├── live.toml              # MODIFY: add MT5 credentials, session tuning
└── optimized.toml         # GENERATED: by optimization pipeline
```

## Architectural Patterns

### Pattern 1: Paper/Live Branch at Execution Point

**What:** All signal analysis, fusion, and trade decisions share 100% of code between paper and live modes. The branch point is a single `if self._config.mode == "paper"` check in `OrderManager.place_market_order()`.

**Why this matters for v1.1:** Adding live execution does NOT require any changes to the signal pipeline, fusion core, or trade manager. Only the execution layer and position monitoring need modification.

**Trade-offs:** Simple and clean, but means live mode inherits all paper mode's decision logic without any live-specific adjustments. This is correct -- the strategy should be identical.

### Pattern 2: Config Layering via TOML Override Chain

**What:** `BotSettings.from_toml(["config/optimized.toml", "config/live.toml"])` layers configs left-to-right. Later files override earlier ones. Field defaults fill gaps.

**Why this matters for v1.1:** The optimization pipeline writes `config/optimized.toml` with just `[signals.fusion]` parameters. The live config adds `[execution] mode="live"`. No manual parameter copying needed.

**Example deployment command:**
```bash
python -m fxsoqqabot run --config config/optimized.toml config/live.toml --no-learning
```

### Pattern 3: Position Lifecycle State Machine

**What:** Currently implicit in `TradeManager._open_position_ticket`. Needs to become explicit for live mode.

**Current states (paper):**
```
NO_POSITION → [fusion says trade + breakers clear + sizing ok] → POSITION_OPEN
POSITION_OPEN → [SL/TP hit detected by PaperExecutor.check_sl_tp()] → NO_POSITION
POSITION_OPEN → [adverse regime] → POSITION_OPEN (tighten SL)
```

**Required states (live):**
```
NO_POSITION → [fusion says trade] → ORDER_PENDING
ORDER_PENDING → [fill confirmed] → POSITION_OPEN
POSITION_OPEN → [server closes via SL/TP] → DETECTING_CLOSE
DETECTING_CLOSE → [deal history retrieved] → NO_POSITION
POSITION_OPEN → [adverse regime] → POSITION_OPEN (modify_sl via MT5)
POSITION_OPEN → [kill switch] → CLOSING
CLOSING → [close fill confirmed] → NO_POSITION
```

**Recommendation:** For v1.1, keep it simple. Do NOT build a full state machine. Instead:
- `_open_position_ticket is None` = no position
- `_open_position_ticket is not None` = position open
- Polling `bridge.get_positions()` detects server-side closes
- This matches the existing TradeManager pattern with minimal changes

### Pattern 4: Synchronous Optimization with Async Backtests

**What:** The optimizer is synchronous (`run_optimization()` uses `asyncio.run()` per trial). Each Optuna objective call spins up a fresh event loop for the async BacktestEngine. This is intentional -- Optuna's API is synchronous.

**Why this matters for v1.1:** The optimization pipeline cannot run inside the trading engine's event loop. It must be a separate CLI command. This is already the case (`cmd_optimize` is sync, not async). No changes needed to this pattern.

## Data Flow Changes for v1.1

### Current Data Flow (Paper Mode)

```
tick_loop (100ms) ──→ tick_buffer ──→ signal_loop (5s)
                                          │
bar_loop (5s) ──→ bar_buffers ────────────┘
                                          │
                                    3 signal modules
                                          │
                                    FusionCore.fuse()
                                          │
                                    TradeManager.evaluate_and_execute()
                                          │
                              OrderManager.place_market_order()
                                          │
                              PaperExecutor.simulate_fill()
                                          │
                                    FillEvent returned
                                          │
tick_loop (100ms) ──→ PaperExecutor.check_sl_tp()
                                          │
                              PaperExecutor.simulate_close()
                                          │
                              _handle_paper_close()
                                    │    │    │
                        trade_logger  weight  learning
                                    tracker  loop
```

### Required Data Flow (Live Mode)

```
tick_loop (100ms) ──→ tick_buffer ──→ signal_loop (5s)
                                          │
bar_loop (5s) ──→ bar_buffers ────────────┘
                                          │
                                    3 signal modules
                                          │
                                    FusionCore.fuse()
                                          │
                                    TradeManager.evaluate_and_execute()
                                          │
                              OrderManager.place_market_order()
                                          │
                              MT5Bridge.order_send()    ← LIVE PATH
                                          │
                                    FillEvent returned
                                          │
health_loop (10s) ──→ _check_live_positions()     ← NEW
                              │
                    bridge.get_positions(symbol)
                              │
                    if tracked ticket missing:
                              │
                    bridge.get_deal_history(ticket)   ← NEW on bridge
                              │
                    _handle_live_close(ticket)         ← NEW, mirrors paper
                              │    │    │
                  trade_logger  weight  learning
                              tracker  loop
```

**Key difference:** Paper mode detects SL/TP via `PaperExecutor.check_sl_tp()` in tick_loop (100ms). Live mode detects server-side closes by polling `get_positions()` -- this should happen in health_loop (10s interval) to avoid hammering MT5 API. Latency between server close and detection is acceptable (up to 10 seconds) because the bot is not HFT.

## Component Change Matrix

| Component | File | Change Type | Size | Dependencies |
|-----------|------|-------------|------|-------------|
| Backtest logging fix | `cli.py` | Modify | Small | None (copy pattern from cmd_optimize) |
| Backtest JIT warmup | `backtest/engine.py` | Modify | Small | Numba cache already persists to disk |
| Chaos direction calibration | `signals/chaos/module.py` | Modify | Medium | ChaosConfig, regime.py |
| Timing urgency calibration | `signals/timing/module.py` | Modify | Medium | TimingConfig |
| Fusion threshold tuning | `config/default.toml` or optimization | Tune | Small | Requires backtest data |
| `modify_sl()` | `execution/orders.py` | Add method | Small | MT5Bridge (TRADE_ACTION_SLTP) |
| `get_deal_history()` | `execution/mt5_bridge.py` | Add method | Small | MT5 `history_deals_get` |
| Live position monitor | `core/engine.py` | Add method | Medium | bridge.get_positions, trade_manager |
| Live close handler | `core/engine.py` | Add method | Medium | Mirrors _handle_paper_close |
| Reconnect for unattended | `core/engine.py` | Modify | Small | Change max_retries to 0 |
| Heartbeat logging | `core/engine.py` | Add to health_loop | Small | None |
| Production log profile | `logging/setup.py` | Modify | Small | structlog config |
| Live config | `config/live.toml` | Expand | Small | MT5 credentials, session windows |

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| v1.1 Demo ($20, 1 week) | Current architecture is sufficient. Single position, single symbol, 10s position polling. No changes to event loop structure. |
| v1.2 Extended ($20-100, months) | Add persistent trade journal in DuckDB for long-term performance analysis. Consider file-based log rotation (structlog + rotating file handler). |
| v2.0 Multi-symbol | Would require multiple signal module instances per symbol, or a SymbolManager that multiplexes. Out of scope for v1.1. |

## Anti-Patterns

### Anti-Pattern 1: Rebuilding Signal Modules in Live Mode

**What people do:** Create separate "live signal modules" with different behavior than backtest/paper.
**Why it is wrong:** Breaks the core architectural guarantee that signal analysis is identical across paper/live/backtest. Any divergence means backtest results are meaningless for live performance prediction.
**Do this instead:** Keep signal modules IDENTICAL. All calibration changes go through config parameters, not code branches.

### Anti-Pattern 2: Polling Positions at Tick Rate (100ms)

**What people do:** Check `bridge.get_positions()` on every tick poll to detect closes faster.
**Why it is wrong:** Each MT5 call goes through `run_in_executor` on a single-thread executor. At 100ms polling, position checks would serialize with tick fetches and create contention.
**Do this instead:** Check positions in health_loop (10s interval). Server-side SL/TP is the source of truth; 10s detection latency is fine for scalping.

### Anti-Pattern 3: Complex State Machine for Position Tracking

**What people do:** Build a formal state machine with ORDER_PENDING, PARTIALLY_FILLED, etc.
**Why it is wrong:** Adds complexity without value for single-position XAUUSD scalping on ECN. FOK/IOC filling means orders either fill completely or not at all.
**Do this instead:** Keep the binary `_open_position_ticket is None / is not None` pattern. Poll `get_positions()` to sync state.

### Anti-Pattern 4: Manual Parameter Tuning Before Running Optimizer

**What people do:** Manually tweak config parameters based on intuition before running the optimization pipeline.
**Why it is wrong:** The optimizer exists specifically to find optimal parameters via systematic search. Manual tuning introduces bias and wastes time.
**Do this instead:** Fix the backtest pipeline first so the optimizer can run. Let Optuna+DEAP find parameters. Manual intervention only for structural changes (adding/removing signal components), not parameter values.

## Integration Points

### External Services

| Service | Integration Pattern | v1.1 Notes |
|---------|---------------------|------------|
| MT5 Terminal | `MT5Bridge` single-thread executor, polling | Add `get_deal_history()`. Increase reconnect resilience. |
| RoboForex ECN | Via MT5 terminal connection | Demo account first. Verify filling modes work. |
| Filesystem | DuckDB/Parquet for analytics, SQLite for state | No changes needed. |

### Internal Boundaries

| Boundary | Communication | v1.1 Changes |
|----------|---------------|-------------|
| Signal modules <-> FusionCore | SignalOutput dataclass (frozen) | No interface changes, only internal computation changes |
| FusionCore <-> TradeManager | FusionResult dataclass (frozen) | No changes |
| TradeManager <-> OrderManager | method calls with FillEvent return | Add modify_sl() method |
| OrderManager <-> MT5Bridge | method calls, async via run_in_executor | Add get_deal_history() |
| Engine <-> Dashboards | TradingEngineState shared object | No changes |
| Engine <-> Learning | Callbacks (on_trade_closed, promote, validate) | Live close handler needs same callback chain as paper |

## Suggested Build Order

Based on dependency analysis, the optimal build order is:

1. **Backtest pipeline fix** (no dependencies on other changes)
   - Fix logging in `cmd_backtest` (copy from `cmd_optimize`)
   - Profile and optimize BacktestEngine per-bar overhead
   - Verify full 6-step pipeline completes

2. **Optimization pipeline verification** (depends on backtest fix)
   - Run optimization end-to-end with fixed backtest
   - Verify `config/optimized.toml` is written and loadable
   - Validate TOML layering: `optimized.toml` + `live.toml`

3. **Signal recalibration** (informed by optimization results)
   - Instrument chaos/timing modules to log actual distributions
   - Tune direction computation and urgency thresholds
   - Re-run optimization with recalibrated modules

4. **Live execution wiring** (independent of signal calibration)
   - Add `modify_sl()` to OrderManager
   - Add `get_deal_history()` to MT5Bridge
   - Add `_check_live_positions()` to engine
   - Add `_handle_live_close()` to engine (mirror of paper handler)
   - Test on demo account in live mode

5. **Demo hardening** (depends on live execution working)
   - Infinite reconnect with capped backoff
   - Heartbeat logging in health_loop
   - Production log level profile
   - Session window tuning
   - Windows signal handling improvement
   - 1-week unattended run test

**Rationale for ordering:**
- Steps 1-2 must come first because optimization results inform signal calibration
- Step 3 uses optimization to find parameters, requires working backtest
- Step 4 is architecturally independent but should follow calibration so live trading uses optimized parameters
- Step 5 is the final polish layer that requires everything else working

## Sources

- `src/fxsoqqabot/core/engine.py` -- TradingEngine implementation, all loops, component wiring (1090 lines)
- `src/fxsoqqabot/execution/orders.py` -- OrderManager with paper/live branch at line 178
- `src/fxsoqqabot/execution/paper.py` -- PaperExecutor with SL/TP monitoring
- `src/fxsoqqabot/execution/mt5_bridge.py` -- MT5 async wrapper, all API methods
- `src/fxsoqqabot/signals/fusion/core.py` -- FusionCore fusion formula
- `src/fxsoqqabot/signals/fusion/trade_manager.py` -- Trade evaluation pipeline
- `src/fxsoqqabot/signals/fusion/weights.py` -- Adaptive EMA weight tracker
- `src/fxsoqqabot/signals/chaos/regime.py` -- Regime classification thresholds
- `src/fxsoqqabot/signals/chaos/module.py` -- ChaosRegimeModule signal production
- `src/fxsoqqabot/signals/timing/module.py` -- QuantumTimingModule timing urgency
- `src/fxsoqqabot/optimization/optimizer.py` -- Full optimization pipeline
- `src/fxsoqqabot/optimization/search_space.py` -- Optuna search space and apply_params_to_settings
- `src/fxsoqqabot/backtest/runner.py` -- Full backtest pipeline runner
- `src/fxsoqqabot/backtest/engine.py` -- BacktestEngine bar replay
- `src/fxsoqqabot/config/models.py` -- All Pydantic config models
- `src/fxsoqqabot/config/loader.py` -- TOML config loading
- `src/fxsoqqabot/cli.py` -- CLI entry points including optimize logging fix pattern
- `config/default.toml` -- Current default configuration
- `config/live.toml` -- Current live config (minimal, just mode="live")
- MT5 Python package documentation for `history_deals_get()`, `TRADE_ACTION_SLTP`

---
*Architecture research for: v1.1 Live Demo Launch*
*Researched: 2026-03-28*
