"""
Strategy -- Module 14 (4-State Machine)

States: Scanning -> Quant Forming -> Box Active -> In Trade

process_bar() is the main loop, called once per M5 bar.
"""

from datetime import datetime
from typing import Optional

from .constants import MAX_DAILY_TRADES, SWING_QUANTUM
from .swing_detector import Bar, detect_swings_atr, bars_from_dataframe
from .wave_counter import count_waves
from .triangle_engine import (
    measure_quant, construct_gann_box, find_green_zone_entry,
    check_explosion_potential,
)
from .convergence import score_convergence
from .three_limits import check_three_limits
from .risk import manage_open_trade, position_size


class TradingState:
    """State machine for triangle-first strategy."""

    SCANNING = 'scanning'
    QUANT_FORMING = 'quant_forming'
    BOX_ACTIVE = 'box_active'
    IN_TRADE = 'in_trade'

    def __init__(self):
        self.phase = self.SCANNING
        self.active_box = None
        self.quant = None
        self.open_trade = None
        self.daily_trades = 0
        self.last_trade_day = None

        # Multi-timeframe state
        self.d1_direction = 'flat'
        self.h1_wave = None
        self.swings_h1: list[dict] = []
        self.swings_h4: list[dict] = []
        self.swings_d1: list[dict] = []

        # Bar accumulators for resampling
        self.h1_bars: list[Bar] = []
        self.h4_bars: list[Bar] = []
        self.d1_bars: list[Bar] = []
        self.all_m5_bars: list[Bar] = []

        # Tracking for quant formation
        self.convergence_bar = 0
        self.convergence_price = 0.0

        # Trade log
        self.closed_trades: list[dict] = []


def process_bar(bar: Bar, state: TradingState) -> TradingState:
    """
    Main loop for v9.1 triangle-first strategy. Called once per M5 bar.
    """
    state.all_m5_bars.append(bar)

    # Reset daily trades at day boundary
    bar_day = bar.time.date() if hasattr(bar.time, 'date') else None
    if bar_day and bar_day != state.last_trade_day:
        state.daily_trades = 0
        state.last_trade_day = bar_day

    # Update multi-timeframe data periodically
    _update_mtf(bar, state)

    # === MANAGE OPEN TRADE ===
    if state.phase == TradingState.IN_TRADE:
        if state.open_trade:
            action = manage_open_trade(state.open_trade, bar, state.h1_wave)
            if action == 'close':
                _close_trade(state.open_trade, bar, state)
                state.open_trade = None
                state.phase = TradingState.SCANNING
        else:
            state.phase = TradingState.SCANNING
        return state

    # === SCANNING: Look for convergence zone ===
    if state.phase == TradingState.SCANNING:
        if len(state.swings_h1) < 4:
            return state

        convergence = score_convergence(
            bar.close, bar.bar_index, bar.time,
            state.swings_h1, state.swings_h4,
            state.h1_wave, None,
        )

        if convergence['is_tradeable']:
            state.phase = TradingState.QUANT_FORMING
            state.convergence_bar = bar.bar_index
            state.convergence_price = bar.close
        return state

    # === QUANT FORMING: Measure initial impulse ===
    if state.phase == TradingState.QUANT_FORMING:
        bars_since = bar.bar_index - state.convergence_bar

        if bars_since > 20:
            state.phase = TradingState.SCANNING
            return state

        quant = measure_quant(
            state.all_m5_bars, state.convergence_bar,
        )
        if quant:
            state.quant = quant
            state.active_box = construct_gann_box(quant, state.all_m5_bars)
            state.phase = TradingState.BOX_ACTIVE
        return state

    # === BOX ACTIVE: Monitor zones, wait for Green Zone ===
    if state.phase == TradingState.BOX_ACTIVE:
        box = state.active_box
        if not box:
            state.phase = TradingState.SCANNING
            return state

        # Box expired?
        if bar.bar_index > box['box']['end']:
            state.phase = TradingState.SCANNING
            state.active_box = None
            return state

        # Which zone?
        zones = box['zones']
        if bar.bar_index < zones['yellow'][0]:
            return state  # RED ZONE - wait
        if bar.bar_index < zones['green'][0]:
            return state  # YELLOW ZONE - watch

        # GREEN ZONE - look for entry
        if state.daily_trades >= MAX_DAILY_TRADES:
            return state

        # Get wave direction
        h1_dir = 'flat'
        if state.h1_wave:
            h1_dir = state.h1_wave.get('direction', 'flat')

        entry = find_green_zone_entry(
            box=box,
            bars=state.all_m5_bars,
            current_bar_idx=bar.bar_index,
            d1_direction=state.d1_direction,
            h1_wave_direction=h1_dir,
            wave_multiplier=4,
        )

        if entry:
            # Check explosion bonus
            expl = check_explosion_potential(box, bar.bar_index, bar.close)
            if expl['explosive']:
                # Adjust TP
                mult = expl['energy_multiplier']
                if entry['direction'] == 'long':
                    entry['tp'] = entry['entry_price'] + entry['tp_distance'] * mult / 4
                else:
                    entry['tp'] = entry['entry_price'] - entry['tp_distance'] * mult / 4
                entry['tp_distance'] = abs(entry['tp'] - entry['entry_price'])
                entry['rr_ratio'] = round(
                    entry['tp_distance'] / entry['sl_distance'], 1,
                )

            # Execute trade
            state.open_trade = {
                'entry_price': entry['entry_price'],
                'sl': entry['sl'],
                'tp': entry['tp'],
                'direction': entry['direction'],
                'entry_bar': bar.bar_index,
                'entry_time': bar.time,
                'sl_distance': entry['sl_distance'],
                'tp_distance': entry['tp_distance'],
                'rr_ratio': entry['rr_ratio'],
            }
            state.phase = TradingState.IN_TRADE
            state.daily_trades += 1

        return state

    return state


