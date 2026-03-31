"""
Gann Geometric Angles — Direction determination from swing highs/lows.

Implements Gann's core teaching from Ch 5A/5B of the Master Commodities Course:
  "The first and always most important angle to draw is a 45-degree angle...
   As long as the market stays above the 45-degree angle, it is in a strong
   position and indicates higher prices."

  "Angles coming down from tops and crossing angles coming up from bottom
   are very important for a change in trend when they cross each other."

The angle ratios (price per time period) from the Gann course:
  Bull side: 1x1 (45°), 2x1 (63.75°), 4x1 (75°), 8x1 (82.5°)
  Bear side: 1x2 (26.25°), 1x4 (15°), 1x8 (7.5°)

Gold vibration base: V=72 (Hellcat formula N=3 → 73.18≈72, confirmed on charts).
Subdivisions: 72/6=12, 72/4=18, 72/3=24, 72/2=36.
Ferro KU series: 1, 2, 3, 5, 7, 11.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field


# ============================================================
# Constants
# ============================================================

GOLD_VIBRATION_BASE = 72.0  # Confirmed by empirical testing on charts

# Gann angle ratios: name -> (price_units_per_time_unit)
# From ascending (low) perspective: how many price units per bar
ANGLE_RATIOS = {
    "1x8": 1 / 8,    # 7.125° — flattest support
    "1x4": 1 / 4,    # 14.04°
    "1x3": 1 / 3,    # 18.43° — important per Gann (3x1 on bear side)
    "1x2": 1 / 2,    # 26.57°
    "1x1": 1.0,       # 45.00° — THE balance line, most important
    "2x1": 2.0,       # 63.43°
    "3x1": 3.0,       # 71.57° — important after prolonged advances
    "4x1": 4.0,       # 75.96°
    "8x1": 8.0,       # 82.88° — steepest, strongest position
}

# Primary angles to use (Gann: "these are all the angles you need")
PRIMARY_RATIOS = ["1x2", "1x1", "2x1", "4x1"]

# Lost motion tolerance (Gann: "2-2.5 units", Ferro: "+/-2 rarely 3")
LOST_MOTION = 3.0


# ============================================================
# Data Structures
# ============================================================

@dataclass
class GannAngle:
    """A single geometric angle line from a swing point."""
    pivot_price: float       # Price at pivot point
    pivot_bar_idx: int       # Bar index of pivot
    pivot_time: object       # Timestamp (pd.Timestamp or None)
    direction: str           # "ascending" (from low) or "descending" (from high)
    ratio_name: str          # e.g., "1x1", "2x1"
    ratio: float             # Price units per time unit
    scale: float             # $/bar for 1 unit (instrument-specific)

    def price_at_bar(self, bar_idx: int) -> float:
        """Compute this angle's price at a given bar index."""
        bars_elapsed = bar_idx - self.pivot_bar_idx
        if bars_elapsed < 0:
            return self.pivot_price
        price_change = bars_elapsed * self.scale * self.ratio
        if self.direction == "ascending":
            return self.pivot_price + price_change
        else:
            return self.pivot_price - price_change

    def bar_at_price(self, target_price: float) -> float:
        """Compute bar index where this angle reaches a target price."""
        if self.scale * self.ratio == 0:
            return float('inf')
        if self.direction == "ascending":
            return self.pivot_bar_idx + (target_price - self.pivot_price) / (self.scale * self.ratio)
        else:
            return self.pivot_bar_idx + (self.pivot_price - target_price) / (self.scale * self.ratio)


@dataclass
class AngleField:
    """Complete set of angles from a single swing point."""
    pivot_price: float
    pivot_bar_idx: int
    pivot_time: object
    pivot_type: str           # "high" or "low"
    scale: float
    timeframe: str
    angles: list = field(default_factory=list)


# ============================================================
# Scale Calibration
# ============================================================

