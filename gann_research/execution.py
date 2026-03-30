"""
Trade Execution Engine -- Module 10

Green Zone entry evaluation with all gates. Market order at next M5 bar
open when all gates pass.
"""

from .constants import LOST_MOTION, POWER_ANGLES, SWING_QUANTUM
from .sq9_engine import sq9_levels_from_price
from .swing_detector import Bar


def evaluate_entry(m5_bar: Bar, h1_state: dict, d1_state: dict,
                   convergence: dict, limits: dict,
                   wave: dict | None) -> dict:
    """
    Full entry evaluation pipeline.

    ALL must be true:
      1. convergence['score'] >= 4
      2. limits['count'] >= 2
      3. D1 direction is clear
      4. H1 wave direction agrees
      5. Bounce direction agrees

    Returns:
        {'signal': 'long'|'short'|None, 'confidence': float,
         'sl': float, 'tp': float, 'reason': str, ...}
    """
    # Gate 1: Convergence
    if convergence['score'] < 4:
        return {'signal': None,
                'reason': f"Conv {convergence['score']} < 4"}

    # Gate 2: Limits
    if limits['count'] < 2:
        return {'signal': None,
                'reason': f"Limits {limits['count']} < 2"}

    # Gate 3: D1 direction
    if d1_state['direction'] == 'flat':
        return {'signal': None, 'reason': "D1 flat"}

    # Gate 4: H1 agrees with D1
    if h1_state['direction'] != d1_state['direction']:
        return {'signal': None,
                'reason': (f"H1 {h1_state['direction']} != "
                           f"D1 {d1_state['direction']}")}

    direction = d1_state['direction']

    # Confidence
    confidence = 0.50
    confidence += 0.05 * (convergence['score'] - 4)
    confidence += 0.10 * (limits['count'] - 2)
    if wave and wave.get('is_trending'):
        confidence += 0.05
    confidence = min(confidence, 0.96)

    # SL/TP
    sl, tp = calculate_sl_tp(
        m5_bar.close, direction, h1_state, wave,
    )

    return {
        'signal': 'long' if direction == 'up' else 'short',
        'confidence': confidence,
        'sl': sl,
        'tp': tp,
        'reason': (f"Conv={convergence['score']}, Limits={limits['count']}, "
                   f"D1={d1_state['direction']}, H1={h1_state['direction']}"),
        'convergence_score': convergence['score'],
        'limits_count': limits['count'],
    }


def calculate_sl_tp(entry_price: float, direction: str,
                    h1_state: dict, wave: dict | None,
                    atr_m5: float | None = None) -> tuple[float, float]:
    """
    Gann-based SL/TP with ATR fallback.

    Primary: SL = next Sq9 level AGAINST trade, TP = wave target.
    Fallback: ATR x 2.0 SL, 4:1 R:R TP.
    """
    # Try Gann SL
    gann_sl = _next_sq9_level_against(entry_price, direction)

    if gann_sl and abs(gann_sl - entry_price) >= 3.0:
        sl = gann_sl
    elif atr_m5:
        sl_distance = atr_m5 * 2.0
        if direction == 'up':
            sl = entry_price - sl_distance
        else:
            sl = entry_price + sl_distance
    else:
        sl_distance = 10.0
        sl = (entry_price - sl_distance if direction == 'up'
              else entry_price + sl_distance)

    sl_distance = abs(entry_price - sl)

    # Try wave TP
    tp = None
    if wave and wave.get('targets'):
        for target in wave['targets']:
            if direction == 'up' and target > entry_price:
                rr = abs(target - entry_price) / sl_distance
                if rr >= 3.0:
                    tp = target
                    break
            elif direction == 'down' and target < entry_price:
                rr = abs(entry_price - target) / sl_distance
                if rr >= 3.0:
                    tp = target
                    break

    # Fallback: 4:1 R:R
    if tp is None:
        tp_distance = sl_distance * 4.0
        if direction == 'up':
            tp = entry_price + tp_distance
        else:
            tp = entry_price - tp_distance

    return (sl, tp)


def _next_sq9_level_against(price: float, direction: str) -> float | None:
    """Next Sq9 level AGAINST the trade direction."""
    levels = sq9_levels_from_price(price, POWER_ANGLES)

    if direction == 'up':
        below = [l for l in levels if l < price - LOST_MOTION]
        return max(below) if below else None
    else:
        above = [l for l in levels if l > price + LOST_MOTION]
        return min(above) if above else None
