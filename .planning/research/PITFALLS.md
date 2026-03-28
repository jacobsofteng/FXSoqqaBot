# Pitfalls Research

**Domain:** XAUUSD Scalping Bot v1.1 -- Live Demo Launch (Signal Recalibration, Paper-to-Live, Large-Scale Backtest, Unattended Operation)
**Researched:** 2026-03-28
**Confidence:** HIGH (codebase analysis + domain research + known v1.0 issues verified)

---

## Critical Pitfalls

These are the pitfalls that will cause the v1.1 demo launch to fail outright. Each one blocks the stated goal of "10-20 trades/day running unattended for 1 week."

---

### Pitfall 1: Chaos Module direction=0 Starves the Fusion of Directional Signal

**What goes wrong:**
The chaos module returns `direction=0.0` for three of five regime states: RANGING, HIGH_CHAOS, and PRE_BIFURCATION. Looking at the `direction_map` in `chaos/module.py` lines 122-129, only TRENDING_UP (+1.0) and TRENDING_DOWN (-1.0) produce nonzero direction. Additionally, the classify_regime function in `regime.py` defaults to RANGING when metrics are ambiguous (lines 72-73). In practice, gold spends 60-80% of its time in non-trending regimes, which means the chaos module contributes `direction=0.0 * confidence * weight = 0.0` to the fusion formula most of the time. This effectively nullifies one-third of the fusion input, making it much harder for the composite score to exceed the confidence threshold.

**Why it happens:**
The v1.0 design treated the chaos module as a regime classifier only, not a directional signal. This was correct for its role (telling the system WHAT the market is doing), but the fusion formula at `core.py` line 99 multiplies `direction * confidence * weight` for the weighted score. When direction is zero, confidence and weight are irrelevant -- the module contributes nothing to the composite. At 10% risk with a $20 account, every rejected trade is a missed opportunity in the narrow viable trading window.

**How to avoid:**
- Decouple the chaos module's regime classification from its directional contribution. The regime informs SL/TP/sizing behavior (which works correctly). The direction should come from a separate mechanism: short-term momentum within the classified regime (e.g., use a 5-bar vs 20-bar close comparison even in RANGING to detect micro-trends).
- Alternative: when direction=0, have the fusion formula exclude that module from the denominator entirely (treat it as "abstaining" rather than "voting neutral"). This preserves the other two modules' signals without dilution.
- Do NOT simply assign random or biased direction to non-trending regimes. That introduces noise, not signal.

**Warning signs:**
- Structured logs show `chaos.direction=0.0` on >50% of fusion cycles
- `fusion_computed` logs show `should_trade=False` with `fused_confidence` values just below threshold
- Trade frequency remains at 0-3/day despite lowering thresholds
- Flow and timing modules show nonzero direction but composite is still too low

**Phase to address:**
Phase 1 (Signal Pipeline Overhaul). This is the highest-priority fix. Without it, no amount of threshold tuning will achieve 10-20 trades/day.

---

### Pitfall 2: Timing Urgency Double-Squared Crushes Confidence to Near-Zero

**What goes wrong:**
In `timing/module.py` line 136, the final confidence is computed as:
```python
final_confidence = (window_conf * 0.6 + phase_conf * 0.4) * urgency
```
But `window_conf` is itself already scaled by urgency in `ou_model.py` line 127:
```python
window_confidence = confidence * min(1.0, urgency)
```
So the urgency factor is applied twice: once inside `window_conf` and once as the outer multiplier. If urgency is 0.5 (moderate), the effective scaling is 0.5 * 0.5 = 0.25 on the OU component, meaning even a perfect R-squared fit with moderate displacement produces a confidence around 0.15-0.25. This systematically suppresses the timing module's contribution to fusion.

**Why it happens:**
The OU model's `compute_entry_window` correctly scales confidence by urgency (low urgency near the mean should produce low confidence). But the module-level `update()` method applies urgency again as an outer multiplier without realizing the inner scaling already accounts for it. This was not caught in v1.0 because the module was tested in isolation with high-urgency scenarios.

