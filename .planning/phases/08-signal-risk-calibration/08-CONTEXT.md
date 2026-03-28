# Phase 8: Signal & Risk Calibration - Context

**Gathered:** 2026-03-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix the signal-to-trade pipeline so it produces 10-20 trade signals per day on backtested London+NY session data at $20 micro-account constraints. This involves fixing chaos direction output, timing urgency compression, fusion confidence thresholds, position sizing parameters, circuit breaker phase-awareness, concurrent position support, and session window expansion.

</domain>

<decisions>
## Implementation Decisions

### Chaos Direction Strategy (SIG-01, SIG-04)
- **D-01:** Default chaos direction mode is **drift** — non-trending regimes (RANGING, HIGH_CHAOS, PRE_BIFURCATION) use recent price momentum (`price_direction` from 20-bar lookback) instead of hardcoded 0.0
- **D-02:** Direction mode is configurable with three options: `zero` (current behavior), `drift` (default), `flow_follow` (borrows flow module direction). Mode is selectable via config and included in Optuna search space per SIG-04
- **D-03:** Drift mode is self-contained within the chaos module — no cross-module coupling required. Flow_follow mode will require cross-module data passing (design deferred to researcher/planner)

### Signal Aggressiveness Tuning (SIG-02, SIG-03, RISK-01)
- **D-04:** Fusion confidence threshold for aggressive phase set to **0.30** (down from 0.50). Selective and conservative thresholds shift proportionally
- **D-05:** Aggressive risk_pct raised to **15%** (0.15) from 10% (0.10) per RISK-01
- **D-06:** SL ATR multiplier reduced to **1.0x** from 2.0x per RISK-01 — tighter stops, smaller risk per trade, more trades accepted by sizer
- **D-07:** All three parameter changes applied **simultaneously** — they were designed as a package in the requirements and should be calibrated together
- **D-08:** Timing urgency double-compression fix per SIG-02 — ensure urgency is applied once, preserving moderate signals above 0.25 confidence

### Concurrent Positions (RISK-03)
- **D-09:** Max concurrent positions raised to **2** (from 1)
- **D-10:** Aggregate exposure cap uses **remaining budget** approach — first position gets full risk budget (15%), second position gets whatever risk budget remains (15% minus position 1's actual risk). Total aggregate exposure never exceeds the single-position risk budget
- **D-11:** At $20 equity with 15% risk, if first position uses ~$1.50 risk, second position gets ~$1.50 remaining. If first position uses the full $3.00 budget, no second position is allowed

### Circuit Breaker Phase-Awareness (RISK-02)
- **D-12:** Daily drawdown limit becomes phase-aware: 15-20% for aggressive, 10% for selective, 5% for conservative (currently flat 5%)
- **D-13:** Exact aggressive drawdown value to be determined by researcher/planner within the 15-20% range specified in RISK-02

### Session Windows (RISK-04)
- **D-14:** Two separate trading windows: **London (08:00-12:00 UTC)** and **London-NY overlap (13:00-17:00 UTC)**
- **D-15:** The 12:00-13:00 UTC gap is **intentionally kept** — London lunch hour is low-liquidity with wider spreads, standard institutional convention to avoid

### Claude's Discretion
- Exact aggressive daily drawdown percentage within the 15-20% range (D-13)
- How flow_follow mode cross-module data passing is implemented (D-03)
- Whether selective/conservative thresholds shift proportionally with aggressive or stay at 0.60/0.70

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — SIG-01 through SIG-04 (signal calibration), RISK-01 through RISK-04 (risk management)

### Signal Pipeline
- `src/fxsoqqabot/signals/chaos/module.py` — Chaos module with direction_map (lines 122-128) that needs drift mode
- `src/fxsoqqabot/signals/chaos/regime.py` — Regime classifier producing the 5 regime states
- `src/fxsoqqabot/signals/timing/module.py` — Timing module with urgency computation (line 136) to check for double-compression
- `src/fxsoqqabot/signals/fusion/core.py` — FusionCore.fuse() with confidence threshold logic
- `src/fxsoqqabot/signals/fusion/phase_behavior.py` — PhaseBehavior with confidence thresholds and regime adjustments

### Risk Management
- `src/fxsoqqabot/risk/sizing.py` — PositionSizer with risk_pct and SL distance calculations
- `src/fxsoqqabot/risk/circuit_breakers.py` — CircuitBreakerManager with flat daily_drawdown_pct
- `src/fxsoqqabot/risk/session.py` — SessionFilter with single window config

### Configuration
- `src/fxsoqqabot/config/models.py` — All config models: RiskConfig (line 16), FusionConfig (line 208), ChaosConfig (line 149), SessionConfig (line 83)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `price_direction` calculation already exists in chaos module (lines 101-104) — drift mode just needs to use it for non-trending regimes
- `PhaseBehavior.get_confidence_threshold()` already does sigmoid interpolation across phases — can be extended for drawdown limits
- `PositionSizer.get_capital_phase()` returns the phase string — reusable for phase-aware drawdown
- `SessionFilter._parse_windows()` already supports multiple window dicts — just needs a second entry in default config

### Established Patterns
- Config-driven behavior: all parameters flow through Pydantic config models in `config/models.py`
- Phase-aware logic uses `get_capital_phase()` to branch on equity level
- Signal modules implement `SignalModule` Protocol with `update()` returning `SignalOutput`
- Circuit breakers use `BreakerState` enum and persist via `StateManager`

### Integration Points
- `FusionConfig.max_concurrent_positions` controls position limit — needs to wire into trade manager
- `FusionConfig` needs new field for chaos direction mode
- `RiskConfig.daily_drawdown_pct` needs to become phase-aware (either multiple fields or a method)
- `SessionConfig.windows` default needs second window entry
- Trade manager (`fusion/trade_manager.py`) needs remaining-budget logic for concurrent positions

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches within the decisions captured above.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 08-signal-risk-calibration*
*Context gathered: 2026-03-28*
