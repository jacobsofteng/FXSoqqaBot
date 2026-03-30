"""
Square of 9 Engine — Module 1

Converts prices to Sq9 degree positions, generates price levels at
specified degree offsets, and implements the even/odd ray system.
"""

import math
from .constants import POWER_ANGLES, LOST_MOTION


def price_to_sq9_degree(price: float) -> float:
    """
    Convert a price value to its degree position on the Square of 9.

    The Sq9 spiral: center = 1, each 360° rotation = one ring outward.
    Number N sits at degree: (sqrt(N) * 180 - 225) % 360

    For Gold: use reduce_gold_price() first to get working number(s).
    """
    if price <= 0:
        return 0.0
    degree = (math.sqrt(price) * 180.0 - 225.0) % 360.0
    return degree


def reduce_gold_price(price: float) -> list[float]:
    """
    Reduce Gold price to Sq9 working number(s).

    Rules:
    - If price >= 1000: take last 3 digits (2072 → 72, 1667 → 667)
    - If price >= 100:  take last 2 digits (923 → 23)
    - Always try BOTH the full price AND the reduced forms
    """
    candidates = [price]
    if price >= 1000:
        r = price % 1000
        if r > 0:
            candidates.append(r)
    if price >= 100:
        r = price % 100
        if r > 0:
            candidates.append(r)
    return candidates


def sq9_levels_from_price(price: float, degrees: list[float] | None = None,
                          count: int = 3) -> list[float]:
    """
    Given a price, find all Sq9 levels at specified degree offsets.

    Algorithm:
      1. Get sqrt of reference price
      2. For each offset, step ±(offset/180) on the sqrt axis
      3. Square back to get price levels
      4. Walk additional rings (±full rotations) to find nearby levels

    Args:
        price: Reference price (e.g., a swing high or low)
        degrees: Degree offsets to check (default: POWER_ANGLES = [30, 45])
        count: Number of rings to walk in each direction

    Returns:
        Sorted list of unique price levels within reasonable range of input
    """
    if degrees is None:
        degrees = POWER_ANGLES

    if price <= 0:
        return []

    ref_sqrt = math.sqrt(price)
    levels = []

    for offset in degrees:
        step = offset / 180.0  # degree offset → sqrt increment
        for ring in range(-count, count + 1):
            if ring == 0:
                continue
            # Each full ring = 2.0 on the sqrt axis
            target_sqrt = ref_sqrt + step * ring
            if target_sqrt > 0:
                level = target_sqrt ** 2
                # Keep levels within a reasonable range of the reference
                if abs(level - price) <= price * 0.15:  # Within 15%
                    levels.append(round(level, 2))

    return sorted(set(levels))


def even_odd_rays(n: int) -> float:
    """
    Even perfect squares (4, 16, 36, 64, ...) ALL map to 135°.
    Odd perfect squares (1, 9, 25, 49, ...) ALL map to 315°.

    These two rays are 180° apart (opposition).

    Args:
        n: The root of the perfect square (n² is the number)

    Returns:
        135.0 for even n, 315.0 for odd n
    """
    if n % 2 == 0:
        return 135.0
    else:
        return 315.0
