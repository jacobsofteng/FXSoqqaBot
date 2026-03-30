"""
Gold-Specific Constants — Section 15 of GANN_STRATEGY_V9_SPEC.md

All constants for XAUUSD Gann trading. DO NOT CHANGE these values.
"""

# === INSTRUMENT ===
INSTRUMENT = "XAUUSD"

# === VIBRATION CONSTANTS ===
# Hellcat: V = ((N * pi / 24) + 24) * N, for Gold N=3 → 73.18 ≈ 72
BASE_VIBRATION = 72
SWING_QUANTUM = 12           # V/6 — strongest H1 signal
GROWTH_QUANTUM = 18          # V/4 — growth by quarters
CORRECTION_QUANTUM = 24      # V/3 — correction by thirds
CUBE_ROOT_STEP = 52          # Constant for $900–$2900
MASTER_TIME = 52             # Master time number ("5 years, 5 months, 5 days")

# === TOLERANCES ===
LOST_MOTION = 3.0            # Dollars ± (Gann: "2–2.5 units", calibrated $2–3)

# === SQ9 ===
POWER_ANGLES = [30, 45]      # Only these two have meaningful hit rates on Gold

# === VIBRATION SERIES ===
KU_SERIES = [1, 2, 3, 5, 7, 11]  # Indivisible units

# === NATURAL SQUARES (H4 bars) with calibrated hit rates ===
NATURAL_SQUARES = {
    4:  0.23,   # 23% of H4 swings last 4 bars (16 hours)
    9:  0.28,   # 28% — STRONGEST
    16: 0.15,
    24: 0.10,
    36: 0.08,
    49: 0.05,
    72: 0.04,
    81: 0.03,
}
NATURAL_SQ = [4, 9, 16, 24, 36, 49, 72, 81]

# === TIME CONSTANTS ===
MAX_HOLD_BARS = 288          # M5 bars = 24 hours
MAX_DAILY_TRADES = 5
INTRADAY_WINDOWS_PRIMARY = [8, 16]       # Hours from session extremum
INTRADAY_WINDOWS_SECONDARY = [11, 13, 19]
INTRADAY_TOLERANCE = 2       # Hours
FOREX_WEEKEND_FACTOR = 5.0 / 7.0  # Trading days / calendar days

# === IMPULSE RATIOS (vibration-scaled, in V-units) ===
IMPULSE_RATIOS = [8, 16, 64]  # 96h, 192h, 768h in V-units

# === TIME CYCLES ===
GREAT_CYCLES_YEARS = [90, 84, 60, 49, 45, 30, 20]
MINOR_CYCLES_YEARS = [13, 10, 7, 5, 3, 2, 1]
DAILY_MINOR_CYCLES = [7, 10, 14, 20, 21, 28, 30]

# === M5 BOX SIZES (all in A=432Hz harmonic series) ===
M5_BOXES = [144, 216, 288, 432]  # All multiples of 72

# === GANN ANGLE RATIOS ===
GANN_ANGLES = {
    '1x1': 1.0,    # 45 degrees — balance
    '2x1': 2.0,    # Price moves 2x time — strong uptrend
    '1x2': 0.5,    # Price moves 0.5x time — weak uptrend
    '4x1': 4.0,    # Very strong trend
    '1x4': 0.25,   # Very weak trend
}

# === VIBRATION OVERRIDE ===
VIBRATION_OVERRIDE_MULTIPLIER = 4  # 4 × V = reversal threshold
# 4 × 72 = $288 macro reversal
# 4 × 12 = $48 micro reversal (H1)

# === CONVERGENCE ===
MIN_CONVERGENCE_SCORE = 4   # Ferro's rule: minimum 4 independent categories
MIN_LIMITS_COUNT = 2        # At least 2 of 3 limits

# === R:R ===
MIN_RR_RATIO = 3.0          # Minimum 3:1 R:R for any trade
