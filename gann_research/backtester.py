"""
Backtester -- Module 16

Full backtest framework with train/test split.
Reports: win rate, R:R ratio, EV per trade, max drawdown,
trades per day, equity curve.

FULL DATASET: train 2009-2019, test 2020-2026.
"""

import struct
from datetime import datetime, timezone
from typing import Optional

from .swing_detector import Bar
from .strategy import TradingState, process_bar, print_diagnostic_report


# Full data ranges per spec
TRAIN_START = "2009-01-01"
TRAIN_END = "2019-12-31"
TEST_START = "2020-01-01"
TEST_END = "2026-03-20"


def load_m5_binary(filepath: str,
                   start_date: str = None,
                   end_date: str = None) -> list[Bar]:
    """
    Load XAUUSD_M5.bin binary data.

    Format:
      - 8-byte header: int64 = record count
      - Records: int32 timestamp + int32 padding(0) + 4 doubles (OHLC)
      - Record size: 40 bytes

    Optional date filtering to select train/test periods.
    """
    bars = []
    record_size = 40
    fmt = '<ii4d'  # int32 ts + int32 pad + 4 doubles (OHLC)

    # Parse date filters
    start_ts = None
    end_ts = None
    if start_date:
        start_ts = datetime.strptime(start_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc).timestamp()
    if end_date:
        end_ts = datetime.strptime(end_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc).timestamp()

    with open(filepath, 'rb') as f:
        data = f.read()

    # Skip 8-byte header
    n_records = struct.unpack('<q', data[:8])[0]
    data = data[8:]

    idx = 0
    for i in range(min(n_records, len(data) // record_size)):
        offset = i * record_size
        chunk = data[offset:offset + record_size]
        if len(chunk) < record_size:
            break
        ts, _pad, o, h, l, c = struct.unpack(fmt, chunk)

        # Date filtering
        if start_ts and ts < start_ts:
            continue
        if end_ts and ts > end_ts:
            continue

        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        bars.append(Bar(
            time=dt, open=o, high=h, low=l, close=c,
            volume=0, bar_index=idx,
        ))
        idx += 1

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
        Dict with all metrics + trade list + diagnostic counters
    """
    state = TradingState()
    equity = start_equity
    equity_curve = [equity]
    all_trades = []

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
                _print_trade_detail(trade, len(all_trades))

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
        state.open_trade['exit_reason'] = 'END_OF_DATA'
        state.open_trade['actual_rr'] = round(
            abs(pnl) / state.open_trade['sl_distance'], 2
        ) if state.open_trade['sl_distance'] > 0 else 0
        equity += pnl
        equity_curve.append(equity)
        all_trades.append(state.open_trade)

    metrics = compute_metrics(all_trades, equity_curve, len(bars), start_equity)
    metrics['diagnostics'] = state.counters
    metrics['state'] = state
    return metrics


def _print_trade_detail(trade: dict, trade_num: int):
    """Print detailed trade info for diagnosis."""
    print(f"\n  Trade #{trade_num}: {trade['direction'].upper()} "
          f"entry=${trade['entry_price']:.2f}")
    print(f"    SL=${trade['sl']:.2f}, TP=${trade['tp']:.2f}")
    print(f"    SL distance: ${trade['sl_distance']:.2f}")
    print(f"    TP distance: ${trade['tp_distance']:.2f}")
    print(f"    Designed R:R: {trade.get('designed_rr', trade.get('rr_ratio', 0)):.1f}:1")
    print(f"    EXIT REASON: {trade.get('exit_reason', 'unknown')}")
    print(f"    Exit price: ${trade['exit_price']:.2f}")
    print(f"    Actual P&L: ${trade['pnl']:+.2f}")
    print(f"    Actual R:R: {trade.get('actual_rr', 0):.2f}:1")
    print(f"    Bars held: {trade.get('bars_held', 0)}")
    if hasattr(trade.get('entry_time', None), 'strftime'):
        print(f"    Entry: {trade['entry_time'].strftime('%Y-%m-%d %H:%M')}")
    if hasattr(trade.get('exit_time', None), 'strftime'):
        print(f"    Exit:  {trade['exit_time'].strftime('%Y-%m-%d %H:%M')}")


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

    # Exit reason breakdown
    exit_reasons = {}
    for t in trades:
        reason = t.get('exit_reason', 'unknown')
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

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
        'exit_reasons': exit_reasons,
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

    # Exit reason breakdown
    if metrics.get('exit_reasons'):
        print(f"\n  Exit reasons:")
        for reason, count in sorted(metrics['exit_reasons'].items()):
            pct = count / metrics['total_trades'] if metrics['total_trades'] > 0 else 0
            print(f"    {reason}: {count} ({pct:.1%})")

    print(f"{'='*60}")
