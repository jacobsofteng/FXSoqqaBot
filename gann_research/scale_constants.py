"""
Scale Constants -- Multi-scale Gann parameters for v9.2

H1 scale = the original v9.1 parameters (unchanged).
M15 scale = Matryoshka half-scale (Hellcat: 36-box -> 18-box).

All hardcoded H1 values from constants.py are reproduced here per-scale.
Modules that need scale awareness import from here instead of constants.py.
"""

from .constants import (
    BASE_VIBRATION, SWING_QUANTUM, LOST_MOTION, POWER_ANGLES,
    MAX_HOLD_BARS, MAX_DAILY_TRADES, NATURAL_SQ,
)


SCALES = {
    'H1': {
        'vibration_quantum': SWING_QUANTUM,       # 12
        'vibration_base': BASE_VIBRATION,          # 72
        'lost_motion': LOST_MOTION,                # 3.0
        'min_convergence_scan': 3,                 # of 6 categories
        'min_convergence_box': 4,                  # of 7 categories
        'power_angles': POWER_ANGLES,              # [30, 45]
        'quant_window': 50,                        # M5 bars forward scan
        'min_quant_pips': SWING_QUANTUM * 0.5,     # 6.0
        'max_diagonal_gap': SWING_QUANTUM * 6,     # 72.0
        'tp_multiplier': 3,                        # wave multiplier
        'max_spread': 0.50,                        # dollars
        'swing_atr_multiplier': 1.5,
        'swing_atr_period': 14,
        'max_hold_bars': MAX_HOLD_BARS,            # 288
        'magic_number': 123456,
        'price_per_h4': 6.0,                       # Gold natural rate
        'm5_per_tf': 12,                           # M5 bars per H1
        'natural_squares': NATURAL_SQ,
    },
    'M15': {
        'vibration_quantum': 6,                    # H1/2 (sqrt scaling)
        'vibration_base': 36,                      # H1/2
        'lost_motion': 2.0,                        # Tighter at smaller scale
        'min_convergence_scan': 3,
        'min_convergence_box': 4,
        'power_angles': POWER_ANGLES,              # [30, 45]
        'quant_window': 30,                        # M15 bars = 7.5 hours max
        'min_quant_pips': 3.0,                     # Half of M15 quantum
        'max_diagonal_gap': 6 * 6,                 # 36.0 = 6 x M15 quantum
        'tp_multiplier': 3,
        'max_spread': 0.30,                        # Stricter
        'swing_atr_multiplier': 1.0,               # Tighter swings
        'swing_atr_period': 14,
        'max_hold_bars': 192,                      # 16 hours (shorter)
        'magic_number': 123457,
        'price_per_h4': 6.0,                       # Same Gold rate
        'm5_per_tf': 3,                            # M5 bars per M15
        'natural_squares': NATURAL_SQ,
    },
}


def get_scale(scale_name: str = 'H1') -> dict:
    """Get scale parameters. Returns H1 by default."""
    return SCALES[scale_name]