**How to avoid:**
- Remove the outer `* urgency` multiplier in `timing/module.py` line 136. The `window_conf` already incorporates urgency through the `compute_entry_window` function.
- OR replace the outer urgency multiplier with a different scaling factor (e.g., `phase_conf` quality or a combined novelty metric) that adds information rather than duplicating it.
- After fixing, verify that timing confidence spans a reasonable range (0.1-0.8 across typical market conditions) rather than clustering near zero.

**Warning signs:**
- Timing module confidence consistently below 0.15 in structured logs
- Timing's `weighted_score` in fusion_computed is negligible compared to flow and chaos
- Changing timing parameters has almost no effect on trade frequency

**Phase to address:**
Phase 1 (Signal Pipeline Overhaul). Fix alongside the chaos direction issue. Both are necessary to achieve meaningful fusion scores.

---

### Pitfall 3: Lowering Fusion Threshold Without Fixing Signal Math Creates Noise Trades

**What goes wrong:**
The fusion threshold for aggressive phase is 0.50 (`aggressive_confidence_threshold`). The known issues list identifies this as "too high." The temptation is to lower it to 0.20-0.30 to generate more trades. But if the chaos direction=0 and timing double-urgency bugs are not fixed first, lowering the threshold admits trades based almost entirely on the flow module alone (since it is the only module producing both nonzero direction AND reasonable confidence). Single-module-driven trades are exactly what the fusion architecture was designed to prevent -- the edge is in fusion, not any single module.

**Why it happens:**
Tuning thresholds is fast (change one number in config). Fixing signal math requires understanding the fusion formula and each module's output characteristics. Under time pressure, developers reach for the easy lever.

**How to avoid:**
- Fix Pitfalls 1 and 2 FIRST. Then measure the distribution of `fused_confidence` values with all three modules contributing meaningfully.
- Set the threshold based on the new distribution. If the median fused_confidence with fixed signals is 0.35, a threshold of 0.25-0.30 is reasonable. If the median is 0.55, keep the threshold at 0.45-0.50.
- Add a "module agreement" check: require at least 2 of 3 modules to have nonzero direction in the same direction before allowing a trade. This prevents single-module trades even at low thresholds.
- Log the per-module contribution to every fusion decision so you can audit what is driving trades.

**Warning signs:**
- More than 70% of trades are driven by a single module (check `module_scores` in fusion logs)
- Win rate drops below 40% after lowering threshold (you are trading noise)
- Drawdown increases proportionally with trade count (no edge, just more bets)

**Phase to address:**
Phase 1 (Signal Pipeline Overhaul). The threshold adjustment comes AFTER signal fixes, not before.

---

### Pitfall 4: Position Sizer Rejects Every Trade at $20 Equity

**What goes wrong:**
The PositionSizer in `sizing.py` computes: `lot_size = risk_amount / (sl_distance * contract_size)`. At $20 equity with 10% aggressive risk: `risk_amount = $2.00`. With ATR-based SL of, say, $3.00 (typical for XAUUSD M5): `lot_size = 2.00 / (3.00 * 100) = 0.0067`. This is below the 0.01 minimum lot. The sizer clamps to 0.01, then checks actual risk: `0.01 * 3.00 * 100 = $3.00`, which is 15% of equity -- exceeding the 10% aggressive limit. Result: `can_trade=False`, trade skipped.

With a wider SL (e.g., $5.00 in high-chaos regime with widen factor): `0.01 * 5.00 * 100 = $5.00` = 25% risk. Even more aggressively rejected. The position sizer correctly implements D-04 ("skip, don't force"), but the math makes it impossible to trade at $20 with ATR-based stops.

**Why it happens:**
XAUUSD's ATR at M5 timeframe typically ranges $2.00-$6.00. With the 2x ATR base multiplier, SL distances of $4.00-$12.00 are common. At 0.01 lot minimum and $20 equity, ANY SL distance above $2.00 produces risk above 10%. This is the fundamental $20 micro-account constraint identified in v1.0 but not yet solved.

