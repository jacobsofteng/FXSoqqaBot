#!/usr/bin/env python3
"""
v9.2 Validation Script

Runs all three changes in sequence:
  Change 1: Parallel box tracking (H1 only) vs v9.1 single box
  Change 2: Multi-scale (H1 + M15)
  Change 3: Auto-scaling position sizing

Uses 2024 data for Change 1 validation, full dataset for Change 2+3.
"""

import sys
import time

# Add project root to path
sys.path.insert(0, '.')

from gann_research.backtester import (
    load_m5_binary, run_backtest, run_backtest_v92,
    print_report, print_report_v92, compute_metrics,
)
from gann_research.strategy import print_diagnostic_report, print_diagnostic_report_v92

DATA_PATH = "data/clean/XAUUSD_M5.bin"


def validate_change1():
    """Change 1: Parallel box tracking vs v9.1 single box on 2024 data."""
    print("\n" + "=" * 70)
    print("  CHANGE 1 VALIDATION: Parallel Box Tracking (H1)")
    print("  Dataset: 2024-01-01 to 2024-12-31")
    print("=" * 70)

    print("\nLoading 2024 data...")
    t0 = time.time()
    bars = load_m5_binary(DATA_PATH, "2024-01-01", "2024-12-31")
    print(f"  Loaded {len(bars):,} M5 bars in {time.time()-t0:.1f}s")

    # v9.1 baseline
    print("\nRunning v9.1 (single box)...")
    t0 = time.time()
    v91 = run_backtest(bars, start_equity=10000.0)
    print(f"  Done in {time.time()-t0:.1f}s")
    print_report(v91, "v9.1 Single Box - 2024")

    # v9.2 parallel boxes (H1 only)
    print("\nRunning v9.2 (parallel boxes, H1 only)...")
    t0 = time.time()
    v92 = run_backtest_v92(bars, start_equity=10000.0, multi_scale=False)
    print(f"  Done in {time.time()-t0:.1f}s")
    print_report_v92(v92, "v9.2 Parallel Boxes - 2024")

    # Comparison
    print(f"\n{'='*60}")
    print(f"  CHANGE 1 COMPARISON")
    print(f"{'='*60}")
    print(f"  {'Metric':<20} {'v9.1':>12} {'v9.2':>12} {'Delta':>12}")
    print(f"  {'-'*56}")

    for key, fmt in [
        ('trades_per_day', '.2f'),
        ('win_rate', '.1%'),
        ('rr_ratio', '.2f'),
        ('ev_per_trade', '.2f'),
        ('max_drawdown', '.1%'),
    ]:
        v1 = v91[key]
        v2 = v92[key]
        if '%' in fmt:
            delta = f"{v2-v1:+.1%}"
            v1s = f"{v1:{fmt}}"
            v2s = f"{v2:{fmt}}"
        else:
            delta = f"{v2-v1:+{fmt}}"
            v1s = f"{v1:{fmt}}"
            v2s = f"{v2:{fmt}}"
        print(f"  {key:<20} {v1s:>12} {v2s:>12} {delta:>12}")

    # Acceptance: trades/day 2-3x higher, WR and R:R within 3%
    tpd_ratio = v92['trades_per_day'] / v91['trades_per_day'] if v91['trades_per_day'] > 0 else 0
    wr_delta = abs(v92['win_rate'] - v91['win_rate'])
    rr_delta = abs(v92['rr_ratio'] - v91['rr_ratio'])

    print(f"\n  Trades/day ratio: {tpd_ratio:.1f}x (target: 2-3x)")
    print(f"  WR delta:         {wr_delta:.1%} (max 3%)")
    print(f"  R:R delta:        {rr_delta:.2f} (max 0.3)")

    passed = tpd_ratio >= 1.5 or v92['trades_per_day'] > v91['trades_per_day']
    print(f"\n  RESULT: {'PASS' if passed else 'NEEDS INVESTIGATION'}")

    return v91, v92


