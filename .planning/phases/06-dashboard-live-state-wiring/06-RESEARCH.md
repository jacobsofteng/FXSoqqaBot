# Phase 6: Dashboard Live State Wiring - Research

**Researched:** 2026-03-28
**Domain:** Engine-to-dashboard state wiring, async state management, bug fixes
**Confidence:** HIGH

## Summary

Phase 6 is a gap-closure phase fixing four distinct integration bugs identified by the v1.0 milestone audit. All the underlying infrastructure (TradingEngineState, TUI app, web dashboard server, KillSwitch, CircuitBreakerManager, AdaptiveWeightTracker) already exists and is tested. The bugs are exclusively wiring-level: attributes never assigned, async methods read as sync, state fields never populated, and a pause flag set but never checked.

The four success criteria map directly to four concrete bug categories: (1) `_current_equity` and `_connected` are referenced by `_update_engine_state()` via `getattr()` but never assigned anywhere on the engine instance, (2) `is_killed` is an async method on KillSwitch but `_update_engine_state()` reads it with `getattr()` as if it were a property, returning a coroutine object (always truthy) instead of a boolean, (3) `equity_history` on TradingEngineState is never appended to, `/api/module-weights` returns hardcoded empty data, and `to_dict()` omits equity_history from WebSocket output, and (4) `is_paused` is toggled by TUI/web callbacks but `_signal_loop()`, `_tick_loop()`, and `_bar_loop()` never check it.

**Primary recommendation:** Fix all four bug categories directly in `engine.py` with targeted edits to `_update_engine_state()`, the three loops, and component initialization. Add a `get_breaker_status()` method to CircuitBreakerManager. No new libraries, no architectural changes.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OBS-01 | Rich terminal TUI dashboard shows in real time: current regime (color-coded), signal confidence per module, open positions with live P&L, spread/slippage metrics, circuit breaker status, daily stats | Bugs 1-3 below prevent equity, connection status, and kill state from displaying correctly. TUI code itself is complete and reads from TradingEngineState -- the issue is the engine never writes correct values. |
| OBS-04 | Lightweight web dashboard shows historical equity curve, trade history with filters, regime timeline, module performance comparison, and cumulative win rate | equity_history never populated (Bug 3), /api/module-weights returns empty (Bug 3b), regime timeline data depends on trade_logger which works. to_dict() omits equity_history from WebSocket stream. |
</phase_requirements>

## Standard Stack

No new libraries required. This phase exclusively modifies existing code.

### Core (already installed)
| Library | Version | Purpose | Phase 6 Usage |
|---------|---------|---------|---------------|
| Textual | 8.1.1 | TUI dashboard | Already works, reads from TradingEngineState |
| FastAPI | 0.115+ | Web dashboard REST/WebSocket | Already works, reads from TradingEngineState |
| structlog | 25.5.0 | Structured logging | Log state wiring changes |

No installation needed.

## Architecture Patterns

### Bug Inventory (4 categories, mapped to success criteria)

#### Bug 1: `_current_equity` and `_connected` never assigned (SC-1)

**Location:** `engine.py` lines 913, 930
```python
# Current broken code:
s.equity = getattr(self, "_current_equity", 0.0)   # line 913
s.is_connected = getattr(self, "_connected", False)  # line 930
```

**Root cause:** `_update_engine_state()` reads `self._current_equity` and `self._connected` via `getattr()` with fallback defaults. Neither attribute is ever assigned on the `TradingEngine` instance. The engine DOES fetch account info in `_health_loop()` (line 563) and `_signal_loop()` (line 642), but it passes `account_info.equity` directly to breaker checks and position sizing without storing it on `self`. The bridge tracks `self._connected` internally but the engine never reads it.

