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
from .strategy import (
    TradingStateV92, process_bar_v92, print_diagnostic_report_v92,
)


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


# ============================================================
# v9.2 BACKTESTER
# ============================================================

def run_backtest_v92(bars: list[Bar],
                     start_equity: float = 10000.0,
                     multi_scale: bool = False,
                     auto_scale_lots: bool = False,
                     verbose: bool = False) -> dict:
    """
    Run v9.2 backtest with parallel boxes and optional multi-scale.

    Args:
        bars: List of M5 bars
        start_equity: Starting account balance
        multi_scale: Enable M15 scale alongside H1
        auto_scale_lots: Use auto-scaling position sizing (Change 3)
        verbose: Print trade details
    """
    state = TradingStateV92(multi_scale=multi_scale)
    equity = start_equity
    equity_curve = [equity]
    all_trades = []

    # Auto-scaling support (imported lazily to allow Change 3 to be optional)
    dd_protection = None
    get_lot_fn = None
    if auto_scale_lots:
        from .position_sizing import get_lot_size, DrawdownProtection
        dd_protection = DrawdownProtection()
        dd_protection.peak = start_equity
        get_lot_fn = get_lot_size

    for i, bar in enumerate(bars):
        bar.bar_index = i
        state = process_bar_v92(bar, state)

        # Process newly closed trades
        while state.closed_trades:
            trade = state.closed_trades.pop(0)
            raw_pnl = trade['pnl']

            if auto_scale_lots and get_lot_fn and dd_protection:
                dd_protection.update(equity)
                scale = trade.get('scale', 'H1')
                raw_lots = get_lot_fn(equity, scale)
                lots = dd_protection.adjust(raw_lots)
                lot_multiplier = lots / 0.01
                trade['lots'] = lots
                trade['lot_multiplier'] = lot_multiplier
                equity += raw_pnl * lot_multiplier
            else:
                trade['lots'] = 0.01
                trade['lot_multiplier'] = 1.0
                equity += raw_pnl

            equity_curve.append(equity)
            all_trades.append(trade)

            if verbose:
                _print_trade_detail(trade, len(all_trades))

    # Close remaining open trades
    for trade in state.box_manager.open_trades[:]:
        if len(bars) > 0:
            last_bar = bars[-1]
            if trade['direction'] == 'long':
                pnl = last_bar.close - trade['entry_price']
            else:
                pnl = trade['entry_price'] - last_bar.close
            trade['pnl'] = pnl
            trade['exit_price'] = last_bar.close
            trade['exit_bar'] = last_bar.bar_index
            trade['exit_time'] = last_bar.time
            trade['won'] = pnl > 0
            trade['bars_held'] = last_bar.bar_index - trade['entry_bar']
            trade['exit_reason'] = 'END_OF_DATA'
            trade['actual_rr'] = round(
                abs(pnl) / trade['sl_distance'], 2
            ) if trade['sl_distance'] > 0 else 0

            if auto_scale_lots and get_lot_fn and dd_protection:
                dd_protection.update(equity)
                lots = dd_protection.adjust(get_lot_fn(equity, trade.get('scale', 'H1')))
                trade['lots'] = lots
                trade['lot_multiplier'] = lots / 0.01
                equity += pnl * trade['lot_multiplier']
            else:
                trade['lots'] = 0.01
                trade['lot_multiplier'] = 1.0
                equity += pnl

            equity_curve.append(equity)
            all_trades.append(trade)

    metrics = compute_metrics(all_trades, equity_curve, len(bars), start_equity)
    metrics['diagnostics'] = state.counters
    metrics['state'] = state

    # Per-scale metrics
    h1_trades = [t for t in all_trades if t.get('scale', 'H1') == 'H1']
    m15_trades = [t for t in all_trades if t.get('scale') == 'M15']
    metrics['h1_metrics'] = compute_metrics(h1_trades, [start_equity], len(bars), start_equity)
    metrics['m15_metrics'] = compute_metrics(m15_trades, [start_equity], len(bars), start_equity)

    return metrics


def print_report_v92(metrics: dict, label: str = ""):
    """Print v9.2 backtest report with per-scale breakdown."""
    print(f"\n{'='*60}")
    print(f"  V9.2 BACKTEST REPORT{(' - ' + label) if label else ''}")
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

    # Per-scale breakdown
    for scale_key, scale_label in [('h1_metrics', 'H1'), ('m15_metrics', 'M15')]:
        sm = metrics.get(scale_key, {})
        if sm and sm.get('total_trades', 0) > 0:
            print(f"\n  --- {scale_label} SCALE ---")
            print(f"    Trades:       {sm['total_trades']}")
            print(f"    Win rate:     {sm['win_rate']:.1%}")
            print(f"    R:R:          {sm['rr_ratio']:.2f}")
            print(f"    EV/trade:     ${sm['ev_per_trade']:.2f}")
            print(f"    Trades/day:   {sm['trades_per_day']:.2f}")

    # Exit reason breakdown
    if metrics.get('exit_reasons'):
        print(f"\n  Exit reasons:")
        for reason, count in sorted(metrics['exit_reasons'].items()):
            pct = count / metrics['total_trades'] if metrics['total_trades'] > 0 else 0
            print(f"    {reason}: {count} ({pct:.1%})")

    print(f"{'='*60}")
