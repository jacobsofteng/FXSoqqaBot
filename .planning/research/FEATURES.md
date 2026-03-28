# Feature Research: v1.1 Live Demo Launch

**Domain:** XAUUSD scalping bot -- signal recalibration, live execution, automated optimization
**Researched:** 2026-03-28
**Confidence:** HIGH (grounded in codebase analysis + domain research)

## Context

v1.0 is shipped with 14.8K LOC, 772+ passing tests, and a complete signal-to-execution pipeline. The critical problem: the bot generates approximately 20 trades per 3 months instead of the target 10-20 trades per day. This research identifies exactly what features are needed for v1.1 to achieve the target trade frequency and run unattended on a demo account.

Root causes are code-level, not architectural. The pipeline is correctly wired but calibrated too conservatively at every stage, creating a multiplicative filter that chokes trade flow.

---

## Feature Landscape

### Table Stakes (Must Ship for v1.1 Demo)

Features without which the bot cannot generate 10-20 trades/day on a demo account.

| Feature | Why Expected | Complexity | Depends On | Notes |
|---------|--------------|------------|------------|-------|
| **Chaos direction for non-trending regimes** | Chaos module returns `direction=0.0` for RANGING, HIGH_CHAOS, PRE_BIFURCATION -- 60-80% of market time. With 3 modules weighted equally and one contributing zero direction, fusion composite collapses. A scalping bot MUST have directional signals during ranging markets. | MEDIUM | None (standalone fix) | The direction_map in `chaos/module.py` lines 122-128 hardcodes `0.0` for 3 of 5 regimes. Fix: allow chaos to contribute a weak directional signal derived from sub-metrics (e.g., Hurst drift, entropy gradient) instead of pure zero. Alternatively, make chaos a regime-only module that provides confidence without direction, and let flow+timing drive direction. |
| **Timing urgency recalibration** | In `timing/module.py` line 136, `final_confidence = (window_conf * 0.6 + phase_conf * 0.4) * urgency`. The urgency term (0-1) multiplies the already-blended confidence, meaning urgency near 0.5 produces ~0.25 confidence. Combined with fusion threshold 0.50, timing rarely contributes enough. | LOW | None (standalone fix) | The urgency-as-multiplier pattern double-penalizes moderate signals. Fix: use urgency as a weighted additive component or apply square-root scaling to preserve moderate signals. Industry standard: urgency should boost confidence when high, not annihilate it when moderate. |
| **Fusion threshold reduction for aggressive phase** | Default `aggressive_confidence_threshold = 0.50` with 3 modules. When chaos=0.0 direction and timing confidence is urgency-scaled, the fusion pipeline cannot reach 0.50. With equal weights (1/3 each), even perfect flow+timing signals produce at best `fused_confidence = 0.67`, which only barely clears threshold. | LOW | None (config change) | Math: 3 modules at equal weight (0.333 each). If chaos confidence=0.6 but direction=0.0, its weighted_score=0. fused_confidence = sum(conf*weight) = only non-zero modules contribute. Threshold 0.30-0.35 for aggressive phase is realistic for compound signals. Optuna should search [0.15, 0.50] for aggressive threshold. |
| **Position sizing for $20 equity** | At $20 equity, 10% risk = $2.00. With ATR*2 SL (gold ATR on M5 during London is ~$1.50-3.00, so SL distance = $3-6), and contract_size=100: lot_size = $2 / ($3 * 100) = 0.0067, rounded to 0.01 min lot. Actual risk at 0.01 lot = $3 * 100 * 0.01 = $3.00 = 15% of equity. The sizer correctly rejects this (15% > 10% limit). | MEDIUM | ATR-based SL recalibration | Two fixes needed: (1) reduce SL distance via lower ATR multiplier (1.0-1.5x instead of 2.0x for aggressive phase), and (2) accept higher risk_pct in aggressive phase (15-20% per trade is standard for $20 micro-account scalping with 1:500 leverage). At SL=$1.50 (1x ATR) and 20% risk: lot = $4 / ($1.50 * 100) = 0.027, rounds to 0.02. Actual risk = $3.00 = 15%. Passes. |
| **Multiple concurrent positions** | `max_concurrent_positions = 1` in config. Single-position limit blocks new trades while one is open. Gold scalps at M5 can last 5-60 minutes. With 1 position and 10-20 trades/day, average hold time must be < 24-48 minutes. Allowing 2-3 concurrent positions provides flexibility without excessive risk. | MEDIUM | Risk management adjustment | Change `max_concurrent_positions` from 1 to 2-3 for aggressive phase. Total exposure still bounded by daily drawdown breaker (5%) and max total drawdown (25%). With 3 positions at 0.01 lot each, max exposure = 3 * 0.01 * $3 SL * 100 = $9 = 45% of $20 -- needs per-position + aggregate risk check. |
| **Circuit breaker recalibration for $20** | Daily drawdown 5% of $20 = $1.00 -- a single losing trade at 0.01 lot with $3 SL costs $3.00, immediately tripping the breaker. Consecutive loss streak at 5 is reasonable but daily_drawdown_pct must accommodate micro-account reality. | LOW | Position sizing fix | Increase `daily_drawdown_pct` to 15-20% for aggressive phase ($20 * 15% = $3.00 = exactly 1 losing trade). Or better: make drawdown limits phase-aware like confidence thresholds. |
| **Live MT5 order execution mode** | Paper executor exists and works. Live path in `orders.py` exists (order_check + order_send), MT5Bridge has all methods. But no integration test on demo account, no trailing stop modification, and `live.toml` only sets `mode = "live"`. | MEDIUM | Position sizing fix, circuit breaker fix | The code path exists but is untested. Need: (1) demo account validation, (2) `TRADE_ACTION_SLTP` for SL/TP modification (trailing stops), (3) position sync on startup (recover existing positions after crash), (4) order_check error code handling (requotes, broker busy). |
| **Trailing stop implementation** | `TradeManager.get_trailing_params()` returns params but nothing calls it to actually modify the SL on MT5. The paper executor's `check_sl_tp()` only checks fixed SL/TP hits. No trailing logic exists in either paper or live mode. | MEDIUM | Live execution mode | MT5 does not have built-in Python trailing stops. Must implement: poll positions every tick, compare current price to activation threshold, if triggered send `TRADE_ACTION_SLTP` to modify SL. Use `mt5.order_send()` with action=`TRADE_ACTION_SLTP`, position ticket, and new SL value. |
| **Automated optimization end-to-end** | Optimizer exists (`optimization/optimizer.py`) but has never completed a run. Uses synchronous `asyncio.run()` per-trial which is slow. Search space covers only FusionConfig params, not the chaos/timing calibration params that are the actual bottleneck. | HIGH | Signal recalibration (must work first) | Current search space: 11 FusionConfig params (thresholds, RR ratios, SL multipliers). Missing from search space: chaos regime classification thresholds, timing urgency scaling, flow signal weights. Must expand search space to cover the parameters that actually gate trade frequency. Also: objective function penalizes <5 trades but target is 10-20/day, need trade count as secondary objective. |