def get_default_scales() -> dict:
    """Default $/bar scales per timeframe based on V=72.

    The 1x1 angle means price moves 1 'unit' per bar.
    For Gold, 1 unit = scale dollars.

    Derived from V=72 base vibration:
      D1: V=72 (base vibration per day)
      H4: V/6 * 4 = 48 (4 hours of daily vibration)
      H1: V/6 = 12 (hourly subdivision)
      M5: V/6/12 = 1.0 (5-min subdivision of hourly)

    These are starting values — calibrate_scale() refines them.
    """
    return {
        "D1": 72.0,
        "H4": 48.0,
        "H1": 12.0,
        "M15": 3.0,
        "M5": 1.0,
    }


def calibrate_scale(
    swings_df: pd.DataFrame,
    ohlc_df: pd.DataFrame,
    candidates: list[float] | None = None,
    vibration: float = GOLD_VIBRATION_BASE,
) -> dict:
    """Empirically find the best $/bar scale for the 1x1 angle.

    Method: For each swing low→high pair, draw the ascending 1x1 at each
    candidate scale. Measure what fraction of trend bars stay above the 1x1.
    Gann says the correct 1x1 is the one price "rests on" during trends.
    Target: ~60-75% of impulse bars above the 1x1.

    Also tests descending 1x1 from highs (% of bars below during downtrends).
    """
    if candidates is None:
        # Based on V=72 subdivisions + KU series members
        candidates = [1.0, 2.0, 3.0, 5.0, 7.0, 12.0, 18.0, 24.0, 36.0, 72.0]

    closes = ohlc_df["close"].values
    lows = ohlc_df["low"].values
    highs = ohlc_df["high"].values
    n = len(ohlc_df)

    if len(swings_df) < 4:
        return {"best_scale": vibration / 6, "scores": {}}

    results = {}
    for scale in candidates:
        above_counts = []
        below_counts = []

        for i in range(len(swings_df) - 1):
            s1 = swings_df.iloc[i]
            s2 = swings_df.iloc[i + 1]
            start_idx = int(s1["bar_index"])
            end_idx = int(s2["bar_index"])
            if end_idx - start_idx < 3:
                continue

            if s1["type"] == "low" and s2["type"] == "high":
                # Ascending 1x1 from low — count % of bars above
                pivot = s1["price"]
                total = 0
                above = 0
                for j in range(start_idx + 1, min(end_idx + 1, n)):
                    angle_price = pivot + (j - start_idx) * scale
                    total += 1
                    if closes[j] >= angle_price - LOST_MOTION:
                        above += 1
                if total > 0:
                    above_counts.append(above / total)

            elif s1["type"] == "high" and s2["type"] == "low":
                # Descending 1x1 from high — count % of bars below
                pivot = s1["price"]
                total = 0
                below = 0
                for j in range(start_idx + 1, min(end_idx + 1, n)):
                    angle_price = pivot - (j - start_idx) * scale
                    total += 1
                    if closes[j] <= angle_price + LOST_MOTION:
                        below += 1
                if total > 0:
                    below_counts.append(below / total)

        # Combine: we want ~65% of trend bars to be on the correct side
        # (not too tight = price always above, not too loose = price always below)
        all_scores = above_counts + below_counts
        if all_scores:
            mean_pct = np.mean(all_scores)
            # Best scale: closest to 65% (Gann's "strong position" = above 1x1)
            target = 0.65
            score = 1.0 - abs(mean_pct - target)
        else:
            mean_pct = 0.0
            score = 0.0

        results[scale] = {
            "mean_pct_correct": mean_pct,
            "score": score,
            "n_upswings": len(above_counts),
            "n_downswings": len(below_counts),
        }

    # Best = highest score
    best_scale = max(results, key=lambda s: results[s]["score"])
    return {
        "best_scale": best_scale,
        "scores": results,
    }


# ============================================================
# Angle Construction
# ============================================================

