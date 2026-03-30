"""
Three-Limit Alignment -- Module 9

Hellcat: "Most traders use only Limit 2 (price-by-price).
When ALL THREE align = 85-96% probability."

Limit 1: Price-by-Time (Sq9 degree of price move == Sq9 degree of time)
Limit 2: Price-by-Price (price at a Gann level)
Limit 3: Time-by-Time (swing duration matches natural square)
"""

from .constants import (
    POWER_ANGLES, LOST_MOTION, SWING_QUANTUM, NATURAL_SQUARES,
)
from .sq9_engine import price_to_sq9_degree, sq9_levels_from_price


def check_three_limits(current_price: float, current_bar: int,
                       swings: list[dict], wave_state: dict | None) -> dict:
    """
    Check all three limits.

    Returns:
        {'limit1': bool, 'limit2': bool, 'limit3': bool,
         'all_three': bool, 'count': int (0-3)}
    """
    last_swing = swings[-1] if swings else None
    if not last_swing:
        return {'limit1': False, 'limit2': False, 'limit3': False,
                'all_three': False, 'count': 0}

    # LIMIT 1: Price-by-Time (with vibration scaling)
    price_move = abs(current_price - last_swing['price'])
    price_units = price_move / SWING_QUANTUM  # Scale by V=12
    time_units = current_bar - last_swing['bar_index']

    limit1 = False
    if price_units > 0 and time_units > 0:
        price_degree = price_to_sq9_degree(price_units)
        time_degree = price_to_sq9_degree(time_units)
        degree_diff = min(
            abs(price_degree - time_degree),
            360 - abs(price_degree - time_degree),
        )
        limit1 = degree_diff <= 5.0  # 5-degree orb

    # LIMIT 2: Price-by-Price (at ANY Gann level)
    limit2 = False
    for sw in swings[-5:]:
        # Sq9 levels
        levels = sq9_levels_from_price(sw['price'], POWER_ANGLES)
        for level in levels:
            if abs(current_price - level) <= LOST_MOTION:
                limit2 = True
                break
        if limit2:
            break

        # Vibration levels
        distance = abs(current_price - sw['price'])
        remainder = distance % SWING_QUANTUM
        if (remainder <= LOST_MOTION
                or (SWING_QUANTUM - remainder) <= LOST_MOTION):
            limit2 = True
            break

    # LIMIT 3: Time-by-Time
    bars_elapsed = current_bar - last_swing['bar_index']
    limit3 = False
    for sq in NATURAL_SQUARES:
        if abs(bars_elapsed - sq) <= 1:
            limit3 = True
            break

    count = sum([limit1, limit2, limit3])

    return {
        'limit1': limit1,
        'limit2': limit2,
        'limit3': limit3,
        'all_three': count == 3,
        'count': count,
    }