### Differentiators (Enhance Demo Quality)

Features that improve demo quality and confidence but are not strictly required for 10-20 trades/day.

| Feature | Value Proposition | Complexity | Depends On | Notes |
|---------|-------------------|------------|------------|-------|
| **Multi-objective optimization (trade frequency + profitability)** | Current objective is profit factor only. A strategy with PF=3.0 and 2 trades is "optimal" but useless for 10-20/day target. Optuna supports multi-objective via `create_study(directions=["maximize", "maximize"])` for PF + trade_count Pareto front. | MEDIUM | Optimization pipeline | Use Optuna's `NSGAIISampler` for multi-objective: maximize profit_factor AND maximize min(trade_count, 20). Pareto-optimal solutions balance both. Critical for finding parameters that actually produce the target frequency. |
| **Position sync on startup** | If bot crashes with open positions, it currently starts fresh. On restart, it should query `mt5.positions_get()` and reconcile with internal state. Without this, orphan positions accumulate. | MEDIUM | Live execution mode | On engine start: call `positions_get(symbol="XAUUSD")`, populate `_open_position_ticket` in TradeManager, set `_open_position_entry` from position data. Without this, the max_concurrent_positions check is bypassed after a crash. |
| **Configurable regime-to-direction mapping** | Hardcoded direction_map in chaos module. Making this configurable allows Optuna to search whether RANGING should contribute a small directional bias based on sub-metrics. | LOW | Chaos direction fix | Add to ChaosConfig: `ranging_direction_mode: str = "zero"` with options "zero", "drift", "flow_follow". Let optimizer decide. |
| **Session-aware signal gating** | Current session filter is binary (13:00-17:00 UTC only). Gold scalps also work well during London (08:00-12:00) and Asian volatility spikes. More granular session control with per-session confidence adjustments. | LOW | None | Extend session windows config to support multiple windows with per-window confidence multipliers. Current config already has `[[session.windows]]` array but only one window defined. |
| **Trade journal with full signal context** | `TradeContextLogger` exists in learning module. Enhancing it to log full signal metadata (all chaos sub-metrics, flow components, timing OU params) per trade decision enables post-demo analysis of "why did it trade / not trade here?" | LOW | None | The logging infrastructure exists. Ensure every FusionResult that produces should_trade=False is also logged with the reason, not just successful trades. Critical for calibration debugging during demo. |
| **Graceful degradation metrics** | When DOM is unavailable (likely on RoboForex), flow module silently falls back to tick-only. Dashboard should show which data sources are active and degradation state. | LOW | None | DOMQualityChecker already tracks this. Expose `dom_checker.is_dom_enabled` in the web dashboard's status endpoint. |
| **Optimization warm-start from previous run** | Optuna supports loading a previous study via `load_study()`. After initial calibration, subsequent optimization runs should start from the best-known parameters rather than from scratch. | LOW | Optimization pipeline | Use Optuna's RDB storage (SQLite-backed) to persist study state. Add `--resume` flag to CLI optimize command. |
| **Config diff visualization** | After optimization produces `config/optimized.toml`, show a human-readable diff of changed parameters with before/after values and the impact on backtest metrics. | LOW | Optimization pipeline | Print a table: parameter name, default value, optimized value, % change. Already have the before/after BotSettings objects in the optimizer. |

