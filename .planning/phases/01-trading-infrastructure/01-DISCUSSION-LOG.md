# Phase 1: Trading Infrastructure - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 01-trading-infrastructure
**Areas discussed:** Safe start strategy, Micro-account risk math, Recovery behavior, Kill switch & safety triggers

---

## Safe Start Strategy

### Q1: Paper trading mode?

| Option | Description | Selected |
|--------|-------------|----------|
| Paper mode first (Recommended) | Dry-run mode with full pipeline, logs trades instead of executing | :heavy_check_mark: |
| Live from day one | Test directly on $20 account with minimum lots | |
| MT5 demo account first | Use RoboForex demo account, switch to live when proven | |

**User's choice:** Paper mode first
**Notes:** None

### Q2: How should paper mode work?

| Option | Description | Selected |
|--------|-------------|----------|
| Full simulation with virtual fills | Simulates order fills using live tick data, models spread/slippage/partial fills | :heavy_check_mark: |
| Log-only mode | Just logs what bot would have done without simulating fills | |
| You decide | Claude picks the approach | |

**User's choice:** Full simulation with virtual fills
**Notes:** None

### Q3: When to switch paper to live?

| Option | Description | Selected |
|--------|-------------|----------|
| Manual switch only | User explicitly changes config flag, no automatic promotion | :heavy_check_mark: |
| Criteria-based with manual approval | Bot recommends going live when metrics met, user must confirm | |
| You decide | Claude picks | |

**User's choice:** Manual switch only
**Notes:** None

---

## Micro-Account Risk Math

### Q1: Position sizing when 1% risk is impossible?

| Option | Description | Selected |
|--------|-------------|----------|
| Accept higher risk in aggressive phase | Allow up to 3-5% risk during $20-$100 phase | :heavy_check_mark: |
| Skip trades that exceed risk limit | Don't trade if 0.01 lot exceeds configured risk % | |
| Dynamic risk by capital phase | 3-5% aggressive, 2% selective, 1% conservative | |
| You decide | Claude picks | |

**User's choice:** Accept higher risk in aggressive phase
**Notes:** None

### Q2: Max risk per trade in aggressive phase?

| Option | Description | Selected |
|--------|-------------|----------|
| Up to 5% | $1.00 risk at $20, allows most scalping setups | |
| Up to 3% | $0.60 risk at $20, more cautious | |
| Up to 10% | $2.00 risk at $20, treats $20 as pure seed money | :heavy_check_mark: |
| You decide | Claude picks | |

**User's choice:** Up to 10% per trade
**Notes:** Very aggressive -- $20 is treated as expendable seed money

### Q3: Risk limits for selective and conservative phases?

| Option | Description | Selected |
|--------|-------------|----------|
| Selective: 3%, Conservative: 1% | Standard step-down | |
| Selective: 5%, Conservative: 2% | Still aggressive but proven by reaching thresholds | :heavy_check_mark: |
| You decide | Claude picks | |

**User's choice:** Selective: 5%, Conservative: 2%
**Notes:** None

---

## Recovery Behavior

### Q1: Crash recovery with open positions?

| Option | Description | Selected |
|--------|-------------|----------|
| Close all and halt | Close everything, wait for manual restart | |
| Reconcile and resume | Match positions against last state, resume managing | |
| Close all, then auto-resume | Flatten everything, then auto-resume trading | :heavy_check_mark: |
| You decide | Claude picks | |

**User's choice:** Close all, then auto-resume
**Notes:** None

### Q2: MT5 connection drop behavior?

| Option | Description | Selected |
|--------|-------------|----------|
| Retry connection, trust server-side SL | Keep retrying, positions protected by server-side stops | :heavy_check_mark: |
| Retry with timeout, then halt | Retry for configurable window, halt if still disconnected | |
| You decide | Claude picks | |

**User's choice:** Retry connection, trust server-side SL
**Notes:** None

### Q3: State persistence level?

| Option | Description | Selected |
|--------|-------------|----------|
| Full state to SQLite | Every position, order, P&L, circuit breaker, session counter, account snapshot | :heavy_check_mark: |
| Minimal critical state | Only daily drawdown, circuit breaker status, trading mode | |
| You decide | Claude picks | |

**User's choice:** Full state to SQLite
**Notes:** None

---

## Kill Switch & Safety Triggers

### Q1: Additional automatic halt conditions?

| Option | Description | Selected |
|--------|-------------|----------|
| Consecutive loss streak | Halt after N consecutive losses | :heavy_check_mark: |
| Spread spike detection | Halt on sustained abnormal spread | :heavy_check_mark: |
| Rapid equity drop | Halt on fast equity decline within short window | :heavy_check_mark: |
| Max daily trade count | Halt after N trades per day | :heavy_check_mark: |

**User's choice:** All four selected
**Notes:** Defense in depth approach

### Q2: Kill switch invocation?

| Option | Description | Selected |
|--------|-------------|----------|
| Terminal command + TUI button | CLI command works independently, TUI button when dashboard available | :heavy_check_mark: |
| Terminal command only | CLI only, keep Phase 1 simple | |
| You decide | Claude picks | |

**User's choice:** Terminal command + TUI button
**Notes:** None

### Q3: Resume policy after safety triggers?

| Option | Description | Selected |
|--------|-------------|----------|
| Manual reset required | Stay halted until explicit user reset | |
| Auto-reset at next session | Counters reset at session boundary, kill switch still manual | :heavy_check_mark: |
| You decide | Claude picks | |

**User's choice:** Auto-reset at next session
**Notes:** Kill switch specifically still requires manual reset

---

## Claude's Discretion

- Project structure and Python package layout
- Async architecture design
- DuckDB/Parquet and SQLite schema design
- MT5-Python communication details
- Configuration file format and structure
- Logging patterns
- Test structure

## Deferred Ideas

None -- discussion stayed within phase scope