**Fix pattern:**
1. In `_health_loop()` after fetching `account_info`, assign `self._current_equity = account_info.equity` and `self._connected = self._bridge.is_connected`
2. In `_signal_loop()` similarly, update `self._current_equity` from `account_info.equity`
3. Initialize `self._current_equity = 0.0` and `self._connected = False` in `__init__`
4. After successful `_connect_mt5()` in `start()`, set `self._connected = True`

**Confidence:** HIGH -- direct code tracing confirms the root cause.

#### Bug 2: `is_killed` reads coroutine object (SC-2)

**Location:** `engine.py` line 934
```python
# Current broken code:
s.is_killed = getattr(self._kill_switch, "is_killed", False)
```

**Root cause:** `KillSwitch.is_killed` is defined as `async def is_killed(self) -> bool:` (kill_switch.py line 73). Using `getattr()` on an async method returns the bound method object, which is always truthy. The code never `await`s it. Since `_update_engine_state()` is a synchronous method (called from the signal loop), it cannot await the async method.

**Fix options (two approaches):**

**Option A (recommended):** Read the kill state directly from the persisted CircuitBreakerSnapshot. The KillSwitch.activate() already writes `BreakerState.KILLED` to the snapshot. The CircuitBreakerManager holds `self._snapshot` which is already in memory (loaded at startup, updated on changes). Add a synchronous property or method to check it.

**Option B:** Cache a `_is_killed` boolean on the KillSwitch instance, updated in `activate()` and `reset()`. The engine reads the cached boolean synchronously.

Option A is better because the breaker snapshot is already the source of truth and is already synchronously accessible via `self._breakers._snapshot.kill_switch`.

**Concrete fix:** Replace the `getattr` line with:
```python
if self._breakers:
    s.is_killed = self._breakers._snapshot.kill_switch == BreakerState.KILLED
```
Or better, add a synchronous `is_killed` property to CircuitBreakerManager that checks `self._snapshot.kill_switch`.

**Confidence:** HIGH -- async method signature confirmed, fix is straightforward.

#### Bug 3: `equity_history` never populated, `/api/module-weights` empty (SC-3)

**Location:** `engine.py` `_update_engine_state()` and `server.py` `/api/module-weights`

**Sub-bugs:**

**3a. equity_history never appended to:**
`TradingEngineState.equity_history` is a `list[float]` initialized empty. No code ever appends to it. The TUI reads `state.equity_history[-50:]` for the sparkline (always empty). The web endpoint `/api/equity` reads `self._state.equity_history` (always empty).

**Fix:** In `_update_engine_state()`, after setting `s.equity`, append the value:
```python
if s.equity > 0:
    s.equity_history.append(s.equity)
    # Cap at reasonable size to prevent unbounded growth
    if len(s.equity_history) > 1000:
        s.equity_history = s.equity_history[-500:]
```
This populates the sparkline and the `/api/equity` endpoint.

**3b. /api/module-weights returns empty:**
```python
# Current broken code (server.py line 152):
return {"data": []}  # Hardcoded placeholder
```
The AdaptiveWeightTracker holds current weights via `get_weights()`. The engine has `self._weight_tracker`. But the DashboardServer has no reference to the weight tracker -- it only receives the TradingEngineState.

**Fix:** Add a `module_weights` field to `TradingEngineState`. Populate it in `_update_engine_state()` from `self._weight_tracker.get_weights()`. Update the `/api/module-weights` endpoint to return `self._state.module_weights` instead of empty data.

**3c. to_dict() omits equity_history:**
`TradingEngineState.to_dict()` serializes 19 fields but excludes `equity_history`. This means the WebSocket stream at `/ws/live` never sends equity history to the web dashboard.

**Fix:** Add `"equity_history": self.equity_history[-50:]` to `to_dict()` (send last 50 points, not full history).

**3d. Regime timeline data:**
The `/api/regime-timeline` endpoint queries `trade_logger.query_trades()` and extracts regime + timestamp. This actually works IF there are trades logged. The issue is upstream: equity is 0 which makes things look broken, but the regime timeline data flow itself is functional.

