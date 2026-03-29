"""
Triangle Engine — Angle crossing detection for Gann's "figure nobody uses."

Hellcat: "The main meaning of Gann's System is in that FIGURE which nobody uses."
Gann Ch 5A: "Angles coming down from tops and crossing angles coming up from
bottom are very important for a change in trend when they cross each other."

A triangle forms when:
  - An ascending angle from a swing low AND
  - A descending angle from a swing high
  converge to the same price at the same time.

The crossing point gives:
  - A PRICE target (where the angles meet)
  - A TIME target (when the angles meet)
  - A DIRECTION bias (which angle set dominates)

Triangle proximity is used as a QUALITY BONUS (adds to convergence score),
NOT a hard gate — to maintain 1-5 trades/day scalping frequency.
"""

import numpy as np
from dataclasses import dataclass, field
from .gann_angles import GannAngle, ANGLE_RATIOS


# ============================================================
# Data Structures
# ============================================================

@dataclass
class AngleCrossing:
    """A point where an ascending and descending angle cross."""
    bar_idx: float           # Bar index of crossing (can be fractional)
    price: float             # Price at crossing
    ascending_angle: GannAngle
    descending_angle: GannAngle
    asc_ratio: str           # e.g., "1x1"
    desc_ratio: str          # e.g., "1x1"
    importance: int          # Higher = more important
    time_from_now: float     # Bars from current bar (negative = past)


@dataclass
class TriangleZone:
    """A cluster of nearby crossings forming a triangle setup."""
    center_bar: float
    center_price: float
    crossings: list = field(default_factory=list)
    num_crossings: int = 0
    importance_score: float = 0.0
    predicted_direction: str = "neutral"  # "long" or "short"


# Importance weights for crossing types
CROSSING_IMPORTANCE = {
    ("1x1", "1x1"): 10,  # Gann's "gravity center" — highest priority
    ("1x1", "2x1"): 8,
    ("2x1", "1x1"): 8,
    ("1x1", "1x2"): 7,
    ("1x2", "1x1"): 7,
    ("2x1", "2x1"): 7,
    ("1x1", "4x1"): 6,
    ("4x1", "1x1"): 6,
    ("2x1", "4x1"): 5,
    ("4x1", "2x1"): 5,
    ("1x2", "2x1"): 5,
}
DEFAULT_IMPORTANCE = 3


# ============================================================
# Crossing Calculation
# ============================================================

def compute_crossing(
    asc_angle: GannAngle,
    desc_angle: GannAngle,
) -> AngleCrossing | None:
    """Compute where an ascending and descending angle cross.

    Math:
      Ascending:  P(t) = price_L + (t - bar_L) * S * R_a
      Descending: P(t) = price_H - (t - bar_H) * S * R_d

      Setting equal:
        price_L + (t - bar_L)*S*R_a = price_H - (t - bar_H)*S*R_d
        t * S * (R_a + R_d) = price_H - price_L + bar_L*S*R_a + bar_H*S*R_d
        t = (price_H - price_L + bar_L*S*R_a + bar_H*S*R_d) / (S * (R_a + R_d))
    """
    if asc_angle.direction != "ascending" or desc_angle.direction != "descending":
        return None

    S_a = asc_angle.scale * asc_angle.ratio
    S_d = desc_angle.scale * desc_angle.ratio

    denominator = S_a + S_d
    if denominator == 0:
        return None

    numerator = (
        desc_angle.pivot_price - asc_angle.pivot_price
        + asc_angle.pivot_bar_idx * S_a
        + desc_angle.pivot_bar_idx * S_d
    )

    cross_bar = numerator / denominator
    cross_price = asc_angle.pivot_price + (cross_bar - asc_angle.pivot_bar_idx) * S_a

    # Sanity: price must be positive and reasonable
    if cross_price <= 0 or cross_price > 50000:
        return None

    # Get importance
    key = (asc_angle.ratio_name, desc_angle.ratio_name)
    importance = CROSSING_IMPORTANCE.get(key, DEFAULT_IMPORTANCE)

    return AngleCrossing(
        bar_idx=cross_bar,
        price=cross_price,
        ascending_angle=asc_angle,
        descending_angle=desc_angle,
        asc_ratio=asc_angle.ratio_name,
        desc_ratio=desc_angle.ratio_name,
        importance=importance,
        time_from_now=0,  # Will be set by caller
    )


