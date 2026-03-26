# Phase 1: Trading Infrastructure - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the data pipeline, MT5 bridge, risk management, and configuration foundation that keeps a $20 XAUUSD scalping account alive. This phase delivers: live tick/DOM/bar data ingestion, order execution through MT5, position sizing across three capital phases, multi-layered safety systems, crash recovery, and configurable parameters -- all without any analysis modules, dashboards, or learning.

Requirements covered: DATA-01, DATA-02, DATA-03, DATA-05, DATA-06, EXEC-01, EXEC-02, EXEC-03, EXEC-04, RISK-01 through RISK-07, CONF-01, CONF-02.

</domain>

<decisions>
## Implementation Decisions

### Safe Start Strategy
- **D-01:** Bot ships with a paper trading mode that runs the full pipeline (data ingestion, signal processing, order generation) but simulates fills instead of executing on MT5. Paper mode uses full virtual fill simulation -- models spread, slippage, and produces realistic P&L tracking against live tick data.
- **D-02:** Switching from paper to live mode is a manual config change only. No automatic promotion. Human always in the loop for the paper-to-live transition.

### Micro-Account Risk Math
- **D-03:** Position sizing accepts higher risk per trade in the aggressive capital phase because $20 is treated as pure seed money. The three-phase risk model:
  - Aggressive ($20-$100): up to **10% risk per trade**
  - Selective ($100-$300): up to **5% risk per trade**
  - Conservative ($300+): up to **2% risk per trade**
- **D-04:** At 0.01 minimum lot size, if the calculated risk still exceeds the phase limit, the trade is skipped. But with 10% risk at $20 ($2.00 risk budget), most gold scalping setups with 0.01 lots should fit.

### Recovery Behavior
- **D-05:** After a Python crash or machine reboot with open positions: bot closes ALL positions immediately, cancels all pending orders, then auto-resumes trading. No manual intervention required to restart, but open positions are always flattened for safety.
- **D-06:** After an MT5 connection drop: bot retries reconnection indefinitely. Server-side stop-losses protect open positions while Python is disconnected. On reconnection, bot reconciles state and resumes management.
- **D-07:** Full state persisted to SQLite for recovery: every open position, pending order, daily P&L, circuit breaker states, session counters, and last known account snapshot. Positions are also read fresh from MT5 on restart for reconciliation.

### Kill Switch & Safety Triggers
- **D-08:** Four automatic circuit breakers beyond daily drawdown (RISK-04):
  1. **Consecutive loss streak** -- halt after N consecutive losing trades (configurable, e.g., 5)
  2. **Spread spike detection** -- halt when spread exceeds threshold for sustained period (e.g., 5x average for 30+ seconds)
  3. **Rapid equity drop** -- halt if equity drops X% within a short window (e.g., 5% in 15 minutes), even if daily limit not hit
  4. **Max daily trade count** -- halt after N trades per day regardless of P&L, prevents runaway overtrading
- **D-09:** Kill switch invocable via CLI command (`python -m fxsoqqabot kill`) AND a TUI dashboard button. CLI works independently of TUI.
- **D-10:** Safety trigger reset policy: daily drawdown, loss streak, rapid equity drop, and max trade counters auto-reset at the configured session boundary. Kill switch requires explicit manual reset via CLI command.

### Claude's Discretion
- Project structure and Python package layout
- Async architecture design (event loop structure, threading model)
- DuckDB/Parquet schema design and partitioning strategy
- SQLite state schema design
- MT5-Python communication architecture details (MetaTrader5 package vs ZeroMQ bridge specifics)
- Configuration file format (YAML vs TOML) and structure
- Logging and error reporting patterns
- Test structure and coverage approach

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Architecture
- `CLAUDE.md` -- Full technology stack decisions, version pinning, inter-module communication patterns, and "what NOT to use" guidance
- `.planning/PROJECT.md` -- Core value statement, eight-module architecture, constraints, build approach
- `.planning/REQUIREMENTS.md` -- All 18 requirements for this phase (DATA-01/02/03/05/06, EXEC-01/02/03/04, RISK-01-07, CONF-01/02) with acceptance criteria

### Technology Decisions
- `CLAUDE.md` §Recommended Stack -- Pinned versions for MetaTrader5, pyzmq, NumPy, DuckDB, Parquet, SQLite, Pydantic, structlog
- `CLAUDE.md` §What NOT to Use -- Explicit exclusion list (no Redis, no Celery, no MongoDB, etc.)
- `CLAUDE.md` §Alternatives Considered -- When to deviate from primary choices

### Broker & Platform
- `CLAUDE.md` §Constraints -- RoboForex ECN specifics, DOM uncertainty, localhost deployment
- `.planning/STATE.md` §Blockers/Concerns -- DOM data quality unknown, $20 lot minimum challenge

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None -- greenfield project, no existing code

### Established Patterns
- None yet -- Phase 1 establishes all patterns for subsequent phases

### Integration Points
- MetaTrader 5 terminal must be running on the same Windows machine
- Python 3.12.x virtual environment managed by uv
- All configuration via YAML/TOML files (CONF-01)

</code_context>

<specifics>
## Specific Ideas

- $20 is treated as expendable seed money in the aggressive phase -- the bot should trade aggressively enough to grow, not cautiously enough to preserve $20
- Server-side stop-losses are the ultimate safety net -- the bot trusts them during disconnections rather than panicking
- Paper mode should be realistic enough to give confidence before going live -- full fill simulation, not just logging

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 01-trading-infrastructure*
*Context gathered: 2026-03-27*
