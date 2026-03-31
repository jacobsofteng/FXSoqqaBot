"""
Strategy -- Module 14 (4-State Machine) with DIAGNOSTIC COUNTERS

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

        # === DIAGNOSTIC COUNTERS ===
        self.counters = {
            'total_m5_bars': 0,

            # SCANNING phase
            'convergence_checked': 0,
            'convergence_score_0': 0,
            'convergence_score_1': 0,
            'convergence_score_2': 0,
            'convergence_score_3': 0,
            'convergence_score_4': 0,
            'convergence_score_5plus': 0,

            # Which categories fire most/least?
            'cat_A_sq9': 0,
            'cat_B_vibration': 0,
            'cat_C_proportional': 0,
            'cat_D_time': 0,
            'cat_E_triangle': 0,
            'cat_F_wave': 0,
            'cat_G_square': 0,

            # Insufficient swings (early data)
            'scanning_no_swings': 0,

            # QUANT phase
            'quant_started': 0,
            'quant_completed': 0,
            'quant_timeout': 0,
            'quant_too_small': 0,

            # BOX phase
            'box_constructed': 0,
            'box_expired_in_red': 0,
            'box_expired_in_yellow': 0,
            'box_expired_in_green': 0,
            'reached_green': 0,

            # GREEN ZONE
            'green_direction_agreed': 0,
            'green_direction_rejected': 0,
            'green_d1_flat': 0,
            'green_gap_ok': 0,
            'green_gap_too_wide': 0,
            'green_rr_ok': 0,
            'green_rr_too_low': 0,
            'green_no_bounds': 0,
            'green_daily_limit': 0,

            # RESULT
            'trades_opened': 0,
            'tp_hit': 0,
            'sl_hit': 0,
            'max_hold_exit': 0,
            'fold_exit': 0,
            'vibration_override_exit': 0,
        }


def process_bar(bar: Bar, state: TradingState) -> TradingState:
    """
    Main loop for v9.1 triangle-first strategy. Called once per M5 bar.
    """
    state.all_m5_bars.append(bar)
    state.counters['total_m5_bars'] += 1

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
            state.counters['scanning_no_swings'] += 1
            return state

        convergence = score_convergence(
            bar.close, bar.bar_index, bar.time,
            state.swings_h1, state.swings_h4,
            state.h1_wave, None,  # No triangle yet in SCANNING
            phase='scanning',
        )

        # Track convergence scores
        state.counters['convergence_checked'] += 1
        score = convergence['score']
        if score == 0:
            state.counters['convergence_score_0'] += 1
        elif score == 1:
            state.counters['convergence_score_1'] += 1
        elif score == 2:
            state.counters['convergence_score_2'] += 1
        elif score == 3:
            state.counters['convergence_score_3'] += 1
        elif score == 4:
            state.counters['convergence_score_4'] += 1
        else:
            state.counters['convergence_score_5plus'] += 1

        # Track which categories fire
        cats = convergence.get('categories', {})
        if cats.get('A_sq9'):
            state.counters['cat_A_sq9'] += 1
        if cats.get('B_vibration'):
            state.counters['cat_B_vibration'] += 1
        if cats.get('C_proportional'):
            state.counters['cat_C_proportional'] += 1
        if cats.get('D_time'):
            state.counters['cat_D_time'] += 1
        if cats.get('E_triangle'):
            state.counters['cat_E_triangle'] += 1
        if cats.get('F_wave'):
            state.counters['cat_F_wave'] += 1
        if cats.get('G_square'):
            state.counters['cat_G_square'] += 1

        if convergence['is_tradeable']:
            state.phase = TradingState.QUANT_FORMING
            state.convergence_bar = bar.bar_index
            state.convergence_price = bar.close
            state.counters['quant_started'] += 1
        return state

    # === QUANT FORMING: Measure initial impulse ===
    if state.phase == TradingState.QUANT_FORMING:
        bars_since = bar.bar_index - state.convergence_bar

        if bars_since > 50:  # Extended from 20 to 50
            state.phase = TradingState.SCANNING
            state.counters['quant_timeout'] += 1
            return state

        quant = measure_quant(
            state.all_m5_bars, state.convergence_bar,
        )
        if quant:
            state.quant = quant
            state.active_box = construct_gann_box(quant, state.all_m5_bars)
            state.phase = TradingState.BOX_ACTIVE
            state.counters['quant_completed'] += 1
            state.counters['box_constructed'] += 1
        elif quant is None and bars_since > 10:
            # Track quant failures that are "too small" vs timeout
            pass
        return state

    # === BOX ACTIVE: Monitor zones, wait for Green Zone ===
    if state.phase == TradingState.BOX_ACTIVE:
        box = state.active_box
        if not box:
            state.phase = TradingState.SCANNING
            return state

        # Box expired?
        if bar.bar_index > box['box']['end']:
            # Track WHERE it expired
            zones = box['zones']
            if bar.bar_index <= zones['yellow'][0]:
                state.counters['box_expired_in_red'] += 1
            elif bar.bar_index <= zones['green'][0]:
                state.counters['box_expired_in_yellow'] += 1
            else:
                state.counters['box_expired_in_green'] += 1
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
        state.counters['reached_green'] += 1

        if state.daily_trades >= MAX_DAILY_TRADES:
            state.counters['green_daily_limit'] += 1
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
            wave_multiplier=3,
        )

        if entry:
            state.counters['green_direction_agreed'] += 1
            state.counters['green_gap_ok'] += 1
            state.counters['green_rr_ok'] += 1

            # Check explosion bonus
            expl = check_explosion_potential(box, bar.bar_index, bar.close)
            if expl['explosive']:
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
                'designed_rr': entry['rr_ratio'],
            }
            state.phase = TradingState.IN_TRADE
            state.daily_trades += 1
            state.counters['trades_opened'] += 1

        else:
            # Diagnose WHY entry was rejected
            _diagnose_green_rejection(box, state, bar, h1_dir)

        return state

    return state


def _diagnose_green_rejection(box: dict, state: TradingState,
                              bar: Bar, h1_dir: str):
    """Track why a green zone bar didn't produce an entry."""
    midpoint_price = box['midpoint']['price']
    current_price = bar.close

    if current_price > midpoint_price:
        midpoint_direction = 'long'
    else:
        midpoint_direction = 'short'

    d1_mapped = 'long' if state.d1_direction == 'up' else ('short' if state.d1_direction == 'down' else None)
    h1_mapped = 'long' if h1_dir == 'up' else ('short' if h1_dir == 'down' else None)

    direction = midpoint_direction
    disagreements = 0
    if d1_mapped and d1_mapped != direction:
        disagreements += 1
    if h1_mapped and h1_mapped != direction:
        disagreements += 1

    if disagreements >= 2:
        state.counters['green_direction_rejected'] += 1
        return

    # Direction passed — check other rejection reasons
    from .triangle_engine import _get_diagonal_bounds_at_bar
    upper, lower = _get_diagonal_bounds_at_bar(
        box['diagonals'], bar.bar_index, box['box']
    )
    if upper is None or lower is None:
        state.counters['green_no_bounds'] += 1
        return

    gap = upper - lower
    if gap <= 0:
        state.counters['green_gap_too_wide'] += 1  # Collapsed/negative gap
        return

    if gap > SWING_QUANTUM * 6:
        state.counters['green_gap_too_wide'] += 1
        return

    # Check R:R
    from .constants import LOST_MOTION
    quant_pips = box['quant']['quant_pips']
    sl_dist = LOST_MOTION * 2
    tp_dist = quant_pips * 2  # wave_multiplier=2
    rr = tp_dist / sl_dist if sl_dist > 0 else 0
    if rr < 2.0:
        state.counters['green_rr_too_low'] += 1


