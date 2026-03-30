"""
Time Structure Engine — Module 4

"TIME is the most important factor." Time windows must be ACTIVE before
any price level becomes tradeable. Natural squares for H4 swing timing,
vibration-scaled impulse durations, intraday reversal windows.
"""

from datetime import datetime

from .constants import (
    NATURAL_SQUARES, SWING_QUANTUM, IMPULSE_RATIOS,
    INTRADAY_WINDOWS_PRIMARY, INTRADAY_WINDOWS_SECONDARY,
    INTRADAY_TOLERANCE, FOREX_WEEKEND_FACTOR,
)


def is_time_window_active(last_swing_time: datetime,
                          last_swing_bars_h4: int,
                          current_time: datetime,
                          current_bar_h4: int) -> dict:
    """
    Check if a natural square time window is currently active.

    Algorithm:
      1. Count H4 bars since last swing
      2. If count is within ±1 of any natural square → window OPEN
      3. Also check vibration-scaled impulse timing on H1

    v9.0 fix: uses vibration-SCALED durations, not fixed hours.

    Returns:
        {
          'active': bool,
          'matching_square': int | None,
          'bars_elapsed': int,
          'window_strength': float (0–1),
          'impulse_match': bool,
        }
    """
    bars_elapsed = current_bar_h4 - last_swing_bars_h4

    # Check natural square timing (±1 H4 bar tolerance)
    for sq, strength in NATURAL_SQUARES.items():
        if abs(bars_elapsed - sq) <= 1:
            return {
                'active': True,
                'matching_square': sq,
                'bars_elapsed': bars_elapsed,
                'window_strength': strength,
                'impulse_match': False,
            }

    # Check vibration-scaled impulse timing (on H1 bars)
    bars_h1 = bars_elapsed * 4  # H4 → H1 conversion
    if SWING_QUANTUM > 0:
        scaled_ratio = bars_h1 / SWING_QUANTUM  # bars / 12

        for ratio in IMPULSE_RATIOS:
            if abs(scaled_ratio - ratio) <= 1:
                return {
                    'active': True,
                    'matching_square': None,
                    'bars_elapsed': bars_elapsed,
                    'window_strength': 0.15,
                    'impulse_match': True,
                }

    return {
        'active': False,
        'matching_square': None,
        'bars_elapsed': bars_elapsed,
        'window_strength': 0.0,
        'impulse_match': False,
    }


def intraday_reversal_window(session_extremum_time: datetime,
                             current_time: datetime) -> dict:
    """
    Check if current time falls within an intraday reversal window.

    PRIMARY: 8h and 16h from session-start extremum (±2h)
    SECONDARY: 11h, 13h, 19h

    Session start = 00:00 UTC for Gold (24h market).
    Session extremum = the high or low of the first 1–2 hours.
    """
    hours_elapsed = (current_time - session_extremum_time).total_seconds() / 3600

    for window in INTRADAY_WINDOWS_PRIMARY:
        if abs(hours_elapsed - window) <= INTRADAY_TOLERANCE:
            return {'active': True, 'window': window, 'type': 'primary'}

    for window in INTRADAY_WINDOWS_SECONDARY:
        if abs(hours_elapsed - window) <= INTRADAY_TOLERANCE:
            return {'active': True, 'window': window, 'type': 'secondary'}

    return {'active': False}


def forex_time_adjustment(calendar_days: int) -> float:
    """
    Forex markets trade 5 days per week, but Gann time counts are
    in CALENDAR days. Adjustment factor: 5/7 = 0.714

    trading_days = calendar_days * (5/7)
    """
    return calendar_days * FOREX_WEEKEND_FACTOR