def build_angle_field(
    pivot_price: float,
    pivot_bar_idx: int,
    pivot_time: object,
    pivot_type: str,
    scale: float,
    timeframe: str = "M5",
    ratio_names: list[str] | None = None,
) -> AngleField:
    """Build a complete set of Gann angles from one swing point.

    From a swing low: ascending angles (price increases over time)
    From a swing high: descending angles (price decreases over time)
    """
    if ratio_names is None:
        ratio_names = list(PRIMARY_RATIOS)

    af = AngleField(
        pivot_price=pivot_price,
        pivot_bar_idx=pivot_bar_idx,
        pivot_time=pivot_time,
        pivot_type=pivot_type,
        scale=scale,
        timeframe=timeframe,
    )

    direction = "ascending" if pivot_type == "low" else "descending"

    for name in ratio_names:
        ratio = ANGLE_RATIOS[name]
        angle = GannAngle(
            pivot_price=pivot_price,
            pivot_bar_idx=pivot_bar_idx,
            pivot_time=pivot_time,
            direction=direction,
            ratio_name=name,
            ratio=ratio,
            scale=scale,
        )
        af.angles.append(angle)

    return af


def compute_active_angles(
    swings_df: pd.DataFrame,
    current_bar_idx: int,
    scale: float,
    max_age_bars: int = 500,
    max_pivots: int = 10,
    ratio_names: list[str] | None = None,
) -> list[GannAngle]:
    """Return all currently active angles from recent swing points.

    An angle is active if its pivot is within max_age_bars and its
    projected price at current_bar is within a reasonable range.
    """
    if len(swings_df) == 0:
        return []

    # Only use swings up to current bar
    mask = swings_df["bar_index"] <= current_bar_idx
    active_swings = swings_df[mask].tail(max_pivots)

    all_angles = []
    for _, sw in active_swings.iterrows():
        age = current_bar_idx - sw["bar_index"]
        if age > max_age_bars or age < 0:
            continue

        af = build_angle_field(
            pivot_price=sw["price"],
            pivot_bar_idx=int(sw["bar_index"]),
            pivot_time=sw.get("time"),
            pivot_type=sw["type"],
            scale=scale,
            ratio_names=ratio_names,
        )
        all_angles.extend(af.angles)

    return all_angles


# ============================================================
# Direction Determination
# ============================================================