### Anti-Features (Do NOT Build for v1.1)

Features that seem valuable but would delay the demo launch or introduce premature complexity.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **ZeroMQ MQL5 EA execution bridge** | Lower latency than Python MT5 package, separates execution from analysis | Massive new dependency (MQL5 EA development, ZeroMQ protocol, serialization). The Python MT5 package already handles order_send() with 1-5ms latency on localhost. ZMQ adds value only for sub-millisecond HFT, which this is not. | Use the existing MT5Bridge + OrderManager for v1.1. ZMQ bridge is a v2.0 feature if latency becomes a bottleneck. |
| **Real-money trading** | "If it works on demo, go live" | $20 real money at risk with uncalibrated signals and untested live execution is irresponsible. Demo testing must run for at least 1 week with 10-20 trades/day before considering real money. | Run demo for 1 week minimum. v1.2 milestone for real-money readiness with additional safety gates. |
| **Deep learning (LSTM/Transformer) for signal generation** | Better pattern recognition than chaos metrics | Requires GPU, massive training data, and introduces opaque black-box decisions. Current 3-module fusion is interpretable and debuggable. DL is a v2.0+ experiment. | Keep scikit-learn RandomForest for regime classification in the learning loop. |
| **Multi-timeframe signal fusion** | "M1 confirms M5 confirms H1" | Adds combinatorial complexity to signal pipeline. Each timeframe needs its own chaos/timing/flow calculation. Currently chaos uses M5 primary + H1 secondary. Adding M1 triples computation time. | Stick with M5 primary, H1 secondary for v1.1. Multi-TF fusion is a v1.3+ research topic. |
| **Custom indicator library (RSI, MACD, Bollinger)** | "Everyone uses these" | Standard TA indicators are the anti-edge. If everyone uses RSI, the signal is priced in. The chaos/flow/timing modules are the differentiating edge. Adding standard indicators dilutes the unique signal. | Keep the 3-module architecture. If standard TA is needed, use it inside existing modules (e.g., RSI as a flow confirmation) rather than as new modules. |
| **Backtesting on tick data** | "M1 bars miss intra-bar movements" | Tick-level backtesting on 10+ years of XAUUSD data (billions of ticks) would take days to run. M1 bars are sufficient for M5-timeframe scalping signals. Tick-level accuracy matters for HFT, not for 5-60 minute hold times. | Continue with M1 bar data from histdata.com. Tick backtesting is a v2.0 infrastructure investment. |
| **VPS deployment** | "24/5 uptime" | Adds DevOps complexity (Windows VPS, MT5 installation, remote monitoring). For a 1-week demo on a personal machine, local execution during market hours is sufficient. | Run locally during London-NY session (13:00-17:00 UTC). VPS deployment is a v1.3+ operational feature. |
| **Self-learning loop activation** | "Let the bot evolve" | The learning loop requires 50+ trades before evolution triggers. With current ~20 trades/3 months, this never fires. Even at 10-20/day, it takes 3-5 days to accumulate enough data. Activating learning during the 1-week demo risks destabilizing calibrated parameters. | Keep learning disabled for v1.1 demo. Collect trade data. Analyze after 1 week. Enable learning in v1.2 if demo data supports it. |
| **News calendar integration** | "Avoid NFP and FOMC" | Requires external API (Forex Factory, Investing.com), parsing, scheduling. The chaos module already detects volatility regime transitions which are the EFFECT of news events. | Rely on chaos module's HIGH_CHAOS and PRE_BIFURCATION detection for implicit news avoidance. Manual note in demo log for major news events. |

