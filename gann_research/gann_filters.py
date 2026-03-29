"""
Gann Trade Filters — Rules from Ferro & Hellcat for 90%+ win rate.

Each filter is a boolean gate. ALL must pass for a valid entry.
These are the conditions that transform 52% into 90%+.
"""

import math
import numpy as np
import pandas as pd

from . import math_core as gann
# from . import planetary  # Stubbed — needs research on known power points


def filter_h1_trend_alignment(
    h1_closes: np.ndarray,
    current_h1_idx: int,
    direction: str,
    lookback: int = 20,
) -> bool:
    """Filter 1: D1/H1 trend must agree with trade direction.

    Ferro: "D1 direction = 60-75% probability minimum"
    Don't go long in a downtrend or short in an uptrend.
    Uses simple slope of last 20 H1 closes.
    """
    start = max(0, current_h1_idx - lookback)
    segment = h1_closes[start:current_h1_idx + 1]
    if len(segment) < 5:
        return True  # Not enough data, allow

    # Linear regression slope
    x = np.arange(len(segment))
    slope = np.polyfit(x, segment, 1)[0]

    if direction == "long" and slope < 0:
        return False  # Don't go long in downtrend
    if direction == "short" and slope > 0:
        return False  # Don't go short in uptrend
    return True


def filter_fold_at_third(
    m5_closes: np.ndarray,
    entry_idx: int,
    direction: str,
    lookback: int = 36,  # ~3 hours of M5 bars
) -> bool:
    """Filter 2: Skip trade if fold (reversal) at 1/3 of prior move.

    Hellcat: "Fold at 1/3 → 80% chance of target miss"
    Check if price reversed direction at approximately 1/3 of the recent swing.
    If fold detected → do NOT trade (80% failure rate).
    """
    start = max(0, entry_idx - lookback)
    segment = m5_closes[start:entry_idx + 1]
    if len(segment) < 12:
        return True  # Not enough data

    # Find the swing range in this segment
    seg_high = segment.max()
    seg_low = segment.min()
    seg_range = seg_high - seg_low
    if seg_range < 3.0:
        return True  # No significant move

    # Check if there's a reversal near 1/3 of the range
    one_third = seg_low + seg_range / 3
    two_thirds = seg_low + seg_range * 2 / 3

    # Count direction changes near 1/3 point
    near_third = 0
    for i in range(1, len(segment) - 1):
        price = segment[i]
        if abs(price - one_third) < seg_range * 0.08 or abs(price - two_thirds) < seg_range * 0.08:
            # Check if direction changed here
            went_up = segment[i] > segment[i - 1]
            will_go_down = segment[i] > segment[min(i + 1, len(segment) - 1)]
            went_down = segment[i] < segment[i - 1]
            will_go_up = segment[i] < segment[min(i + 1, len(segment) - 1)]
            if (went_up and will_go_down) or (went_down and will_go_up):
                near_third += 1

    # If multiple reversals near 1/3 → fold present → skip
    return near_third < 2


def filter_speed_acceleration(
    m5_closes: np.ndarray,
    entry_idx: int,
    lookback: int = 24,  # 2 hours
) -> bool:
    """Filter 3: Don't enter if speed > acceleration (move exhausting).

    Hellcat/FFM: "When remaining_speed > acceleration → movement STOPS"
    If the current move is already exhausting, the Gann level won't hold.
    """
    if entry_idx < lookback + 5:
        return True

    # Split lookback into two halves
    half = lookback // 2
    first_half = m5_closes[entry_idx - lookback:entry_idx - half]
    second_half = m5_closes[entry_idx - half:entry_idx + 1]

    if len(first_half) < 3 or len(second_half) < 3:
        return True

    # Initial speed (first half)
    initial_move = abs(first_half[-1] - first_half[0])
    initial_time = len(first_half)
    if initial_time == 0:
        return True
    speed = initial_move / initial_time
    acceleration = speed ** 2

    # Remaining speed (second half)
    remaining_move = abs(second_half[-1] - second_half[0])
    remaining_time = len(second_half)
    if remaining_time == 0:
        return True
    remaining_speed = remaining_move / remaining_time

    # If remaining speed exceeds acceleration → move is exhausting → skip
    if remaining_speed > acceleration and acceleration > 0.5:
        return False

    return True