def determine_angle_direction(
    current_price: float,
    current_bar_idx: int,
    active_angles: list[GannAngle],
    lost_motion: float = LOST_MOTION,
) -> dict:
    """Determine directional bias from Gann angle field.

    Gann Ch 5A: "As long as the market stays above the 45-degree angle,
    it is in a strong position and indicates higher prices."

    Gann Ch 5B: "After an option makes bottom and starts up, draw angles
    from the low point... After it makes top, draw angles from the top."

    Strategy (following Gann's actual rules):
    1. Find the MOST RECENT swing point (whether high or low)
    2. If last swing was LOW: check ascending 1x1 — if price above → LONG
    3. If last swing was HIGH: check descending 1x1 — if price below → SHORT
    4. If the angle has been broken, check the NEXT most recent opposite angle
    5. Strength = how many angle levels support the direction

    This eliminates the "neutral zone" problem: the most recent swing always
    gives a clear direction unless its angle has been broken.
    """
    result = {
        "direction": "neutral",
        "strength": 0,
        "nearest_support_angle": None,
        "nearest_resistance_angle": None,
        "asc_1x1_price": None,
        "desc_1x1_price": None,
        "details": [],
    }

    if not active_angles:
        return result

    ascending = [a for a in active_angles if a.direction == "ascending"]
    descending = [a for a in active_angles if a.direction == "descending"]

    # Find the most recent ascending and descending 1x1 angles
    asc_1x1 = _find_most_recent(ascending, "1x1", current_bar_idx)
    desc_1x1 = _find_most_recent(descending, "1x1", current_bar_idx)

    asc_1x1_price = asc_1x1.price_at_bar(current_bar_idx) if asc_1x1 else None
    desc_1x1_price = desc_1x1.price_at_bar(current_bar_idx) if desc_1x1 else None

    result["asc_1x1_price"] = asc_1x1_price
    result["desc_1x1_price"] = desc_1x1_price

    # Determine which swing is more recent
    most_recent_asc_bar = asc_1x1.pivot_bar_idx if asc_1x1 else -1
    most_recent_desc_bar = desc_1x1.pivot_bar_idx if desc_1x1 else -1

    if most_recent_asc_bar > most_recent_desc_bar:
        # Most recent swing was a LOW → primary bias is LONG
        # Check if price is still above the ascending 1x1
        if asc_1x1_price is not None and current_price >= asc_1x1_price - lost_motion:
            result["direction"] = "long"
        elif desc_1x1_price is not None and current_price <= desc_1x1_price + lost_motion:
            # Ascending 1x1 broken, AND below descending → bearish
            result["direction"] = "short"
        else:
            # Ascending broken but not yet below descending → still lean long
            # (price retraced but hasn't reversed fully)
            result["direction"] = "long"
    elif most_recent_desc_bar > most_recent_asc_bar:
        # Most recent swing was a HIGH → primary bias is SHORT
        if desc_1x1_price is not None and current_price <= desc_1x1_price + lost_motion:
            result["direction"] = "short"
        elif asc_1x1_price is not None and current_price >= asc_1x1_price - lost_motion:
            # Descending 1x1 broken, AND above ascending → bullish
            result["direction"] = "long"
        else:
            result["direction"] = "short"
    else:
        # No angles or same bar → use price relative to both
        if asc_1x1_price is not None and current_price > asc_1x1_price:
            result["direction"] = "long"
        elif desc_1x1_price is not None and current_price < desc_1x1_price:
            result["direction"] = "short"

    # Calculate strength: count supporting angles
    bull_strength = 0
    bear_strength = 0

    for a in ascending:
        a_price = a.price_at_bar(current_bar_idx)
        if current_price > a_price - lost_motion:
            bull_strength += 1

    for a in descending:
        a_price = a.price_at_bar(current_bar_idx)
        if current_price < a_price + lost_motion:
            bear_strength += 1

    if result["direction"] == "long":
        result["strength"] = bull_strength
    elif result["direction"] == "short":
        result["strength"] = bear_strength

    # Find nearest support and resistance angles for SL/TP
    result["nearest_support_angle"] = _find_nearest_support(
        ascending, current_price, current_bar_idx, lost_motion
    )
    result["nearest_resistance_angle"] = _find_nearest_resistance(
        descending, current_price, current_bar_idx, lost_motion
    )

    if asc_1x1_price is not None:
        result["details"].append(f"Asc 1x1=${asc_1x1_price:.1f}")
    if desc_1x1_price is not None:
        result["details"].append(f"Desc 1x1=${desc_1x1_price:.1f}")
    result["details"].append(f"Bull str={bull_strength}, Bear str={bear_strength}")

    return result


def multi_tf_direction(
    directions_by_tf: dict,
    timeframe_priority: list[str] | None = None,
) -> dict:
    """Multi-timeframe angle direction alignment.

    Gann's execution hierarchy:
      D1 → overall direction (60-75% probability)
      H1 → entry direction (must agree with D1)
      M5 → entry timing (must agree with H1)

    Only trade when all available timeframes agree.
    """
    if timeframe_priority is None:
        timeframe_priority = ["D1", "H4", "H1", "M5"]

    result = {
        "direction": "neutral",
        "aligned": False,
        "tf_directions": {},
        "alignment_count": 0,
    }

    directions = []
    for tf in timeframe_priority:
        if tf in directions_by_tf:
            d = directions_by_tf[tf]
            dir_val = d["direction"] if isinstance(d, dict) else d
            result["tf_directions"][tf] = dir_val
            if dir_val != "neutral":
                directions.append(dir_val)

    if not directions:
        return result

    # Check alignment: all non-neutral directions must agree
    unique_dirs = set(directions)
    if len(unique_dirs) == 1:
        result["direction"] = directions[0]
        result["aligned"] = True
        result["alignment_count"] = len(directions)
    else:
        # Conflict — use highest timeframe's direction but mark not aligned
        for tf in timeframe_priority:
            if tf in result["tf_directions"] and result["tf_directions"][tf] != "neutral":
                result["direction"] = result["tf_directions"][tf]
                break
        result["aligned"] = False
        result["alignment_count"] = max(
            sum(1 for d in directions if d == "long"),
            sum(1 for d in directions if d == "short"),
        )

    return result