**How to avoid:**
- Raise the aggressive_risk_pct from 0.10 to 0.15 or even 0.20 for the $20 phase. Acknowledge that $20 is a proof-of-concept capital level where standard risk management is mathematically impossible. Document this explicitly.
- Reduce the SL ATR multiplier from 2.0 to 1.0-1.5 during the aggressive phase. Tighter stops mean more stop-outs but enable position entry. The bot needs live trade data to learn -- zero trades teaches nothing.
- Alternatively, reduce computation_timeout or use a tighter timeframe for ATR (M1 instead of M5) to produce smaller ATR values and thus smaller SL distances.
- Consider a "demo mode override" for the 1-week observation period: cap risk at 0.01 lot unconditionally and accept the oversized risk percentage. On a demo account, the capital is virtual. The goal is observing execution behavior, not preserving virtual capital.

**Warning signs:**
- Zero trades generated over a full trading session despite fusion producing `should_trade=True`
- Logs show repeated `trade_skipped_risk_exceeds_limit` with `actual_risk_pct` values of 0.12-0.30
- Backtest generates trades (because it may use different equity assumptions) but live does not

**Phase to address:**
Phase 1 (Signal Pipeline Overhaul) for the configuration fix. The sizer logic itself is correct and should not be weakened -- only the thresholds need adjustment for the $20 phase.

---

### Pitfall 5: Backtest Log Flood -- 147K Debug Lines in First Window Kills Performance

**What goes wrong:**
The backtest runner processes 3.8M bars. Each bar triggers signal module updates, which log at DEBUG level via structlog. The chaos module alone generates 5 metrics per bar = 5 debug entries. Across 3 modules, that is ~15 debug lines per bar. At 3.8M bars: ~57M potential log lines. Even with structlog's efficient filtering, the overhead of constructing log context dictionaries, checking log levels, and formatting is measurable. The known issue reports 147K lines in the FIRST walk-forward window alone, suggesting DEBUG level is active during backtesting.

**Why it happens:**
The default config sets `level = "INFO"` but the backtest engine logs exceptions at DEBUG (`log.debug("signal_module_error", ...)` in `engine.py` line 118). If modules throw frequent exceptions during early bars (insufficient data), these DEBUG logs accumulate. Additionally, structlog's `cache_logger_on_first_use` may not be set, causing logger assembly overhead on every call.

**How to avoid:**
- Set log level to WARNING or ERROR during backtesting. The backtest runner should override the config's log level before starting: `structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))`.
- Use structlog's `make_filtering_bound_logger()` which makes debug methods return `None` immediately -- literally `return None` with zero overhead per the official docs.
- Move per-bar signal module debug logging behind a `if self._logger.isEnabledFor(logging.DEBUG)` guard to avoid constructing log context dicts when debug is disabled.
- Add a `--verbose` flag to the backtest CLI for when you actually need debug output, defaulting to quiet mode.
- Consider batch result collection: accumulate backtest metrics in memory and write a summary at the end rather than logging per-bar results.

**Warning signs:**
- Backtest takes >10 minutes for a single walk-forward window on 3.8M bars
- Disk I/O spikes during backtest (log file growing rapidly)
- Memory usage climbs steadily during backtest (log string accumulation)
- Backtest appears "stuck" but is actually just processing log output

**Phase to address:**
Phase 2 (Backtesting Pipeline Fix). Must be resolved before automated optimization can run (Phase 3), since optimization runs the backtest dozens of times.

---

### Pitfall 6: Paper-to-Live Switch Without order_check Validation

**What goes wrong:**
The OrderManager in `orders.py` correctly calls `order_check()` before `order_send()` in live mode (lines 185-195). However, paper mode bypasses this entirely (line 178-182 routes directly to PaperExecutor). This means paper trading never validates:
- Broker filling mode compatibility
- Stops level minimum distance
- Margin requirements
- Volume step compliance
- Symbol availability in Market Watch

When switching from paper to live, the first trade may fail for reasons that were never tested: wrong filling mode, SL too close to price, insufficient margin, or XAUUSD not in Market Watch.

**Why it happens:**
Paper mode was designed to simulate fills without MT5 interaction. This is correct for simulation but means zero live-path validation occurs until the actual switch to live mode.

