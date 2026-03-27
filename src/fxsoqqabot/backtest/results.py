"""BacktestResult and TradeRecord frozen dataclasses.

Canonical data types for recording individual trade outcomes and aggregate
backtest performance. Used by BacktestExecutor to build trade history and
returned by BacktestEngine as the final result.

Both are frozen (immutable) dataclasses with __slots__ for memory efficiency,
following the Phase 1 pattern (TickEvent, BarEvent, FillEvent).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """A single completed backtest trade.

    Attributes:
        entry_time: Unix timestamp (seconds) when position opened.
        exit_time: Unix timestamp (seconds) when position closed.
        action: Trade direction -- "buy" or "sell".
        symbol: Instrument symbol (e.g. "XAUUSD").
        volume: Position size in lots.
        entry_price: Fill price at entry (includes spread + slippage).
        exit_price: Fill price at exit (includes slippage).
        sl: Stop-loss price level.
        tp: Take-profit price level or None.
        pnl: Net P&L after commission.
        commission: Round-trip commission charged.
        regime: RegimeState value string at trade entry.
        slippage_entry: Slippage incurred at entry in price units.
        slippage_exit: Slippage incurred at exit in price units.
        spread_at_entry: Spread at time of entry in price units.
    """

    entry_time: int
    exit_time: int
    action: str
    symbol: str
    volume: float
    entry_price: float
    exit_price: float
    sl: float
    tp: float | None
    pnl: float
    commission: float
    regime: str
    slippage_entry: float
    slippage_exit: float
    spread_at_entry: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Aggregate result of a complete backtest run.

    Contains all trade records and performance metrics. Immutable to
    prevent accidental mutation after computation.

    Attributes:
        trades: Tuple of all TradeRecord instances from the backtest.
        starting_equity: Account equity at backtest start.
        final_equity: Account equity after all trades closed.
        total_commission: Sum of all trade commissions.
        total_bars_processed: Number of M1 bars replayed.
        start_time: Unix timestamp of first bar.
        end_time: Unix timestamp of last bar.
    """

    trades: tuple[TradeRecord, ...]
    starting_equity: float
    final_equity: float
    total_commission: float
    total_bars_processed: int
    start_time: int
    end_time: int

    @property
    def n_trades(self) -> int:
        """Total number of trades executed."""
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        """Fraction of trades with positive P&L.

        Returns 0.0 if no trades.
        """
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades)

    @property
    def profit_factor(self) -> float:
        """Gross profit / gross loss.

        Returns float('inf') if no losing trades, 0.0 if no winning trades.
        """
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @property
    def max_drawdown_pct(self) -> float:
        """Maximum drawdown as percentage of peak equity.

        Computes the equity curve from trade P&Ls and finds the
        largest peak-to-trough decline as a fraction of the peak.

        Returns 0.0 if no trades or no drawdown occurred.
        """
        if not self.trades:
            return 0.0

        equity = self.starting_equity
        peak = equity
        max_dd = 0.0

        for trade in self.trades:
            equity += trade.pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        return max_dd
