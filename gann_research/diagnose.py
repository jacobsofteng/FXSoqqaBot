#!/usr/bin/env python3
"""
Diagnostic Runner — Find where the trade funnel drops to zero.

Usage:
    python -m gann_research.diagnose [--period 2024H1] [--verbose]

Runs strategy on specified data period with full diagnostic counters.
"""

import sys
import time
import argparse

from .backtester import load_m5_binary, run_backtest, print_report
from .strategy import print_diagnostic_report


DATA_FILE = "data/clean/XAUUSD_M5.bin"

PERIODS = {
    '2024H1': ('2024-01-01', '2024-07-01'),
    '2024H2': ('2024-07-01', '2025-01-01'),
    '2024':   ('2024-01-01', '2025-01-01'),
    '2023':   ('2023-01-01', '2024-01-01'),
    'train':  ('2009-01-01', '2020-01-01'),
    'test':   ('2020-01-01', '2026-04-01'),
    'full':   (None, None),
}


def main():
    parser = argparse.ArgumentParser(description="Diagnostic funnel runner")
    parser.add_argument("--period", default="2024H1",
                        choices=list(PERIODS.keys()),
                        help="Data period to test")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print individual trade details")
    args = parser.parse_args()

    start_date, end_date = PERIODS[args.period]

    print(f"\n{'='*70}")
    print(f"  DIAGNOSTIC RUN: {args.period}")
    print(f"  Period: {start_date or 'start'} to {end_date or 'end'}")
    print(f"{'='*70}")

    print(f"\nLoading M5 data...")
    t0 = time.time()
    bars = load_m5_binary(DATA_FILE, start_date, end_date)
    print(f"  Loaded {len(bars):,} M5 bars in {time.time()-t0:.1f}s")

    if not bars:
        print("ERROR: No bars loaded. Check data file path.")
        return

    print(f"  Date range: {bars[0].time} to {bars[-1].time}")
    print(f"  Trading days: {len(bars)/288:.0f}")

    print(f"\nRunning backtest...")
    t0 = time.time()
    metrics = run_backtest(bars, start_equity=10000.0, verbose=args.verbose)
    elapsed = time.time() - t0
    print(f"  Completed in {elapsed:.1f}s")

    # Print backtest results
    print_report(metrics, label=args.period)

    # Print diagnostic funnel
    if metrics.get('state'):
        print_diagnostic_report(metrics['state'])

    # Print trade detail summary if we have trades
    trades = metrics.get('trades', [])
    if trades and len(trades) <= 50:
        print(f"\n{'='*70}")
        print(f"  ALL TRADES ({len(trades)} total)")
        print(f"{'='*70}")
        for i, t in enumerate(trades):
            dr = t.get('designed_rr', t.get('rr_ratio', 0))
            ar = t.get('actual_rr', 0)
            print(f"  #{i+1}: {t['direction']:5s} "
                  f"entry=${t['entry_price']:.2f} "
                  f"SL=${t['sl']:.2f} TP=${t['tp']:.2f} "
                  f"exit=${t.get('exit_price',0):.2f} "
                  f"P&L=${t.get('pnl',0):+.2f} "
                  f"R:R={dr:.1f}→{ar:.1f} "
                  f"reason={t.get('exit_reason','?')} "
                  f"held={t.get('bars_held',0)}bars")
    elif trades:
        # Too many trades, show summary
        print(f"\n  {len(trades)} trades total (showing first 20 + last 10):")
        for i in range(min(20, len(trades))):
            t = trades[i]
            dr = t.get('designed_rr', t.get('rr_ratio', 0))
            ar = t.get('actual_rr', 0)
            print(f"  #{i+1}: {t['direction']:5s} "
                  f"entry=${t['entry_price']:.2f} "
                  f"exit=${t.get('exit_price',0):.2f} "
                  f"P&L=${t.get('pnl',0):+.2f} "
                  f"R:R={dr:.1f}→{ar:.1f} "
                  f"reason={t.get('exit_reason','?')}")
        print(f"  ... ({len(trades)-30} more trades) ...")
        for i in range(max(20, len(trades)-10), len(trades)):
            t = trades[i]
            dr = t.get('designed_rr', t.get('rr_ratio', 0))
            ar = t.get('actual_rr', 0)
            print(f"  #{i+1}: {t['direction']:5s} "
                  f"entry=${t['entry_price']:.2f} "
                  f"exit=${t.get('exit_price',0):.2f} "
                  f"P&L=${t.get('pnl',0):+.2f} "
                  f"R:R={dr:.1f}→{ar:.1f} "
                  f"reason={t.get('exit_reason','?')}")


if __name__ == "__main__":
    main()
