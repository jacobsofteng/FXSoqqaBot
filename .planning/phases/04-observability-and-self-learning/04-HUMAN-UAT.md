---
status: partial
phase: 04-observability-and-self-learning
source: [04-VERIFICATION.md]
started: 2026-03-28T01:00:00Z
updated: 2026-03-28T01:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. TUI Visual Layout
expected: Three equal columns -- left (regime/signals/order flow), center (position/risk/trades), right (stats/sparkline/kill button). Kill button docked to bottom of right column.
result: [pending]

### 2. TUI Traffic-Light Color Coding
expected: Red for HIGH_CHAOS/PRE_BIFURCATION; yellow for RANGING; green for TRENDING_UP/TRENDING_DOWN.
result: [pending]

### 3. Web Dashboard LAN Accessibility
expected: Dashboard renders in mobile browser with all three tabs navigable; WebSocket connects and shows live data.
result: [pending]

### 4. WebSocket Reconnect After Server Restart
expected: Dashboard shows disconnected state briefly, then reconnects automatically with exponential backoff.
result: [pending]

### 5. Kill Switch End-to-End
expected: All open positions closed, is_killed=True, TUI shows KILLED in red, no new trades placed.
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