def filter_price_time_squaring(
    entry_price: float,
    ref_swing_price: float,
    bars_from_ref: int,
    tolerance_deg: float = 15.0,
) -> bool:
    """Filter 4: Only trade when price-time is near squared.

    Ferro: "When price and time meet, changes are inevitable"
    Price degrees ≈ time degrees on Sq9 → valid entry.
    """
    price_move = abs(entry_price - ref_swing_price)
    if price_move < 2 or bars_from_ref < 2:
        return True  # Too small to measure

    price_deg = gann.price_to_sq9_degree(price_move)
    time_deg = gann.price_to_sq9_degree(bars_from_ref)

    diff = abs(price_deg - time_deg)
    diff = min(diff, 360 - diff)

    return diff <= tolerance_deg


def filter_time_not_expired(
    bars_from_ref_swing: int,
    natural_square_window: int = 81,  # Largest natural square
) -> bool:
    """Filter 5: 'Safe to buy/sell while time has not expired.'

    Hellcat: Don't enter if we're past the natural square timing window.
    Natural squares: 4, 9, 16, 24, 36, 49, 72, 81.
    """
    return bars_from_ref_swing <= natural_square_window


def filter_price_not_ahead(
    m5_closes: np.ndarray,
    entry_idx: int,
    gann_level: float,
    direction: str,
) -> bool:
    """Filter 6: If price arrived at Gann level TOO FAST → accumulation.

    Hellcat: "Price ahead of time = stored potential energy → breakout"
    Don't fade when price has arrived early (it will explode through).
    Instead, ONLY trade WITH the momentum.
    """
    if entry_idx < 12:
        return True

    # Check speed of arrival at this level
    lookback = min(12, entry_idx)
    recent = m5_closes[entry_idx - lookback:entry_idx + 1]
    speed = abs(recent[-1] - recent[0]) / lookback

    # If speed is very high (>2x median), price arrived early → accumulation
    if lookback >= 6:
        median_bar_range = np.median(np.abs(np.diff(recent)))
        if median_bar_range > 0 and speed > median_bar_range * 3:
            # Price arrived very fast → it will break through, don't fade
            return False

    return True