**Confidence:** HIGH -- all confirmed by code inspection.

#### Bug 4: Pause flag not checked in loops (SC-4)

**Location:** `engine.py` `_signal_loop()`, `_tick_loop()`, `_bar_loop()`

**Root cause:** `_handle_pause()` toggles `self._engine_state.is_paused` (line 969), and the TUI callback does the same. But none of the three main loops check `self._engine_state.is_paused` before doing work.

**Fix pattern:** At the top of each loop iteration, check the pause flag:
```python
# In _signal_loop, _tick_loop, _bar_loop:
while self._running:
    if self._engine_state.is_paused:
        await asyncio_sleep(interval_s)
        continue
    # ... rest of loop body
```

**Design decision:** Tick loop should probably still poll ticks (to keep buffers fresh for unpausing), but skip trade-related activity. Signal loop and bar loop should skip evaluation entirely. The exact behavior to implement:

- `_signal_loop`: Skip signal evaluation, fusion, and trade execution when paused. This is the critical one -- it prevents new trades.
- `_tick_loop`: Continue polling ticks (buffer freshness), but skip paper SL/TP checking when paused (no position changes while paused).
- `_bar_loop`: Continue refreshing bars (keep data current for when we unpause).

Alternatively, the simplest correct approach per the success criteria ("skip evaluation") is:
- `_signal_loop`: Skip entire body when paused
- `_tick_loop`: Skip entire body when paused
- `_bar_loop`: Skip entire body when paused

The success criteria says "_signal_loop, _tick_loop, and _bar_loop skip evaluation until unpaused" which suggests all three skip. The simpler approach of `continue` on all three is cleaner and matches the spec.

**Confidence:** HIGH -- straightforward loop guard.

### Additional Fix: CircuitBreakerManager.get_breaker_status()

The engine's `_update_engine_state()` calls `self._breakers.get_snapshot()` (line 918) but this method does not exist. The try/except silently swallows the AttributeError, meaning `breaker_status` in the dashboard state dict is never properly populated.

**Fix:** Add a synchronous method to CircuitBreakerManager that returns breaker status as a dict. It should expose all breaker states from `self._snapshot`:
```python
def get_breaker_status(self) -> dict[str, str]:
    """Return all breaker states as a dict for dashboard display."""
    return {
        "kill_switch": self._snapshot.kill_switch.value,
        "daily_drawdown": self._snapshot.daily_drawdown.value,
        "loss_streak": self._snapshot.loss_streak.value,
        "rapid_equity_drop": self._snapshot.rapid_equity_drop.value,
        "max_trades": self._snapshot.max_trades.value,
        "spread_spike": self._snapshot.spread_spike.value,
    }
```

Then update the engine to call this instead of the nonexistent `get_snapshot()`.

### Recommended File Edit Summary

| File | Changes |
|------|---------|
| `src/fxsoqqabot/core/engine.py` | Add `_current_equity`/`_connected` attrs to `__init__`; assign them in `_health_loop`/`_signal_loop`/`start`; fix `is_killed` read; populate `equity_history`; populate `module_weights`; add pause guards to all three loops; fix breaker_status population |
| `src/fxsoqqabot/core/state_snapshot.py` | Add `module_weights` field; add `equity_history` to `to_dict()` |
| `src/fxsoqqabot/risk/circuit_breakers.py` | Add `get_breaker_status()` method and `is_killed` property |
| `src/fxsoqqabot/dashboard/web/server.py` | Update `/api/module-weights` to read from state instead of returning empty |

### Anti-Patterns to Avoid