**How to avoid:**
- Add a "dry-run live validation" step before the 1-week demo launch. With `mode=live` but a separate "validate only" flag, run `order_check()` on a sample request without calling `order_send()`. This validates the entire request construction pipeline against the real broker.
- On the FIRST live trade, log the full request dict and the `order_check` result at INFO level. Compare against paper trade requests to verify structural compatibility.
- Validate filling mode ONCE at startup by calling `_determine_filling_mode()` even in paper mode. Cache and log the result. RoboForex ECN typically requires IOC filling for XAUUSD.
- Verify XAUUSD is in Market Watch: `mt5.symbol_select("XAUUSD", True)` must be called before any data or trading operations.

**Warning signs:**
- `order_check` returns retcode != 0 on the first live trade
- `order_send` returns 10013 (TRADE_RETCODE_INVALID), 10016 (TRADE_RETCODE_INVALID_STOPS), or 10014 (TRADE_RETCODE_INVALID_VOLUME)
- `symbol_info` returns None for XAUUSD (not in Market Watch)

**Phase to address:**
Phase 4 (Live MT5 Execution). Add validation checks during connection setup, not at first trade time.

---

### Pitfall 7: MT5 Terminal Disconnects During Unattended Operation

**What goes wrong:**
The MT5 terminal can lose connection for many reasons during a week of unattended operation:
1. RoboForex server maintenance (typically weekends but also random maintenance)
2. Windows Update forcing a restart
3. Network interruption
4. MT5 terminal auto-update
5. Screen lock / display driver sleep causing the terminal UI to freeze
6. MT5 "AutoTrading" button getting disabled after an update or crash

The `MT5Bridge.reconnect_loop()` handles connection loss with exponential backoff, but it only checks `terminal_info().connected`. It does NOT detect:
- MT5 terminal process crashed entirely (terminal_info returns None but initialize() also fails)
- MT5 restarted but AutoTrading is disabled
- MT5 connected to broker but on a different account (after manual intervention)
- Weekend market closure (not a disconnection, but trading is impossible)

**Why it happens:**
The bridge assumes MT5 terminal is always running and just needs reconnection. In a week-long unattended scenario, the terminal itself may crash, Windows may restart, or the terminal may be reconfigured by an automatic update.

**How to avoid:**
- Add MT5 process monitoring: check if `terminal64.exe` is running before attempting reconnection. If the process is dead, attempt to restart it via `subprocess.Popen` pointing to the MT5 path.
- After successful reconnection, verify account details match expected (login, server, trading allowed).
- Implement a weekend detector: check if the market is open before attempting trades. XAUUSD typically closes Friday 22:00 UTC and reopens Sunday 23:00 UTC.
- Disable Windows automatic restart for updates during the demo period: `gsudo schtasks /Change /TN "\Microsoft\Windows\UpdateOrchestrator\Reboot" /Disable` or set active hours.
- Keep the MT5 terminal visible (not minimized behind other windows) and disable display sleep. The MT5 Python API communicates via the terminal's internal pipe server, which can become unresponsive if the terminal UI is frozen.
- Add a heartbeat file: write current timestamp to a file every 60 seconds. An external watchdog script (Task Scheduler) checks the file and restarts the bot if stale.

**Warning signs:**
- `mt5_reconnect_attempt` logs appearing repeatedly without `mt5_reconnected`
- Gaps in structured log timestamps (bot was down without logging)
- `terminal_info` returns None persistently (terminal is not running)
- Trade count drops to zero during market hours with no breaker trips

**Phase to address:**
Phase 5 (Demo Hardening). This is specifically the unattended operation hardening phase.

---

### Pitfall 8: Crash Recovery Leaves Orphaned Positions

**What goes wrong:**
If the Python process crashes while a position is open, the position remains on the MT5 server with the SL set at trade entry time. The bot has no record of this position when it restarts. It may then open a SECOND position on the same signal, or the orphaned position may hit its SL/TP without the bot tracking the outcome. The circuit breakers lose count of daily trades and P&L. The adaptive weight tracker does not learn from the orphaned trade outcome.

