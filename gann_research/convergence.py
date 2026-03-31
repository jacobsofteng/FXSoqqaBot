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
                      triangle: dict | None,
                      phase: str = 'scanning') -> dict:
    """
    Score convergence using INDEPENDENT categories.

    CRITICAL: Each category contributes MAX 1 POINT.

    Categories (SCANNING phase uses A-D, F, G — 6 categories max):
      A. Sq9 price level (30 or 45 deg from any recent swing)
      B. Vibration level (V=12 multiple from any swing)
      C. Proportional division (1/3, 1/2, 2/3 of any swing range)
      D. Time window (natural square from last H4 swing)
      E. Triangle crossing — ONLY in BOX_ACTIVE phase (circular dependency)
      F. Wave target (near a wave counting target)
      G. Price-time square (price units ~= time units)

    Threshold: 3 in SCANNING (of 6 categories), 4 in BOX_ACTIVE (of 7).

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
    # ONLY counts in BOX_ACTIVE phase — circular dependency in SCANNING
    cat_e = False
    if phase == 'box_active' and triangle and triangle.get('power_points'):
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
    # Gann squaring: price move in dollars ≈ time in H4 bars × scale
    # Gold scale: ~$6/H4 bar (V=72 / 12 H4_bars_per_day ≈ $6)
    # Check if price_move ≈ time_h4 × 6, within 40% tolerance
    PRICE_PER_H4 = 6.0  # $6 per H4 bar (Gold natural rate)
    cat_g = False
    for sw in recent_swings:
        price_move = abs(current_price - sw['price'])
        bars_elapsed = current_bar - sw['bar_index']  # M5 bars
        time_h4 = bars_elapsed / 48  # M5 -> H4

        if time_h4 >= 1 and price_move >= SWING_QUANTUM:
            expected_price = time_h4 * PRICE_PER_H4
            ratio = price_move / expected_price if expected_price > 0 else 0
            if 0.6 <= ratio <= 1.4:
                cat_g = True
                details['G'] = (f"Squared: move=${price_move:.0f}, "
                                f"expected=${expected_price:.0f} "
                                f"({time_h4:.0f}H4×$6, ratio={ratio:.2f})")
                break
    categories['G_square'] = cat_g

    # --- FINAL SCORE ---
    score = sum(1 for v in categories.values() if v)

    # In SCANNING phase: 6 categories (A-D, F, G). Threshold = 3.
    # In BOX_ACTIVE phase: 7 categories (A-G). Threshold = 4.
    if phase == 'scanning':
        threshold = 3
    else:
        threshold = MIN_CONVERGENCE_SCORE

    return {
        'score': score,
        'categories': categories,
        'details': details,
        'is_tradeable': score >= threshold,
    }