- **Using getattr() for state that should be explicit attributes:** The root cause of Bug 1. Define attributes explicitly in `__init__` rather than relying on `getattr(self, name, default)`.
- **Reading async methods synchronously without await:** The root cause of Bug 2. If a value is needed synchronously, cache it or provide a sync accessor.
- **Hardcoded placeholder returns in production endpoints:** Bug 3b. The `/api/module-weights` endpoint returns empty data with a comment "placeholder until learning loop wired." Placeholders in production code should at minimum read available data.
- **Setting flags without checking them:** Bug 4. A pause flag that is toggled but never consulted is a behavioral lie.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| State synchronization between engine and dashboards | Custom pub/sub or event system | Direct field assignment on shared TradingEngineState (existing pattern) | The existing pattern works fine -- the fields just need to be written. No need to add complexity. |
| Kill switch state checking | New async polling mechanism | Read from in-memory CircuitBreakerSnapshot which is already loaded | The snapshot is already in memory and updated on changes. No need for additional DB queries. |
| Equity history storage | Separate time-series database | Append to list on TradingEngineState (capped at 1000) | For dashboard sparkline and equity chart, a capped in-memory list is sufficient. Historical equity is already persisted in SQLite account_snapshots table. |

## Common Pitfalls

### Pitfall 1: Unbounded equity_history growth
**What goes wrong:** Appending to `equity_history` every signal loop iteration (every few seconds) without bounds creates memory growth over hours/days.
**Why it happens:** Signal loop runs every `bar_refresh_interval_seconds` (default likely 5-30s). Over 8 hours that is 960-5760 entries minimum.
**How to avoid:** Cap the list at 1000 entries. Trim to 500 when it exceeds 1000 to avoid excessive list slicing on every append.
**Warning signs:** Memory growth over time, slow dashboard renders.

### Pitfall 2: Race condition on is_paused toggle
**What goes wrong:** TUI callback toggles `is_paused` in the app thread while loops check it in the asyncio event loop. In CPython this is safe due to GIL for simple bool assignment, but could cause a single iteration to see inconsistent state.
**Why it happens:** TUI's action_toggle_pause runs in Textual's thread, not the asyncio loop.
**How to avoid:** Since is_paused is a simple bool on a dataclass and CPython's GIL makes single attribute reads/writes atomic, this is safe for our use case. No threading lock needed.
**Warning signs:** None -- this is a theoretical concern that CPython's GIL handles.

### Pitfall 3: Pause not stopping in-flight trades
**What goes wrong:** A trade decision has been made but not yet executed when pause is toggled. The trade may still execute.
**Why it happens:** The check is at loop top, but evaluate_and_execute is a single async call.
**How to avoid:** Check `is_paused` once at loop top (before any work). If the signal evaluation is already in progress, it completes. This is acceptable behavior -- the pause takes effect at the next loop iteration, not mid-execution.
**Warning signs:** A trade executing 1 cycle after pause. This is by design.

### Pitfall 4: _handle_kill callback signature mismatch
**What goes wrong:** `_handle_kill()` calls `self._kill_switch.activate(self._order_manager)` but `KillSwitch.activate()` is defined as `async def activate(self) -> dict:` with no parameters -- it uses `self._order_manager` from its own constructor.
**Why it happens:** The engine passes `_order_manager` to the KillSwitch constructor AND tries to pass it again in the kill callback. The signature mismatch will cause a TypeError.
**How to avoid:** Fix `_handle_kill()` to call `await self._kill_switch.activate()` without arguments. Also update the cached `is_killed` state after activation.
**Warning signs:** Kill switch activation from dashboard fails with TypeError.

### Pitfall 5: CircuitBreakerManager.get_snapshot does not exist
**What goes wrong:** Engine calls `self._breakers.get_snapshot()` inside try/except which silently fails. Breaker status in dashboard is never populated.
**Why it happens:** The method was referenced but never implemented. The internal `self._snapshot` attribute exists but no public accessor was created.
**How to avoid:** Add a `get_breaker_status()` method that returns the status dict. Update the engine to call it.
**Warning signs:** Dashboard breaker_status always shows empty or default values.

## Code Examples

### Fix 1: Assign _current_equity and _connected in engine.__init__ and loops

