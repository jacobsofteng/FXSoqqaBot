# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — FXSoqqaBot MVP

**Shipped:** 2026-03-28
**Phases:** 7 | **Plans:** 32 | **Tasks:** 59

### What Was Built
- Complete XAUUSD trading infrastructure: async MT5 bridge, market data pipeline, order execution, paper trading, crash recovery
- Three-module signal pipeline (chaos regime, order flow, quantum timing) with confidence-weighted fusion and adaptive EMA weights
- Scientific backtesting framework sharing 100% of live analysis code via DataFeedProtocol abstraction
- Dual dashboards (Rich TUI + FastAPI web) with live equity, regime, signals, positions, module weights
- Self-learning evolution loop: DEAP GA, shadow variants, ML regime classifier, walk-forward promotion gate
- Full cross-phase integration: all 6 E2E flows verified, all feedback loops wired

### What Worked
- **Coarse-grained phases**: 4 core phases + 3 gap closure phases was the right granularity — each phase delivered a complete capability
- **Per-phase verification**: Catching integration gaps early via gsd-verifier prevented compound failures
- **Protocol-based abstraction**: DataFeedProtocol and SignalModule Protocol enabled code sharing between live and backtest paths with zero duplication
- **TDD with behavioral spot-checks**: Writing tests alongside implementation caught issues fast; 772+ tests serve as living documentation
- **Gap closure phases**: The audit-then-fix cycle (phases 5-7) was efficient — targeted fixes rather than reopening completed phases

### What Was Inefficient
- **Initial per-phase verification missed cross-phase integration**: All 4 original phases passed individually, but 8 integration gaps only surfaced in the milestone audit. Should verify cross-phase wiring earlier.
- **SUMMARY frontmatter tagging incomplete**: 17/47 requirements missing from SUMMARY `requirements-completed` frontmatter. The verification still caught them, but the 3-source cross-reference flagged unnecessary noise.
- **DOM always None**: The DOM data path is fully implemented but never exercised because MarketDataFeed doesn't expose `latest_dom`. This was deferred rather than cut — should have been explicit in requirements.

### Patterns Established
- **SignalModule Protocol pattern**: `@runtime_checkable` Protocol with `update(tick_arrays, bar_arrays, dom)` method — reuse for any future signal modules
- **Component-level testing with mocked I/O**: Test at the component boundary (not full TradingEngine) with real sub-components and mocked MT5. Avoids live terminal dependency.
- **Singleton row pattern in SQLite**: `id=1 CHECK` constraint for global state (circuit breakers). Clean, atomic updates.
- **TYPE_CHECKING imports for circular deps**: Use `from __future__ import annotations` + `TYPE_CHECKING` block for cross-module references
- **asyncio.to_thread for blocking computation**: Wrap scipy/numpy/nolds calls to avoid blocking the event loop
- **Fail-safe rejection**: When uncertain (validator errors, insufficient data), reject rather than allow through

### Key Lessons
1. **Cross-phase integration verification should happen incrementally**, not just at milestone audit time. Each new phase should verify its wiring to upstream phases as part of its own verification.
2. **Learning disabled by default is correct** for a $20 account — but this means the entire learning pipeline (LEARN-04/05/06) is never exercised at default config. Consider a "dry-run" mode that runs the learning loop without applying changes.
3. **Gap closure phases are highly efficient** — targeted, small-scope, fast to execute. Better to ship the main phases and audit/fix than to try to get cross-phase wiring perfect on the first pass.
4. **DataFeedProtocol abstraction was worth the upfront cost** — zero separate backtest code paths means signal module improvements automatically benefit both live and backtest modes.

### Cost Observations
- Model mix: ~50% opus (execution), ~40% sonnet (research/verification/integration), ~10% haiku
- Sessions: ~8-10 sessions over 2 days
- Notable: Gap closure phases (5-7) were very fast (3-4 min per plan) compared to core phases (5-9 min per plan)

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 7 | 32 | Initial release — established verification + audit + gap closure cycle |

### Cumulative Quality

| Milestone | Tests | LOC Source | LOC Tests | Requirements |
|-----------|-------|-----------|-----------|-------------|
| v1.0 | 772+ | 14,811 | 14,594 | 47/47 satisfied |

### Top Lessons (Verified Across Milestones)

1. Cross-phase integration gaps are the #1 risk — verify wiring incrementally, not just at audit
2. Protocol-based abstraction pays dividends in code reuse and testability
3. Gap closure phases are cheaper than getting cross-phase integration right on first pass