---

## Feature Dependencies

```
[Chaos Direction Fix]
    |
    +--enhances--> [Fusion Threshold Reduction]
    |                  |
    |                  +--enables--> [Automated Optimization]
    |                                    |
    +--enhances--> [Multi-Objective Optimization]
                                         |
[Timing Urgency Fix]                     |
    |                                    |
    +--enhances--> [Fusion Threshold Reduction]
                                         |
[Position Sizing Fix] <--requires-- [ATR SL Recalibration]
    |
    +--enables--> [Live MT5 Execution]
    |                 |
    |                 +--enables--> [Trailing Stop Implementation]
    |                 |
    |                 +--enables--> [Position Sync on Startup]
    |
[Circuit Breaker Recalibration]
    |
    +--enables--> [Live MT5 Execution]
    |
[Concurrent Positions] --requires--> [Aggregate Risk Check]

[Automated Optimization] --requires--> [Expanded Search Space]
    |
    +--enhances--> [Config Diff Visualization]
    |
    +--enhances--> [Optimization Warm-Start]
```

### Dependency Notes

- **Chaos direction fix enables everything downstream:** Without directional signals during 60-80% of market time, no amount of threshold tuning or optimization produces trades. This is the root cause and must be fixed first.
- **Position sizing fix requires ATR SL recalibration:** The sizing math fails because SL distance (ATR*2) is too large for $20 equity. Reducing ATR multiplier from 2.0x to 1.0-1.5x brings SL within risk budget. These must change together.
- **Live MT5 execution requires working sizing:** Sending 0-lot orders to MT5 produces errors. Sizing must work before live execution can be tested.
- **Optimization requires working signals:** Running Optuna on a pipeline that produces 0 trades per trial returns PF=0.0 for all trials. Signals must generate trades before optimization can find good parameters.
- **Multi-objective optimization enhances base optimization:** Not a hard dependency but without it, Optuna will find high-PF-low-frequency solutions. Add as Phase 2 enhancement.
- **Concurrent positions conflicts with single-position trailing stop logic:** TradeManager tracks one `_open_position_ticket`. Supporting 2-3 positions requires refactoring to a position dict. Must be done carefully.

---

