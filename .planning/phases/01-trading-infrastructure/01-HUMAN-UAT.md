---
status: partial
phase: 01-trading-infrastructure
source: [01-VERIFICATION.md]
started: 2026-03-27T11:00:00Z
updated: 2026-03-27T11:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Live MT5 tick stream
expected: XAUUSD ticks arrive at sub-second frequency, spread ~0.30-0.50 for ECN
result: [pending]

### 2. Paper market order via CLI
expected: FillEvent logged with is_paper=True, simulated slippage, correct lot size from PositionSizer
result: [pending]

### 3. Circuit breaker persistence across restart
expected: CircuitBreakerSnapshot loads from SQLite on restart with daily_drawdown=tripped
result: [pending]

### 4. Concurrent kill switch from second terminal
expected: All positions closed, kill_switch=KILLED in SQLite, bot halts new trade decisions
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