This is especially dangerous during the unattended demo week because no human is watching.

**Why it happens:**
The `TradeManager._open_position_ticket` is in-memory state. The `PaperExecutor._positions` dict is in-memory. Neither is persisted to SQLite across crashes. The engine has crash recovery logic (loading breaker state from SQLite), but position tracking relies on runtime state.

**How to avoid:**
- On startup, call `mt5.positions_get(symbol="XAUUSD")` to discover any existing positions. If positions exist with the bot's magic number, adopt them into the TradeManager's state.
- Persist open position ticket, entry price, and regime to SQLite when a position is opened. On crash recovery, load and reconcile with MT5 server state.
- Add a `close_all_positions()` call as the FIRST action after reconnection if the bot cannot reconcile its state (fail-safe: flat is safe).
- Log a critical alert if orphaned positions are discovered on startup: `WARN: Found 1 position opened by bot (magic=20260327) that was not tracked. Adopting.`

**Warning signs:**
- After restart, `mt5.positions_get()` returns positions with the bot's magic number
- Circuit breaker daily_trade_count does not match actual MT5 trade history
- Equity mismatch between bot's tracked equity and MT5 account equity

**Phase to address:**
Phase 4 (Live MT5 Execution) for position persistence. Phase 5 (Demo Hardening) for full crash recovery orchestration.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Raising risk_pct to 0.20 at $20 | Enables trading | Normalizes reckless risk management; habits carry into higher capital phases | Demo week only, with explicit code comment and config flag marking it as demo override |
| Hardcoding `starting_balance=20.0` in PaperExecutor | Quick paper mode | Diverges from config; real equity at restart may differ from 20 | Never -- should read from config.risk or account_info |
| Lowering fusion threshold without signal fixes | More trades immediately | Trades on noise; no edge; false confidence in trade frequency | Never -- fix signals first |
| Disabling circuit breakers during demo | Avoids breaker trips that halt demo observation | Masks real problems; demo results are not representative | Never |
| Using `log.debug` in hot loops during backtest | Easy debugging during development | 147K+ lines per window; backtest unusable at scale | Only with explicit `--verbose` flag |
| Skipping order_check in live mode | Faster execution | First failures are undiagnosed; requests may be malformed | Never -- order_check is cheap (~1ms) |
| Not persisting open positions to SQLite | Simpler code | Orphaned positions after crash; double-open risk | Paper mode only; must persist in live mode |

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| MT5 Python initialize() | Not checking return value; continuing to trade after False | Always check `if not mt5.initialize(): raise`; log `mt5.last_error()` |
| MT5 order_send() volume | Passing integer 0 instead of float 0.01 | All numeric fields (volume, sl, tp, price) must be float, never int |
| MT5 symbol_info_tick() | Calling before adding symbol to Market Watch | Call `mt5.symbol_select("XAUUSD", True)` at startup before any data/trading |
| MT5 filling mode | Hardcoding ORDER_FILLING_FOK | Query `symbol_info().filling_mode` bitmask; RoboForex ECN typically requires IOC |
| MT5 stops level | Setting SL too close to current price | Check `symbol_info().trade_stops_level * symbol_info().point` for minimum distance |
| MT5 weekend | Sending orders during market close (Fri 22:00 - Sun 23:00 UTC) | Check market hours before order placement; XAUUSD has specific session windows |
| RoboForex demo vs live | Assuming demo execution matches live (it does not -- demo fills are instant, live has variable latency) | Treat demo results as optimistic; apply 15-20% "reality discount" per gold EA research |
| structlog in backtest | Leaving DEBUG level active during multi-million-bar replay | Use `make_filtering_bound_logger(logging.WARNING)` for backtest runs |
| DuckDB during backtest | Writing per-bar analytical data during replay | Batch-write results after backtest completes, not during bar-by-bar replay |

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Per-bar `asyncio.to_thread` in backtest | Backtest is 10x slower than vectorized | Use synchronous chaos metric calls in backtest engine (skip `asyncio.to_thread` wrapper) | >100K bars in a single window |
| Per-bar structlog debug logging | 147K lines in first window; I/O bound | Set WARNING level for backtest; use `make_filtering_bound_logger` | >50K bars |
| `await mod.initialize()` repeated per walk-forward window | Numba JIT warmup runs every window (~2-5 sec) | Initialize Numba JIT once before walk-forward loop; pass warm modules | >3 walk-forward windows |
| Full signal pipeline on every bar in backtest | Chaos metrics computed on 300+ bars but only last value used | Cache intermediate results; only recompute when bar buffer changes materially | >500K bars |
| `executor.check_sl_tp(bar)` iterating all open positions per bar | O(n*m) where n=bars, m=positions | Use sorted position list with early exit; max_concurrent_positions=1 helps | >100 concurrent positions (unlikely given limit=1, but relevant for future multi-position) |
| Pandas DataFrame row iteration in backtest | `.iloc[-1]` in hot loop is slow | Pre-convert DataFrame to dict-of-arrays or NumPy structured array before replay loop | >1M bars |