# ============================================================
# Angle-Based SL/TP
# ============================================================

def angle_based_sl(
    direction: str,
    entry_price: float,
    current_bar_idx: int,
    active_angles: list[GannAngle],
    lost_motion: float = LOST_MOTION,
    fallback_sl: float = 10.0,
) -> float:
    """Calculate stop loss based on nearest supporting angle.

    Gann Ch 5A: "You can buy every time it rests on the 45-degree angle
    with a stop loss order 1, 2, or 3 cents under the 45-degree angle."
    """
    if direction == "long":
        # Find ascending angle just below entry price
        support = _find_nearest_support(
            [a for a in active_angles if a.direction == "ascending"],
            entry_price, current_bar_idx, lost_motion
        )
        if support:
            sl_price = support.price_at_bar(current_bar_idx) - lost_motion
            # Sanity: SL must be below entry
            if sl_price < entry_price:
                return sl_price
        return entry_price - fallback_sl
    else:
        # Find descending angle just above entry price
        resistance = _find_nearest_resistance(
            [a for a in active_angles if a.direction == "descending"],
            entry_price, current_bar_idx, lost_motion
        )
        if resistance:
            sl_price = resistance.price_at_bar(current_bar_idx) + lost_motion
            if sl_price > entry_price:
                return sl_price
        return entry_price + fallback_sl


def angle_based_tp(
    direction: str,
    entry_price: float,
    current_bar_idx: int,
    active_angles: list[GannAngle],
    gann_levels: list | None = None,
    fallback_tp: float = 23.0,
) -> float:
    """Calculate take profit from next angle crossing or convergence level.

    Priority: next convergence level in direction > angle projection > fallback.
    """
    # First try: next Gann convergence level (existing logic, pass through)
    if gann_levels:
        best_tp = None
        for lvl in gann_levels:
            lvl_price = lvl if isinstance(lvl, (int, float)) else lvl.get("price", lvl)
            if direction == "long" and lvl_price > entry_price + 3.0:
                if best_tp is None or lvl_price < best_tp:
                    best_tp = lvl_price
            elif direction == "short" and lvl_price < entry_price - 3.0:
                if best_tp is None or lvl_price > best_tp:
                    best_tp = lvl_price
        if best_tp is not None and abs(best_tp - entry_price) < 150.0:
            return best_tp

    # Fallback
    if direction == "long":
        return entry_price + fallback_tp
    else:
        return entry_price - fallback_tp


# ============================================================
# Helper Functions
# ============================================================

def _find_most_recent(
    angles: list[GannAngle],
    ratio_name: str,
    current_bar_idx: int,
) -> GannAngle | None:
    """Find the most recent angle of a specific ratio type."""
    matching = [a for a in angles if a.ratio_name == ratio_name]
    if not matching:
        return None
    # Most recent = highest pivot_bar_idx that is <= current_bar
    valid = [a for a in matching if a.pivot_bar_idx <= current_bar_idx]
    if not valid:
        return None
    return max(valid, key=lambda a: a.pivot_bar_idx)


def _find_nearest_support(
    ascending_angles: list[GannAngle],
    current_price: float,
    current_bar_idx: int,
    lost_motion: float = LOST_MOTION,
) -> GannAngle | None:
    """Find the ascending angle closest below current price (support)."""
    best = None
    best_dist = float('inf')
    for a in ascending_angles:
        a_price = a.price_at_bar(current_bar_idx)
        if a_price < current_price + lost_motion:
            dist = current_price - a_price
            if 0 <= dist < best_dist:
                best = a
                best_dist = dist
    return best


def _find_nearest_resistance(
    descending_angles: list[GannAngle],
    current_price: float,
    current_bar_idx: int,
    lost_motion: float = LOST_MOTION,
) -> GannAngle | None:
    """Find the descending angle closest above current price (resistance)."""
    best = None
    best_dist = float('inf')
    for a in descending_angles:
        a_price = a.price_at_bar(current_bar_idx)
        if a_price > current_price - lost_motion:
            dist = a_price - current_price
            if 0 <= dist < best_dist:
                best = a
                best_dist = dist
    return best
