"""
Risk Management -- Module 11

Position sizing (2% risk, min 0.01 lot), max hold, trade management.
"""

import math

from .constants import (
    BASE_VIBRATION, MAX_HOLD_BARS, LOST_MOTION,
)
from .proportional import check_fold
from .vibration import check_vibration_override
from .swing_detector import Bar


MAX_DAILY_TRADES = 5


def position_size(account_balance: float, sl_distance: float,
                  risk_pct: float = 0.02) -> float:
    """
    Risk-based position sizing.

    Gold: 1 standard lot = 100 oz. $1 move = $100/lot.
    0.01 lot = $1 per $1 move.

    For $20 account: use 0.01 minimum.
    """
    risk_amount = account_balance * risk_pct
    dollar_per_lot = 100.0  # $100 per standard lot per $1 move
    lots = risk_amount / (sl_distance * dollar_per_lot)
    lots = max(0.01, math.floor(lots * 100) / 100)
    return lots


def manage_open_trade(trade: dict, current_bar: Bar,
                      current_wave: dict | None) -> str:
    """
    Active trade management.

    Rules:
      1. Max hold: 288 M5 bars (24h) -> force close
      2. Fold at 1/3 -> tighten TP
      3. Vibration override (4x V = $288 move) -> close
      4. SL/TP hit -> close

    Returns: 'hold' | 'close' | 'trail_to_breakeven'
    """
    bars_held = current_bar.bar_index - trade['entry_bar']

    if bars_held >= MAX_HOLD_BARS:
        return 'close'

    current_price = current_bar.close

    # Check SL hit
    if trade['direction'] == 'long' and current_bar.low <= trade['sl']:
        return 'close'
    if trade['direction'] == 'short' and current_bar.high >= trade['sl']:
        return 'close'

    # Check TP hit
    if trade['direction'] == 'long' and current_bar.high >= trade['tp']:
        return 'close'
    if trade['direction'] == 'short' and current_bar.low <= trade['tp']:
        return 'close'

    # Trailing stop: when price moves 2R in your favor, trail SL to breakeven
    sl_dist = trade.get('sl_distance', 0)
    if sl_dist > 0:
        if trade['direction'] == 'long':
            unrealized = current_bar.high - trade['entry_price']
            if unrealized >= sl_dist * 2 and trade['sl'] < trade['entry_price']:
                trade['sl'] = trade['entry_price']  # exact breakeven
        else:
            unrealized = trade['entry_price'] - current_bar.low
            if unrealized >= sl_dist * 2 and trade['sl'] > trade['entry_price']:
                trade['sl'] = trade['entry_price']  # exact breakeven

    # Check vibration override
    move = abs(current_price - trade['entry_price'])
    if check_vibration_override(move):
        return 'close'

    return 'hold'