## Security Mistakes

Domain-specific security issues for a trading bot.

| Mistake | Risk | Prevention |
|---------|------|------------|
| MT5 credentials in `default.toml` checked into git | Account compromised; unauthorized trading | Move credentials to environment variables or `.env` file; add `*.env` to `.gitignore`; use Pydantic `pydantic-settings` env var loading |
| Web dashboard API key "changeme" in config | Anyone on the network can control the bot (kill switch, view equity) | Generate a random API key on first run; store in `.env`; require HTTPS in non-localhost deployment |
| No rate limiting on web dashboard endpoints | DoS attack on local API could starve trading engine of CPU | Add rate limiting middleware; dashboard is secondary to trading engine |
| Logging account password in structlog | Password visible in log files | Never bind `mt5_password` to logger context; use `***` masking in any config logging |
| Unencrypted WebSocket for dashboard | Man-in-the-middle could inject commands | Use WSS (TLS) if dashboard is accessed from non-localhost |

## UX Pitfalls

Common monitoring/operator experience mistakes for an unattended trading bot.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No alerting when bot stops trading | Operator doesn't know bot is idle for hours | Send notification (email, Telegram, or file-based alert) if no trade evaluation occurs for 30+ minutes during session hours |
| Dashboard only shows current state, not history | Cannot diagnose "what happened at 3 AM" | Persist engine state snapshots to DuckDB every 60 seconds; add historical view to web dashboard |
| Breaker trip with no explanation | Operator sees "trading halted" but doesn't know why | Show which breaker tripped, what value triggered it, and what the threshold was |
| Log files grow unbounded during week-long run | Disk fills up; bot crashes | Implement log rotation (daily, max 7 files, 100MB each); structlog -> RotatingFileHandler |
| No distinction between "no signal" and "signal rejected" | Cannot tell if bot is broken vs. waiting for opportunity | Dashboard should show: last fusion result, last trade decision with reason, time since last trade |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces for v1.1.

