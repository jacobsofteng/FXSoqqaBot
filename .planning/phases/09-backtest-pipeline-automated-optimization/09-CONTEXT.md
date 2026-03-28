# Phase 9: Backtest Pipeline & Automated Optimization - Context

**Gathered:** 2026-03-28
**Status:** Ready for planning

<domain>
## Phase Boundary

A single command runs the full backtest-optimize-validate pipeline on 3.8M bars of historical data and writes an `optimized.toml` with data-driven parameters. The pipeline must complete without hanging, log flooding, or manual intervention. The optimizer uses multi-objective Pareto optimization (profit factor + trade count), supports warm-start from previous studies, and displays a config diff after completion.

</domain>

<decisions>
## Implementation Decisions

### Multi-Objective Optimization Strategy (OPT-03)
- **D-01:** Use Optuna's built-in **NSGA-II** (`NSGAIISampler`) for true multi-objective Pareto front optimization with two objectives: profit factor and normalized trade count
- **D-02:** Trade count normalized as **trades per day** based on backtest window calendar days — directly comparable to the 10-20/day target
- **D-03:** Pareto front selection strategy: **trade count priority** — select the Pareto-optimal config closest to 10-20 trades/day, then maximize profit factor within that band
- **D-04:** Minimum profit factor floor: **PF >= 1.0** — any profitable strategy qualifies at the demo stage. PF refinement comes from later optimization cycles

### Search Space Expansion (OPT-02)
- **D-05:** Expand search space from 11 to ~20 parameters by adding three new categories:
  - **Risk params:** risk_pct, SL ATR multiplier, daily drawdown limit
  - **Chaos thresholds:** Hurst threshold, Lyapunov threshold, entropy window, bifurcation sensitivity
  - **Timing urgency:** OU mean_reversion_strength, urgency_floor, phase_transition_threshold
- **D-06:** Chaos `direction_mode` included as a **categorical parameter** (zero/drift/flow_follow) — Optuna NSGA-II handles mixed continuous+categorical spaces
- **D-07:** Session windows stay **fixed** per Phase 8 decisions (D-14, D-15) — not included in search space
- **D-08:** **Fold DEAP GA weight evolution into Optuna NSGA-II** — signal weights (chaos/flow/timing) become 3 additional continuous parameters in the unified search. Eliminates the two-phase optimization design. Weights co-optimize with all other params instead of being optimized in isolation

### Pipeline Reliability (OPT-01)
- **D-09:** Progress reporting: **Rich progress bar** during processing + compact summary table at end. Per-window/per-trial detail suppressed to a log file. Terminal stays clean
- **D-10:** Hang guard: **per-step timeout** (e.g., 10 min per walk-forward window). If exceeded, log warning and skip to next window/step. Pipeline completes with partial results rather than hanging forever
- **D-11:** Log flooding control: **suppress structlog to WARNING level** during optimization trials. Each BacktestEngine run generates hundreds of log entries — at 50+ trials that's thousands of lines. Only surface errors. Restore normal logging for final validation

### Warm-Start & Config Diff (OPT-04)
- **D-12:** Study persistence via **Optuna SQLite backend** (`RDBStorage`) at `data/optuna_study.db`. Re-running loads previous trials automatically
- **D-13:** Search space changes between runs: **continue with new space** — Optuna handles natively. Old trials inform existing params, new params explored from scratch. Log a warning showing which params were added/removed
- **D-14:** Config diff output: **side-by-side table** after optimization — Parameter | Default | Optimized | Change%. Sorted by magnitude of change

### Data Cleanup
- **D-15:** Clean up stale artifacts from previous incomplete runs before pipeline execution: remove `data/backtest_results.log` (35 MB), `data/optimizer_results.log` (811 MB), `data/optimizer_scalping_results.log` (6.7 MB), `data/analytics.duckdb` (3.4 MB). Keep `histdata/` (raw CSVs), `historical/` (ingested Parquet), `state.db` (operational state)

### Claude's Discretion
- Exact per-step timeout duration (10 min suggested, but Claude can adjust based on profiling)
- Specific bounds for new search space parameters (chaos thresholds, timing urgency ranges)
- Whether to use Rich or tqdm for progress bars (Rich already a dependency)
- Implementation of the Pareto front selection algorithm (knee point vs target proximity)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — OPT-01 through OPT-04 (backtesting & optimization requirements)