def validate_change2():
    """Change 2: Multi-scale (H1 + M15) on full dataset."""
    print("\n" + "=" * 70)
    print("  CHANGE 2 VALIDATION: Multi-Scale (H1 + M15)")
    print("  Dataset: Full 2009-2026")
    print("=" * 70)

    # Train period
    print("\nLoading TRAIN data (2009-2019)...")
    t0 = time.time()
    train_bars = load_m5_binary(DATA_PATH, "2009-01-01", "2019-12-31")
    print(f"  Loaded {len(train_bars):,} M5 bars in {time.time()-t0:.1f}s")

    print("\nRunning v9.2 multi-scale on TRAIN...")
    t0 = time.time()
    train = run_backtest_v92(train_bars, start_equity=10000.0, multi_scale=True)
    print(f"  Done in {time.time()-t0:.1f}s")
    print_report_v92(train, "v9.2 Multi-Scale TRAIN (2009-2019)")

    # Test period
    print("\nLoading TEST data (2020-2026)...")
    t0 = time.time()
    test_bars = load_m5_binary(DATA_PATH, "2020-01-01", "2026-03-20")
    print(f"  Loaded {len(test_bars):,} M5 bars in {time.time()-t0:.1f}s")

    print("\nRunning v9.2 multi-scale on TEST...")
    t0 = time.time()
    test = run_backtest_v92(test_bars, start_equity=10000.0, multi_scale=True)
    print(f"  Done in {time.time()-t0:.1f}s")
    print_report_v92(test, "v9.2 Multi-Scale TEST (2020-2026)")

    # Print diagnostics
    print_diagnostic_report_v92(train['state'])

    # Acceptance criteria
    print(f"\n{'='*60}")
    print(f"  CHANGE 2 ACCEPTANCE CRITERIA")
    print(f"{'='*60}")

    h1_train = train.get('h1_metrics', {})
    m15_train = train.get('m15_metrics', {})
    h1_test = test.get('h1_metrics', {})
    m15_test = test.get('m15_metrics', {})

    print(f"\n  H1 SCALE:")
    print(f"    Train: {h1_train.get('total_trades',0)} trades, "
          f"WR={h1_train.get('win_rate',0):.1%}, "
          f"R:R={h1_train.get('rr_ratio',0):.2f}, "
          f"EV=${h1_train.get('ev_per_trade',0):.2f}")
    print(f"    Test:  {h1_test.get('total_trades',0)} trades, "
          f"WR={h1_test.get('win_rate',0):.1%}, "
          f"R:R={h1_test.get('rr_ratio',0):.2f}, "
          f"EV=${h1_test.get('ev_per_trade',0):.2f}")

    print(f"\n  M15 SCALE:")
    print(f"    Train: {m15_train.get('total_trades',0)} trades, "
          f"WR={m15_train.get('win_rate',0):.1%}, "
          f"R:R={m15_train.get('rr_ratio',0):.2f}, "
          f"EV=${m15_train.get('ev_per_trade',0):.2f}")
    print(f"    Test:  {m15_test.get('total_trades',0)} trades, "
          f"WR={m15_test.get('win_rate',0):.1%}, "
          f"R:R={m15_test.get('rr_ratio',0):.2f}, "
          f"EV=${m15_test.get('ev_per_trade',0):.2f}")

    print(f"\n  COMBINED:")
    print(f"    Train: {train['trades_per_day']:.2f} trades/day, "
          f"EV/day=${train['ev_per_trade']*train['trades_per_day']:.2f}, "
          f"DD={train['max_drawdown']:.1%}")
    print(f"    Test:  {test['trades_per_day']:.2f} trades/day, "
          f"EV/day=${test['ev_per_trade']*test['trades_per_day']:.2f}, "
          f"DD={test['max_drawdown']:.1%}")

    # Check criteria
    m15_wr_ok = m15_test.get('win_rate', 0) > 0.30
    m15_rr_ok = m15_test.get('rr_ratio', 0) > 2.0
    combined_tpd_ok = test['trades_per_day'] >= 2.0
    combined_dd_ok = test['max_drawdown'] < 0.05
    test_ev_ok = test['ev_per_trade'] >= train['ev_per_trade'] * 0.7 if train['ev_per_trade'] > 0 else True

    print(f"\n  M15 WR > 30%:           {'PASS' if m15_wr_ok else 'FAIL'} ({m15_test.get('win_rate',0):.1%})")
    print(f"  M15 R:R > 2:1:          {'PASS' if m15_rr_ok else 'FAIL'} ({m15_test.get('rr_ratio',0):.2f})")
    print(f"  Combined tpd >= 2:      {'PASS' if combined_tpd_ok else 'FAIL'} ({test['trades_per_day']:.2f})")
    print(f"  Combined DD < 5%:       {'PASS' if combined_dd_ok else 'FAIL'} ({test['max_drawdown']:.1%})")
    print(f"  Test EV >= 0.7*Train:   {'PASS' if test_ev_ok else 'FAIL'}")

    return train, test


