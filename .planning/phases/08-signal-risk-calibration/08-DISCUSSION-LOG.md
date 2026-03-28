# Phase 8: Signal & Risk Calibration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-28
**Phase:** 08-signal-risk-calibration
**Areas discussed:** Chaos direction strategy, Signal aggressiveness tuning, Concurrent positions, Session window expansion

---

## Chaos Direction Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Drift | Use 20-bar price momentum for non-trending regimes. Self-contained in chaos module. | ✓ |
| Flow follow | Borrow flow module's direction signal. Richer but adds cross-module coupling. | |
| Zero | Keep current behavior (direction=0.0 for non-trending). Safest but defeats SIG-01. | |

**User's choice:** Drift
**Notes:** Recommended as simplest approach that immediately unblocks >30% of bars producing nonzero direction per SIG-01 without module coupling.

---

## Signal Aggressiveness Tuning

### Q1: Fusion threshold default

| Option | Description | Selected |
|--------|-------------|----------|
| 0.25 | Most aggressive, maximum trade frequency | |
| 0.30 | Middle ground, leaves room for Optuna to push either direction | ✓ |
| 0.35 | More selective, closer to current behavior | |

**User's choice:** 0.30
**Notes:** Recommended middle-ground value.

### Q2: Change strategy

| Option | Description | Selected |
|--------|-------------|----------|
| All at once | Flip threshold + risk_pct + ATR multiplier together | ✓ |
| Threshold first | Change threshold, measure, then adjust risk/SL | |

**User's choice:** All at once
**Notes:** Parameters designed as a package in the requirements.

---

## Concurrent Positions

### Q1: How many concurrent positions

| Option | Description | Selected |
|--------|-------------|----------|
| 2 | Each position gets ~7.5% of 15% budget. At $20 = $1.50 risk each. | ✓ |
| 3 | More diversified but thinner risk slices. At $20 = $1.00 each, may hit min lot rejection. | |

**User's choice:** 2
**Notes:** Recommended due to micro-account constraints at $20.

### Q2: Aggregate cap mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Equal split | Always divide budget by max positions (7.5% each) | |
| Remaining budget | First position gets full 15%, second gets remainder | ✓ |

**User's choice:** Remaining budget
**Notes:** More complex but uses capital more efficiently.

---

## Session Window Expansion

| Option | Description | Selected |
|--------|-------------|----------|
| Keep the gap | Two windows: 08:00-12:00 and 13:00-17:00. Avoids low-liquidity lunch hour. | ✓ |
| Close the gap | One continuous window: 08:00-17:00 | |
| Shrink the gap | Compromise like 08:00-12:00 and 12:30-17:00 | |

**User's choice:** Keep the gap
**Notes:** Standard institutional convention. London lunch hour is low-liquidity with wider spreads.

---

## Claude's Discretion

- Exact aggressive daily drawdown percentage within 15-20% range
- Flow_follow mode cross-module implementation details
- Whether selective/conservative confidence thresholds shift proportionally

## Deferred Ideas

None — discussion stayed within phase scope.
