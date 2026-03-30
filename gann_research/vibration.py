"""
Vibration System — Module 2

Gold vibration V=72. Swing quantum V/6=12 (strongest H1 signal),
growth quantum V/4=18, correction quantum V/3=24.
"""

from .constants import (
    BASE_VIBRATION, SWING_QUANTUM, GROWTH_QUANTUM,
    CORRECTION_QUANTUM, VIBRATION_OVERRIDE_MULTIPLIER,
)


def vibration_levels(swing_price: float, direction: str,
                     count: int = 10) -> list[float]:
    """
    Generate vibration-based S/R levels from a swing point.

    Ferro's rule:
    - Price GROWS by quarters (V/4 = 18 increments when trending)
    - Price CORRECTS by thirds (V/3 = 24 increments when retracing)

    Args:
        swing_price: Price of the swing high or low
        direction: 'growth' (with trend) or 'correction' (counter-trend)
        count: Number of levels in each direction

    Returns:
        List of price levels (excludes swing_price itself)
    """
    if direction == 'growth':
        quantum = GROWTH_QUANTUM   # 18
    else:
        quantum = CORRECTION_QUANTUM  # 24

    levels = []
    for i in range(-count, count + 1):
        if i == 0:
            continue
        levels.append(swing_price + i * quantum)
    return levels


def vibration_swing_levels(swing_price: float, count: int = 10) -> list[float]:
    """
    Generate swing-quantum levels. V/6=12 is the strongest H1 signal.
    Every multiple of $12 from a swing point is a potential reaction zone.

    Args:
        swing_price: Price of the swing point
        count: Number of levels in each direction

    Returns:
        List of price levels at $12 multiples from swing
    """
    return [swing_price + i * SWING_QUANTUM
            for i in range(-count, count + 1) if i != 0]


def check_vibration_override(move_from_swing: float) -> bool:
    """
    When price exceeds 4x the vibration constant from a swing point,
    expect a SHARP reversal.

    4 * 72 = 288. If price moves $288+ from a swing → reversal signal.

    DO NOT FADE this signal — only trade WITH the reversal momentum.
    """
    return abs(move_from_swing) >= VIBRATION_OVERRIDE_MULTIPLIER * BASE_VIBRATION  # $288
