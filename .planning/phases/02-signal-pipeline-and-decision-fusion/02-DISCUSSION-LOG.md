# Phase 2: Signal Pipeline and Decision Fusion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 02-signal-pipeline-and-decision-fusion
**Areas discussed:** Signal fusion strategy, Regime-to-behavior mapping, Entry/exit parameters, DOM vs tick-only investment

---

## Signal Fusion Strategy

### Q1: Resolving conflicting signals

| Option | Description | Selected |
|--------|-------------|----------|
| Confidence-weighted blend | Each module outputs score + confidence. Fusion multiplies score x confidence x adaptive weight. Highest composite wins. | ✓ |
| Hierarchical veto | Modules have priority order. Chaos acts as gate. More conservative. | |
| Unanimous agreement | All modules must agree. Fewest trades but highest conviction. | |
| You decide | Claude picks approach. | |

**User's choice:** Confidence-weighted blend (Recommended)
**Notes:** None

### Q2: Adaptive weight mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Decay smoothly | EMA of module accuracy over rolling window. Stable, no sudden weight flips. | ✓ |
| Hard threshold cutoff | Weight drops to near-zero below accuracy threshold. More aggressive muting. | |
| You decide | Claude picks mechanism. | |

**User's choice:** Decay smoothly (Recommended)
**Notes:** None

### Q3: Minimum confidence threshold

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, configurable minimum | Fused confidence must exceed threshold before trade fires. | ✓ |
| No minimum | Always trade if direction agrees. | |
| You decide | Claude picks. | |

**User's choice:** Yes, configurable minimum (Recommended)
**Notes:** None

### Q4: Phase-aware thresholds

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, phase-aware thresholds | Aggressive: lower threshold (0.5). Conservative: higher (0.7). | ✓ |
| Single fixed threshold | One threshold regardless of equity. | |
| You decide | Claude picks. | |

**User's choice:** Yes, phase-aware thresholds (Recommended)
**Notes:** None

---

## Regime-to-Behavior Mapping

### Q1: High-chaos / pre-bifurcation behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Reduce activity, don't stop | Raise threshold, widen SL, reduce size. Still trades on high conviction. | ✓ |
| Full halt until regime clears | Stop trading entirely in chaos. Most conservative. | |
| Trade the chaos | Widen TP targets, accept wider SL. Aggressive. | |
| You decide | Claude picks. | |

**User's choice:** Reduce activity, don't stop (Recommended)
**Notes:** None

### Q2: Ranging regime behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Mean-reversion scalps | Fade extremes, tight TP at range midpoint. | |
| Sit out ranging markets | Only trade trending regimes. | |
| Let fusion decide | No hardcoded ranging behavior. Regime is context, not veto. | ✓ |
| You decide | Claude picks. | |

**User's choice:** Let fusion decide
**Notes:** User chose non-default. Philosophy: regime informs but doesn't dictate behavior.

### Q3: Regime transitions with open positions

| Option | Description | Selected |
|--------|-------------|----------|
| Tighten stops on adverse transition | Tighten SL to lock profit or reduce loss. Don't force-close. | ✓ |
| Force-close on adverse shift | Immediately exit on unfavorable regime change. | |
| Ignore regime for open positions | Regime only affects new trade decisions. | |
| You decide | Claude picks. | |

**User's choice:** Tighten stops on adverse transition (Recommended)
**Notes:** None

### Q4: Regime-conditional fusion weights

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, regime-conditional weights | Each regime has different weight profile for modules. | |
| No, weights adapt purely from accuracy | EMA handles it implicitly. No hardcoded regime-weight maps. | ✓ |
| You decide | Claude picks. | |

**User's choice:** No, weights adapt purely from accuracy
**Notes:** User chose non-default. Prefers the adaptive mechanism to handle regime-weight relationships organically.

---

## Entry/Exit Parameters

### Q1: Take-profit strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Dynamic RR based on regime | Trending 3:1, ranging 1.5:1, high-chaos 2:1. SL from ATR x chaos multiplier. | ✓ |
| Fixed risk-reward ratio | Always 2:1 regardless of regime. Simple. | |
| No fixed TP -- exit on signal reversal | Set SL only, exit when signals reverse. | |
| You decide | Claude picks. | |

**User's choice:** Dynamic RR based on regime (Recommended)
**Notes:** None

### Q2: Trailing stops

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, regime-aware trailing | Trending: trail at 0.5x ATR after 1x SL profit. Ranging: no trailing. Chaos: 0.3x ATR. | ✓ |
| No trailing stops | Fixed SL and TP only. | |
| You decide | Claude picks. | |

**User's choice:** Yes, regime-aware trailing (Recommended)
**Notes:** None

### Q3: Concurrent positions

| Option | Description | Selected |
|--------|-------------|----------|
| One position at a time | Simpler risk, clearer P&L. $20 account constraint. | ✓ |
| Up to N concurrent positions | 2-3 concurrent with total exposure limit. | |
| You decide | Claude picks. | |

**User's choice:** One position at a time (Recommended)
**Notes:** None

### Q4: Quantum timing veto power

| Option | Description | Selected |
|--------|-------------|----------|
| Soft delay, not veto | Delay entry up to 5 min but can't block. | |
| Hard veto | Unfavorable timing skips the trade entirely. | |
| No veto -- timing is just a weight | Contributes to blend like any other module. Low confidence reduces score. | ✓ |
| You decide | Claude picks. | |

**User's choice:** No veto -- timing is just a weight
**Notes:** User chose non-default. Consistent with fusion philosophy: no single module has veto power.

---

## DOM vs Tick-Only Investment

### Q1: Effort split between DOM and tick analysis

| Option | Description | Selected |
|--------|-------------|----------|
| Tick-first, DOM as enhancement | 80% tick / 20% DOM. DOM is optional layer. | ✓ |
| Equal investment in both | 50/50 effort split. | |
| DOM-first, degrade to tick | 70% DOM / 30% tick. | |
| You decide | Claude picks. | |

**User's choice:** Tick-first, DOM as enhancement (Recommended)
**Notes:** None

### Q2: Institutional footprint detection approach

| Option | Description | Selected |
|--------|-------------|----------|
| Statistical anomaly detection | Detect via statistical signatures in tick data. | ✓ (combined) |
| Volume profile clustering | Build volume-at-price profiles from tick data. | ✓ (combined) |
| You decide | Claude picks. | |

**User's choice:** Both approaches combined
**Notes:** User interrupted selection to specify: use statistical anomaly detection as primary method AND volume profile clustering together. Not either/or.

### Q3: DOM quality gating

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-detect quality | Sample DOM for 60s on startup. Enable if depth >= 5 levels, updates >= 1/sec. | ✓ |
| Always try DOM, ignore if empty | No quality gate. Use whatever's available. | |
| You decide | Claude picks. | |

**User's choice:** Auto-detect quality (Recommended)
**Notes:** None

---

## Claude's Discretion

- Signal module abstract interface design
- Package structure for signals
- Algorithm selection for chaos computations
- Quantum timing simplified implementation
- Config model structure
- SQLite schema extensions
- Engine integration pattern
- ATR computation approach

## Deferred Ideas

None -- discussion stayed within phase scope
