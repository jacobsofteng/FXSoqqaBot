"""
Triangle Engine -- Module 7 (THE CORE)

Three functions:
  measure_quant()         -- measure initial impulse at convergence zones
  construct_gann_box()    -- build box with all diagonals and intersections
  find_green_zone_entry() -- find precision entry with tiny SL / huge TP

Follows GANN_TRIANGLE_RECONSTRUCTION.md exactly.
"""

from .constants import (
    LOST_MOTION, BASE_VIBRATION, SWING_QUANTUM, NATURAL_SQ,
)
from .swing_detector import Bar


# ============================================================
# 1. QUANT MEASUREMENT
# ============================================================

def measure_quant(bars: list[Bar], convergence_bar_index: int,
                  vibration_quantum: float = SWING_QUANTUM) -> dict | None:
    """
    Measure the quant (initial impulse) when price hits a convergence zone.

    Algorithm:
      1. Price touches zone with convergence >= 4
      2. First reaction (bounce) = the quant
      3. quant_pips = distance from level to reaction extreme
      4. quant_bars = bars from level touch to reaction extreme
      5. Round quant_pips to nearest vibration quantum ($12)
      6. Round quant_bars to nearest natural square (4, 9, 16)
      7. Box dimensions from Egyptian 3-4-5 proportion

    Returns dict with quant measurements, or None if no quant formed.
    """
    if convergence_bar_index >= len(bars) - 2:
        return None

    touch_bar = bars[convergence_bar_index]
    touch_price = touch_bar.close

    # Scan forward for the first reversal (the quant)
    extreme_price = touch_price
    extreme_bar = convergence_bar_index
    direction = None

    scan_limit = min(convergence_bar_index + 50, len(bars))
    for i in range(convergence_bar_index + 1, scan_limit):
        if direction is None or direction == 'up':
            if bars[i].high > extreme_price:
                extreme_price = bars[i].high
                extreme_bar = i
                direction = 'up'
        if direction is None or direction == 'down':
            if bars[i].low < extreme_price:
                extreme_price = bars[i].low
                extreme_bar = i
                direction = 'down'

        # Quant complete when price reverses by 1/3 of the move
        move = abs(extreme_price - touch_price)
        if move < vibration_quantum * 0.5:
            continue  # Need at least half a quantum to measure

        if direction == 'up' and bars[i].low < extreme_price - move / 3:
            break
        if direction == 'down' and bars[i].high > extreme_price + move / 3:
            break

    quant_pips = abs(extreme_price - touch_price)
    quant_bars = extreme_bar - convergence_bar_index

    if quant_pips < vibration_quantum * 0.5 or quant_bars < 1:
        return None

    # Round to vibration quantum
    box_height = round(quant_pips / vibration_quantum) * vibration_quantum
    if box_height < vibration_quantum:
        box_height = vibration_quantum

    # Round bars to nearest natural square
    box_width_base = min(NATURAL_SQ, key=lambda x: abs(x - quant_bars))

    # Apply Egyptian 3-4-5 proportion: box_width = base * (4/3)
    box_width = max(int(box_width_base * (4.0 / 3.0)), 4)

    # Triangle apex: where the two main diagonals meet (2/3 to 3/4 of box)
    triangle_apex_bar = convergence_bar_index + int(box_width * 0.75)

    # Price-per-bar scale for Gann angles (1x1)
    scale = box_height / box_width if box_width > 0 else 1.0

    return {
        'quant_pips': quant_pips,
        'quant_bars': quant_bars,
        'box_height': box_height,
        'box_width': box_width,
        'scale_price_per_bar': scale,
        'triangle_apex_bar': triangle_apex_bar,
        'direction': direction,
        'touch_price': touch_price,
        'extreme_price': extreme_price,
        'convergence_bar_index': convergence_bar_index,
    }


# ============================================================
# 2. GANN BOX CONSTRUCTION
# ============================================================

