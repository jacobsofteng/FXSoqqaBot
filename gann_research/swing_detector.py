"""
Swing Detector — ATR-based ZigZag for identifying significant highs/lows.

Uses a FIXED threshold (no tuning) based on ATR to avoid overfitting.
The threshold is set ONCE before any tests run.
"""

import numpy as np
import pandas as pd


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def detect_swings(
    df: pd.DataFrame,
    atr_multiplier: float = 2.5,
    atr_period: int = 14,
    min_bars_between: int = 3,
) -> pd.DataFrame:
    """Detect significant swing highs and lows using ATR-based ZigZag.

    Tracks the running extremum in the current direction. When price reverses
    by threshold from that extremum, the extremum is confirmed as a swing.

    Parameters are FIXED:
        atr_multiplier=2.5 : swing must reverse by 2.5x ATR to be significant
        atr_period=14      : standard ATR period
        min_bars_between=3 : minimum bars between consecutive swings
    """
    atr = compute_atr(df, atr_period)

    highs = df["high"].values
    lows = df["low"].values
    times = df.index
    atr_vals = atr.values
    n = len(df)

    swings = []

    # State: 1 = tracking up (looking for high), -1 = tracking down (looking for low)
    state = 0
    # Current extremum being tracked
    ext_val = 0.0
    ext_idx = 0

    for i in range(atr_period, n):
        current_atr = atr_vals[i]
        if np.isnan(current_atr) or current_atr <= 0:
            continue
        threshold = current_atr * atr_multiplier

        if state == 0:
            # Initialize: find first significant move
            ext_val = highs[i]
            ext_idx = i
            low_val = lows[i]
            low_idx = i

            # Look for first reversal to establish direction
            if i > atr_period:
                # Check if we've moved up significantly from recent low
                recent_low = lows[max(atr_period, i - 20):i + 1].min()
                recent_low_idx = max(atr_period, i - 20) + lows[max(atr_period, i - 20):i + 1].argmin()
                if highs[i] - recent_low >= threshold:
                    # Upswing detected, the low is a swing low
                    swings.append({
                        "time": times[recent_low_idx],
                        "price": recent_low,
                        "type": "low",
                        "bar_index": recent_low_idx,
                    })
                    state = 1  # Now tracking up
                    ext_val = highs[i]
                    ext_idx = i
                    continue

                recent_high = highs[max(atr_period, i - 20):i + 1].max()
                recent_high_idx = max(atr_period, i - 20) + highs[max(atr_period, i - 20):i + 1].argmax()
                if recent_high - lows[i] >= threshold:
                    # Downswing detected, the high is a swing high
                    swings.append({
                        "time": times[recent_high_idx],
                        "price": recent_high,
                        "type": "high",
                        "bar_index": recent_high_idx,
                    })
                    state = -1  # Now tracking down
                    ext_val = lows[i]
                    ext_idx = i
                    continue

        elif state == 1:
            # Tracking up — looking for swing HIGH
            if highs[i] > ext_val:
                ext_val = highs[i]
                ext_idx = i

            # Has price reversed down enough to confirm the high?
            if ext_val - lows[i] >= threshold:
                # Confirm swing high
                if not swings or ext_idx - swings[-1]["bar_index"] >= min_bars_between:
                    swings.append({
                        "time": times[ext_idx],
                        "price": ext_val,
                        "type": "high",
                        "bar_index": ext_idx,
                    })
                # Switch to tracking down
                state = -1
                ext_val = lows[i]
                ext_idx = i

        elif state == -1:
            # Tracking down — looking for swing LOW
            if lows[i] < ext_val:
                ext_val = lows[i]
                ext_idx = i

            # Has price reversed up enough to confirm the low?
            if highs[i] - ext_val >= threshold:
                # Confirm swing low
                if not swings or ext_idx - swings[-1]["bar_index"] >= min_bars_between:
                    swings.append({
                        "time": times[ext_idx],
                        "price": ext_val,
                        "type": "low",
                        "bar_index": ext_idx,
                    })
                # Switch to tracking up
                state = 1
                ext_val = highs[i]
                ext_idx = i

    return pd.DataFrame(swings)


def detect_swings_multitf(
    m1: pd.DataFrame,
    timeframes: list[str] | None = None,
    atr_multiplier: float = 2.5,
) -> dict[str, pd.DataFrame]:
    """Detect swings on multiple timeframes."""
    from . import data_loader

    if timeframes is None:
        timeframes = ["M5", "M15", "H1", "H4", "D1"]

    results = {}
    for tf in timeframes:
        resampled = data_loader.resample_timeframe(m1, tf)
        swings = detect_swings(resampled, atr_multiplier=atr_multiplier)
        results[tf] = swings
        print(f"  {tf}: {len(swings)} swings detected")
    return results