## MVP Definition

### Launch With (v1.1 Core)

Minimum features to run a 1-week demo at 10-20 trades/day.

- [x] **Chaos direction for non-trending regimes** -- Without this, 60-80% of market time produces zero signal
- [x] **Timing urgency recalibration** -- Remove double-penalty on moderate urgency signals
- [x] **Fusion threshold reduction** -- Lower aggressive threshold from 0.50 to 0.25-0.35
- [x] **Position sizing for $20 equity** -- Lower ATR multiplier, increase aggressive risk_pct
- [x] **Circuit breaker recalibration** -- Phase-aware drawdown limits for micro-account
- [x] **Multiple concurrent positions (2-3)** -- Unlock trade frequency without requiring ultra-short hold times
- [x] **Live MT5 execution on demo** -- order_check + order_send + position tracking
- [x] **Trailing stop implementation** -- SL modification via TRADE_ACTION_SLTP
- [x] **Automated optimization with expanded search space** -- Single command backtest-optimize-validate-write

### Add After 1-Week Demo (v1.1.x)

Features to add once core demo is running and producing trade data.

- [ ] **Multi-objective optimization** -- Trigger: first optimization run finds high-PF but low-frequency solutions
- [ ] **Position sync on startup** -- Trigger: first crash during active position
- [ ] **Optimization warm-start** -- Trigger: second optimization run needed
- [ ] **Trade journal analysis tooling** -- Trigger: 100+ trades accumulated
- [ ] **Session-aware signal gating** -- Trigger: analysis shows trades outside London-NY are net negative

### Future Consideration (v1.2+)

Features to defer until demo validates the approach.

- [ ] **Self-learning loop activation** -- Need 1000+ trade history for reliable evolution
- [ ] **ZeroMQ MQL5 bridge** -- Only if Python MT5 latency proven insufficient
- [ ] **VPS deployment** -- After strategy is stable enough for 24/5 operation
- [ ] **Real-money transition** -- After 2+ weeks profitable demo with 500+ trades

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Risk if Skipped | Priority |
|---------|------------|---------------------|-----------------|----------|
| Chaos direction fix | HIGH | MEDIUM | CRITICAL -- no trades without it | P0 |
| Timing urgency fix | HIGH | LOW | HIGH -- halves timing contribution | P0 |
| Fusion threshold reduction | HIGH | LOW | CRITICAL -- threshold gates all trades | P0 |
| Position sizing fix | HIGH | MEDIUM | CRITICAL -- all trades rejected at $20 | P0 |
| Circuit breaker recalibration | HIGH | LOW | HIGH -- breakers trip after 1 loss | P0 |
| Concurrent positions (2-3) | MEDIUM | MEDIUM | MEDIUM -- limits frequency to 1-at-a-time | P1 |
| Live MT5 execution | HIGH | MEDIUM | CRITICAL -- cannot demo without it | P1 |
| Trailing stop implementation | MEDIUM | MEDIUM | MEDIUM -- fixed SL/TP still works | P1 |
| Automated optimization (expanded) | HIGH | HIGH | HIGH -- manual calibration is guesswork | P1 |
| Multi-objective optimization | MEDIUM | MEDIUM | LOW -- PF-only works for first pass | P2 |
| Position sync on startup | MEDIUM | MEDIUM | LOW -- manual restart during demo week | P2 |
| Trade journal enhancements | MEDIUM | LOW | LOW -- basic logging exists | P2 |
| Config diff visualization | LOW | LOW | NONE -- nice to have | P3 |
| Session-aware gating | LOW | LOW | NONE -- current window is adequate | P3 |

**Priority key:**
- P0: Prerequisite -- bot literally cannot trade without these
- P1: Must have for demo launch
- P2: Should have, add during demo week
- P3: Nice to have, post-demo

---

## Competitor / Reference Analysis

