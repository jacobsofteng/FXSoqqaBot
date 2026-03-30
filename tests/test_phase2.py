"""
Phase 2 Tests — Detection Systems

Tests swing detection and wave counting on real XAUUSD data.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

from gann_research.swing_detector import (
    detect_swings_atr, detect_swings_df, bars_from_dataframe, Bar,
)
from gann_research.wave_counter import count_waves, unit_vibration_check


# ============================================================
# UNIT TESTS (synthetic data)
# ============================================================

def make_bars(prices: list[tuple], start_time=None) -> list[Bar]:
    """Create bars from (high, low, close) tuples for testing."""
    if start_time is None:
        start_time = datetime(2024, 1, 1)
    bars = []
    for i, (h, l, c) in enumerate(prices):
        bars.append(Bar(
            time=start_time + timedelta(hours=i),
            open=c,
            high=h,
            low=l,
            close=c,
            volume=100,
            bar_index=i,
        ))
    return bars


def test_swing_detection_basic():
    """Detect clear up-down-up pattern."""
    # Clear zigzag: 100→120→105→125
    prices = []
    # Rise from 100 to 120 over 10 bars
    for i in range(10):
        p = 100 + i * 2
        prices.append((p + 1, p - 1, p))
    # Drop from 120 to 105 over 10 bars
    for i in range(10):
        p = 120 - i * 1.5
        prices.append((p + 1, p - 1, p))
    # Rise from 105 to 125 over 10 bars
    for i in range(10):
        p = 105 + i * 2
        prices.append((p + 1, p - 1, p))

    bars = make_bars(prices)
    swings = detect_swings_atr(bars, atr_period=5, atr_multiplier=1.0)

    assert len(swings) >= 2, f"Expected >=2 swings, got {len(swings)}"
    # Should have at least one high and one low
    types = [s['type'] for s in swings]
    assert 'high' in types, "No swing high detected"
    assert 'low' in types, "No swing low detected"
    print(f"  [PASS] basic swing detection: {len(swings)} swings found")


def test_swing_alternation():
    """Swings should alternate high/low."""
    # Bigger zigzag
    prices = []
    for cycle in range(5):
        for i in range(15):
            p = 2000 + cycle * 5 + i * 3
            prices.append((p + 2, p - 2, p))
        for i in range(15):
            p = 2045 + cycle * 5 - i * 3
            prices.append((p + 2, p - 2, p))

    bars = make_bars(prices)
    swings = detect_swings_atr(bars, atr_period=10, atr_multiplier=1.0)

    for i in range(1, len(swings)):
        assert swings[i]['type'] != swings[i - 1]['type'], \
            f"Swings {i-1} and {i} are both {swings[i]['type']}"
    print(f"  [PASS] swing alternation: {len(swings)} swings all alternate")


def test_wave_counter_basic():
    """Wave counter on synthetic swings."""
    swings = [
        {'type': 'low',  'price': 2000, 'time': datetime(2024, 1, 1), 'bar_index': 0, 'atr_at_swing': 10},
        {'type': 'high', 'price': 2050, 'time': datetime(2024, 1, 2), 'bar_index': 24, 'atr_at_swing': 10},
        {'type': 'low',  'price': 2030, 'time': datetime(2024, 1, 3), 'bar_index': 48, 'atr_at_swing': 10},
        {'type': 'high', 'price': 2080, 'time': datetime(2024, 1, 4), 'bar_index': 72, 'atr_at_swing': 10},
        {'type': 'low',  'price': 2060, 'time': datetime(2024, 1, 5), 'bar_index': 96, 'atr_at_swing': 10},
        {'type': 'high', 'price': 2110, 'time': datetime(2024, 1, 6), 'bar_index': 120, 'atr_at_swing': 10},
    ]

    result = count_waves(swings, 'H1')
    assert result is not None
    assert result['wave_0_size'] > 0
    assert result['direction'] in ('up', 'down')
    assert len(result['targets']) > 0
    assert isinstance(result['is_trending'], bool)
    print(f"  [PASS] wave counter: wave {result['wave_number']}, "
          f"dir={result['direction']}, W0=${result['wave_0_size']:.0f}")


def test_wave_counter_insufficient_data():
    """Wave counter returns None with < 4 swings."""
    swings = [
        {'type': 'low', 'price': 2000, 'time': datetime(2024, 1, 1), 'bar_index': 0, 'atr_at_swing': 10},
        {'type': 'high', 'price': 2050, 'time': datetime(2024, 1, 2), 'bar_index': 24, 'atr_at_swing': 10},
    ]
    result = count_waves(swings, 'H1')
    assert result is None
    print("  [PASS] wave counter returns None with < 4 swings")


def test_unit_vibration():
    """Temporal symmetry check."""
    a = {'time': datetime(2024, 1, 1, 0), 'price': 2000}
    b = {'time': datetime(2024, 1, 1, 10), 'price': 2050}
    c = {'time': datetime(2024, 1, 1, 20), 'price': 2020}
    assert unit_vibration_check(a, b, c) is True  # 10h == 10h

    # Break symmetry
    c2 = {'time': datetime(2024, 1, 2, 10), 'price': 2020}  # 24h vs 10h
    assert unit_vibration_check(a, b, c2) is False
    print("  [PASS] unit vibration temporal symmetry")


# ============================================================
# REAL DATA TEST
# ============================================================

def test_real_data():
    """Load actual XAUUSD data, detect swings on H1, show 10 swings + wave counts."""
    try:
        import pandas as pd
    except ImportError:
        print("  [SKIP] pandas not available")
        return

    # Try loading parquet data
    data_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "clean", "XAUUSD_M1_clean.parquet"
    )

    if not os.path.exists(data_path):
        print(f"  [SKIP] No data at {data_path}")
        return

    print(f"  Loading parquet data...")
    df_m1 = pd.read_parquet(data_path)
    print(f"  Loaded {len(df_m1):,} M1 bars")

    # Ensure datetime index
    if not isinstance(df_m1.index, pd.DatetimeIndex):
        if 'time' in df_m1.columns:
            df_m1.set_index('time', inplace=True)

    # Take a sample period: Jan-Mar 2024
    sample = df_m1['2024-01':'2024-03']
    if len(sample) == 0:
        # Try earlier period
        sample = df_m1['2023-01':'2023-03']
    if len(sample) == 0:
        sample = df_m1.iloc[-100000:]  # Last 100k bars

    print(f"  Sample: {len(sample):,} M1 bars, {sample.index[0]} to {sample.index[-1]}")

    # Resample to H1
    h1 = sample.resample('1h').agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum',
    }).dropna(subset=['open'])
    print(f"  H1 bars: {len(h1):,}")

    # Detect swings on H1
    swings = detect_swings_df(h1, atr_period=14, atr_multiplier=1.5)
    print(f"  H1 swings detected: {len(swings)}")

    # Show 10 swings
    print(f"\n  {'='*70}")
    print(f"  10 DETECTED H1 SWINGS:")
    print(f"  {'='*70}")
    print(f"  {'#':>3} {'Type':>5} {'Price':>10} {'Time':>22} {'ATR':>8}")
    print(f"  {'-'*70}")
    for i, s in enumerate(swings[:10]):
        print(f"  {i+1:3d} {s['type']:>5} {s['price']:10.2f} {str(s['time']):>22} {s['atr_at_swing']:8.2f}")

    assert len(swings) >= 10, f"Expected >=10 swings, got {len(swings)}"

    # Wave counting on H1
    wave_state = count_waves(swings, 'H1')
    if wave_state:
        print(f"\n  {'='*70}")
        print(f"  WAVE COUNT RESULTS:")
        print(f"  {'='*70}")
        print(f"  Wave number: {wave_state['wave_number']}")
        print(f"  Direction:   {wave_state['direction']}")
        print(f"  Wave 0 price: ${wave_state['wave_0_price']:.2f}")
        print(f"  Wave 0 size:  ${wave_state['wave_0_size']:.2f}")
        print(f"  Trending:     {wave_state['is_trending']}")
        print(f"  Correcting:   {wave_state['is_correcting']}")
        print(f"  Targets:      {[f'${t:.2f}' for t in wave_state['targets'][:5]]}")
        print(f"  Legend swings: {len(wave_state['legend_swings'])}")
        print(f"  Scenario swings: {len(wave_state['scenario_swings'])}")
    else:
        print("  Wave count: None (insufficient data)")

    # Also do H4 swings
    h4 = sample.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum',
    }).dropna(subset=['open'])
    swings_h4 = detect_swings_df(h4, atr_period=14, atr_multiplier=1.5)
    print(f"\n  H4 swings detected: {len(swings_h4)}")

    # D1 swings
    d1 = sample.resample('1D').agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum',
    }).dropna(subset=['open'])
    swings_d1 = detect_swings_df(d1, atr_period=14, atr_multiplier=1.5)
    print(f"  D1 swings detected: {len(swings_d1)}")

    print(f"\n  [PASS] real data swing detection and wave counting")


# ============================================================
# RUN ALL TESTS
# ============================================================

def run_all():
    tests = [
        ("Unit Tests", [
            test_swing_detection_basic,
            test_swing_alternation,
            test_wave_counter_basic,
            test_wave_counter_insufficient_data,
            test_unit_vibration,
        ]),
        ("Real Data", [
            test_real_data,
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
