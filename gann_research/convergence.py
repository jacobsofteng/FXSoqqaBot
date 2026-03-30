"""
Convergence Scorer -- Module 8 (FIXED)

7-category independent scoring. Each category contributes MAX 1 point.
No category can inflate the score by having multiple sub-signals.
Score 0-7. Minimum 4 to be tradeable (Ferro's rule).
"""

from .constants import (
    POWER_ANGLES, LOST_MOTION, SWING_QUANTUM, NATURAL_SQUARES,
    MIN_CONVERGENCE_SCORE,
)
from .sq9_engine import sq9_levels_from_price
from .vibration import vibration_swing_levels
from .proportional import proportional_levels
from .time_structure import is_time_window_active

from datetime import datetime


def score_convergence(current_price: float, current_bar: int,
                      current_time: datetime,
                      swings_h1: list[dict],
                      swings_h4: list[dict],
                      wave_state: dict | None,
                      triangle: dict | None) -> dict:
    """
    Score convergence using INDEPENDENT categories.

    CRITICAL: Each category contributes MAX 1 POINT.

    Categories:
      A. Sq9 price level (30 or 45 deg from any recent swing)
      B. Vibration level (V=12 multiple from any swing)
      C. Proportional division (1/3, 1/2, 2/3 of any swing range)
      D. Time window (natural square from last H4 swing)
      E. Triangle crossing (near a power point)
      F. Wave target (near a wave counting target)
      G. Price-time square (price units ~= time units)

    Returns:
        {'score': int (0-7), 'categories': dict, 'details': dict,
         'is_tradeable': bool}
    """
    categories = {}
    details = {}

    if not swings_h1 or len(swings_h1) < 2:
        return {'score': 0, 'categories': {}, 'details': {},
                'is_tradeable': False}

    recent_swings = swings_h1[-5:]

    # --- CATEGORY A: Sq9 Price Level ---
    cat_a = False
    for sw in recent_swings:
        levels = sq9_levels_from_price(sw['price'], POWER_ANGLES)
        for level in levels:
            if abs(current_price - level) <= LOST_MOTION:
                cat_a = True
                details['A'] = (f"Sq9 level {level:.1f} from "
                                f"swing {sw['price']:.1f}")
                break
        if cat_a:
            break
    categories['A_sq9'] = cat_a

    # --- CATEGORY B: Vibration Level ---
    cat_b = False
    for sw in recent_swings:
        distance = abs(current_price - sw['price'])
        remainder = distance % SWING_QUANTUM
        if (remainder <= LOST_MOTION
                or (SWING_QUANTUM - remainder) <= LOST_MOTION):
            cat_b = True
            details['B'] = f"V=12 multiple from swing {sw['price']:.1f}"
            break
    categories['B_vibration'] = cat_b

    # --- CATEGORY C: Proportional Division ---
    cat_c = False
    for i in range(len(recent_swings) - 1):
        for j in range(i + 1, len(recent_swings)):
            hi = max(recent_swings[i]['price'], recent_swings[j]['price'])
            lo = min(recent_swings[i]['price'], recent_swings[j]['price'])
            if hi - lo < SWING_QUANTUM:
                continue
            levels = proportional_levels(hi, lo)
            for frac, level in levels.items():
                if frac in ['1/3', '1/2', '2/3']:
                    if abs(current_price - level) <= LOST_MOTION:
                        cat_c = True
                        details['C'] = (f"{frac} of {lo:.1f}-{hi:.1f} "
                                        f"= {level:.1f}")
                        break
            if cat_c:
                break
        if cat_c:
            break
    categories['C_proportional'] = cat_c

    # --- CATEGORY D: Time Window ---
    # Swing bar_index values are in M5 units; convert to H4 bars (48 M5 = 1 H4)
    cat_d = False
    if swings_h4 and len(swings_h4) >= 1:
        last_h4 = swings_h4[-1]
        h4_bars_elapsed = (current_bar - last_h4['bar_index']) // 48
        time_check = is_time_window_active(
            last_h4['time'], 0,
            current_time, h4_bars_elapsed,
        )
        cat_d = time_check['active']
        if cat_d:
            details['D'] = (f"Time window: sq={time_check['matching_square']}, "
                            f"str={time_check['window_strength']:.2f}")
    categories['D_time'] = cat_d

    # --- CATEGORY E: Triangle Crossing ---
    cat_e = False
    if triangle and triangle.get('power_points'):
        for pp in triangle['power_points']:
            price_match = abs(current_price - pp['price']) <= LOST_MOTION * 2
            bar_match = abs(current_bar - pp['bar']) <= 3
            if price_match and bar_match:
                cat_e = True
                details['E'] = (f"Triangle power point: "
                                f"price={pp['price']:.1f}, bar={pp['bar']}")
                break
    categories['E_triangle'] = cat_e

    # --- CATEGORY F: Wave Target ---
    cat_f = False
    if wave_state and wave_state.get('targets'):
        for target in wave_state['targets'][:4]:
            if abs(current_price - target) <= LOST_MOTION * 2:
                cat_f = True
                details['F'] = f"Wave target {target:.1f}"
                break
    categories['F_wave'] = cat_f

    # --- CATEGORY G: Price-Time Square ---
    # Convert M5 bars to H1 bars (12 M5 = 1 H1) for price-time squaring
    # Require both values >= 3 for meaningful squaring (not noise)
    cat_g = False
    if recent_swings:
        last_swing = recent_swings[-1]
        price_move = abs(current_price - last_swing['price'])
        price_units = price_move / SWING_QUANTUM
        time_units = (current_bar - last_swing['bar_index']) / 12  # M5 -> H1

        if (price_units >= 3 and time_units >= 3
                and abs(price_units - time_units) <= 1):
            cat_g = True
            details['G'] = (f"Squared: price_units={price_units:.1f}, "
                            f"time_units={time_units:.1f}")
    categories['G_square'] = cat_g

    # --- FINAL SCORE ---
    score = sum(1 for v in categories.values() if v)

    return {
        'score': score,
        'categories': categories,
        'details': details,
        'is_tradeable': score >= MIN_CONVERGENCE_SCORE,
    }
