"""
Gann Math Core — All formulas from GANN_METHOD_ANALYSIS.md Part 13/17.

Every function here is a FIXED formula with no tunable parameters.
Parameters come from the research (Hellcat, Ferro, Gann course).
"""

import math
import numpy as np


# ============================================================
# Square of 9
# ============================================================

def price_to_sq9_degree(price: float) -> float:
    """Convert price to Square of 9 degree position (0-360)."""
    if price <= 0:
        return 0.0
    return (math.sqrt(price) * 180.0 - 225.0) % 360.0


def sq9_add_degrees(price: float, degrees: float) -> float:
    """Add degrees on Sq9 to get target price (resistance)."""
    sqrt_p = math.sqrt(max(price, 0.01))
    sqrt_target = sqrt_p + degrees / 180.0
    return sqrt_target ** 2


def sq9_subtract_degrees(price: float, degrees: float) -> float:
    """Subtract degrees on Sq9 to get target price (support)."""
    sqrt_p = math.sqrt(max(price, 0.01))
    sqrt_target = sqrt_p - degrees / 180.0
    if sqrt_target < 0:
        return 0.0
    return sqrt_target ** 2


def sq9_levels(price: float) -> dict[str, float]:
    """Calculate all standard Sq9 S/R levels from a reference price.

    Standard offsets: 45, 90, 120, 180, 240, 270, 315, 360 degrees.
    Returns both resistance (above) and support (below).
    """
    offsets = [45, 90, 120, 180, 240, 270, 315, 360]
    levels = {}
    for deg in offsets:
        levels[f"+{deg}"] = sq9_add_degrees(price, deg)
        levels[f"-{deg}"] = sq9_subtract_degrees(price, deg)
    return levels


# ============================================================
# Gold price reduction
# ============================================================

def reduce_gold_price(price: float) -> int:
    """Reduce Gold price to Sq9 base number: 2072 -> 72, 1667 -> 667."""
    return int(price) % 1000


# ============================================================
# Proportional levels (Gann ratios, NOT Fibonacci)
# ============================================================

GANN_RATIOS = {
    "1/8": 1 / 8,
    "1/4": 1 / 4,
    "1/3": 1 / 3,
    "3/8": 3 / 8,
    "1/2": 1 / 2,
    "5/8": 5 / 8,
    "2/3": 2 / 3,
    "3/4": 3 / 4,
    "7/8": 7 / 8,
}

FIBONACCI_RATIOS = {
    "23.6%": 0.236,
    "38.2%": 0.382,
    "50.0%": 0.500,
    "61.8%": 0.618,
    "78.6%": 0.786,
}


def retracement_level(swing_high: float, swing_low: float, ratio: float) -> float:
    """Calculate retracement level between swing high and low."""
    return swing_high - (swing_high - swing_low) * ratio


def extension_level(swing_low: float, swing_high: float, ratio: float) -> float:
    """Calculate extension level above swing high."""
    move = swing_high - swing_low
    return swing_high + move * ratio


# ============================================================
# Impulse progression (Ferro)
# ============================================================

IMPULSE_HOURS = [72, 96, 144, 192, 576, 768]
# Base: 72, 144, 576
# With +1/3: 96, 192, 768


def impulse_progression(base: int = 72) -> list[dict]:
    """Calculate impulse time progression. Each = base + 1/3 of base."""
    bases = [base, base * 2, base * 8]
    return [{"base": b, "third": b // 3, "total": b + b // 3} for b in bases]


# ============================================================
# Natural squares fan
# ============================================================

NATURAL_SQUARES = [4, 9, 16, 24, 36, 49, 72, 81]


# ============================================================
# Vibration constant (Hellcat)
# ============================================================

def vibration_constant(pair_number: int) -> float:
    """Hellcat's vibration constant formula: ((N*pi/24)+24)*N."""
    n = pair_number
    return ((n * math.pi / 24) + 24) * n


# Known:
# EUR/USD: N=5 -> 123.27
# GBP/USD: N~6 -> 148.71 (~149)
# Gold candidates: N=3 -> 73.18 (~72)

VIBRATION_CANDIDATES = {
    "N=1": vibration_constant(1),   # 25.13
    "N=2": vibration_constant(2),   # 49.26
    "N=3": vibration_constant(3),   # 73.18
    "N=5": vibration_constant(5),   # 123.27
    "N=7": vibration_constant(7),   # 174.39
    "N=11": vibration_constant(11), # 278.18
    "direct_7": 7.0,
    "direct_53": 53.0,
    "direct_72": 72.0,
}


# ============================================================
# Speed / Acceleration stop rule (FFM)
# ============================================================

def speed_acceleration_stop(
    initial_pips: float,
    initial_hours: float,
    remaining_pips: float,
    remaining_hours: float,
) -> dict:
    """When remaining_speed > speed^2, movement STOPS."""
    if initial_hours <= 0 or remaining_hours <= 0:
        return {"will_stop": False, "speed": 0, "accel": 0, "rem_speed": 0}
    speed = initial_pips / initial_hours
    accel = speed ** 2
    rem_speed = remaining_pips / remaining_hours
    return {
        "will_stop": rem_speed > accel,
        "speed": speed,
        "accel": accel,
        "rem_speed": rem_speed,
    }


# ============================================================
# Differential numerology (Hellcat)
# ============================================================

def differential_numerology(past: float, present: float) -> float:
    """diff(past, present)^2 = future increment."""
    return (present - past) ** 2


# ============================================================
# Conservation law
# ============================================================

def check_conservation(price_range: float, time_range: float) -> dict:
    """price x time = constant within a box. time/price = fractal ratio."""
    product = price_range * time_range
    ratio = time_range / price_range if price_range != 0 else 0
    return {"product": product, "ratio": ratio}


# ============================================================
# Impulse exhaustion (circle unrolling)
# ============================================================

def impulse_exhaustion_time(price_range: float) -> float:
    """Time to exhaustion = pi * price_range (in homogeneous units)."""
    return math.pi * price_range


# ============================================================
# Intraday reversal windows
# ============================================================

INTRADAY_REVERSAL_HOURS = [8, 16]
INTRADAY_CORRECTION_HOURS = [11, 13, 19]


# ============================================================
# Even / Odd degree system
# ============================================================

def even_odd_degrees(price: float) -> tuple[float, float]:
    """Calculate even and odd degree positions on Sq9."""
    even = price_to_sq9_degree(price)
    odd = (even + 180.0) % 360.0
    return even, odd


# ============================================================
# Wave algorithm (Hellcat)
# ============================================================

def wave_target(wave_0_size: float, n_completed_even_waves: int) -> float:
    """wave(0) * (N+1) = wave(2N+1)."""
    return wave_0_size * (n_completed_even_waves + 1)


# ============================================================
# Legend:Scenario ratio
# ============================================================

LEGEND_SCENARIO_RATIO = 4.0  # Legend / Scenario ~ 4:1