def find_crossings(
    active_angles: list[GannAngle],
    current_bar: int,
    lookahead_bars: int = 200,
    lookback_bars: int = 50,
) -> list[AngleCrossing]:
    """Find all crossing points between ascending and descending angles.

    Only returns crossings within the time window:
      [current_bar - lookback_bars, current_bar + lookahead_bars]
    """
    ascending = [a for a in active_angles if a.direction == "ascending"]
    descending = [a for a in active_angles if a.direction == "descending"]

    crossings = []
    min_bar = current_bar - lookback_bars
    max_bar = current_bar + lookahead_bars

    for asc in ascending:
        for desc in descending:
            # Skip if from same pivot (shouldn't happen but guard)
            if asc.pivot_bar_idx == desc.pivot_bar_idx:
                continue

            crossing = compute_crossing(asc, desc)
            if crossing is None:
                continue

            # Filter by time window
            if crossing.bar_idx < min_bar or crossing.bar_idx > max_bar:
                continue

            crossing.time_from_now = crossing.bar_idx - current_bar
            crossings.append(crossing)

    # Sort by importance (highest first), then by proximity to current bar
    crossings.sort(key=lambda c: (-c.importance, abs(c.time_from_now)))
    return crossings


# ============================================================
# Triangle Zone Detection
# ============================================================

def find_triangle_zones(
    crossings: list[AngleCrossing],
    tolerance_bars: float = 6.0,
    tolerance_price: float = 8.0,
) -> list[TriangleZone]:
    """Cluster nearby crossings into triangle zones.

    When multiple angle pairs cross within tolerance_bars and tolerance_price,
    they form a single triangle setup — the more crossings, the stronger.
    """
    if not crossings:
        return []

    # Simple greedy clustering
    used = set()
    zones = []

    for i, c in enumerate(crossings):
        if i in used:
            continue

        # Start a new cluster with this crossing
        cluster = [c]
        used.add(i)

        for j, other in enumerate(crossings):
            if j in used:
                continue
            if (abs(other.bar_idx - c.bar_idx) <= tolerance_bars and
                    abs(other.price - c.price) <= tolerance_price):
                cluster.append(other)
                used.add(j)

        # Build the zone
        center_bar = np.mean([x.bar_idx for x in cluster])
        center_price = np.mean([x.price for x in cluster])
        total_importance = sum(x.importance for x in cluster)

        # Direction prediction:
        # If ascending angles are steeper on average, bias is bullish at crossing
        # (price is being pushed up more aggressively than down)
        asc_ratios = [x.ascending_angle.ratio for x in cluster]
        desc_ratios = [x.descending_angle.ratio for x in cluster]
        avg_asc_ratio = np.mean(asc_ratios)
        avg_desc_ratio = np.mean(desc_ratios)

        if avg_asc_ratio > avg_desc_ratio * 1.2:
            predicted = "long"   # Ascending angles steeper → bull bias
        elif avg_desc_ratio > avg_asc_ratio * 1.2:
            predicted = "short"  # Descending angles steeper → bear bias
        else:
            predicted = "neutral"  # Balanced → need other factors

        zone = TriangleZone(
            center_bar=center_bar,
            center_price=center_price,
            crossings=cluster,
            num_crossings=len(cluster),
            importance_score=total_importance,
            predicted_direction=predicted,
        )
        zones.append(zone)

    # Sort by importance score (highest first)
    zones.sort(key=lambda z: -z.importance_score)
    return zones


# ============================================================
# Main Interface for Scalp Sim
# ============================================================

def get_upcoming_triangle_setups(
    active_angles: list[GannAngle],
    current_bar: int,
    current_price: float,
    max_future_bars: int = 100,
    max_past_bars: int = 12,
    price_range: float = 200.0,
) -> list[TriangleZone]:
    """Get triangle zones near current price and time.

    Returns zones within:
      - Time: [current_bar - max_past_bars, current_bar + max_future_bars]
      - Price: [current_price - price_range, current_price + price_range]
    """
    crossings = find_crossings(
        active_angles, current_bar,
        lookahead_bars=max_future_bars,
        lookback_bars=max_past_bars,
    )

    # Filter by price proximity
    crossings = [
        c for c in crossings
        if abs(c.price - current_price) <= price_range
    ]

    zones = find_triangle_zones(crossings)

    # Further filter: only zones within price range
    zones = [
        z for z in zones
        if abs(z.center_price - current_price) <= price_range
    ]

    return zones


def check_triangle_proximity(
    entry_price: float,
    entry_bar: int,
    upcoming_zones: list[TriangleZone],
    price_tolerance: float = 10.0,
    time_tolerance_bars: int = 12,
) -> tuple[bool, TriangleZone | None]:
    """Check if entry is near a triangle crossing point.

    Used as QUALITY BONUS (adds to convergence), NOT a hard gate.

    Returns (is_near_triangle, matching_zone).
    """
    for zone in upcoming_zones:
        price_dist = abs(entry_price - zone.center_price)
        time_dist = abs(entry_bar - zone.center_bar)

        if price_dist <= price_tolerance and time_dist <= time_tolerance_bars:
            return True, zone

    return False, None


def triangle_direction_bonus(
    direction: str,
    zone: TriangleZone | None,
) -> int:
    """Score bonus for direction agreeing with triangle prediction.

    Returns 0-2 bonus points for convergence score.
    """
    if zone is None:
        return 0

    bonus = 1  # Being near any triangle is +1

    # If direction matches triangle prediction, extra +1
    if zone.predicted_direction == direction:
        bonus += 1

    return bonus