def construct_gann_box(quant: dict, bars: list[Bar]) -> dict:
    """
    Build the full Gann Box from the measured quant.

    Ferro's 4-step template construction:
      Step 1: BOX DIMENSIONS from quant
      Step 2: DIVIDE BOTH AXES (by 8ths and 3rds)
      Step 3: DRAW ALL DIAGONALS (corners, Gann angles, inner square)
      Step 4: COMPUTE ALL INTERSECTIONS, classify zones
    """
    touch_price = quant['touch_price']
    extreme_price = quant['extreme_price']
    box_start = quant['convergence_bar_index']

    # Step 1: Box boundaries
    box_top = max(touch_price, extreme_price) + LOST_MOTION
    box_bottom = min(touch_price, extreme_price) - LOST_MOTION
    box_height = box_top - box_bottom

    # Extend to vibration-aligned dimensions
    box_height_ext = max(box_height, SWING_QUANTUM * 2)
    box_height_ext = ((int(box_height_ext) // SWING_QUANTUM) + 1) * SWING_QUANTUM

    # Recenter
    center_price = (box_top + box_bottom) / 2
    box_top = center_price + box_height_ext / 2
    box_bottom = center_price - box_height_ext / 2

    box_width = quant['box_width']
    box_end = box_start + box_width

    # 1x1 scale
    scale = box_height_ext / box_width if box_width > 0 else 1.0

    # Step 2: Grid divisions
    price_fracs = [0, 1/8, 1/4, 1/3, 3/8, 1/2, 5/8, 2/3, 3/4, 7/8, 1]
    time_fracs = [0, 1/8, 1/4, 1/3, 3/8, 1/2, 5/8, 2/3, 3/4, 7/8, 1]

    price_levels = [box_bottom + box_height_ext * f for f in price_fracs]
    time_points = [box_start + int(box_width * f) for f in time_fracs]

    # Step 3: Generate all diagonals
    corners = [
        (box_start, box_bottom),   # BL
        (box_start, box_top),      # TL
        (box_end, box_bottom),     # BR
        (box_end, box_top),        # TR
    ]

    mid_price = center_price
    mid_time = box_start + box_width // 2

    diagonals = []

    # Main diagonals from corners
    for i in range(len(corners)):
        for j in range(i + 1, len(corners)):
            diagonals.append({
                'start': corners[i], 'end': corners[j], 'type': 'main',
            })

    # Gann angles from each corner
    angle_ratios = [1.0, 2.0, 0.5, 4.0, 0.25]
    for cx, cy in corners:
        for ratio in angle_ratios:
            slope = scale * ratio
            for direction in [1, -1]:
                end_x = box_end if cx == box_start else box_start
                end_y = cy + direction * slope * abs(end_x - cx)
                if box_bottom <= end_y <= box_top:
                    diagonals.append({
                        'start': (cx, cy),
                        'end': (end_x, end_y),
                        'type': f'gann_{ratio}',
                    })

    # Inner Square diagonals (from midpoints to corners)
    midpoints = [
        (mid_time, box_bottom),
        (mid_time, box_top),
        (box_start, mid_price),
        (box_end, mid_price),
    ]
    for mp in midpoints:
        for c in corners:
            diagonals.append({'start': mp, 'end': c, 'type': 'inner'})

    # Corner-to-grid diagonals (the "green lines")
    for cx, cy in corners:
        for p in price_levels:
            end_x = box_end if cx == box_start else box_start
            diagonals.append({
                'start': (cx, cy), 'end': (end_x, p), 'type': 'grid',
            })

    # Step 4: Find all intersections
    intersections = _find_all_intersections(diagonals, LOST_MOTION, 2)

    # Classify zones
    green_start_bar = box_start + int(box_width * 2 / 3)
    yellow_start_bar = box_start + int(box_width * 1 / 3)

    # Power points in Green Zone
    green_zone_points = [
        p for p in intersections
        if p['bar'] >= green_start_bar and p['bar'] <= box_end
    ]
    green_zone_points.sort(key=lambda x: -x['count'])

    return {
        'box': {
            'top': box_top,
            'bottom': box_bottom,
            'start': box_start,
            'end': box_end,
            'width': box_width,
            'height': box_height_ext,
            'scale': scale,
        },
        'price_levels': price_levels,
        'time_points': time_points,
        'diagonals': diagonals,
        'all_intersections': intersections,
        'power_points': [p for p in intersections if p['count'] >= 3],
        'absolute_points': [p for p in intersections if p['count'] >= 5],
        'green_zone_points': green_zone_points,
        'zones': {
            'red': (box_start, yellow_start_bar),
            'yellow': (yellow_start_bar, green_start_bar),
            'green': (green_start_bar, box_end),
        },
        'midpoint': {
            'price': mid_price,
            'bar': mid_time,
        },
        'quant': quant,
    }


# ============================================================
# 3. GREEN ZONE ENTRY
# ============================================================

def find_green_zone_entry(box: dict, bars: list[Bar], current_bar_idx: int,
                          d1_direction: str, h1_wave_direction: str,
                          wave_multiplier: int = 4) -> dict | None:
    """
    Find precision entry point in the Green Zone.

    Prerequisites (ALL must be true):
      1. Current bar is in Green Zone (>= 2/3 of box width)
      2. Midpoint test has resolved (we know direction)
      3. D1 direction agrees
      4. H1 wave direction agrees
      5. Price is within the triangle bounds

    SL = opposite diagonal boundary + lost motion ($3-6)
    TP = quant x wave_multiplier ($24-72+)
    """
    zones = box['zones']
    green_start, green_end = zones['green']

    if current_bar_idx < green_start or current_bar_idx > green_end:
        return None

    if current_bar_idx >= len(bars):
        return None

    # Determine midpoint resolution
    midpoint_price = box['midpoint']['price']
    current_price = bars[current_bar_idx].close

    if current_price > midpoint_price:
        midpoint_direction = 'long'
    else:
        midpoint_direction = 'short'

    if d1_direction == 'flat':
        return None

    d1_mapped = 'long' if d1_direction == 'up' else 'short'
    h1_mapped = 'long' if h1_wave_direction == 'up' else 'short'

    # All directions must agree
    if not (midpoint_direction == d1_mapped == h1_mapped):
        return None

    direction = midpoint_direction

    # Find bounding diagonals at current bar
    upper_bound, lower_bound = _get_diagonal_bounds_at_bar(
        box['diagonals'], current_bar_idx, box['box']
    )

    if upper_bound is None or lower_bound is None:
        return None

    triangle_gap = upper_bound - lower_bound
    if triangle_gap <= 0:
        return None

    # Gap should be small (diagonals converging) -- max 4 quanta ($48)
    if triangle_gap > SWING_QUANTUM * 4:
        return None

    quant_pips = box['quant']['quant_pips']

    # Entry and SL/TP from diagonal geometry
    if direction == 'long':
        entry_price = lower_bound + LOST_MOTION
        sl = lower_bound - LOST_MOTION
        tp = entry_price + quant_pips * wave_multiplier
    else:
        entry_price = upper_bound - LOST_MOTION
        sl = upper_bound + LOST_MOTION
        tp = entry_price - quant_pips * wave_multiplier

    sl_distance = abs(entry_price - sl)
    tp_distance = abs(tp - entry_price)
    rr = tp_distance / sl_distance if sl_distance > 0 else 0

    if rr < 3.0:
        return None

    # Confidence from nearby power points
    nearby_power = [
        p for p in box['green_zone_points']
        if abs(p['bar'] - current_bar_idx) <= 2
        and abs(p['price'] - current_price) <= LOST_MOTION * 2
    ]

    confidence = 0.70
    if nearby_power:
        max_count = max(p['count'] for p in nearby_power)
        confidence += min(0.25, max_count * 0.05)

    return {
        'entry_price': round(entry_price, 2),
        'sl': round(sl, 2),
        'tp': round(tp, 2),
        'sl_distance': round(sl_distance, 2),
        'tp_distance': round(tp_distance, 2),
        'rr_ratio': round(rr, 1),
        'direction': direction,
        'confidence': round(confidence, 3),
        'triangle_gap': round(triangle_gap, 2),
        'reason': (f"Green zone entry, gap=${triangle_gap:.1f}, "
                   f"R:R={rr:.1f}:1, {len(nearby_power)} power points"),
    }


def check_explosion_potential(box: dict, current_bar_idx: int,
                              current_price: float) -> dict:
    """
    Check if an explosive breakout is imminent.

    Conditions:
      1. In last 1/6 of box (>= 83% of width)
      2. Diagonal gap < 1 vibration quantum ($12)
      3. Price oscillating (not trending)
    """
    box_start = box['box']['start']
    box_end = box['box']['end']
    box_width = box['box']['width']

    explosion_start = box_start + int(box_width * 5 / 6)

    if current_bar_idx < explosion_start:
        return {'explosive': False}

    upper, lower = _get_diagonal_bounds_at_bar(
        box['diagonals'], current_bar_idx, box['box']
    )
    gap = upper - lower if upper and lower else SWING_QUANTUM * 2

    if gap > SWING_QUANTUM:
        return {'explosive': False}

    quant_pips = box['quant']['quant_pips']
    quant_bars = max(box['quant']['quant_bars'], 1)
    bars_in_triangle = current_bar_idx - box_start
    oscillations = bars_in_triangle / quant_bars

    energy_multiplier = min(10, max(2, int(oscillations)))

    return {
        'explosive': True,
        'gap': gap,
        'energy_multiplier': energy_multiplier,
        'tp_multiplier': energy_multiplier,
        'bars_to_apex': box_end - current_bar_idx,
    }


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _find_all_intersections(diagonals: list, price_tol: float,
                            bar_tol: int) -> list:
    """Find all intersection points between diagonal pairs, cluster nearby."""
    raw = []

    for i in range(len(diagonals)):
        for j in range(i + 1, len(diagonals)):
            pt = _line_intersect(
                diagonals[i]['start'], diagonals[i]['end'],
                diagonals[j]['start'], diagonals[j]['end'],
            )
            if pt:
                raw.append({
                    'bar': pt[0],
                    'price': pt[1],
                    'types': [diagonals[i]['type'], diagonals[j]['type']],
                })

    # Cluster nearby crossings
    clusters = []
    used = set()

    for i, c in enumerate(raw):
        if i in used:
            continue
        cluster = [c]
        used.add(i)
        for j, c2 in enumerate(raw):
            if j in used:
                continue
            if (abs(c['bar'] - c2['bar']) <= bar_tol
                    and abs(c['price'] - c2['price']) <= price_tol):
                cluster.append(c2)
                used.add(j)

        avg_bar = sum(x['bar'] for x in cluster) / len(cluster)
        avg_price = sum(x['price'] for x in cluster) / len(cluster)
        all_types = []
        for x in cluster:
            all_types.extend(x['types'])

        clusters.append({
            'bar': int(round(avg_bar)),
            'price': round(avg_price, 2),
            'count': len(cluster),
            'types': list(set(all_types)),
        })

    return sorted(clusters, key=lambda x: -x['count'])


def _line_intersect(p1, p2, p3, p4):
    """2D line segment intersection. Returns (x, y) or None."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-10:
        return None

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

    if 0 <= t <= 1 and 0 <= u <= 1:
        x = x1 + t * (x2 - x1)
        y = y1 + t * (y2 - y1)
        return (round(x), round(y, 2))
    return None


def _get_diagonal_bounds_at_bar(diagonals: list, bar_idx: int,
                                box: dict) -> tuple:
    """Find upper and lower diagonal values at a specific bar."""
    upper = box['top']
    lower = box['bottom']
    mid = (upper + lower) / 2

    for d in diagonals:
        x1, y1 = d['start']
        x2, y2 = d['end']

        if x2 == x1:
            continue

        t = (bar_idx - x1) / (x2 - x1)
        if t < 0 or t > 1:
            continue

        price_at_bar = y1 + t * (y2 - y1)

        if price_at_bar > mid and price_at_bar < upper:
            upper = price_at_bar
        elif price_at_bar < mid and price_at_bar > lower:
            lower = price_at_bar

    return (upper, lower)
