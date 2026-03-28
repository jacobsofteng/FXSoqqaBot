# Requirements: FXSoqqaBot

**Defined:** 2026-03-28
**Core Value:** The bot reads the market's true state through the fusion of all analysis modules and trades with the dominant forces. The edge is the fusion.

## v1.1 Requirements

Requirements for Live Demo Launch milestone. Each maps to roadmap phases.

### Signal Calibration

- [x] **SIG-01**: Chaos module produces nonzero directional signal during RANGING, HIGH_CHAOS, and PRE_BIFURCATION regimes using drift-based or flow-following direction
- [x] **SIG-02**: Timing module urgency applied once (not double-squared), preserving moderate urgency signals above 0.25 confidence
- [x] **SIG-03**: Fusion confidence threshold for aggressive phase reduced to 0.25-0.35 range (configurable, Optuna-searchable)
- [x] **SIG-04**: Chaos regime-to-direction mapping is configurable (zero/drift/flow_follow modes) and included in optimization search space

### Risk Management

- [x] **RISK-01**: Position sizer accepts trades at $20 equity with ATR x1.0 SL multiplier and 15% aggressive risk_pct
- [x] **RISK-02**: Circuit breaker daily drawdown limit is phase-aware (15-20% for aggressive, 10% for selective, 5% for conservative)
- [x] **RISK-03**: Bot supports 2-3 concurrent positions with aggregate exposure across all open positions capped at the single-position risk budget (e.g., 15% total, not 15% per position)
- [x] **RISK-04**: Trading session windows include London (08:00-12:00 UTC) and London-NY overlap (13:00-17:00 UTC)

### Backtesting & Optimization

- [ ] **OPT-01**: Backtest pipeline completes full 6-step run on 3.8M bars of historical data without hanging or log flooding
- [x] **OPT-02**: Optimization search space expanded from 11 to ~20 parameters including chaos thresholds, timing urgency, risk/SL config
- [ ] **OPT-03**: Multi-objective optimization maximizes profit factor AND normalized trade count via Pareto front
- [ ] **OPT-04**: Optimization supports warm-start from previous study and displays config diff after completion

### Live Execution

- [ ] **EXEC-01**: Bot executes real orders on MT5 demo account via order_check + order_send with retcode error handling
- [ ] **EXEC-02**: Trailing stops modify SL on active positions via TRADE_ACTION_SLTP polling
- [ ] **EXEC-03**: Bot reconciles MT5 positions with internal state on startup (crash recovery)
- [ ] **EXEC-04**: Bot runs unattended with auto-reconnection, heartbeat monitoring, log rotation, and desktop alerts

## Future Requirements

Deferred to post-demo milestone. Tracked but not in current roadmap.

### Post-Demo Enhancements

- **LEARN-01**: Self-learning loop activation after 1000+ trade history accumulated
- **INFRA-01**: ZeroMQ MQL5 EA bridge for sub-millisecond execution latency
- **INFRA-02**: VPS deployment for 24/5 unattended operation
- **LIVE-01**: Real-money trading transition with additional safety gates after 2+ weeks profitable demo

## Out of Scope

| Feature | Reason |
|---------|--------|
| Deep learning / neural networks (LSTM, Transformer) | Overfits on small datasets, opaque decisions, requires GPU — keep interpretable hybrid approach |
| Multi-timeframe signal fusion (M1+M5+H1) | Triples computation time, combinatorial complexity — stick with M5 primary, H1 secondary |
| Custom indicator library (RSI, MACD, Bollinger) | Standard TA is priced-in anti-edge — chaos/flow/timing fusion IS the differentiator |
| Tick-level backtesting | Billions of ticks = days to run — M1 bars sufficient for M5 scalping signals |
| News calendar integration | Chaos module detects volatility regime transitions (the effect of news) — redundant |
| Real-money trading in v1.1 | Irresponsible without 1+ week profitable demo data — defer to v1.2 |
| MQL5 Expert Advisor | MT5 Python bridge order_send() is sufficient for same-machine demo — ZMQ bridge is v2.0 |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SIG-01 | Phase 8 | Complete |
| SIG-02 | Phase 8 | Complete |
| SIG-03 | Phase 8 | Complete |
| SIG-04 | Phase 8 | Complete |
| RISK-01 | Phase 8 | Complete |
| RISK-02 | Phase 8 | Complete |
| RISK-03 | Phase 8 | Complete |
| RISK-04 | Phase 8 | Complete |
| OPT-01 | Phase 9 | Pending |
| OPT-02 | Phase 9 | Complete |
| OPT-03 | Phase 9 | Pending |
| OPT-04 | Phase 9 | Pending |
| EXEC-01 | Phase 10 | Pending |
| EXEC-02 | Phase 10 | Pending |
| EXEC-03 | Phase 10 | Pending |
| EXEC-04 | Phase 10 | Pending |

**Coverage:**
- v1.1 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0

---
*Requirements defined: 2026-03-28*
*Last updated: 2026-03-28 after roadmap creation*