### Prior Phase Context
- `.planning/phases/08-signal-risk-calibration/08-CONTEXT.md` — Phase 8 decisions on chaos direction modes (D-01 through D-03), signal thresholds (D-04 through D-08), risk params (D-05, D-06), session windows (D-14, D-15)

### Backtest Pipeline
- `src/fxsoqqabot/backtest/runner.py` — Full 6-step pipeline orchestrator (ingestion, walk-forward, OOS, Monte Carlo, regime eval, Feigenbaum stress)
- `src/fxsoqqabot/backtest/engine.py` — BacktestEngine: synchronous bar-by-bar replay using exact same signal pipeline as live trading
- `src/fxsoqqabot/backtest/validation.py` — WalkForwardValidator with rolling windows
- `src/fxsoqqabot/backtest/monte_carlo.py` — Monte Carlo trade sequence shuffling
- `src/fxsoqqabot/backtest/historical.py` — HistoricalDataLoader (CSV ingestion, Parquet, DuckDB)
- `src/fxsoqqabot/backtest/config.py` — BacktestConfig with OOS ratios, MC params
- `src/fxsoqqabot/backtest/regime_tagger.py` — RegimeTagger for per-regime performance
- `src/fxsoqqabot/backtest/stress_test.py` — FeigenbaumStressTest for chaos transitions

### Optimization
- `src/fxsoqqabot/optimization/optimizer.py` — Two-phase optimizer (Optuna TPE + DEAP GA) — needs refactor to unified NSGA-II
- `src/fxsoqqabot/optimization/search_space.py` — Current 11-param search space (OPTUNA_SEARCH_SPACE dict) — needs expansion to ~20
- `src/fxsoqqabot/optimization/deap_weights.py` — DEAP weight evolution — to be folded into Optuna

### Configuration
- `src/fxsoqqabot/config/models.py` — BotSettings, FusionConfig, ChaosConfig, RiskConfig, SessionConfig

### Signal Modules (search space targets)
- `src/fxsoqqabot/signals/chaos/module.py` — ChaosRegimeModule with direction_mode, Hurst/Lyapunov thresholds
- `src/fxsoqqabot/signals/timing/module.py` — QuantumTimingModule with urgency computation
- `src/fxsoqqabot/signals/timing/phase_transition.py` — Phase transition detection, ATR computation

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BacktestEngine` — 100% shared signal pipeline code between live and backtest (no separate backtest paths)
- `HistoricalDataLoader` — CSV-to-Parquet ingestion with DuckDB, handles 2015-2026 data
- `WalkForwardValidator` — Rolling window walk-forward with OOS evaluation
- `run_monte_carlo()` — Trade sequence Monte Carlo simulation
- `RegimeTagger` — Per-regime performance breakdown
- `FeigenbaumStressTest` — Chaos transition stress testing
- `apply_params_to_settings()` — Maps flat param dict to nested BotSettings
- `sample_trial()` — Optuna trial sampling with threshold ordering constraints
- `evolve_weights()` — DEAP GA weight evolution (to be folded into Optuna)

### Established Patterns
- Config-driven: all params flow through Pydantic models in `config/models.py`
- Optimizer is SYNCHRONOUS — each objective call uses `asyncio.run()` to bridge to async BacktestEngine
- Fast proxy: 3-month window backtest for optimization, full walk-forward for validation only
- Threshold ordering enforced: aggressive < selective < conservative

### Integration Points
- `OPTUNA_SEARCH_SPACE` dict in `search_space.py` — primary expansion point for new params
- `apply_params_to_settings()` — must be extended to map new params (risk, chaos, timing) to BotSettings
- `optimizer.py` `run_optimization()` — main refactor target: TPESampler → NSGAIISampler, two-phase → unified
- `runner.py` `run_full_backtest()` — needs progress bar wrapper and log suppression
- CLI `backtest` and `optimize` subcommands — entry points for the pipeline

</code_context>

<specifics>
## Specific Ideas

- The 811 MB `optimizer_results.log` from the previous incomplete run demonstrates exactly why D-11 (log suppression during trials) is critical
- Data cleanup (D-15) should happen as step 0 of the pipeline, not as a separate manual step

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 09-backtest-pipeline-automated-optimization*
*Context gathered: 2026-03-28*