| Feature | XauBot / SmartT (Commercial) | Open-source MT5 bots (GitHub) | Our Approach |
|---------|------------------------------|-------------------------------|--------------|
| Signal generation | Proprietary AI/ML, black-box | Standard TA (RSI, MACD, MAs) | Chaos regime + order flow + quantum timing fusion. Unique but needs calibration. |
| Trade frequency | 5-15 trades/day typical | Varies wildly (1-100/day) | Target 10-20/day via signal recalibration |
| Stop loss sizing | Adaptive ATR or fixed pips (10-30 pip range for scalps) | Usually fixed pips | ATR-based with regime adjustment. Need to reduce from 2x to 1-1.5x for scalping. |
| Position sizing | Fixed lot or % risk (typically 0.5-2% per trade) | Usually fixed lot (0.01) | Dynamic per-phase % risk. Need to increase aggressive phase risk for $20 viability. |
| Trailing stops | Built into EA (MQL5-native) | MQL5-native or Python polling | Python polling via TRADE_ACTION_SLTP. Adequate for M5 scalping (not HFT). |
| Optimization | Manual parameter sweep or proprietary | Rarely automated | Optuna TPE + DEAP GA with walk-forward validation. Strongest approach among non-commercial bots. |
| Crash recovery | State persistence + auto-reconnect (VPS) | Varies (many have none) | State persistence exists (SQLite). Need position sync on startup. |
| Risk management | Basic (daily loss limit, lot limit) | Minimal (fixed lot) | 5 circuit breakers + kill switch + session filter. Most comprehensive in class, but needs micro-account tuning. |

---

## Detailed Feature Specifications

### Chaos Direction Fix

**Problem:** `direction_map` in `chaos/module.py` returns 0.0 for RANGING, HIGH_CHAOS, PRE_BIFURCATION.

**Solution options (pick one):**

1. **Drift-based direction (recommended):** For RANGING, compute short-term price drift from the last 5-10 bars and use sign as weak direction (+/- 0.3). Confidence scaled by Hurst distance from 0.5 (more mean-reverting = stronger contrarian signal).

2. **Flow-following direction:** During RANGING, chaos module outputs direction=0.0 but fusion should still produce trades from flow+timing alone. This requires reducing chaos weight or making fusion work with 2-of-3 modules.

3. **Chaos as regime-only module:** Chaos contributes regime classification (confidence, metadata) but direction is always derived from flow+timing. Simplest change but reduces chaos module's contribution.

**Recommendation:** Option 2 is the safest -- it does not change the chaos module's behavior but makes fusion resilient to one module contributing zero direction. The fusion formula already handles this correctly (normalized by total_confidence_weight), but the threshold is the bottleneck. Lowering the threshold to 0.25-0.35 combined with the timing urgency fix may be sufficient. If not, fall back to Option 1.

### Position Sizing Math for $20

Current settings and the math:
- Equity: $20, aggressive phase
- Risk: 10% = $2.00
- Gold M5 ATR during London: ~$1.50-$3.00 (150-300 pips)
- SL = ATR * 2.0 = $3.00-$6.00
- Lot = $2.00 / ($3.00 * 100) = 0.0067, rounds to min 0.01
- Actual risk at 0.01: $3.00 * 100 * 0.01 = $3.00 = 15% -- REJECTED

**Fix:**
- SL ATR multiplier: 1.0x (not 2.0x) for aggressive phase
- SL = $1.50, lot = $2.00 / ($1.50 * 100) = 0.013, rounds to 0.01
- Actual risk: $1.50 * 100 * 0.01 = $1.50 = 7.5% -- PASSES at 10%
- OR increase aggressive_risk_pct to 15% and keep ATR*1.5
- SL = $2.25, lot = $3.00 / ($2.25 * 100) = 0.013, rounds to 0.01
- Actual risk: $2.25 * 100 * 0.01 = $2.25 = 11.25% -- PASSES at 15%

**Recommendation:** ATR * 1.0x for scalping + 15% risk per trade for aggressive phase. This is standard for micro-account forex scalping. The tight SL is compensated by 1:500 leverage and small lot sizes.

### Optimization Search Space Expansion

Current search space: 11 FusionConfig parameters.

