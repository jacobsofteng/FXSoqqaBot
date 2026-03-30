"""
Wave Counting System — Module 6

Implements Hellcat's vpM2F(t) protocol:
  Legend phase: count BACKWARDS from transition: ..., -3, -2, -1
  Wave 0: transition point (Legend ends, Scenario begins)
  Scenario phase: count FORWARD: +1, +2, +3, +4, +5

Wave target formula: wave_target = wave_0_size × (N + 1)
Direction: odd waves = trending, even waves = correcting.
"""

import math
from typing import Optional

from .constants import SWING_QUANTUM


def count_waves(swings: list[dict], timeframe: str = 'H1') -> Optional[dict]:
    """
    Wave counting using vpM2F(t) protocol.

    Legend:Scenario ratio:
      H1: 1:1 (look back N swings, predict N forward)
      D1: 4:1 (look back 4N swings, predict N forward)

    Args:
        swings: List of swing dicts from detect_swings_atr()
        timeframe: 'H1' or 'D1' to select ratio

    Returns:
        {
          'wave_number': int,
          'wave_0_price': float,
          'wave_0_size': float,
          'direction': 'up' | 'down',
          'targets': list[float],
          'is_trending': bool,
          'is_correcting': bool,
          'legend_swings': list,
          'scenario_swings': list,
        }
        or None if insufficient data
    """
    if len(swings) < 4:
        return None

    ratio = 1.0 if timeframe == 'H1' else 4.0

    wave_0_idx = _find_wave_0(swings, ratio)
    if wave_0_idx is None:
        return None

    wave_0_swing = swings[wave_0_idx]
    legend_swings = swings[:wave_0_idx]
    scenario_swings = swings[wave_0_idx:]

    # Wave 0 size = the price move of the first scenario swing
    if len(scenario_swings) >= 2:
        wave_0_size = abs(scenario_swings[1]['price'] - scenario_swings[0]['price'])
    else:
        wave_0_size = abs(swings[-1]['price'] - swings[-2]['price'])

    # Current wave number
    current_wave = len(scenario_swings) - 1

    # Direction: wave 0's swing type defines the scenario
    if scenario_swings[0]['type'] == 'low':
        direction = 'up'
    else:
        direction = 'down'

    # Generate targets: wave_target = wave_0_size × (n + 1)
    targets = []
    for n in range(1, 8):
        if direction == 'up':
            target = wave_0_swing['price'] + wave_0_size * (n + 1)
        else:
            target = wave_0_swing['price'] - wave_0_size * (n + 1)
        targets.append(round(target, 2))

    return {
        'wave_number': current_wave,
        'wave_0_price': wave_0_swing['price'],
        'wave_0_size': wave_0_size,
        'direction': direction,
        'targets': targets,
        'is_trending': current_wave % 2 == 1,
        'is_correcting': current_wave % 2 == 0,
        'legend_swings': legend_swings,
        'scenario_swings': scenario_swings,
    }


def _find_wave_0(swings: list[dict], ratio: float) -> Optional[int]:
    """
    Find the wave 0 transition point.

    Heuristic: wave 0 is the swing where the size relationship between
    consecutive swings changes significantly — where swing_size[i]/swing_size[i-1]
    crosses through 1.0 dramatically.

    For H1 (ratio=1): look at last 6–10 swings.
    For D1 (ratio=4): look at last 15–20 swings.
    """
    lookback = int(6 * ratio)
    start = max(0, len(swings) - lookback)

    if len(swings) - start < 3:
        return start

    best_idx = start
    best_score = 0.0

    for i in range(start + 2, len(swings)):
        prev_size = abs(swings[i - 1]['price'] - swings[i - 2]['price'])
        curr_size = abs(swings[i]['price'] - swings[i - 1]['price'])

        if prev_size == 0:
            continue

        ratio_change = curr_size / prev_size
        # Wave 0 = where the ratio dramatically shifts
        if ratio_change > 1.5 or ratio_change < 0.67:
            score = abs(math.log(ratio_change))
            if score > best_score:
                best_score = score
                best_idx = i - 1

    return best_idx if best_score > 0.3 else None


def unit_vibration_check(swing_a: dict, swing_b: dict, swing_c: dict) -> bool:
    """
    Atomic unit of movement: 0 → 1 → 2.

    Rule: time from 0→1 MUST EQUAL time from 1→2 (temporal symmetry).
    If this holds, the current movement is "within vibration" and safe to hold.
    When symmetry breaks, the vibration chain may be ending.

    Allows ±20% tolerance.
    """
    time_01 = (swing_b['time'] - swing_a['time']).total_seconds()
    time_12 = (swing_c['time'] - swing_b['time']).total_seconds()

    if time_01 == 0:
        return False

    ratio = time_12 / time_01
    return 0.8 <= ratio <= 1.2