def _close_trade(trade: dict, bar: Bar, state: TradingState):
    """Close a trade and record P&L."""
    if trade['direction'] == 'long':
        # Check if SL or TP was hit
        if bar.low <= trade['sl']:
            exit_price = trade['sl']
        elif bar.high >= trade['tp']:
            exit_price = trade['tp']
        else:
            exit_price = bar.close
        pnl = exit_price - trade['entry_price']
    else:
        if bar.high >= trade['sl']:
            exit_price = trade['sl']
        elif bar.low <= trade['tp']:
            exit_price = trade['tp']
        else:
            exit_price = bar.close
        pnl = trade['entry_price'] - exit_price

    trade['exit_price'] = exit_price
    trade['exit_bar'] = bar.bar_index
    trade['exit_time'] = bar.time
    trade['pnl'] = pnl
    trade['won'] = pnl > 0
    trade['bars_held'] = bar.bar_index - trade['entry_bar']

    state.closed_trades.append(trade)


def _resample_m5_to_higher(m5_bars: list[Bar], period_bars: int) -> list[Bar]:
    """Resample M5 bars into higher timeframe bars.
    period_bars = 12 for H1 (12 x 5min), 48 for H4, 288 for D1.
    bar_index is set to the M5 start index of each period for easy mapping.
    """
    result = []
    for start in range(0, len(m5_bars), period_bars):
        chunk = m5_bars[start:start + period_bars]
        if not chunk:
            break
        result.append(Bar(
            time=chunk[0].time,
            open=chunk[0].open,
            high=max(b.high for b in chunk),
            low=min(b.low for b in chunk),
            close=chunk[-1].close,
            volume=sum(b.volume for b in chunk),
            bar_index=start,  # M5 index for cross-timeframe mapping
        ))
    return result


def _update_mtf(bar: Bar, state: TradingState):
    """Update multi-timeframe swings and wave counts."""
    n = len(state.all_m5_bars)

    # Resample every 12 M5 bars (= 1 H1 bar) for efficiency
    if n % 12 != 0 and n > 50:
        return

    # Use a sliding window to avoid O(n^2) — last 2000 H1 bars max
    window = min(n, 24000)  # 24000 M5 = 2000 H1 bars
    m5_window = state.all_m5_bars[-window:]

    # Resample M5 -> H1, H4, D1
    if n >= 24:
        h1_bars = _resample_m5_to_higher(m5_window, 12)
        if len(h1_bars) >= 20:
            state.swings_h1 = detect_swings_atr(
                h1_bars, atr_period=14, atr_multiplier=1.5,
            )

    if n >= 200:
        h4_bars = _resample_m5_to_higher(m5_window, 48)
        if len(h4_bars) >= 20:
            state.swings_h4 = detect_swings_atr(
                h4_bars, atr_period=14, atr_multiplier=1.5,
            )

    if n >= 1000:
        d1_bars = _resample_m5_to_higher(m5_window, 288)
        if len(d1_bars) >= 20:
            state.swings_d1 = detect_swings_atr(
                d1_bars, atr_period=14, atr_multiplier=1.5,
            )

    # Wave counting
    if len(state.swings_h1) >= 4:
        state.h1_wave = count_waves(state.swings_h1, 'H1')

    # D1 direction
    if len(state.swings_d1) >= 3:
        s1 = state.swings_d1[-3]
        s3 = state.swings_d1[-1]
        if s3['price'] > s1['price']:
            state.d1_direction = 'up'
        elif s3['price'] < s1['price']:
            state.d1_direction = 'down'
        else:
            state.d1_direction = 'flat'
    elif len(state.swings_h1) >= 3:
        s1 = state.swings_h1[-3]
        s3 = state.swings_h1[-1]
        if s3['price'] > s1['price']:
            state.d1_direction = 'up'
        elif s3['price'] < s1['price']:
            state.d1_direction = 'down'
        else:
            state.d1_direction = 'flat'