- [ ] **Signal pipeline overhaul:** Often missing validation that ALL three modules produce nonzero direction at least some of the time -- verify by running 1000 bars and checking direction distribution for each module
- [ ] **Live MT5 execution:** Often missing `mt5.symbol_select("XAUUSD", True)` call at startup -- verify by starting with a fresh MT5 install where XAUUSD is not in Market Watch
- [ ] **Live MT5 execution:** Often missing handling of `order_send` retcode 10004 (TRADE_RETCODE_REQUOTE) -- verify by checking all retcode branches, not just 10009 (DONE)
- [ ] **Position tracking:** Often missing reconciliation between bot state and MT5 server state on restart -- verify by killing bot mid-trade and restarting
- [ ] **Backtest pipeline:** Often missing the case where the first walk-forward window has too few bars for chaos module (needs 300+ for Lyapunov) -- verify with a small data slice
- [ ] **Automated optimization:** Often missing a timeout per trial -- verify by checking if a single Optuna trial can run forever without cancellation
- [ ] **Demo hardening:** Often missing weekend handling -- verify by checking what happens if the bot runs through Friday close to Sunday open
- [ ] **Demo hardening:** Often missing log rotation -- verify by checking if structlog has a RotatingFileHandler configured
- [ ] **Session filter:** Often missing timezone-aware session reset -- verify with a clock set to different timezones
- [ ] **Circuit breakers:** Often missing the case where `daily_starting_equity` is never set (remains 0.0, making daily_dd check divide by zero or always pass) -- verify startup sequence sets this from account_info

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Chaos direction=0 killing fusion | LOW | Config change + small code fix in chaos module to derive micro-direction from price action. Regression test with existing 772 tests. |
| Timing urgency double-squared | LOW | Remove one `* urgency` multiplier. One-line fix. Run timing module tests to verify confidence range. |
| Threshold lowered before signal fix | MEDIUM | Revert threshold. Fix signals. Re-measure confidence distribution. Set new threshold from data. |
| Position sizer rejecting all trades at $20 | LOW | Raise aggressive_risk_pct in config or reduce sl_atr_base_multiplier. Config-only change. |
| Backtest log flood | LOW | Set log level to WARNING in backtest runner. 5-minute fix. |
| First live trade fails (filling/stops) | LOW | Read error code from `order_check` result. Fix request format. Re-deploy. No position was opened so no financial impact. |
| MT5 terminal crash during demo week | MEDIUM | Restart terminal via subprocess. Bot reconnect_loop picks up. Check for orphaned positions. Log gap in data. |
| Orphaned position after crash | HIGH | Manually check MT5 for open positions. Close manually if necessary. Reconcile bot state database. Lost tracking of that trade's outcome means learning loop has a gap. |
| Bot silent for hours (no trades, no errors) | MEDIUM | Check: session filter (outside trading hours?), circuit breakers (tripped?), fusion scores (below threshold?), MT5 connection (alive?). Multiple potential causes require systematic diagnosis. |

## Pitfall-to-Phase Mapping

How v1.1 roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Chaos direction=0 | Phase 1 (Signal Overhaul) | Run 1000 bars, verify chaos direction != 0 on >30% of bars |
| Timing urgency double-squared | Phase 1 (Signal Overhaul) | Verify timing confidence spans 0.1-0.8 range across test data |
| Threshold without signal fix | Phase 1 (Signal Overhaul) | Measure fused_confidence distribution BEFORE and AFTER signal fixes |
| Position sizer rejection at $20 | Phase 1 (Signal Overhaul) | Verify at least 1 trade can be sized at $20 equity with typical ATR |
| Backtest log flood | Phase 2 (Backtest Fix) | Full pipeline runs in <30 min on 3.8M bars with WARNING log level |
| Paper-to-live validation gap | Phase 4 (Live Execution) | Run order_check on constructed request before first real order_send |
| MT5 terminal disconnection | Phase 5 (Demo Hardening) | Simulate disconnection (kill terminal) and verify bot reconnects within 2 minutes |
| Orphaned positions | Phase 4 (Live Execution) + Phase 5 (Demo Hardening) | Kill bot with open position, restart, verify position is detected and adopted |
| Weekend handling | Phase 5 (Demo Hardening) | Run bot from Friday 21:00 through Monday 01:00 UTC, verify no errors during market close |
| Log rotation | Phase 5 (Demo Hardening) | Run bot for 24 hours, verify log files are rotated and total size is bounded |
| Alerting for silent bot | Phase 5 (Demo Hardening) | Disable session window, verify alert fires after 30 minutes of no activity |

## Phase-Specific Warnings

