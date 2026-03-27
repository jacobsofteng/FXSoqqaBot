"""Monte Carlo trade sequence shuffling per D-07.

Evaluates strategy robustness by shuffling trade P&L sequences and measuring
tail risk statistics. Implements the D-07 dual threshold:
- Criterion 1: 5th percentile of final equity must be net positive (p < 0.05)
- Criterion 2: Median run must be profitable AND 95th percentile max drawdown < 40%

Note (Pitfall 5): Shuffling trade sequences breaks temporal dependencies.
This is a known limitation -- the Monte Carlo test validates that the
strategy's edge does not depend on a lucky trade ordering, NOT that it
is temporally robust. Regime-aware evaluation (D-08) addresses temporal
dependency separately.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    """Result of Monte Carlo simulation per D-07.

    Attributes:
        n_simulations: Number of shuffle iterations performed.
        pct_5_equity: 5th percentile of final equity distribution.
        median_equity: 50th percentile (median) of final equity distribution.
        pct_95_max_dd: 95th percentile of max drawdown distribution (fraction, e.g. 0.25 = 25%).
        p_value: Fraction of runs with final equity below starting equity.
        passes_threshold: True if both D-07 criteria are met.
        equity_distribution: All final equities for histogram rendering.
    """

    n_simulations: int
    pct_5_equity: float
    median_equity: float
    pct_95_max_dd: float
    p_value: float
    passes_threshold: bool
    equity_distribution: tuple[float, ...]


def run_monte_carlo(
    trade_pnls: np.ndarray,
    starting_equity: float,
    n_simulations: int = 10_000,
    max_drawdown_threshold: float = 0.40,
    seed: int = 42,
) -> MonteCarloResult:
    """Monte Carlo trade sequence shuffling per D-07.

    Shuffles the trade P&L array n_simulations times. For each shuffle,
    builds an equity curve and records the final equity and maximum
    drawdown. Then computes tail risk statistics and evaluates the
    D-07 dual threshold.

    Algorithm:
    1. Create numpy RNG with given seed for reproducibility.
    2. For each of n_simulations iterations:
       a. Shuffle trade_pnls using rng.permutation()
       b. Build equity curve: starting_equity + cumsum(shuffled_pnls)
       c. Record final equity
       d. Compute max drawdown: max((running_max - equity) / running_max)
    3. Compute statistics:
       - pct_5_equity = np.percentile(final_equities, 5)
       - median_equity = np.percentile(final_equities, 50)
       - pct_95_max_dd = np.percentile(max_drawdowns, 95)
       - p_value = np.mean(final_equities < starting_equity)
    4. Evaluate D-07 dual threshold:
       - Criterion 1: pct_5_equity > starting_equity
       - Criterion 2: median_equity > starting_equity AND pct_95_max_dd < max_drawdown_threshold
       - passes = criterion_1 AND criterion_2

    Args:
        trade_pnls: 1D array of trade P&Ls (net of commission).
        starting_equity: Account equity before trades.
        n_simulations: Number of shuffle iterations.
        max_drawdown_threshold: Maximum acceptable 95th percentile drawdown (fraction).
        seed: Random seed for reproducibility.

    Returns:
        MonteCarloResult with all computed statistics.
    """
    # Edge case: zero trades
    if len(trade_pnls) == 0:
        return MonteCarloResult(
            n_simulations=n_simulations,
            pct_5_equity=starting_equity,
            median_equity=starting_equity,
            pct_95_max_dd=0.0,
            p_value=1.0,
            passes_threshold=False,
            equity_distribution=(starting_equity,),
        )

    rng = np.random.default_rng(seed)
    n_trades = len(trade_pnls)

    final_equities = np.empty(n_simulations, dtype=np.float64)
    max_drawdowns = np.empty(n_simulations, dtype=np.float64)

    for i in range(n_simulations):
        shuffled = rng.permutation(trade_pnls)
        equity_curve = starting_equity + np.cumsum(shuffled)

        final_equities[i] = equity_curve[-1]

        # Max drawdown computation
        running_max = np.maximum.accumulate(equity_curve)
        # Prepend starting equity to running_max to capture drawdown from start
        running_max = np.maximum(running_max, starting_equity)
        drawdowns = (running_max - equity_curve) / np.where(
            running_max > 0, running_max, 1.0
        )
        max_drawdowns[i] = float(drawdowns.max()) if len(drawdowns) > 0 else 0.0

    # Compute statistics
    pct_5_equity = float(np.percentile(final_equities, 5))
    median_equity = float(np.percentile(final_equities, 50))
    pct_95_max_dd = float(np.percentile(max_drawdowns, 95))
    p_value = float(np.mean(final_equities < starting_equity))

    # D-07 dual threshold evaluation
    criterion_1 = pct_5_equity > starting_equity
    criterion_2 = median_equity > starting_equity and pct_95_max_dd < max_drawdown_threshold
    passes = criterion_1 and criterion_2

    return MonteCarloResult(
        n_simulations=n_simulations,
        pct_5_equity=pct_5_equity,
        median_equity=median_equity,
        pct_95_max_dd=pct_95_max_dd,
        p_value=p_value,
        passes_threshold=passes,
        equity_distribution=tuple(final_equities.tolist()),
    )
