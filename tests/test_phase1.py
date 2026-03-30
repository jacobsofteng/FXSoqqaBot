"""
Phase 1 Unit Tests — Core Math Library

Tests from Section 19 of GANN_STRATEGY_V9_SPEC.md plus additional coverage.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
from datetime import datetime, timedelta

from gann_research.constants import (
    BASE_VIBRATION, SWING_QUANTUM, GROWTH_QUANTUM, CORRECTION_QUANTUM,
    LOST_MOTION, POWER_ANGLES, NATURAL_SQUARES, NATURAL_SQ,
    VIBRATION_OVERRIDE_MULTIPLIER, MAX_HOLD_BARS, MAX_DAILY_TRADES,
)
from gann_research.sq9_engine import (
    price_to_sq9_degree, reduce_gold_price, sq9_levels_from_price,
    even_odd_rays,
)
from gann_research.vibration import (
    vibration_levels, vibration_swing_levels, check_vibration_override,
)
from gann_research.proportional import proportional_levels, check_fold
from gann_research.time_structure import (
    is_time_window_active, intraday_reversal_window, forex_time_adjustment,
)


# ============================================================
# 1. CONSTANTS TESTS
# ============================================================

def test_constants_values():
    """All Gold constants have correct values."""
    assert BASE_VIBRATION == 72
    assert SWING_QUANTUM == 12
    assert GROWTH_QUANTUM == 18
    assert CORRECTION_QUANTUM == 24
    assert LOST_MOTION == 3.0
    assert POWER_ANGLES == [30, 45]
    assert NATURAL_SQ == [4, 9, 16, 24, 36, 49, 72, 81]
    assert MAX_HOLD_BARS == 288
    assert MAX_DAILY_TRADES == 5
    assert VIBRATION_OVERRIDE_MULTIPLIER == 4
    print("  [PASS] constants values")


def test_vibration_relationships():
    """Vibration quanta are correct fractions of base."""
    assert SWING_QUANTUM == BASE_VIBRATION // 6    # V/6 = 12
    assert GROWTH_QUANTUM == BASE_VIBRATION // 4   # V/4 = 18
    assert CORRECTION_QUANTUM == BASE_VIBRATION // 3  # V/3 = 24
    print("  [PASS] vibration relationships")


# ============================================================
# 2. SQ9 ENGINE TESTS (Section 19 of spec)
# ============================================================

def test_sq9_even_squares_at_135():
    """Even perfect squares (4, 16, 36, 64, 100, 144) ALL map to 135°."""
    even_squares = [4, 16, 36, 64, 100, 144]
    for sq in even_squares:
        deg = price_to_sq9_degree(sq)
        assert abs(deg - 135.0) < 0.1, f"sq={sq}, got degree={deg}, expected 135"
    print("  [PASS] even squares -> 135 deg")


def test_sq9_odd_squares_at_315():
    """Odd perfect squares (1, 9, 25, 49, 81, 121) ALL map to 315°."""
    odd_squares = [1, 9, 25, 49, 81, 121]
    for sq in odd_squares:
        deg = price_to_sq9_degree(sq)
        assert abs(deg - 315.0) < 0.1, f"sq={sq}, got degree={deg}, expected 315"
    print("  [PASS] odd squares -> 315 deg")


def test_sq9_180_apart():
    """Even ray (135°) and odd ray (315°) are 180° apart."""
    assert abs(315 - 135) == 180
    print("  [PASS] 135° and 315° are 180° apart")


def test_sq9_edge_cases():
    """Edge cases: 0 and negative."""
    assert price_to_sq9_degree(0) == 0.0
    assert price_to_sq9_degree(-5) == 0.0
    print("  [PASS] sq9 edge cases")


def test_reduce_gold_price():
    """Gold price reduction to working numbers."""
    r = reduce_gold_price(2072)
    assert 2072 in r
    assert 72 in r  # last 3 digits

    r = reduce_gold_price(1667)
    assert 1667 in r
    assert 667 in r

    r = reduce_gold_price(3150)
    assert 3150 in r
    assert 150 in r
    assert 50 in r  # last 2 digits

    r = reduce_gold_price(923)
    assert 923 in r
    assert 23 in r

    print("  [PASS] reduce_gold_price")


def test_even_odd_rays():
    """even_odd_rays function returns correct degrees."""
    assert even_odd_rays(2) == 135.0
    assert even_odd_rays(4) == 135.0
    assert even_odd_rays(6) == 135.0
    assert even_odd_rays(1) == 315.0
    assert even_odd_rays(3) == 315.0
    assert even_odd_rays(5) == 315.0
    print("  [PASS] even_odd_rays()")


def test_sq9_levels_from_price():
    """sq9_levels_from_price generates levels near reference price."""
    levels = sq9_levels_from_price(2072.0, [30, 45])
    assert len(levels) > 0
    # All levels should be within 15% of reference
    for level in levels:
        assert abs(level - 2072.0) <= 2072.0 * 0.15 + 1
    print(f"  [PASS] sq9_levels_from_price: {len(levels)} levels from 2072")


# ============================================================
# 3. VIBRATION TESTS (Section 19 of spec)
# ============================================================

def test_vibration_swing_levels_from_2072():
    """$12 quantum from swing at $2072."""
    levels = vibration_swing_levels(2072.0, count=5)
    assert 2060.0 in levels, f"2060 not in {levels}"   # 2072 - 12
    assert 2084.0 in levels, f"2084 not in {levels}"   # 2072 + 12
    assert 2048.0 in levels, f"2048 not in {levels}"   # 2072 - 24
    assert 2096.0 in levels, f"2096 not in {levels}"   # 2072 + 24
    print("  [PASS] swing levels $12 quantum from $2072")


def test_vibration_growth_levels():
    """Growth quantum ($18) from $2072."""
    levels = vibration_levels(2072.0, 'growth', count=3)
    assert 2054.0 in levels, f"2054 not in {levels}"   # 2072 - 18
    assert 2090.0 in levels, f"2090 not in {levels}"   # 2072 + 18
    print("  [PASS] growth levels $18 quantum from $2072")


def test_vibration_correction_levels():
    """Correction quantum ($24) from $2072."""
    levels = vibration_levels(2072.0, 'correction', count=3)
    assert 2048.0 in levels  # 2072 - 24
    assert 2096.0 in levels  # 2072 + 24
    print("  [PASS] correction levels $24 quantum from $2072")


def test_vibration_override_288():
    """4x override at $288."""
    assert check_vibration_override(290) is True   # > 288
    assert check_vibration_override(288) is True   # == 288
    assert check_vibration_override(200) is False  # < 288
    assert check_vibration_override(-290) is True  # abs > 288
    print("  [PASS] 4x vibration override at $288")


def test_vibration_level_count():
    """Vibration levels generates correct count."""
    levels = vibration_swing_levels(2000.0, count=5)
    assert len(levels) == 10  # 5 above + 5 below (no 0)
    print("  [PASS] vibration level count")


# ============================================================
# 4. PROPORTIONAL DIVISION TESTS
# ============================================================

def test_proportional_levels_2000_2100():
    """1/3, 1/2, 2/3 of a $2000–$2100 range."""
    levels = proportional_levels(2100.0, 2000.0)

    assert abs(levels['1/3'] - 2033.33) < 0.01, f"1/3 = {levels['1/3']}"
    assert abs(levels['1/2'] - 2050.0) < 0.01, f"1/2 = {levels['1/2']}"
    assert abs(levels['2/3'] - 2066.67) < 0.01, f"2/3 = {levels['2/3']}"
    print("  [PASS] proportional levels $2000–$2100")


def test_proportional_secondary_levels():
    """Secondary proportional levels."""
    levels = proportional_levels(2100.0, 2000.0)

    assert abs(levels['1/4'] - 2025.0) < 0.01
    assert abs(levels['3/4'] - 2075.0) < 0.01
    assert abs(levels['7/8'] - 2087.5) < 0.01
    assert abs(levels['1/8'] - 2012.5) < 0.01
    print("  [PASS] secondary proportional levels")


def test_proportional_all_keys():
    """All expected fraction keys present."""
    levels = proportional_levels(2100.0, 2000.0)
    expected = {'1/3', '1/2', '2/3', '1/4', '3/4', '3/8', '5/8', '7/8', '1/8'}
    assert set(levels.keys()) == expected
    print("  [PASS] all proportional keys present")


def test_check_fold():
    """Fold detection at 1/3 of movement."""
    # Swing from 2000 to target 2090, 1/3 = 2030
    result = check_fold(2030.0, 2000.0, 2090.0)
    assert result['fold_detected'] is True
    assert abs(result['adjusted_tp_best'] - 2045.0) < 0.01  # 1/2 of move
    assert abs(result['adjusted_tp_worst'] - 2022.5) < 0.01  # 1/4 of move
    assert result['miss_probability'] == 0.80
    print("  [PASS] fold detection at 1/3")


def test_no_fold():
    """No fold when price is far from 1/3."""
    result = check_fold(2050.0, 2000.0, 2090.0)
    assert result['fold_detected'] is False
    print("  [PASS] no fold when not at 1/3")


def test_fold_within_lost_motion():
    """Fold detects within lost motion tolerance."""
    # 1/3 of 2000→2090 is 2030. Price at 2032 is within $3 lost motion.
    result = check_fold(2032.0, 2000.0, 2090.0)
    assert result['fold_detected'] is True
    print("  [PASS] fold within lost motion")


# ============================================================
# 5. TIME STRUCTURE TESTS
# ============================================================

def test_natural_square_matching_9():
    """Natural square matching for 9 H4 bars (strongest: 28%)."""
    t0 = datetime(2024, 1, 1)
    result = is_time_window_active(
        last_swing_time=t0,
        last_swing_bars_h4=0,
        current_time=t0 + timedelta(hours=36),  # 9 H4 bars
        current_bar_h4=9,
    )
    assert result['active'] is True
    assert result['matching_square'] == 9
    assert abs(result['window_strength'] - 0.28) < 0.01
    print("  [PASS] natural square 9 H4 bars")


def test_natural_square_tolerance():
    """Window active within ±1 bar tolerance."""
    t0 = datetime(2024, 1, 1)
    # 8 bars = 9 - 1, should match 9
    result = is_time_window_active(t0, 0, t0 + timedelta(hours=32), 8)
    assert result['active'] is True
    assert result['matching_square'] == 9

    # 10 bars = 9 + 1, should match 9
    result = is_time_window_active(t0, 0, t0 + timedelta(hours=40), 10)
    assert result['active'] is True
    assert result['matching_square'] == 9
    print("  [PASS] natural square ±1 tolerance")


def test_natural_square_4():
    """4 H4 bars (16 hours)."""
    t0 = datetime(2024, 1, 1)
    result = is_time_window_active(t0, 0, t0, 4)
    assert result['active'] is True
    assert result['matching_square'] == 4
    print("  [PASS] natural square 4 H4 bars")


def test_natural_square_16():
    """16 H4 bars."""
    t0 = datetime(2024, 1, 1)
    result = is_time_window_active(t0, 0, t0, 16)
    assert result['active'] is True
    assert result['matching_square'] == 16
    print("  [PASS] natural square 16 H4 bars")


def test_no_time_window():
    """No window active at 7 H4 bars (between 4+1 and 9-1)."""
    t0 = datetime(2024, 1, 1)
    result = is_time_window_active(t0, 0, t0 + timedelta(hours=28), 7)
    # 7 is not within ±1 of 4(5) or 9(8)
    # Actually 7 is within 1 of... no: |7-4|=3, |7-9|=2 → no match for squares
    # But wait: there's also impulse check. 7*4=28 H1 bars, 28/12=2.33 — not near 8,16,64
    assert result['active'] is False
    print("  [PASS] no time window at 7 H4 bars")


def test_impulse_timing():
    """Vibration-scaled impulse timing (96 H1 bars = ratio 8)."""
    t0 = datetime(2024, 1, 1)
    # 24 H4 bars = 96 H1 bars, 96/12 = 8.0 → matches IMPULSE_RATIOS[0]
    # But 24 is also a natural square! Test with 24±1 to see if NS catches it first.
    result = is_time_window_active(t0, 0, t0, 24)
    assert result['active'] is True  # Matches natural square 24
    print("  [PASS] impulse timing (caught by natural square 24)")


def test_impulse_only():
    """Pure impulse match (not a natural square)."""
    t0 = datetime(2024, 1, 1)
    # ratio 64: bars_h4 * 4 / 12 = 64 → bars_h4 = 192
    # 192 is far from any natural square (max is 81)
    result = is_time_window_active(t0, 0, t0, 192)
    assert result['active'] is True
    assert result['impulse_match'] is True
    assert result['matching_square'] is None
    print("  [PASS] pure impulse match at 192 H4 bars (ratio 64)")


def test_intraday_reversal_primary():
    """Primary reversal window at 8h and 16h."""
    t0 = datetime(2024, 1, 1, 2, 0)  # Session extremum at 02:00
    # 8 hours later = 10:00
    result = intraday_reversal_window(t0, datetime(2024, 1, 1, 10, 0))
    assert result['active'] is True
    assert result['window'] == 8
    assert result['type'] == 'primary'

    # 16 hours later = 18:00
    result = intraday_reversal_window(t0, datetime(2024, 1, 1, 18, 0))
    assert result['active'] is True
    assert result['window'] == 16
    print("  [PASS] intraday primary windows 8h and 16h")


def test_intraday_reversal_tolerance():
    """Intraday window within ±2h tolerance."""
    t0 = datetime(2024, 1, 1, 2, 0)
    # 6 hours later (8h - 2h)
    result = intraday_reversal_window(t0, datetime(2024, 1, 1, 8, 0))
    assert result['active'] is True
    print("  [PASS] intraday tolerance ±2h")


def test_intraday_no_window():
    """No intraday window at 4h from extremum."""
    t0 = datetime(2024, 1, 1, 2, 0)
    result = intraday_reversal_window(t0, datetime(2024, 1, 1, 6, 0))
    # 4h from extremum — not within ±2h of 8 or 16
    # |4-8| = 4 > 2 and |4-11| = 7 > 2
    assert result['active'] is False
    print("  [PASS] no intraday window at 4h")


def test_forex_time_adjustment():
    """Forex calendar-to-trading conversion."""
    assert abs(forex_time_adjustment(7) - 5.0) < 0.01  # 7 cal = 5 trading
    assert abs(forex_time_adjustment(14) - 10.0) < 0.01
    assert abs(forex_time_adjustment(0) - 0.0) < 0.01
    print("  [PASS] forex time adjustment")


# ============================================================
# RUN ALL TESTS
# ============================================================

def run_all():
    tests = [
        ("Constants", [test_constants_values, test_vibration_relationships]),
        ("Sq9 Engine", [
            test_sq9_even_squares_at_135,
            test_sq9_odd_squares_at_315,
            test_sq9_180_apart,
            test_sq9_edge_cases,
            test_reduce_gold_price,
            test_even_odd_rays,
            test_sq9_levels_from_price,
        ]),
        ("Vibration", [
            test_vibration_swing_levels_from_2072,
            test_vibration_growth_levels,
            test_vibration_correction_levels,
            test_vibration_override_288,
            test_vibration_level_count,
        ]),
        ("Proportional", [
            test_proportional_levels_2000_2100,
            test_proportional_secondary_levels,
            test_proportional_all_keys,
            test_check_fold,
            test_no_fold,
            test_fold_within_lost_motion,
        ]),
        ("Time Structure", [
            test_natural_square_matching_9,
            test_natural_square_tolerance,
            test_natural_square_4,
            test_natural_square_16,
            test_no_time_window,
            test_impulse_timing,
            test_impulse_only,
            test_intraday_reversal_primary,
            test_intraday_reversal_tolerance,
            test_intraday_no_window,
            test_forex_time_adjustment,
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

    print(f"\n{'='*50}")
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'='*50}")

    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