def compute_independent_convergence(
    entry_price: float,
    h1_swings: pd.DataFrame,
    bars_from_last_swing: int,
    vibration: float = 12.0,
    tolerance: float = 5.0,
    entry_time: pd.Timestamp = None,
) -> dict:
    """Compute INDEPENDENT convergence factors (7 binary flags).

    Each factor is binary (present or not). Max score = 7.
    Need 4+ for high-probability trades (Ferro: "minimum 4 convergences").
    Gann lists 9 mathematical points; we check 7.

    Factors:
      A: Sq9 level from most recent swing matches entry price
      B: Sq9 level from second most recent swing matches (independent evidence)
      C: Vibration multiple of move from any recent swing
      D: Proportional level (1/3, 1/2, 2/3, 3/4) of recent swing range
      E: Natural square timing (bars from last swing near 4,9,16,24,36,49,72,81)
      F: Price-time squaring (Sq9 degree of price ~ Sq9 degree of time)
      G: Planetary alignment (barrier planet Sq9 degree matches entry price)

    Returns dict with individual flags, total score, and detail strings.
    """
    result = {
        "sq9_swing_n": False,       # Factor A
        "sq9_swing_n1": False,      # Factor B
        "vibration": False,         # Factor C
        "proportional": False,      # Factor D
        "natural_sq_timing": False, # Factor E
        "price_time_sq": False,     # Factor F
        "planetary": False,         # Factor G
        "planetary_timing": 0,      # Bonus: middle wheel timing score
        "score": 0,
        "details": [],
    }

    if len(h1_swings) < 3:
        return result

    recent = h1_swings.tail(10)

    # --- Factor A: Sq9 from most recent swing ---
    last_swing = recent.iloc[-1]
    ref_a = last_swing["price"]
    for deg in [30, 45, 60, 90, 120, 180, 270, 360]:
        lvl_up = gann.sq9_add_degrees(ref_a, deg)
        lvl_dn = gann.sq9_subtract_degrees(ref_a, deg)
        if min(abs(entry_price - lvl_up), abs(entry_price - lvl_dn)) <= tolerance:
            result["sq9_swing_n"] = True
            result["details"].append(f"Sq9+/-{deg}deg from swing[-1]")
            break

    # --- Factor B: Sq9 from second most recent swing (independent) ---
    if len(recent) >= 2:
        prev_swing = recent.iloc[-2]
        ref_b = prev_swing["price"]
        for deg in [30, 45, 60, 90, 120, 180, 270, 360]:
            lvl_up = gann.sq9_add_degrees(ref_b, deg)
            lvl_dn = gann.sq9_subtract_degrees(ref_b, deg)
            if min(abs(entry_price - lvl_up), abs(entry_price - lvl_dn)) <= tolerance:
                result["sq9_swing_n1"] = True
                result["details"].append(f"Sq9+/-{deg}deg from swing[-2]")
                break

    # --- Factor C: Vibration multiple from any recent swing ---
    for _, sw in recent.iterrows():
        move = abs(entry_price - sw["price"])
        if move > 5 and vibration > 0:
            rem = move % vibration
            if min(rem, vibration - rem) <= 3.0:
                n_mult = round(move / vibration)
                result["vibration"] = True
                result["details"].append(f"Vx{n_mult} from ${sw['price']:.0f}")
                break

    # --- Factor D: Proportional level of recent swing range ---
    if len(recent) >= 2:
        for i in range(len(recent) - 1):
            if result["proportional"]:
                break
            p1 = recent.iloc[i]["price"]
            p2 = recent.iloc[i + 1]["price"]
            swing_range = abs(p1 - p2)
            if swing_range > 5:
                low = min(p1, p2)
                for frac_name, frac in [("1/3", 1/3), ("1/2", 1/2), ("2/3", 2/3), ("3/4", 3/4)]:
                    expected = low + swing_range * frac
                    if abs(entry_price - expected) <= tolerance:
                        result["proportional"] = True
                        result["details"].append(f"Prop {frac_name} of ${swing_range:.0f} range")
                        break

    # --- Factor E: Natural square timing ---
    for ns in gann.NATURAL_SQUARES:
        if abs(bars_from_last_swing - ns) <= 2:
            result["natural_sq_timing"] = True
            result["details"].append(f"Timing near {ns} bars (actual={bars_from_last_swing})")
            break

    # --- Factor F: Price-time squaring ---
    if len(recent) >= 1:
        last_ref = recent.iloc[-1]["price"]
        price_move = abs(entry_price - last_ref)
        if price_move > 1 and bars_from_last_swing > 1:
            p_deg = gann.price_to_sq9_degree(price_move)
            t_deg = gann.price_to_sq9_degree(bars_from_last_swing)
            diff = abs(p_deg - t_deg)
            diff = min(diff, 360 - diff)
            if diff <= 15:
                result["price_time_sq"] = True
                result["details"].append(f"P-T squared: delta {diff:.0f}deg")

    # --- Factor G: Planetary alignment (Ferro's "third wheel") ---
    # STUBBED: needs calibration on known past power points.
    # Current random degree matching has no edge (~95% hit rate = noise).
    # TODO: research proper planet-price calibration for Gold.

    # Total independent score
    result["score"] = sum([
        result["sq9_swing_n"],
        result["sq9_swing_n1"],
        result["vibration"],
        result["proportional"],
        result["natural_sq_timing"],
        result["price_time_sq"],
        result["planetary"],
    ])

    return result


