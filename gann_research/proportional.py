"""
Proportional Division Calculator — Module 3

Divides swing ranges into Gann proportional levels.
Ferro: corrections by thirds (1/3, 2/3), growth by quarters (1/4, 1/2, 3/4).
Strongest levels: 1/3 and 1/2 (empirically confirmed).
"""

from .constants import LOST_MOTION


def proportional_levels(swing_high: float, swing_low: float) -> dict[str, float]:
    """
    Divide a swing range into Gann proportional levels.

    Primary divisions (for trading): 1/3, 1/2, 2/3
    Secondary divisions (for convergence scoring): 1/4, 3/8, 5/8, 3/4, 7/8, 1/8

    Args:
        swing_high: Swing high price
        swing_low: Swing low price

    Returns:
        Dict with fraction labels as keys, price levels as values
    """
    range_size = swing_high - swing_low

    primary = {
        '1/3': swing_low + range_size * (1 / 3),
        '1/2': swing_low + range_size * (1 / 2),
        '2/3': swing_low + range_size * (2 / 3),
    }

    secondary = {
        '1/8': swing_low + range_size * (1 / 8),
        '1/4': swing_low + range_size * (1 / 4),
        '3/8': swing_low + range_size * (3 / 8),
        '5/8': swing_low + range_size * (5 / 8),
        '3/4': swing_low + range_size * (3 / 4),
        '7/8': swing_low + range_size * (7 / 8),
    }

    return {**primary, **secondary}


def check_fold(current_price: float, swing_start: float,
               target: float) -> dict:
    """
    Hellcat's fold rule: if price folds (reverses) at exactly 1/3 of the
    movement toward target:
    - Best case: reaches 1/2 of target
    - Worst case: reaches 1/4 of target
    - 80% chance of target miss

    This is a STOP-LOSS / TARGET ADJUSTMENT rule, not an entry rule.

    Returns:
        {'fold_detected': bool, 'adjusted_tp_best': float,
         'adjusted_tp_worst': float, 'miss_probability': float}
    """
    total_move = target - swing_start
    if total_move == 0:
        return {'fold_detected': False}

    one_third = swing_start + total_move / 3

    fold_detected = abs(current_price - one_third) <= LOST_MOTION

    if fold_detected:
        return {
            'fold_detected': True,
            'adjusted_tp_best': swing_start + total_move / 2,
            'adjusted_tp_worst': swing_start + total_move / 4,
            'miss_probability': 0.80,
        }
    return {'fold_detected': False}