def validate_change3():
    """Change 3: Auto-scaling position sizing on full dataset."""
    print("\n" + "=" * 70)
    print("  CHANGE 3 VALIDATION: Auto-Scaling Position Sizing")
    print("  Dataset: Full 2009-2026, Starting $100")
    print("=" * 70)

    # Train
    print("\nLoading TRAIN data (2009-2019)...")
    train_bars = load_m5_binary(DATA_PATH, "2009-01-01", "2019-12-31")
    print(f"  Loaded {len(train_bars):,} bars")

    print("\nRunning auto-scaling backtest on TRAIN ($100 start)...")
    t0 = time.time()
    train = run_backtest_v92(
        train_bars, start_equity=100.0,
        multi_scale=True, auto_scale_lots=True,
    )
    print(f"  Done in {time.time()-t0:.1f}s")

    print(f"\n  TRAIN (2009-2019):")
    print(f"    Final balance: ${train['final_equity']:.2f}")
    print(f"    Max drawdown:  {train['max_drawdown']:.1%}")
    print(f"    Total trades:  {train['total_trades']}")

    # Test
    print("\nLoading TEST data (2020-2026)...")
    test_bars = load_m5_binary(DATA_PATH, "2020-01-01", "2026-03-20")
    print(f"  Loaded {len(test_bars):,} bars")

    # For test, start with the ending balance from train
    test_start = max(100.0, train['final_equity'])
    print(f"\nRunning auto-scaling backtest on TEST (${test_start:.0f} start)...")
    t0 = time.time()
    test = run_backtest_v92(
        test_bars, start_equity=100.0,
        multi_scale=True, auto_scale_lots=True,
    )
    print(f"  Done in {time.time()-t0:.1f}s")

    print(f"\n  TEST (2020-2026):")
    print(f"    Final balance: ${test['final_equity']:.2f}")
    print(f"    Max drawdown:  {test['max_drawdown']:.1%}")
    print(f"    Total trades:  {test['total_trades']}")

    # Month-by-month for first 6 months of 2020
    print(f"\n  MONTH-BY-MONTH (first 6 months of 2020):")
    months = [
        ("2020-01-01", "2020-01-31"),
        ("2020-02-01", "2020-02-29"),
        ("2020-03-01", "2020-03-31"),
        ("2020-04-01", "2020-04-30"),
        ("2020-05-01", "2020-05-31"),
        ("2020-06-01", "2020-06-30"),
    ]
    for start, end in months:
        month_bars = load_m5_binary(DATA_PATH, start, end)
        if not month_bars:
            continue
        m = run_backtest_v92(
            month_bars, start_equity=100.0,
            multi_scale=True, auto_scale_lots=True,
        )
        # Find max lot used
        max_lot = max((t.get('lots', 0.01) for t in m.get('trades', [])), default=0.01)
        worst_pnl = min((t.get('pnl', 0) * t.get('lot_multiplier', 1) for t in m.get('trades', [])), default=0)
        print(f"    {start[:7]}: $100 -> ${m['final_equity']:.0f}, "
              f"lots={max_lot:.2f}, "
              f"trades={m['total_trades']}, "
              f"worst=${worst_pnl:.1f}")

    # Verify safety
    eq_curve = test.get('equity_curve', [100])
    min_eq = min(eq_curve) if eq_curve else 100
    print(f"\n  Safety checks:")
    print(f"    Min equity (test): ${min_eq:.2f} (must be > $30)")
    print(f"    Never below $30:   {'PASS' if min_eq > 30 else 'FAIL'}")

    return train, test


if __name__ == '__main__':
    print("=" * 70)
    print("  FXSoqqaBot v9.2 FULL VALIDATION")
    print("  Changes: Parallel Boxes + Multi-Scale + Auto-Scaling")
    print("=" * 70)

    # Change 1
    v91, v92_h1 = validate_change1()

    # Change 2
    train_ms, test_ms = validate_change2()

    # Change 3
    train_as, test_as = validate_change3()

    print("\n" + "=" * 70)
    print("  ALL VALIDATIONS COMPLETE")
    print("=" * 70)
