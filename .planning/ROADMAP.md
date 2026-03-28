# Roadmap: FXSoqqaBot

## Milestones

- [x] **v1.0 MVP** - Phases 1-7 (shipped 2026-03-28)
- [ ] **v1.1 Live Demo Launch** - Phases 8-10 (in progress)

## Phases

<details>
<summary>v1.0 MVP (Phases 1-7) - SHIPPED 2026-03-28</summary>

7 phases, 32 plans, 59 tasks completed. 47/47 v1 requirements satisfied.
See [v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md) for full archive.

</details>

### v1.1 Live Demo Launch

**Milestone Goal:** Make the bot trade 10-20 times/day with optimized signals and run unattended on the RoboForex demo account for a 1-week observation period.

**Phase Numbering:**
- Integer phases (8, 9, 10): Planned milestone work
- Decimal phases (8.1, 9.1): Urgent insertions (marked with INSERTED)

- [ ] **Phase 8: Signal & Risk Calibration** - Fix signal pipeline bugs and risk parameters so the bot generates 10-20 trades/day on backtested data
- [ ] **Phase 9: Backtest Pipeline & Automated Optimization** - Fix backtest performance, run Optuna optimization, produce validated optimized.toml
- [ ] **Phase 10: Live Execution & Demo Launch** - Wire live MT5 execution, harden for unattended operation, start 1-week demo

## Phase Details

### Phase 8: Signal & Risk Calibration
**Goal**: The signal-to-trade pipeline produces meaningful, frequent trade signals from the multi-module fusion at $20 micro-account constraints
**Depends on**: v1.0 (complete)
**Requirements**: SIG-01, SIG-02, SIG-03, SIG-04, RISK-01, RISK-02, RISK-03, RISK-04
**Success Criteria** (what must be TRUE):
  1. Running 1000+ bars of historical data produces chaos direction != 0 on more than 30% of bars across all regime types
  2. Timing module confidence spans the 0.1-0.8 range across representative data (no double-compression)
  3. Fusion pipeline generates 10-20 trade signals per day on backtested London+NY sessions with the calibrated threshold
  4. Position sizer accepts trades at $20 equity without rejecting every signal, and aggregate exposure across concurrent positions stays within the single-position risk budget
  5. Circuit breaker daily drawdown limits are phase-aware (15-20% aggressive, 10% selective, 5% conservative) and do not trip on a single losing trade at $20
**Plans:** 2 plans
Plans:
- [x] 08-01-PLAN.md -- Signal pipeline fixes: config defaults, chaos direction modes, timing double-compression fix
- [x] 08-02-PLAN.md -- Risk management upgrades: phase-aware drawdown, concurrent positions, backtest sync

### Phase 9: Backtest Pipeline & Automated Optimization
**Goal**: A single command runs the full backtest-optimize-validate pipeline and writes an optimized.toml with data-driven parameters
**Depends on**: Phase 8
**Requirements**: OPT-01, OPT-02, OPT-03, OPT-04
**Success Criteria** (what must be TRUE):
  1. Full 6-step backtest pipeline completes on 3.8M bars of historical data without hanging, log flooding, or manual intervention
  2. Optimization search space covers ~20 parameters including chaos thresholds, timing urgency, SL/ATR config, and fusion thresholds
  3. Running the optimizer produces a Pareto front balancing profit factor against normalized trade count, and the selected config achieves target trade frequency
  4. An optimized.toml file exists on disk with all tuned parameters, and the user can see what changed from defaults via config diff output
**Plans:** 2 plans
Plans:
- [x] 09-01-PLAN.md -- Search space expansion: ~20 params across fusion/weights/risk/chaos/timing, configurable regime thresholds
- [ ] 09-02-PLAN.md -- Unified NSGA-II optimizer: Pareto front, Rich progress, hang guard, warm-start, config diff, CLI update

### Phase 10: Live Execution & Demo Launch
**Goal**: The bot executes real trades on the MT5 demo account and runs unattended for a 1-week observation period
**Depends on**: Phase 9
**Requirements**: EXEC-01, EXEC-02, EXEC-03, EXEC-04
**Success Criteria** (what must be TRUE):
  1. Bot places and closes real orders on the RoboForex demo account with proper error handling for requotes, invalid stops, and volume errors
  2. Active positions have trailing stops that modify SL as price moves favorably
  3. After a simulated crash and restart, the bot detects and adopts orphaned MT5 positions instead of opening duplicates
  4. Bot runs for 24+ hours unattended with auto-reconnection, heartbeat monitoring, log rotation, and desktop alerts on critical events (kill switch, circuit breaker, MT5 disconnect)
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 8 -> 9 -> 10

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 8. Signal & Risk Calibration | v1.1 | 2/2 | Complete | 2026-03-28 |
| 9. Backtest Pipeline & Automated Optimization | v1.1 | 0/2 | Planned | - |
| 10. Live Execution & Demo Launch | v1.1 | 0/0 | Not started | - |