def check_three_limits(
    entry_price: float,
    ref_swing_price: float,
    bars_from_ref: int,
    h1_swings: pd.DataFrame,
    vibration: float = 12.0,
    tolerance: float = 5.0,
) -> dict:
    """Check Hellcat's 3-limit alignment system.

    THREE LIMITS must align (most traders use only one):
      Limit 1: Price-by-Time — Sq9 degree of PRICE move ≈ Sq9 degree of TIME elapsed
      Limit 2: Price-by-Price — entry matches a Gann price level (Sq9/vibration/proportional)
      Limit 3: Time-by-Time — swing duration matches a Gann time target (natural squares)

    When all three align = 85-96% per Hellcat (Part 3.10).
    "If you know 1/3 of the movement, the remaining 2/3 is determined."

    Returns dict with each limit status and combined confidence.
    """
    result = {
        "limit1_price_by_time": False,
        "limit2_price_by_price": False,
        "limit3_time_by_time": False,
        "limits_aligned": 0,
        "details": [],
    }

    # --- Limit 1: Price-by-Time ---
    # Ferro: "86/86", "60/60", "116/116" — same NUMBER in price and time units.
    # For Gold: scale price move by vibration quantum (12) to get Gann price units.
    # Then compare Sq9 degrees of scaled price vs time bars.
    # Also check direct ratio: price_move / bars = near a Gann angle (1:1, 2:1, 1:2).
    price_move = abs(entry_price - ref_swing_price)
    if price_move > 1 and bars_from_ref > 1:
        # Method A: Sq9 degree comparison with vibration-scaled price
        scaled_price = price_move / vibration if vibration > 0 else price_move
        p_deg = gann.price_to_sq9_degree(scaled_price)
        t_deg = gann.price_to_sq9_degree(bars_from_ref)
        diff = abs(p_deg - t_deg)
        diff = min(diff, 360 - diff)
        if diff <= 20:
            result["limit1_price_by_time"] = True
            result["details"].append(f"L1: Pdeg={p_deg:.0f} Tdeg={t_deg:.0f} delta={diff:.0f} (scaled)")

        # Method B: Direct ratio check — Gann angles are 1:1, 2:1, 1:2, 4:1, 1:4
        if not result["limit1_price_by_time"]:
            ratio = scaled_price / bars_from_ref
            gann_angles = [0.25, 0.5, 1.0, 2.0, 4.0]  # 1:4, 1:2, 1:1, 2:1, 4:1
            for angle in gann_angles:
                if abs(ratio - angle) / angle <= 0.15:  # 15% tolerance
                    result["limit1_price_by_time"] = True
                    result["details"].append(
                        f"L1: ratio={ratio:.2f} ~= {angle} (Gann angle)")
                    break

    # --- Limit 2: Price-by-Price ---
    # Does entry price sit on a Gann price level from ANY recent swing?
    if len(h1_swings) >= 2:
        recent = h1_swings.tail(5)
        for _, sw in recent.iterrows():
            if result["limit2_price_by_price"]:
                break
            ref = sw["price"]
            # Check Sq9 levels
            for deg in [30, 45, 60, 90, 120, 180, 270, 360]:
                lvl_up = gann.sq9_add_degrees(ref, deg)
                lvl_dn = gann.sq9_subtract_degrees(ref, deg)
                if min(abs(entry_price - lvl_up), abs(entry_price - lvl_dn)) <= tolerance:
                    result["limit2_price_by_price"] = True
                    result["details"].append(f"L2: Sq9+/-{deg}deg from ${ref:.0f}")
                    break
            # Check vibration multiples
            if not result["limit2_price_by_price"]:
                move = abs(entry_price - ref)
                if move > 5 and vibration > 0:
                    rem = move % vibration
                    if min(rem, vibration - rem) <= 3.0:
                        result["limit2_price_by_price"] = True
                        result["details"].append(f"L2: V-multiple from ${ref:.0f}")

    # --- Limit 3: Time-by-Time ---
    # Does the duration from reference swing match a Gann time target?
    # Check natural squares
    for ns in gann.NATURAL_SQUARES:
        if abs(bars_from_ref - ns) <= 2:
            result["limit3_time_by_time"] = True
            result["details"].append(f"L3: {bars_from_ref} bars ~= {ns} (natural square)")
            break

    # Also check proportional time divisions of the prior swing duration
    if not result["limit3_time_by_time"] and len(h1_swings) >= 3:
        recent = h1_swings.tail(5)
        for i in range(len(recent) - 1):
            prior_dur = abs(recent.iloc[i + 1]["bar_index"] - recent.iloc[i]["bar_index"])
            if prior_dur > 3:
                for frac_name, frac in [("1/3", 1/3), ("1/2", 1/2), ("2/3", 2/3), ("1.0", 1.0)]:
                    expected_time = prior_dur * frac
                    if abs(bars_from_ref - expected_time) <= 2:
                        result["limit3_time_by_time"] = True
                        result["details"].append(
                            f"L3: {bars_from_ref} bars ~= {frac_name}x{prior_dur} (proportional time)")
                        break
            if result["limit3_time_by_time"]:
                break

    result["limits_aligned"] = sum([
        result["limit1_price_by_time"],
        result["limit2_price_by_price"],
        result["limit3_time_by_time"],
    ])

    return result