def _close_trade(trade: dict, bar: Bar, state: TradingState):
    """Close a trade and record P&L with exit reason tracking."""
    bars_held = bar.bar_index - trade['entry_bar']
    exit_reason = 'unknown'

    if trade['direction'] == 'long':
        if bar.low <= trade['sl']:
            exit_price = trade['sl']
            exit_reason = 'SL_HIT'
        elif bar.high >= trade['tp']:
            exit_price = trade['tp']
            exit_reason = 'TP_HIT'
        elif bars_held >= 288:
            exit_price = bar.close
            exit_reason = 'MAX_HOLD'
        else:
            exit_price = bar.close
            exit_reason = 'OTHER'
        pnl = exit_price - trade['entry_price']
    else:
        if bar.high >= trade['sl']:
            exit_price = trade['sl']
            exit_reason = 'SL_HIT'
        elif bar.low <= trade['tp']:
            exit_price = trade['tp']
            exit_reason = 'TP_HIT'
        elif bars_held >= 288:
            exit_price = bar.close
            exit_reason = 'MAX_HOLD'
        else:
            exit_price = bar.close
            exit_reason = 'OTHER'
        pnl = trade['entry_price'] - exit_price

    # Check for fold/vibration override exits
    if exit_reason == 'OTHER':
        move = abs(bar.close - trade['entry_price'])
        if move >= 288:  # vibration override
            exit_reason = 'VIBRATION_OVERRIDE'
        else:
            exit_reason = 'FOLD'

    trade['exit_price'] = exit_price
    trade['exit_bar'] = bar.bar_index
    trade['exit_time'] = bar.time
    trade['pnl'] = pnl
    trade['won'] = pnl > 0
    trade['bars_held'] = bars_held
    trade['exit_reason'] = exit_reason

    # Actual R:R
    if trade['sl_distance'] > 0:
        trade['actual_rr'] = round(abs(pnl) / trade['sl_distance'], 2) if pnl > 0 else round(-abs(pnl) / trade['sl_distance'], 2)
    else:
        trade['actual_rr'] = 0

    # Update diagnostic counters
    if exit_reason == 'TP_HIT':
        state.counters['tp_hit'] += 1
    elif exit_reason == 'SL_HIT':
        state.counters['sl_hit'] += 1
    elif exit_reason == 'MAX_HOLD':
        state.counters['max_hold_exit'] += 1
    elif exit_reason == 'FOLD':
        state.counters['fold_exit'] += 1
    elif exit_reason == 'VIBRATION_OVERRIDE':
        state.counters['vibration_override_exit'] += 1

    state.closed_trades.append(trade)