def count_waves(
    swings_df: pd.DataFrame,
    current_bar_idx: int,
) -> dict:
    """Count waves from H1 swings to determine trade direction.

    Implements Hellcat/FFM wave counting protocol (GANN_METHOD_ANALYSIS Part 3.4):

    Legend phase (analyzing history):
      Count backwards from transition: -N, ..., -3, -2, -1
      Each wave = one swing in the Legend pattern

    Transition (wave 0):
      The point where Legend ends, Scenario begins
      Highest probability direction change

    Scenario phase (predicting future):
      Count forward: +1, +2, +3, +4, +5...

    Direction logic:
      - Identify the current impulse direction from recent swings
      - Count completed waves in the impulse
      - Odd waves (1,3,5) = impulse direction; Even waves (2,4) = corrections
      - After wave 5: expect reversal (Legend → Scenario transition)
      - Wave 0 size sets all future targets: wave(0) × (N+1) = wave(2N+1)

    Returns dict with wave number, direction, confidence, and expected target.
    """
    result = {
        "wave_number": 0,
        "direction": "neutral",  # "long", "short", "neutral"
        "confidence": 0.0,       # 0.0 to 1.0
        "phase": "unknown",      # "legend", "scenario", "transition"
        "wave_0_size": 0.0,
        "expected_target": 0.0,
        "impulse_direction": "neutral",
        "details": [],
    }

    if len(swings_df) < 4:
        return result

    # Only use swings up to current bar
    mask = swings_df["bar_index"] <= current_bar_idx
    active = swings_df[mask]
    if len(active) < 4:
        return result

    # Get the last several swings for wave analysis
    recent = active.tail(10)
    prices = recent["price"].values
    types = recent["type"].values
    indices = recent["bar_index"].values

    # Determine dominant impulse direction from the larger swing structure
    # Look at the net move over the last several swings
    # The impulse direction = direction of the LARGEST recent swing
    swing_moves = []
    for i in range(len(prices) - 1):
        move = prices[i + 1] - prices[i]
        swing_moves.append(move)

    if not swing_moves:
        return result

    # Find the largest swing (wave 0 candidate) — sets all subsequent targets
    abs_moves = [abs(m) for m in swing_moves]
    max_idx = np.argmax(abs_moves)
    wave_0_size = abs_moves[max_idx]
    wave_0_direction = "up" if swing_moves[max_idx] > 0 else "down"

    result["wave_0_size"] = wave_0_size
    result["impulse_direction"] = "long" if wave_0_direction == "up" else "short"

    # Count waves AFTER wave 0 (the largest swing)
    # Waves after wave 0 alternate: odd = impulse, even = correction
    waves_after = swing_moves[max_idx + 1:]
    n_waves_after = len(waves_after)

    # Count how many even waves exceeded wave 0 (for target calculation)
    n_even_exceeding = 0
    for i, m in enumerate(waves_after):
        wave_num = i + 1
        if wave_num % 2 == 0 and abs(m) > wave_0_size:
            n_even_exceeding += 1

    # Calculate expected target using Hellcat's formula
    # wave(0) × (N+1) = wave(2N+1)
    result["expected_target"] = wave_0_size * (n_even_exceeding + 1)

    # Determine current wave number and phase
    current_wave = n_waves_after + 1  # Next wave to form
    result["wave_number"] = current_wave

    # Phase determination
    if current_wave <= 5:
        # Still in impulse sequence — Scenario phase (predictable)
        result["phase"] = "scenario"
        # Odd waves go WITH impulse, even waves are corrections
        if current_wave % 2 == 1:
            # Odd wave = impulse direction
            result["direction"] = result["impulse_direction"]
            result["confidence"] = 0.7 - (current_wave - 1) * 0.05  # Decreasing confidence
        else:
            # Even wave = correction (opposite direction)
            result["direction"] = "short" if result["impulse_direction"] == "long" else "long"
            result["confidence"] = 0.5  # Corrections less predictable
    elif current_wave == 6:
        # Wave 5 completed → approaching transition (wave 0 of next cycle)
        result["phase"] = "transition"
        # Expect reversal of impulse
        result["direction"] = "short" if result["impulse_direction"] == "long" else "long"
        result["confidence"] = 0.75  # Transition = high probability reversal
    else:
        # Post-transition: ABC correction phase (Legend of next cycle)
        result["phase"] = "legend"
        # In ABC: A and C go against prior impulse, B is minor retrace
        abc_wave = (current_wave - 6)  # 1=A, 2=B, 3=C
        if abc_wave % 2 == 1:  # A or C
            result["direction"] = "short" if result["impulse_direction"] == "long" else "long"
            result["confidence"] = 0.6
        else:  # B
            result["direction"] = result["impulse_direction"]
            result["confidence"] = 0.4

    # Add additional context from recent price action
    last_type = types[-1]
    last_price = prices[-1]
    current_direction_from_last = "long" if last_type == "low" else "short"

    result["details"].append(f"Wave {current_wave}, phase={result['phase']}")
    result["details"].append(f"Impulse={result['impulse_direction']}, W0=${wave_0_size:.0f}")
    result["details"].append(f"Last swing: {last_type} at ${last_price:.0f}")
    result["details"].append(f"Expected target: ${result['expected_target']:.0f}")

    return result


def swing_pairs(swings_df: pd.DataFrame) -> list[dict]:
    """Extract consecutive high-low or low-high pairs for analysis."""
    pairs = []
    for i in range(len(swings_df) - 1):
        s1 = swings_df.iloc[i]
        s2 = swings_df.iloc[i + 1]
        if s1["type"] == s2["type"]:
            continue
        pairs.append({
            "start_time": s1["time"],
            "end_time": s2["time"],
            "start_price": s1["price"],
            "end_price": s2["price"],
            "start_type": s1["type"],
            "end_type": s2["type"],
            "price_move": abs(s2["price"] - s1["price"]),
            "start_idx": s1["bar_index"],
            "end_idx": s2["bar_index"],
            "duration_bars": s2["bar_index"] - s1["bar_index"],
        })
    return pairs