# ============================================================
# Gann's 5 Rules for Trend Changes (Ch 11 of Master Course)
# ============================================================

def filter_time_overbalance(
    m5_closes: np.ndarray,
    entry_idx: int,
    direction: str,
    lookback: int = 72,  # ~6 hours of M5 bars
) -> bool:
    """Gann Rule 2: Time overbalancing.

    'When a reversal comes that exceeds the previous TIME movement,
    consider that the trend has changed, at least temporarily.'

    If the current reaction in TIME exceeds the prior impulse in TIME,
    the trend may have changed → don't trade in the old direction.
    """
    if entry_idx < lookback + 10:
        return True

    segment = m5_closes[entry_idx - lookback:entry_idx + 1]
    if len(segment) < 20:
        return True

    # Find the last peak and trough in the segment
    peak_idx = np.argmax(segment)
    trough_idx = np.argmin(segment)

    # Determine which came first to know the impulse direction
    if peak_idx < trough_idx:
        # Up move then down move (impulse=up, reaction=down)
        impulse_time = peak_idx  # bars from start to peak
        reaction_time = trough_idx - peak_idx  # bars from peak to trough
        current_move_dir = "short"  # We're in the reaction (down)
    else:
        # Down move then up move (impulse=down, reaction=up)
        impulse_time = trough_idx
        reaction_time = peak_idx - trough_idx
        current_move_dir = "long"

    if impulse_time <= 0:
        return True

    # If reaction time exceeds impulse time, trend may have changed
    if reaction_time > impulse_time:
        # We're in a time-overbalanced state
        # Trading in the OLD impulse direction is risky
        if direction != current_move_dir:
            return False  # Don't trade against the overbalancing

    return True


def filter_price_overbalance(
    m5_closes: np.ndarray,
    entry_idx: int,
    direction: str,
    lookback: int = 72,
) -> bool:
    """Gann Rule 4: Price overbalancing.

    'When the price breaks back one-half or more of the previous SWING,
    this is an indication of a change in trend.'

    If current retracement exceeds 50% of prior impulse, trend weakening.
    """
    if entry_idx < lookback + 10:
        return True

    segment = m5_closes[entry_idx - lookback:entry_idx + 1]
    if len(segment) < 20:
        return True

    peak = np.max(segment)
    trough = np.min(segment)
    current = segment[-1]

    swing_range = peak - trough
    if swing_range < 5:
        return True

    peak_idx = np.argmax(segment)
    trough_idx = np.argmin(segment)

    if peak_idx > trough_idx:
        # Last major move was UP, now checking retracement
        retracement = peak - current
        if retracement > swing_range * 0.5:
            # More than 50% retraced → up trend weakening
            if direction == "long":
                return False
    else:
        # Last major move was DOWN, now checking rally
        rally = current - trough
        if rally > swing_range * 0.5:
            # More than 50% rallied → down trend weakening
            if direction == "short":
                return False

    return True


