# Phase 3: Backtesting and Validation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 03-backtesting-and-validation
**Areas discussed:** Historical data strategy, Validation pass/fail criteria, Spread & slippage realism, Out-of-sample holdout

---

## Historical Data Strategy

### Data Sources

| Option | Description | Selected |
|--------|-------------|----------|
| histdata M1 bars + MT5 ticks | Use histdata.com M1 bars for 2015-2024 bulk history. Layer in MT5 tick data for most recent 1-2 years. | ✓ |
| MT5 bars only | Use only MT5's built-in history (1-3 years). Simpler but limited. | |
| histdata M1 bars only | No tick-level backtesting. Simpler but loses signal fidelity. | |

**User's choice:** histdata M1 bars + MT5 ticks (Recommended)
**Notes:** None

### Module Degradation (Bar-Only Mode)

| Option | Description | Selected |
|--------|-------------|----------|
| Graceful module degradation | Modules run in 'bar-only' mode with reduced confidence when only M1 bars available. | ✓ |
| Synthetic tick generation | Generate synthetic ticks from M1 bars. More complex, introduces assumptions. | |
| Skip tick-dependent signals | Disable order flow and quantum timing when only bars available. | |

**User's choice:** Graceful module degradation (Recommended)
**Notes:** None

### Data Quality

| Option | Description | Selected |
|--------|-------------|----------|
| Strict validation | Validate, flag, reject bad data. | |
| Minimal validation | Basic parsing and sorting only. | |
| Validate + auto-repair | Strict validation + interpolate small gaps, filter outliers. | ✓ |

**User's choice:** Validate + auto-repair
**Notes:** None

### Storage Format

| Option | Description | Selected |
|--------|-------------|----------|
| Convert to Parquet | Parse CSVs once, store as Parquet partitioned by year/month. | ✓ |
| DuckDB import | Import directly into DuckDB tables. | |
| Load from CSV each run | Parse CSVs fresh each backtest run. | |

**User's choice:** Convert to Parquet (Recommended)
**Notes:** None

---

## Validation Pass/Fail Criteria

### Walk-Forward Window Sizing

| Option | Description | Selected |
|--------|-------------|----------|
| 6mo train / 2mo validate | ~50 windows from 2015-present. Balances training data with statistical power. | ✓ |
| 12mo train / 3mo validate | Larger windows, fewer of them (~30). | |
| 3mo train / 1mo validate | Shorter windows, more of them (~100+). | |
| You decide | Claude picks optimal sizing. | |

**User's choice:** 6mo train / 2mo validate (Recommended)
**Notes:** None

### Walk-Forward Threshold

| Option | Description | Selected |
|--------|-------------|----------|
| Profitable in 70%+ windows | Net profitable in at least 70% of windows. PF > 1.2 aggregate. | ✓ (combined) |
| Profitable in every window | 100% window win rate. | |
| Positive expectancy aggregate | Total P&L positive with PF > 1.5. Individual windows can lose. | ✓ (combined) |

**User's choice:** Combined: 70%+ windows profitable AND aggregate PF > 1.5
**Notes:** User explicitly requested combining option 1 and 3. Dual threshold -- both must pass.

### Monte Carlo Criteria

| Option | Description | Selected |
|--------|-------------|----------|
| 95th percentile profitable | 5th percentile equity curve must be net positive (p < 0.05). | ✓ (combined) |
| 99th percentile profitable | Even worst 1% must be profitable. | |
| Median profitable + bounded drawdown | Median profitable AND 95th percentile max DD < 40% of peak. | ✓ (combined) |

**User's choice:** Combined: 5th percentile net positive AND median profitable with bounded drawdown
**Notes:** User explicitly requested combining option 1 and 3.

### Regime Evaluation Taxonomy

| Option | Description | Selected |
|--------|-------------|----------|
| Match chaos module regimes | 5 regimes: trending-up, trending-down, ranging, high-chaos, pre-bifurcation. | ✓ |
| Simplified regime set | 3 regimes: trending, ranging, volatile. | |
| You decide | Claude picks optimal taxonomy. | |

**User's choice:** Match chaos module regimes (Recommended)
**Notes:** None

---

## Spread & Slippage Realism

### Spread Model

| Option | Description | Selected |
|--------|-------------|----------|
| Session-aware dynamic spread | Time-of-day and volatility based. Calibrated from MT5 tick data. | ✓ |
| Fixed spread per regime | Assign spreads by chaos regime. | |
| Worst-case fixed spread | Single conservative fixed spread for all. | |

**User's choice:** Session-aware dynamic spread (Recommended)
**Notes:** None

### Slippage Model

| Option | Description | Selected |
|--------|-------------|----------|
| Stochastic slippage | Random from calibrated distribution. 80% zero, 15% 1-pip, 4% 2-pip, 1% 3+. | ✓ |
| Fixed adverse slippage | Always assume 1-2 pip adverse. | |
| No slippage modeling | Fills at bar price, no slippage. | |

**User's choice:** Stochastic slippage (Recommended)
**Notes:** None

### Commission Modeling

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, model commissions | Include RoboForex ECN rates, hardcoded. | |
| No, skip commissions | Ignore commissions. | |
| Configurable per-lot cost | Adjustable commission parameter. Default to RoboForex ECN rates. | ✓ |

**User's choice:** Configurable per-lot cost
**Notes:** None

---

## Out-of-Sample Holdout

### Holdout Size

| Option | Description | Selected |
|--------|-------------|----------|
| Last 6 months | ~Oct 2025 - Mar 2026. Balance of data and validation confidence. | ✓ |
| Last 12 months | Full year. More rigorous but loses training data. | |
| Last 3 months | Minimal holdout. Maximizes training data. | |

**User's choice:** Last 6 months (Recommended)
**Notes:** None

### OOS Failure Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Hard fail -- strategy rejected | PF < 50% of in-sample or DD > 2x = overfit, rejected. | ✓ |
| Soft warning with metrics | Log divergence but don't auto-reject. | |
| Automatic parameter scaling | Scale down risk on underperformance. | |

**User's choice:** Hard fail -- strategy rejected (Recommended)
**Notes:** None

---

## Claude's Discretion

- DataFeedProtocol + Clock abstraction design
- vectorbt integration approach
- Feigenbaum stress testing implementation
- Backtest result storage and reporting
- histdata.com CSV parsing
- Walk-forward optimizer coordination

## Deferred Ideas

None -- discussion stayed within phase scope
