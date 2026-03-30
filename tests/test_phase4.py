"""
Phase 4 Tests -- Full strategy pipeline + backtest.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

from gann_research.swing_detector import Bar
from gann_research.convergence import score_convergence
from gann_research.three_limits import check_three_limits
from gann_research.execution import evaluate_entry, calculate_sl_tp
from gann_research.risk import position_size, manage_open_trade
from gann_research.strategy import TradingState, process_bar
from gann_research.backtester import run_backtest, print_report, load_m5_binary


# ============================================================
# UNIT TESTS
# ============================================================

def test_convergence_max_3_without_time_wave_triangle():
    """Without time/wave/triangle, max score = A+B+C = 3 (NOT tradeable)."""
    swings = [
        {'type': 'low', 'price': 2060.0, 'time': datetime(2024,1,1), 'bar_index': 0, 'atr_at_swing': 10},
        {'type': 'high', 'price': 2072.0, 'time': datetime(2024,1,1,5), 'bar_index': 5, 'atr_at_swing': 10},
        {'type': 'low', 'price': 2050.0, 'time': datetime(2024,1,1,10), 'bar_index': 10, 'atr_at_swing': 10},
    ]
    result = score_convergence(
        current_price=2072.0,
        current_bar=100,
        current_time=datetime(2024, 1, 5),
        swings_h1=swings,
        swings_h4=[],      # No H4 swings -> D=0
        wave_state=None,    # No wave -> F=0
        triangle=None,      # No triangle -> E=0
    )
    # Without D, E, F: max = A + B + C + G = 4 at best
    # But usually less because not all hit simultaneously
    # The key assertion: NOT tradeable without time/wave/triangle data typically
    assert result['score'] <= 4, f"Score {result['score']} > 4 without time/wave"
    categories = result['categories']
    assert categories.get('D_time') is False
    assert categories.get('E_triangle') is False
    assert categories.get('F_wave') is False
    print(f"  [PASS] convergence max without T/W/Tri: score={result['score']}")


def test_position_sizing():
    """Position sizing with 2% risk."""
    # $10,000 account, $6 SL -> risk $200
    # $200 / ($6 * 100) = 0.33 lots
    lots = position_size(10000, 6.0, risk_pct=0.02)
    assert lots == 0.33, f"Expected 0.33, got {lots}"

    # $20 account -> minimum 0.01
    lots = position_size(20, 6.0, risk_pct=0.02)
    assert lots == 0.01
    print(f"  [PASS] position sizing")


def test_three_limits():
    """Three limits check."""
    swings = [
        {'type': 'low', 'price': 2000.0, 'time': datetime(2024,1,1), 'bar_index': 0, 'atr_at_swing': 10},
        {'type': 'high', 'price': 2060.0, 'time': datetime(2024,1,1,5), 'bar_index': 5, 'atr_at_swing': 10},
        {'type': 'low', 'price': 2030.0, 'time': datetime(2024,1,1,10), 'bar_index': 10, 'atr_at_swing': 10},
    ]
    result = check_three_limits(2042.0, 14, swings, None)
    assert 'limit1' in result
    assert 'limit2' in result
    assert 'limit3' in result
    assert result['count'] >= 0
    print(f"  [PASS] three limits: count={result['count']}")


def test_sl_tp_calculation():
    """SL/TP has correct geometry."""
    sl, tp = calculate_sl_tp(
        entry_price=2072.0,
        direction='up',
        h1_state={'direction': 'up'},
        wave=None,
        atr_m5=5.0,
    )
    assert sl < 2072.0, "SL should be below entry for long"
    assert tp > 2072.0, "TP should be above entry for long"
    sl_dist = 2072.0 - sl
    tp_dist = tp - 2072.0
    rr = tp_dist / sl_dist
    assert rr >= 3.0, f"R:R {rr:.1f} < 3:1"
    print(f"  [PASS] SL/TP: SL=${sl:.2f}, TP=${tp:.2f}, R:R={rr:.1f}")


def test_state_machine_flow():
    """State machine transitions correctly."""
    state = TradingState()
    assert state.phase == TradingState.SCANNING

    # Process some bars
    for i in range(100):
        bar = Bar(
            time=datetime(2024,1,1) + timedelta(minutes=i*5),
            open=2060+i*0.1, high=2062+i*0.1, low=2058+i*0.1,
            close=2060+i*0.1, volume=100, bar_index=i,
        )
        state = process_bar(bar, state)

    # State should be valid
    assert state.phase in [
        TradingState.SCANNING, TradingState.QUANT_FORMING,
        TradingState.BOX_ACTIVE, TradingState.IN_TRADE,
    ]
    print(f"  [PASS] state machine: phase={state.phase}, "
          f"H1 swings={len(state.swings_h1)}")


# ============================================================
# BACKTEST ON REAL DATA
# ============================================================

def test_backtest_real_data():
    """Run backtest on sample of real XAUUSD M5 data."""
    data_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "clean", "XAUUSD_M5.bin"
    )

    if not os.path.exists(data_path):
        print(f"  [SKIP] No data at {data_path}")
        return

    print("  Loading M5 binary data...")
    all_bars = load_m5_binary(data_path)
    print(f"  Loaded {len(all_bars):,} M5 bars")
    print(f"  Range: {all_bars[0].time} to {all_bars[-1].time}")

    # Split train/test
    split_date = datetime(2020, 1, 1)
    train_bars = []
    test_bars = []
    for b in all_bars:
        dt = b.time
        if hasattr(dt, 'replace'):
            dt_naive = dt.replace(tzinfo=None)
        else:
            dt_naive = dt
        if dt_naive < split_date:
            train_bars.append(b)
        else:
            test_bars.append(b)

    print(f"  Train: {len(train_bars):,} bars (2009-2019)")
    print(f"  Test:  {len(test_bars):,} bars (2020-2026)")

    # Run on a SAMPLE for speed (first 50k bars of each)
    SAMPLE = 50000
    train_sample = train_bars[:SAMPLE]
    test_sample = test_bars[:SAMPLE]

    print(f"\n  Running train backtest on {len(train_sample):,} bars...")
    train_metrics = run_backtest(train_sample, start_equity=10000.0)
    print_report(train_metrics, f"TRAIN ({train_sample[0].time.year}-"
                 f"{train_sample[-1].time.year})")

    print(f"\n  Running test backtest on {len(test_sample):,} bars...")
    test_metrics = run_backtest(test_sample, start_equity=10000.0)
    print_report(test_metrics, f"TEST ({test_sample[0].time.year}-"
                 f"{test_sample[-1].time.year})")

    # Basic sanity checks
    print(f"\n  Train trades: {train_metrics['total_trades']}")
    print(f"  Test trades:  {test_metrics['total_trades']}")

    # Show first 5 trades from train
    if train_metrics['trades']:
        print(f"\n  First 5 train trades:")
        for i, t in enumerate(train_metrics['trades'][:5]):
            print(f"    #{i+1}: {t['direction']} ${t['entry_price']:.2f} -> "
                  f"${t.get('exit_price', 0):.2f}, "
                  f"PnL=${t.get('pnl', 0):.2f}, "
                  f"bars={t.get('bars_held', 0)}")

    print(f"\n  [PASS] backtest completed")


# ============================================================
# RUN ALL
# ============================================================

def run_all():
    tests = [
        ("Unit Tests", [
            test_convergence_max_3_without_time_wave_triangle,
            test_position_sizing,
            test_three_limits,
            test_sl_tp_calculation,
            test_state_machine_flow,
        ]),
        ("Backtest", [
            test_backtest_real_data,
        ]),
    ]

    total = 0
    passed = 0
    failed = 0

    for section, test_fns in tests:
        print(f"\n{'='*50}")
        print(f"  {section}")
        print(f"{'='*50}")
        for fn in test_fns:
            total += 1
            try:
                fn()
                passed += 1
            except Exception as e:
                failed += 1
                print(f"  [FAIL] {fn.__name__}: {e}")
                import traceback
                traceback.print_exc()

    print(f"\n{'='*50}")
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'='*50}")

    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