**Add to search space:**
- `chaos.hurst_trending_threshold`: [0.50, 0.75] (currently hardcoded 0.6)
- `chaos.hurst_ranging_threshold`: [0.35, 0.55] (currently hardcoded 0.45)
- `chaos.bifurcation_threshold`: [0.5, 0.9] (currently hardcoded 0.7)
- `chaos.lyapunov_chaos_threshold`: [0.3, 0.8] (currently hardcoded 0.5)
- `chaos.entropy_chaos_threshold`: [0.5, 0.9] (currently hardcoded 0.7)
- `timing.urgency_exponent`: [0.3, 1.0] (new -- applies pow(urgency, exponent) to soften)
- `risk.aggressive_risk_pct`: [0.10, 0.25]
- `execution.sl_atr_multiplier`: [0.5, 2.5] (currently fixed 2.0)
- `fusion.max_concurrent_positions`: {1, 2, 3} (categorical)

This expands from 11 to ~20 parameters. Optuna TPE handles 20 dimensions well within 100-200 trials.

**Objective function:**
```python
# Multi-objective: maximize both
# 1. Profit factor (capped at 5.0)
# 2. Normalized trade count: min(daily_trades / target, 1.0)
# Pareto-optimal solutions balance both
```

### Live Execution Checklist

The code path exists but needs these additions:
1. `live.toml` must include MT5 credentials (currently has only `mode = "live"`)
2. Add `order_check` retcode-to-message mapping for common errors (10006=requote, 10013=invalid request, 10014=invalid volume, 10015=invalid stops, 10016=trade disabled)
3. Implement `modify_sl_tp()` method in OrderManager for trailing stops
4. Add heartbeat monitoring: if no tick received for 30s, trigger reconnection
5. Position reconciliation on startup: query MT5 positions, populate TradeManager state
6. Spread check before order: if current spread > 2x average, delay entry (already in circuit breakers but needs integration with order flow)

---

## Sources

- [Best Timeframes for Scalping Gold -- M5 vs M15](https://xaubot.com/best-timeframes-for-scalping-gold-with-xaubot/) -- M5 sweet spot for gold scalping
- [Gold Scalping Strategy on MT5](https://xmsignal.com/en/blog/gold-scalping-strategy-mt5/) -- 10-20 pip targets, 15-30 pip SL
- [XAUUSD Lot Size and Risk Management](https://www.defcofx.com/xauusd-pips-and-lot-size/) -- pip value $0.01 per 0.01 lot
- [XAUUSD Scalping Strategies](https://www.forexgdp.com/analysis/xauusd/scalping-gold-strategies/) -- multi-indicator fusion reduces false signals
- [MT5 Python Trailing Stop Implementation](https://appnologyjames.medium.com/metatrader-5-python-trailing-stop-2c562a541b48) -- TRADE_ACTION_SLTP pattern
- [Modifying Open Trades in MT5 with Python](https://medium.com/@elospieconomics/algorithmic-trading-with-python-and-mt5-modifying-open-trades-8622d31632f3) -- SL/TP modification best practices
- [Walk-Forward Optimization with Bayesian Optimization](https://github.com/TonyMa1/walk-forward-backtester) -- Optuna + walk-forward pattern
- [Optuna Multi-Objective Optimization](https://optuna.org/) -- NSGAIISampler for Pareto front
- [Gold Trading Strategy 2026](https://www.thinkmarkets.com/en/trading-academy/commodities/gold-trading-strategy-2026/) -- ATR-based SL sizing for gold
- [Hyperparameter Optimization with Strategy Backtesting](https://piotrpomorski.substack.com/p/hyperparameter-optimisation-with) -- Optuna + Sharpe ratio objective
- [Python MT5 Integration Guide 2025](https://metatraderapi.cloud/guides/python-mt5-integration/) -- order_send, positions_get, error handling
- [MQL5 Forum: Trailing Stop in Python](https://www.mql5.com/en/forum/427801) -- No built-in Python trailing stop, must implement via order_send

---
*Feature research for: FXSoqqaBot v1.1 Live Demo Launch*
*Researched: 2026-03-28*
