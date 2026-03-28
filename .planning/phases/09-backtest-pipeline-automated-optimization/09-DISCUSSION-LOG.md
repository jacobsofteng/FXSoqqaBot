# Phase 9: Backtest Pipeline & Automated Optimization - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-28
**Phase:** 09-backtest-pipeline-automated-optimization
**Areas discussed:** Pareto front strategy, Search space expansion, Pipeline reliability, Warm-start & config diff

---

## Pareto Front Strategy

### Q1: How should the optimizer select from the Pareto front?

| Option | Description | Selected |
|--------|-------------|----------|
| Trade count priority | Select config closest to 10-20 trades/day target, maximize PF within that band | ✓ |
| Profit factor priority | Highest PF with minimum trade count floor (>=5/day) | |
| Balanced scalarization | Weighted score combining both objectives | |

**User's choice:** Trade count priority
**Notes:** The v1.1 goal is hitting trade frequency — PF above 1.0 is sufficient at demo stage.

### Q2: NSGA-II or scalarization?

| Option | Description | Selected |
|--------|-------------|----------|
| NSGA-II multi-objective | Optuna built-in NSGAIISampler, true Pareto front | ✓ |
| Weighted scalarization | Single score, stays with TPESampler | |

**User's choice:** NSGA-II multi-objective

### Q3: Trade count normalization?

| Option | Description | Selected |
|--------|-------------|----------|
| Trades per day | Normalize to trades/day based on calendar days | ✓ |
| Raw trade count | Absolute count, depends on window size | |

**User's choice:** Trades per day

### Q4: Minimum profit factor floor?

| Option | Description | Selected |
|--------|-------------|----------|
| PF >= 1.0 | Any profitable strategy qualifies | ✓ |
| PF >= 1.2 | 20% edge required | |
| PF >= 1.5 | 50% edge required | |

**User's choice:** PF >= 1.0

---

## Search Space Expansion

### Q1: Include chaos direction_mode as categorical?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, categorical | Let optimizer try zero/drift/flow_follow | ✓ |
| Fix to drift | Lock Phase 8 default, don't search | |
| You decide | Claude picks | |

**User's choice:** Yes, categorical

### Q2: Which new parameter categories? (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| Risk params | risk_pct, SL ATR multiplier, daily drawdown limit | ✓ |
| Chaos thresholds | Hurst threshold, Lyapunov threshold, entropy window, bifurcation sensitivity | ✓ |
| Timing urgency | OU mean_reversion_strength, urgency_floor, phase_transition_threshold | ✓ |
| Session windows | Session start/end hours | |

**User's choice:** Risk params, Chaos thresholds, Timing urgency (session windows excluded — stay fixed per Phase 8)

### Q3: DEAP GA separate or fold into Optuna?

| Option | Description | Selected |
|--------|-------------|----------|
| Fold into Optuna | Signal weights become 3 more Optuna params, unified search | ✓ |
| Keep DEAP separate | Preserve current two-phase design | |
| You decide | Claude picks | |

**User's choice:** Fold into Optuna

---

## Pipeline Reliability

### Q1: Progress reporting style?

| Option | Description | Selected |
|--------|-------------|----------|
| Progress bar + summary | Rich progress bar, detail to log file | ✓ |
| Verbose console output | Print everything to console | |
| Quiet + log file | Console shows only stage transitions | |

**User's choice:** Progress bar + summary

### Q2: Hang guard behavior?

| Option | Description | Selected |
|--------|-------------|----------|
| Timeout + skip | Per-step timeout, skip on exceed, partial results | ✓ |
| Timeout + abort | Abort entire pipeline on timeout | |
| No timeout | Trust the engine | |

**User's choice:** Timeout + skip

### Q3: Log flooding control?

| Option | Description | Selected |
|--------|-------------|----------|
| Suppress structlog in trials | Set to WARNING during optimization, restore for validation | ✓ |
| Log to file only | Redirect all output to file | |
| You decide | Claude picks | |

**User's choice:** Suppress structlog in trials

---

## Warm-Start & Config Diff

### Q1: Study persistence method?

| Option | Description | Selected |
|--------|-------------|----------|
| SQLite storage | Optuna RDBStorage at data/optuna_study.db | ✓ |
| Journal file | Flat file storage | |
| No persistence | Always start fresh | |

**User's choice:** SQLite storage

### Q2: Config diff display format?

| Option | Description | Selected |
|--------|-------------|----------|
| Side-by-side table | Parameter/Default/Optimized/Change% table | ✓ |
| TOML diff | Unified diff of TOML files | |
| You decide | Claude picks | |

**User's choice:** Side-by-side table

### Q3: Search space change handling?

| Option | Description | Selected |
|--------|-------------|----------|
| Continue with new space | Optuna handles natively, log warning for changes | ✓ |
| Prompt user to confirm | Ask before continuing with changed space | |
| Always start fresh on change | Discard old study | |

**User's choice:** Continue with new space

---

## Additional User Input

User noted stale data files from previous incomplete backtest run in `data/` folder:
- `backtest_results.log` (35 MB), `optimizer_results.log` (811 MB), `optimizer_scalping_results.log` (6.7 MB), `analytics.duckdb` (3.4 MB)
- User authorized cleanup of these files as part of Phase 9 pipeline

## Claude's Discretion

- Exact per-step timeout duration
- Specific bounds for new search space parameters
- Rich vs tqdm for progress bars
- Pareto front selection algorithm implementation

## Deferred Ideas

None — discussion stayed within phase scope.