Detailed warnings organized by which v1.1 phase they affect.

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Signal Overhaul | Recalibrating for 200x more trades causes overfitting to recent data | Use walk-forward validation on the new parameters; do not optimize thresholds on the same data used to test frequency |
| Signal Overhaul | Changing one module's output range breaks fusion balance | After any module change, verify all three modules' output distributions are comparable (direction range, confidence range) |
| Signal Overhaul | Removing chaos direction=0 creates false directional signals | Use micro-trend within regime (short momentum), not regime-as-direction; validate that RANGING regime does not systematically favor one direction |
| Backtest Fix | Fixed log flood but introduced silent failures | After setting WARNING level, verify that actual errors (exceptions, order failures) are still logged |
| Backtest Fix | Walk-forward windows too small after data split | Ensure each window has minimum 1000 M1 bars (about 3 trading days) for chaos module warmup |
| Automated Optimization | Optuna optimizes on in-sample, overfits | Use the existing walk-forward + OOS gate as Optuna's objective, not raw profit |
| Live Execution | order_check passes but order_send still fails | Possible causes: price moved during check-to-send gap, margin changed, breaker tripped on server side. Always handle order_send failure even after successful check. |
| Live Execution | Demo account fills instantly but live will not | Do not tune execution timing based on demo fills. Plan for 100-500ms latency in real ECN. |
| Demo Hardening | Bot seems stable for 3 days, crashes on day 4 | Memory leak from tick buffer growth, structlog context accumulation, or DuckDB connection pool exhaustion. Monitor RSS memory usage over time. |
| Demo Hardening | Bot works in London session but fails in Asian session | Lower liquidity = wider spreads = spread spike breaker trips = no trading. Verify session windows and spread thresholds are appropriate for all configured sessions. |

## Sources

- Codebase analysis: `src/fxsoqqabot/signals/chaos/module.py` lines 122-129 (direction_map), `src/fxsoqqabot/signals/chaos/regime.py` lines 52-73 (classify_regime), `src/fxsoqqabot/signals/timing/module.py` line 136 (double urgency), `src/fxsoqqabot/signals/timing/ou_model.py` line 127 (inner urgency), `src/fxsoqqabot/signals/fusion/core.py` lines 96-108 (fusion formula), `src/fxsoqqabot/risk/sizing.py` lines 117-132 (position sizing math), `src/fxsoqqabot/execution/orders.py` lines 178-182 (paper bypass), `src/fxsoqqabot/execution/mt5_bridge.py` (reconnection logic)
- [MQL5 Python order_send documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py) -- return codes, request structure
- [MQL5 forum: Send order errors](https://www.mql5.com/en/forum/343594/page2) -- common data type and filling mode mistakes
- [Paper vs Live Slippage Analysis](https://markrbest.github.io/paper-vs-live/) -- execution differences between simulation and production
- [Paper vs Live Bots: Execution Differences Exposed](https://blog.pickmytrade.trade/paper-vs-live-bots-execution-differences/) -- fill quality, spread widening, market impact
- [structlog performance documentation](https://www.structlog.org/en/stable/performance.html) -- make_filtering_bound_logger, cache_logger_on_first_use
- [Overfitting in Algorithmic Trading (Coinmonks)](https://medium.com/coinmonks/overfitting-in-algorithmic-trading-navigating-the-pitfalls-e87aa942a584) -- signal recalibration pitfalls
- [Robustness Tests for Algorithmic Trading Strategies](https://www.buildalpha.com/robustness-testing-guide/) -- walk-forward validation, parameter stability
- [How to fix accidental disconnection of MetaTrader](https://medium.com/the-trading-scientist/how-to-fix-accidental-disconnection-of-metatrader-2365ea899c3f) -- terminal monitoring
- [Gold Scalping Strategy on MT5 (2026)](https://xmsignal.com/en/blog/gold-scalping-strategy-mt5/) -- XAUUSD spread behavior, session timing
- [How We Built a Profitable Gold Trading Bot (54% ROI)](https://www.nadcab.com/blog/gold-trading-bot-xauusd-development-journey) -- reality discount on backtest results
- [Lot Sizes for Small Accounts](https://leverage.trading/what-lot-size-to-use-for-a-small-forex-account/) -- $20 account micro lot constraints
- [MQL5 forum: Backtest consuming too much memory](https://www.mql5.com/en/forum/464097) -- large-scale backtest resource management
- [ChartVPS: Avoid server crash during backtesting](https://chartvps.com/helpdesk/how-to-avoid-server-crash-during-mt4-mt5-backtesting-and-optimization/) -- memory and CPU optimization

---
*Pitfalls research for: FXSoqqaBot v1.1 Live Demo Launch*
*Researched: 2026-03-28*