def _resample_m5_to_higher(m5_bars: list[Bar], period_bars: int) -> list[Bar]:
    """Resample M5 bars into higher timeframe bars.
    period_bars = 12 for H1 (12 x 5min), 48 for H4, 288 for D1.
    bar_index uses the GLOBAL M5 index of the first bar in each chunk.
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
            bar_index=chunk[0].bar_index,  # GLOBAL M5 index, not window-local
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


def print_diagnostic_report(state: TradingState):
    """Print the full diagnostic funnel report."""
    c = state.counters
    total = c['total_m5_bars']
    days = total / 288 if total > 0 else 1

    print(f"\n{'='*70}")
    print(f"  DIAGNOSTIC FUNNEL REPORT")
    print(f"{'='*70}")
    print(f"  Total M5 bars: {total:,} ({days:.0f} trading days)")
    print()

    # SCANNING
    checked = c['convergence_checked']
    print(f"  --- SCANNING PHASE ---")
    print(f"  Bars with no swings (skipped):  {c['scanning_no_swings']:,}")
    print(f"  Convergence checks:             {checked:,}")
    if checked > 0:
        print(f"    Score 0: {c['convergence_score_0']:,} ({c['convergence_score_0']/checked:.1%})")
        print(f"    Score 1: {c['convergence_score_1']:,} ({c['convergence_score_1']/checked:.1%})")
        print(f"    Score 2: {c['convergence_score_2']:,} ({c['convergence_score_2']/checked:.1%})")
        print(f"    Score 3: {c['convergence_score_3']:,} ({c['convergence_score_3']/checked:.1%})")
        print(f"    Score 4: {c['convergence_score_4']:,} ({c['convergence_score_4']/checked:.1%})")
        print(f"    Score 5+: {c['convergence_score_5plus']:,} ({c['convergence_score_5plus']/checked:.1%})")
        print()
        print(f"  Category fire rates (of {checked:,} checks):")
        print(f"    A (Sq9):          {c['cat_A_sq9']:,} ({c['cat_A_sq9']/checked:.1%})")
        print(f"    B (Vibration):    {c['cat_B_vibration']:,} ({c['cat_B_vibration']/checked:.1%})")
        print(f"    C (Proportional): {c['cat_C_proportional']:,} ({c['cat_C_proportional']/checked:.1%})")
        print(f"    D (Time):         {c['cat_D_time']:,} ({c['cat_D_time']/checked:.1%})")
        print(f"    E (Triangle):     {c['cat_E_triangle']:,} ({c['cat_E_triangle']/checked:.1%})")
        print(f"    F (Wave):         {c['cat_F_wave']:,} ({c['cat_F_wave']/checked:.1%})")
        print(f"    G (Square):       {c['cat_G_square']:,} ({c['cat_G_square']/checked:.1%})")

    # QUANT
    print(f"\n  --- QUANT PHASE ---")
    print(f"  Quant started:    {c['quant_started']:,}")
    print(f"  Quant completed:  {c['quant_completed']:,}")
    print(f"  Quant timeout:    {c['quant_timeout']:,}")
    if c['quant_started'] > 0:
        print(f"  Completion rate:  {c['quant_completed']/c['quant_started']:.1%}")

    # BOX
    print(f"\n  --- BOX PHASE ---")
    print(f"  Boxes constructed:    {c['box_constructed']:,}")
    print(f"  Expired in Red:       {c['box_expired_in_red']:,}")
    print(f"  Expired in Yellow:    {c['box_expired_in_yellow']:,}")
    print(f"  Expired in Green:     {c['box_expired_in_green']:,}")
    print(f"  Reached Green Zone:   {c['reached_green']:,}")

    # GREEN ZONE
    green = c['reached_green']
    print(f"\n  --- GREEN ZONE ---")
    print(f"  Green zone bars:        {green:,}")
    print(f"  Direction agreed:       {c['green_direction_agreed']:,}")
    print(f"  Direction rejected:     {c['green_direction_rejected']:,}")
    print(f"  D1 flat:                {c['green_d1_flat']:,}")
    print(f"  Gap too wide:           {c['green_gap_too_wide']:,}")
    print(f"  No diagonal bounds:     {c['green_no_bounds']:,}")
    print(f"  R:R too low:            {c['green_rr_too_low']:,}")
    print(f"  Daily limit hit:        {c['green_daily_limit']:,}")

    # TRADES
    trades = c['trades_opened']
    print(f"\n  --- TRADE RESULTS ---")
    print(f"  Trades opened:      {trades:,}")
    print(f"  Trades/day:         {trades/days:.2f}")
    if trades > 0:
        print(f"  TP hit:             {c['tp_hit']:,} ({c['tp_hit']/trades:.1%})")
        print(f"  SL hit:             {c['sl_hit']:,} ({c['sl_hit']/trades:.1%})")
        print(f"  Max hold exit:      {c['max_hold_exit']:,} ({c['max_hold_exit']/trades:.1%})")
        print(f"  Fold exit:          {c['fold_exit']:,} ({c['fold_exit']/trades:.1%})")
        print(f"  Vibration override: {c['vibration_override_exit']:,} ({c['vibration_override_exit']/trades:.1%})")

    print(f"{'='*70}")