```python
# In __init__:
self._current_equity: float = 0.0
self._connected: bool = False

# In _health_loop, after account_info fetch:
account_info = await self._bridge.get_account_info()
if account_info is not None:
    self._current_equity = account_info.equity
self._connected = self._bridge.is_connected

# In _signal_loop, after account_info fetch:
account_info = await self._bridge.get_account_info()
equity = account_info.equity if account_info else 20.0
self._current_equity = equity
```

### Fix 2: Read is_killed synchronously from breaker snapshot

```python
# In circuit_breakers.py - add property:
@property
def is_killed(self) -> bool:
    """Synchronous check if kill switch is active."""
    return self._snapshot.kill_switch == BreakerState.KILLED

# In engine.py _update_engine_state:
if self._breakers:
    s.is_killed = self._breakers.is_killed
```

### Fix 3: Populate equity_history and module_weights

```python
# In _update_engine_state:
# Equity history (append and cap)
if s.equity > 0:
    s.equity_history.append(s.equity)
    if len(s.equity_history) > 1000:
        s.equity_history = s.equity_history[-500:]

# Module weights
if self._weight_tracker:
    s.module_weights = self._weight_tracker.get_weights()
```

### Fix 4: Pause guard in loops

```python
# In each loop (_signal_loop, _tick_loop, _bar_loop):
while self._running:
    if self._engine_state.is_paused:
        await asyncio_sleep(interval_s)
        continue
    # ... existing loop body
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| getattr(self, attr, default) for engine state | Explicit instance attributes set in __init__ | This phase | Eliminates silent None/default behavior |
| Async method read via getattr (coroutine leak) | Synchronous property on cached snapshot | This phase | Returns actual boolean instead of truthy coroutine |
| Placeholder empty returns in API endpoints | Read from shared state dataclass | This phase | API returns real data |

## Open Questions

1. **Equity history granularity**
   - What we know: Signal loop runs every `bar_refresh_interval_seconds` and health loop every 10s. Both update equity.
   - What's unclear: Should equity_history be populated from _signal_loop (tied to signal cycle) or _health_loop (regular interval)?
   - Recommendation: Populate from _health_loop for consistent 10-second intervals, independent of signal activity. This gives cleaner sparkline data.

2. **Module weights history vs current**
   - What we know: `/api/module-weights` currently returns empty. The web charts expect time-series data (timestamp + per-module weight).
   - What's unclear: Should we store weight history over time, or just return current weights?
   - Recommendation: For this gap-closure phase, return current weights as a single data point. Full time-series weight history is a future enhancement. The endpoint should return `{"data": [{"chaos": 0.33, "flow": 0.33, "timing": 0.33}]}` at minimum.

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection of `engine.py`, `state_snapshot.py`, `kill_switch.py`, `circuit_breakers.py`, `server.py`, `app.py`, `widgets.py`
- v1.0 milestone audit report (`.planning/v1.0-MILESTONE-AUDIT.md`)
- ROADMAP.md Phase 6 success criteria

### Secondary (MEDIUM confidence)
- None needed -- all findings are from direct code reading

### Tertiary (LOW confidence)
- None

## Project Constraints (from CLAUDE.md)

- **Python 3.12.x** runtime
- **pytest** for testing with `pytest-asyncio` for async tests
- **structlog** for logging (not loguru)
- **Textual 8.1.1** for TUI (already in use)
- **FastAPI** for web dashboard (already in use)
- **No new dependencies needed** for this phase
- **ruff** for linting/formatting
- **mypy** for type checking
- Test at component level (not full TradingEngine) to avoid MT5 dependency per Phase 05 decision

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new libraries, existing codebase only
- Architecture: HIGH - bugs identified via direct code tracing, fixes are mechanical
- Pitfalls: HIGH - all edge cases identified from existing code patterns

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (stable -- fixes are against stable codebase)
