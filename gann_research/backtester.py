"""
Backtester -- Module 16

Full backtest framework with train/test split.
Reports: win rate, R:R ratio, EV per trade, max drawdown,
trades per day, equity curve.
"""

import struct
from datetime import datetime, timezone
from typing import Optional

from .swing_detector import Bar
from .strategy import TradingState, process_bar


def load_m5_binary(filepath: str) -> list[Bar]:
    """
    Load XAUUSD_M5.bin binary data.

    Format:
      - 8-byte header: int64 = record count
      - Records: int32 timestamp + int32 padding(0) + 4 doubles (OHLC)
      - Record size: 40 bytes
    """
    bars = []
    record_size = 40
    fmt = '<ii4d'  # int32 ts + int32 pad + 4 doubles (OHLC)

    with open(filepath, 'rb') as f:
        data = f.read()

    # Skip 8-byte header
    n_records = struct.unpack('<q', data[:8])[0]
    data = data[8:]

    for i in range(min(n_records, len(data) // record_size)):
        offset = i * record_size
        chunk = data[offset:offset + record_size]
        if len(chunk) < record_size:
            break
        ts, _pad, o, h, l, c = struct.unpack(fmt, chunk)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        bars.append(Bar(
            time=dt, open=o, high=h, low=l, close=c,
            volume=0, bar_index=i,
        ))

    return bars


def run_backtest(bars: list[Bar],
                 start_equity: float = 10000.0,
                 verbose: bool = False) -> dict:
    """
    Run full backtest of the v9.1 triangle strategy.

    Args:
        bars: List of M5 bars
        start_equity: Starting account balance
        verbose: Print trade details

    Returns:
        Dict with all metrics + trade list
    """
    state = TradingState()
    equity = start_equity
    equity_curve = [equity]
    all_trades = []  # Track trades separately so state list can be consumed

    for i, bar in enumerate(bars):
        bar.bar_index = i  # Ensure sequential indexing
        state = process_bar(bar, state)

        # Process any newly closed trades
        while state.closed_trades:
            trade = state.closed_trades.pop(0)
            pnl = trade['pnl']
            equity += pnl
            equity_curve.append(equity)
            all_trades.append(trade)

            if verbose:
                print(f"  Trade #{len(all_trades)}: "
                      f"{trade['direction']} ${trade['entry_price']:.2f} "
                      f"-> ${trade['exit_price']:.2f}, "
                      f"PnL=${pnl:.2f}, Eq=${equity:.2f}")

    # Close any remaining open trade
    if state.open_trade and len(bars) > 0:
        last_bar = bars[-1]
        if state.open_trade['direction'] == 'long':
            pnl = last_bar.close - state.open_trade['entry_price']
        else:
            pnl = state.open_trade['entry_price'] - last_bar.close
        state.open_trade['pnl'] = pnl
        state.open_trade['exit_price'] = last_bar.close
        state.open_trade['exit_bar'] = last_bar.bar_index
        state.open_trade['exit_time'] = last_bar.time
        state.open_trade['won'] = pnl > 0
        state.open_trade['bars_held'] = last_bar.bar_index - state.open_trade['entry_bar']
        equity += pnl
        equity_curve.append(equity)
        all_trades.append(state.open_trade)

    return compute_metrics(all_trades, equity_curve, len(bars), start_equity)


def compute_metrics(trades: list, equity_curve: list,
                    total_bars: int, start_equity: float) -> dict:
    """Compute all performance metrics."""
    if not trades:
        return {
            'total_trades': 0,
            'win_rate': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'rr_ratio': 0,
            'ev_per_trade': 0,
            'max_drawdown': 0,
            'trades_per_day': 0,
            'final_equity': start_equity,
            'equity_curve': equity_curve,
            'trades': [],
        }

    wins = [t for t in trades if t.get('pnl', 0) > 0]
    losses = [t for t in trades if t.get('pnl', 0) <= 0]

    win_rate = len(wins) / len(trades) if trades else 0
    avg_win = (sum(t['pnl'] for t in wins) / len(wins)) if wins else 0
    avg_loss = (abs(sum(t['pnl'] for t in losses)) / len(losses)) if losses else 1

    rr = avg_win / avg_loss if avg_loss > 0 else 0
    ev = win_rate * avg_win - (1 - win_rate) * avg_loss

    # Max drawdown
    peak = equity_curve[0]
    max_dd = 0
    for eq in equity_curve:
        peak = max(peak, eq)
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Trades per day (288 M5 bars = 1 day)
    total_days = total_bars / 288 if total_bars > 0 else 1
    tpd = len(trades) / total_days

    return {
        'total_trades': len(trades),
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'rr_ratio': rr,
        'ev_per_trade': ev,
        'max_drawdown': max_dd,
        'trades_per_day': tpd,
        'final_equity': equity_curve[-1] if equity_curve else start_equity,
        'equity_curve': equity_curve,
        'trades': trades,
    }


def print_report(metrics: dict, label: str = ""):
    """Print a formatted backtest report."""
    print(f"\n{'='*60}")
    print(f"  BACKTEST REPORT{(' - ' + label) if label else ''}")
    print(f"{'='*60}")
    print(f"  Total trades:     {metrics['total_trades']}")
    print(f"  Win rate:         {metrics['win_rate']:.1%}")
    print(f"  Avg win:          ${metrics['avg_win']:.2f}")
    print(f"  Avg loss:         ${metrics['avg_loss']:.2f}")
    print(f"  R:R ratio:        {metrics['rr_ratio']:.2f}")
    print(f"  EV per trade:     ${metrics['ev_per_trade']:.2f}")
    print(f"  Max drawdown:     {metrics['max_drawdown']:.1%}")
    print(f"  Trades per day:   {metrics['trades_per_day']:.2f}")
    print(f"  Final equity:     ${metrics['final_equity']:.2f}")
    print(f"{'='*60}")