def filter_fourth_time_through(
    m5_closes: np.ndarray,
    m5_highs: np.ndarray,
    m5_lows: np.ndarray,
    entry_idx: int,
    gann_level: float,
    direction: str,
    lookback: int = 144,  # ~12 hours of M5
    touch_tolerance: float = 3.0,
) -> bool:
    """Gann Rule: Fourth time through.

    'When prices reach the same level the fourth time, they nearly
    always go through.'  — Gann Ch 11

    If this is the 4th (or more) touch of a level, DON'T fade it.
    Only trade WITH the breakout direction.
    """
    if entry_idx < lookback:
        return True

    # Count how many times price has touched this level
    touch_count = 0
    start = max(0, entry_idx - lookback)
    for i in range(start, entry_idx):
        if m5_lows[i] <= gann_level + touch_tolerance and m5_highs[i] >= gann_level - touch_tolerance:
            touch_count += 1

    if touch_count >= 3:
        # This is the 4th+ touch — price likely breaks through
        # Only allow trades WITH the breakout (not fading)
        current = m5_closes[entry_idx]
        if direction == "long" and current < gann_level:
            return False  # Don't go long below level on 4th touch
        if direction == "short" and current > gann_level:
            return False  # Don't go short above level on 4th touch

    return True


def detect_signal_bar(
    m5_opens: np.ndarray,
    m5_highs: np.ndarray,
    m5_lows: np.ndarray,
    m5_closes: np.ndarray,
    bar_idx: int,
) -> dict:
    """Detect Gann Signal Day/Bar pattern.

    Gann: 'On the day that an option has a sharp break after a prolonged
    decline, it closes higher than the opening or above the halfway point...
    it is an indication that the buying is better than the selling.'

    On M5 bars: a wide-range bar that closes in the opposite direction
    of the prior move = exhaustion/reversal signal.
    """
    if bar_idx < 5:
        return {"is_signal": False}

    bar_open = m5_opens[bar_idx]
    bar_high = m5_highs[bar_idx]
    bar_low = m5_lows[bar_idx]
    bar_close = m5_closes[bar_idx]
    bar_range = bar_high - bar_low

    if bar_range < 1.0:
        return {"is_signal": False}

    # Calculate prior move direction (last 5 bars)
    prior_move = m5_closes[bar_idx] - m5_closes[bar_idx - 5]

    # Bar midpoint
    midpoint = (bar_high + bar_low) / 2

    # Bullish signal: close above midpoint after decline
    if prior_move < -2.0 and bar_close > midpoint:
        return {
            "is_signal": True,
            "direction": "long",
            "strength": (bar_close - bar_low) / bar_range,  # 0-1
        }

    # Bearish signal: close below midpoint after advance
    if prior_move > 2.0 and bar_close < midpoint:
        return {
            "is_signal": True,
            "direction": "short",
            "strength": (bar_high - bar_close) / bar_range,
        }

    return {"is_signal": False}


def apply_all_filters(
    direction: str,
    entry_price: float,
    entry_idx: int,
    gann_level: float,
    m5_closes: np.ndarray,
    h1_closes: np.ndarray,
    h1_bar_idx: int,
    ref_swing_price: float,
    bars_from_ref: int,
    skip_trend_filter: bool = False,
    m5_highs: np.ndarray | None = None,
    m5_lows: np.ndarray | None = None,
    m5_opens: np.ndarray | None = None,
) -> tuple[bool, str]:
    """Apply ALL Gann filters. Returns (pass, reason_if_failed).

    skip_trend_filter: When using angle-based direction, the H1 SMA trend
    filter is redundant (angles already determine trend). Skip it to avoid
    conflicting signals that kill trade frequency.
    """
    if not skip_trend_filter:
        if not filter_h1_trend_alignment(h1_closes, h1_bar_idx, direction):
            return False, "trend_misalign"

    if not filter_fold_at_third(m5_closes, entry_idx, direction):
        return False, "fold_at_third"

    if not filter_speed_acceleration(m5_closes, entry_idx):
        return False, "speed_exhaustion"

    if not filter_price_time_squaring(entry_price, ref_swing_price, bars_from_ref):
        return False, "not_squared"

    if not filter_time_not_expired(bars_from_ref):
        return False, "time_expired"

    if not filter_price_not_ahead(m5_closes, entry_idx, gann_level, direction):
        return False, "price_ahead"

    # NEW: Fourth-time-through rule (Gann Ch 11)
    if m5_highs is not None and m5_lows is not None:
        if not filter_fourth_time_through(
            m5_closes, m5_highs, m5_lows, entry_idx, gann_level, direction
        ):
            return False, "fourth_touch_breakout"

    return True, "passed"
