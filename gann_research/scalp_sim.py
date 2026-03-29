"""
Gann Scalping Simulation — M5 entries at Gann levels.

Ferro's workflow:
  D1/H4: Calculate today's Gann levels (Sq9, vibration, proportional)
  H1: Identify convergence zones (4+ factors)
  M5: Enter when price touches a Gann level → scalp to next level

Capital model: $20 start, 1:500 leverage, 0.01 lot minimum
Commission: $0.06 per 0.01 lot round trip (RoboForex ECN)
Gold: 1 lot = 100 oz, 0.01 lot = 1 oz, pip = $0.01
"""

import math
import numpy as np
import pandas as pd
from dataclasses import dataclass
from collections import defaultdict

from . import math_core as gann
from . import gann_filters as filters
from . import gann_angles
from . import triangle_engine
from .swing_detector import detect_swings, swing_pairs, compute_atr, count_waves
from .data_loader import resample_timeframe


@dataclass
class ScalpTrade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    direction: str
    lot_size: float
    pnl_dollars: float
    commission: float
    net_pnl: float
    sl_price: float
    tp_price: float
    exit_reason: str  # 'tp', 'sl', 'time'
    convergence_score: int  # OLD additive score (kept for comparison)
    independent_score: int  # NEW: 0-6 independent factor count
    limits_aligned: int     # NEW: 0-3 limit alignment count
    wave_number: int        # NEW: current wave number
    wave_phase: str         # NEW: 'legend', 'scenario', 'transition'
    gann_level: float
    hold_bars: int  # M5 bars
    angle_direction: str    # NEW: 'long', 'short', 'neutral' from Gann angles
    angle_strength: int     # NEW: how many angles support direction
    triangle_bonus: int     # NEW: 0-2 bonus from triangle proximity


def calculate_gann_levels(
    h1_swings: pd.DataFrame,
    current_price: float,
    vibration: float = 12.0,
) -> list[dict]:
    """Calculate active Gann S/R levels from recent H1 swings.

    Combines: Sq9 levels, vibration multiples, proportional levels.
    Now tracks source TYPES per level for independent convergence counting.
    Returns sorted list of levels with source types and convergence data.
    """
    levels = defaultdict(lambda: {
        "price": 0,
        "sources": [],
        "convergence": 0,
        "has_sq9": False,
        "has_vibration": False,
        "has_proportional": False,
        "sq9_swing_refs": set(),  # Which swings produced Sq9 hits
    })
    tolerance = 3.0  # $3 clustering tolerance

    # Use last 10 swing points as references
    recent_swings = h1_swings.tail(10)

    for sw_idx, (_, sw) in enumerate(recent_swings.iterrows()):
        ref = sw["price"]

        # Sq9 levels at key degrees
        for deg in [30, 45, 60, 72, 90, 120, 180, 270, 360]:
            for fn, label in [(gann.sq9_add_degrees, f"Sq9+{deg}"),
                              (gann.sq9_subtract_degrees, f"Sq9-{deg}")]:
                lvl = fn(ref, deg)
                key = round(lvl / tolerance) * tolerance
                levels[key]["price"] = lvl
                levels[key]["sources"].append(label)
                levels[key]["convergence"] += 1
                levels[key]["has_sq9"] = True
                levels[key]["sq9_swing_refs"].add(sw_idx)

        # Vibration multiples
        for mult in range(1, 10):
            for direction in [1, -1]:
                lvl = ref + direction * mult * vibration
                key = round(lvl / tolerance) * tolerance
                levels[key]["price"] = lvl
                levels[key]["sources"].append(f"V{mult}x{direction}")
                levels[key]["convergence"] += 1
                levels[key]["has_vibration"] = True

    # Proportional levels from recent swing pairs
    if len(recent_swings) >= 2:
        for i in range(len(recent_swings) - 1):
            high = max(recent_swings.iloc[i]["price"], recent_swings.iloc[i + 1]["price"])
            low = min(recent_swings.iloc[i]["price"], recent_swings.iloc[i + 1]["price"])
            rng = high - low
            if rng < 5:
                continue
            for frac_name, frac in gann.GANN_RATIOS.items():
                lvl = low + rng * frac
                key = round(lvl / tolerance) * tolerance
                levels[key]["price"] = lvl
                levels[key]["sources"].append(f"Prop{frac_name}")
                levels[key]["convergence"] += 1
                levels[key]["has_proportional"] = True

    # Filter to levels near current price (within $200)
    result = []
    for key, data in levels.items():
        if abs(data["price"] - current_price) < 200:
            # Convert set to count for serialization
            data["n_sq9_swings"] = len(data["sq9_swing_refs"])
            del data["sq9_swing_refs"]
            result.append(data)

    # Sort by convergence (highest first)
    result.sort(key=lambda x: x["convergence"], reverse=True)
    return result


def run_scalp_simulation(
    m1: pd.DataFrame,
    starting_capital: float = 20.0,
    leverage: int = 500,
    vibration: float = 12.0,
    sl_dollars: float = 10.0,      # $10 stop loss (≈10 pips gold)
    tp_dollars: float = 23.0,      # $23 take profit (≈23 pips)
    min_convergence: int = 3,      # Minimum Gann convergence to enter
    max_daily_trades: int = 10,
    commission_per_001lot: float = 0.06,  # RoboForex ECN
    risk_per_trade_pct: float = 0.02,     # Risk 2% per trade
    max_hold_m5_bars: int = 108,   # 9 H1 bars = 9*12 M5 = natural square timing
    dataset_name: str = "full",
    use_angle_direction: bool = True,  # NEW: use Gann angles for direction
    m5_scale: float = 1.0,             # NEW: $/bar for M5 1x1 angle
    h1_scale: float = 12.0,            # NEW: $/bar for H1 1x1 angle
    d1_scale: float = 72.0,            # NEW: $/bar for D1 1x1 angle
    require_multi_tf: bool = True,     # NEW: require multi-TF alignment
) -> dict:
    """Run M5 scalping simulation with real capital model.

    Entry: M5 bar touches a Gann level with convergence >= min_convergence
    Direction: Gann angle field (if use_angle_direction=True) or fade (legacy)
    SL: Angle-based or $10 from entry
    TP: Next Gann level or $23 from entry
    Sizing: risk_per_trade_pct of equity / sl_dollars * contract_value
    """
    dir_mode = "ANGLE" if use_angle_direction else "FADE (legacy)"
    print(f"\n=== GANN SCALP SIMULATION [{dataset_name}] ===")
    print(f"  Capital: ${starting_capital}, Leverage: 1:{leverage}")
    print(f"  SL: ${sl_dollars}, TP: ${tp_dollars}, R:R: 1:{tp_dollars/sl_dollars:.1f}")
    print(f"  Min convergence: {min_convergence}, Max daily: {max_daily_trades}")
    print(f"  Direction mode: {dir_mode}")

    # Build H1 swings for Gann level calculation
    h1 = resample_timeframe(m1, "H1")
    h1_swings = detect_swings(h1, atr_multiplier=2.5)
    print(f"  H1 swings: {len(h1_swings)}")

    # Work on M5 bars
    m5 = resample_timeframe(m1, "M5")
    m5_highs = m5["high"].values
    m5_lows = m5["low"].values
    m5_closes = m5["close"].values
    m5_opens = m5["open"].values
    m5_times = m5.index
    print(f"  M5 bars: {len(m5):,}")

    # Simulation state
    equity = starting_capital
    peak_equity = starting_capital
    max_drawdown = 0.0
    trades = []
    daily_trade_count = 0
    current_day = None
    position = None  # Active position (only 1 at a time)

    # Gann levels cache (recalculate every 12 M5 bars = 1 hour)
    gann_levels_cache = []
    cache_update_counter = 0
    # Wave counting cache (recalculate every 12 M5 bars)
    wave_cache = {"wave_number": 0, "direction": "neutral", "confidence": 0,
                  "phase": "unknown", "wave_0_size": 0, "expected_target": 0,
                  "impulse_direction": "neutral", "details": []}

    # NEW: Angle direction caches
    active_m5_angles = []
    h1_angle_direction = {"direction": "neutral", "strength": 0}
    d1_angle_direction = {"direction": "neutral", "strength": 0}
    triangle_zones_cache = []
    d1_cache_counter = 0  # Update D1 direction once per day (288 M5 bars)

    # Build D1 and H4 swings for multi-TF angle analysis
    d1 = resample_timeframe(m1, "D1") if use_angle_direction else None
    d1_swings = detect_swings(d1, atr_multiplier=2.5) if d1 is not None else pd.DataFrame()
    if use_angle_direction:
        print(f"  D1 swings: {len(d1_swings)}")

    contract_size = 100.0  # 1 lot = 100 oz for XAUUSD

    for bar_idx in range(60, len(m5)):  # Start after warmup
        bar_time = m5_times[bar_idx]
        bar_day = bar_time.date()

        # Reset daily counter
        if bar_day != current_day:
            current_day = bar_day
            daily_trade_count = 0

        # Check open position SL/TP
        if position is not None:
            hit_sl = False
            hit_tp = False
            exit_price = 0

            if position["direction"] == "long":
                if m5_lows[bar_idx] <= position["sl"]:
                    hit_sl = True
                    exit_price = position["sl"]
                elif m5_highs[bar_idx] >= position["tp"]:
                    hit_tp = True
                    exit_price = position["tp"]
            else:
                if m5_highs[bar_idx] >= position["sl"]:
                    hit_sl = True
                    exit_price = position["sl"]
                elif m5_lows[bar_idx] <= position["tp"]:
                    hit_tp = True
                    exit_price = position["tp"]

            # Time exit
            bars_held = bar_idx - position["entry_idx"]
            if not hit_sl and not hit_tp and bars_held >= max_hold_m5_bars:
                exit_price = m5_closes[bar_idx]
                exit_reason = "time"
            elif hit_sl:
                exit_reason = "sl"
            elif hit_tp:
                exit_reason = "tp"
            else:
                continue  # Position still open, no exit

            # Calculate P&L
            if position["direction"] == "long":
                pnl_per_oz = exit_price - position["entry_price"]
            else:
                pnl_per_oz = position["entry_price"] - exit_price

            lot_size = position["lot_size"]
            gross_pnl = pnl_per_oz * lot_size * contract_size
            commission = commission_per_001lot * (lot_size / 0.01) * 2  # round trip
            net_pnl = gross_pnl - commission

            equity += net_pnl
            if equity > peak_equity:
                peak_equity = equity
            dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd

            trades.append(ScalpTrade(
                entry_time=m5_times[position["entry_idx"]],
                exit_time=bar_time,
                entry_price=position["entry_price"],
                exit_price=exit_price,
                direction=position["direction"],
                lot_size=lot_size,
                pnl_dollars=gross_pnl,
                commission=commission,
                net_pnl=net_pnl,
                sl_price=position["sl"],
                tp_price=position["tp"],
                exit_reason=exit_reason,
                convergence_score=position["convergence"],
                independent_score=position["independent_score"],
                limits_aligned=position["limits_aligned"],
                wave_number=position["wave_number"],
                wave_phase=position["wave_phase"],
                gann_level=position["gann_level"],
                hold_bars=bars_held,
                angle_direction=position.get("angle_direction", "fade"),
                angle_strength=position.get("angle_strength", 0),
                triangle_bonus=position.get("triangle_bonus", 0),
            ))
            position = None
            continue

        # No position open — look for entry
        if daily_trade_count >= max_daily_trades:
            continue
        if equity <= -starting_capital * 10:
            break  # Stop only at catastrophic loss (research mode)

        # Update Gann levels + wave cache + angles every hour
        cache_update_counter += 1
        if cache_update_counter >= 12 or not gann_levels_cache:
            cache_update_counter = 0
            # Get H1 swings up to current time
            mask = h1_swings["time"] <= bar_time
            recent = h1_swings[mask]
            if len(recent) >= 3:
                gann_levels_cache = calculate_gann_levels(
                    recent, m5_closes[bar_idx], vibration
                )
                # Update wave counting (Priority 3)
                h1_bar_approx = bar_idx // 12
                wave_cache = count_waves(recent, h1_bar_approx)

                # NEW: Update angle caches
                if use_angle_direction:
                    # Convert H1 swing bar_index to M5 space (×12)
                    recent_m5 = recent.copy()
                    recent_m5["bar_index"] = recent_m5["bar_index"] * 12

                    # M5 angles from H1 swings in M5 bar space
                    active_m5_angles = gann_angles.compute_active_angles(
                        recent_m5, bar_idx, m5_scale,
                        max_age_bars=7200,  # ~50 days of M5 bars
                        max_pivots=10,
                    )

                    # H1 angle direction (H1 bar space)
                    h1_angles = gann_angles.compute_active_angles(
                        recent, h1_bar_approx, h1_scale,
                        max_age_bars=600,
                        max_pivots=8,
                    )
                    h1_angle_direction = gann_angles.determine_angle_direction(
                        m5_closes[bar_idx], h1_bar_approx, h1_angles,
                    )

                    # Triangle zones from M5 angles
                    triangle_zones_cache = triangle_engine.get_upcoming_triangle_setups(
                        active_m5_angles, bar_idx, m5_closes[bar_idx],
                        max_future_bars=100, max_past_bars=12,
                    )

        # NEW: Update D1 direction once per day
        if use_angle_direction:
            d1_cache_counter += 1
            if d1_cache_counter >= 288 or d1_angle_direction["direction"] == "neutral":
                d1_cache_counter = 0
                if len(d1_swings) >= 3:
                    d1_bar_approx = bar_idx // 288  # M5 to D1 conversion
                    d1_mask = d1_swings["bar_index"] <= d1_bar_approx
                    d1_recent = d1_swings[d1_mask]
                    if len(d1_recent) >= 2:
                        # D1 angles in D1 bar space
                        d1_angles = gann_angles.compute_active_angles(
                            d1_recent, d1_bar_approx, d1_scale,
                            max_age_bars=200,
                            max_pivots=6,
                        )
                        d1_angle_direction = gann_angles.determine_angle_direction(
                            m5_closes[bar_idx], d1_bar_approx, d1_angles,
                        )

        if not gann_levels_cache:
            continue

        # Check if current M5 bar touches any Gann level
        current_close = m5_closes[bar_idx]
        current_high = m5_highs[bar_idx]
        current_low = m5_lows[bar_idx]
        prev_close = m5_closes[bar_idx - 1]

        # Map M5 bar to H1 bar index for trend filter
        h1_bar_idx = bar_idx // 12  # M5 to H1 approximation

        # Find last H1 swing for reference
        mask = h1_swings["time"] <= bar_time
        recent_swings = h1_swings[mask]
        if len(recent_swings) < 3:
            continue
        last_swing = recent_swings.iloc[-1]
        ref_swing_price = last_swing["price"]
        bars_from_ref = bar_idx - (h1.index.searchsorted(last_swing["time"]) * 12)
        bars_from_ref_h1 = max(1, bars_from_ref // 12)

        for level_data in gann_levels_cache:
            level = level_data["price"]
            touch_tol = 2.0  # $2 touch tolerance (Ferro's +/-2)

            # Check if bar touches level FIRST (cheap check)
            if not (current_low <= level + touch_tol and current_high >= level - touch_tol):
                continue

            # Keep old convergence as a baseline gate (relaxed threshold)
            if level_data["convergence"] < min_convergence:
                continue

            # === DIRECTION ===
            # Ferro's hierarchy: D1→direction, H1→entry zone, M5→timing
            if use_angle_direction:
                # PRIMARY: H1 angle direction (most reliable for scalping)
                h1_dir = h1_angle_direction.get("direction", "neutral")
                d1_dir = d1_angle_direction.get("direction", "neutral")

                if h1_dir != "neutral":
                    # H1 gives clear direction — use it
                    direction = h1_dir
                    angle_dir_str = h1_dir
                    angle_strength = h1_angle_direction.get("strength", 0)

                    # D1 disagreement blocks trade (but neutral = allow)
                    if require_multi_tf and d1_dir != "neutral" and d1_dir != direction:
                        continue
                elif d1_dir != "neutral":
                    # H1 is neutral but D1 has direction — use D1
                    direction = d1_dir
                    angle_dir_str = d1_dir
                    angle_strength = d1_angle_direction.get("strength", 0)
                else:
                    # Both neutral — fall back to M5 angles or fade
                    if active_m5_angles:
                        m5_dir = gann_angles.determine_angle_direction(
                            m5_closes[bar_idx], bar_idx, active_m5_angles,
                        )
                        if m5_dir["direction"] != "neutral":
                            direction = m5_dir["direction"]
                            angle_dir_str = m5_dir["direction"]
                            angle_strength = m5_dir["strength"]
                        else:
                            # All neutral — fall back to fade
                            if prev_close < level:
                                direction = "short"
                            else:
                                direction = "long"
                            angle_dir_str = "fade"
                            angle_strength = 0
                    else:
                        if prev_close < level:
                            direction = "short"
                        else:
                            direction = "long"
                        angle_dir_str = "fade"
                        angle_strength = 0
            else:
                # Legacy FADE logic (kept for comparison)
                if prev_close < level:
                    direction = "short"
                else:
                    direction = "long"
                angle_dir_str = "fade"
                angle_strength = 0

            entry_price = level + (0.5 if direction == "long" else -0.5)

            # === PRIORITY 1: Independent convergence scoring ===
            # Enrichment — computed for analysis but NOT used as entry gate.
            # The old convergence count (additive) is the validated gate.
            indep = filters.compute_independent_convergence(
                entry_price=level,
                h1_swings=recent_swings,
                bars_from_last_swing=bars_from_ref_h1,
                vibration=vibration,
                entry_time=bar_time,
            )

            # === TRIANGLE PROXIMITY BONUS ===
            tri_bonus = 0
            if use_angle_direction and triangle_zones_cache:
                near_tri, tri_zone = triangle_engine.check_triangle_proximity(
                    entry_price, bar_idx, triangle_zones_cache,
                    price_tolerance=10.0, time_tolerance_bars=12,
                )
                if near_tri:
                    tri_bonus = triangle_engine.triangle_direction_bonus(
                        direction, tri_zone,
                    )

            # === PRIORITY 2: 3-Limit alignment ===
            # Enrichment — computed for analysis. Used as BONUS, not gate.
            limits = filters.check_three_limits(
                entry_price=level,
                ref_swing_price=ref_swing_price,
                bars_from_ref=bars_from_ref_h1,
                h1_swings=recent_swings,
                vibration=vibration,
            )

            # === PRIORITY 3: Wave phase (informational, not direction) ===
            # Wave counting tells us IF this is a good time to trade,
            # not WHICH direction. Direction = fade at level + trend filter.
            # Reject trades where wave says we're in a low-confidence zone.
            if wave_cache["phase"] == "transition" and wave_cache["confidence"] >= 0.6:
                # At transition, wave direction should AGREE with our fade direction
                # If they disagree, the level might not hold → skip
                if wave_cache["direction"] != direction:
                    continue

            # === APPLY ALL GANN FILTERS (the 52% → 90% path) ===
            # When using angle direction, skip the old SMA trend filter
            # (angle direction already handles trend alignment)
            passed, reason = filters.apply_all_filters(
                direction=direction,
                entry_price=entry_price,
                entry_idx=bar_idx,
                gann_level=level,
                m5_closes=m5_closes,
                h1_closes=h1["close"].values,
                h1_bar_idx=min(h1_bar_idx, len(h1) - 1),
                ref_swing_price=ref_swing_price,
                bars_from_ref=bars_from_ref_h1,
                skip_trend_filter=use_angle_direction,
                m5_highs=m5_highs,
                m5_lows=m5_lows,
                m5_opens=m5_opens,
            )
            if not passed:
                continue  # Filter rejected this trade

            # SL/TP: Angle-based first, Gann level fallback, then fixed fallback
            if use_angle_direction and active_m5_angles:
                # Angle-based SL: below nearest supporting angle
                # Gann Ch 5A: "stop loss 1-3 cents under the 45-degree angle"
                sl = gann_angles.angle_based_sl(
                    direction, entry_price, bar_idx,
                    active_m5_angles, fallback_sl=sl_dollars,
                )
                # TP: next Gann convergence level in direction
                gann_level_prices = [
                    lvl["price"] for lvl in gann_levels_cache
                    if lvl["price"] != level_data["price"]
                ]
                tp = gann_angles.angle_based_tp(
                    direction, entry_price, bar_idx,
                    active_m5_angles, gann_levels=gann_level_prices,
                    fallback_tp=tp_dollars,
                )
            else:
                # Legacy: Gann level-based TP/SL
                tp_level = None
                sl_level = None
                for other in gann_levels_cache:
                    if other["price"] == level_data["price"]:
                        continue
                    other_price = other["price"]
                    dist = abs(other_price - entry_price)
                    if dist < 3.0 or dist > 150.0:
                        continue
                    if direction == "long":
                        if other_price > entry_price and (tp_level is None or other_price < tp_level):
                            tp_level = other_price
                        if other_price < entry_price and (sl_level is None or other_price > sl_level):
                            sl_level = other_price
                    else:
                        if other_price < entry_price and (tp_level is None or other_price > tp_level):
                            tp_level = other_price
                        if other_price > entry_price and (sl_level is None or other_price < sl_level):
                            sl_level = other_price
                tp = tp_level if tp_level else entry_price + (tp_dollars if direction == "long" else -tp_dollars)
                sl = sl_level if sl_level else entry_price + (-sl_dollars if direction == "long" else sl_dollars)

            # R:R filter
            sl_dist = abs(entry_price - sl)
            tp_dist = abs(tp - entry_price)
            if sl_dist < 1.0 or tp_dist < 3.0:
                continue
            if tp_dist / sl_dist < 1.0:
                continue

            # Position sizing: risk X% of equity
            risk_amount = equity * risk_per_trade_pct
            lot_size = risk_amount / (sl_dollars * contract_size)
            lot_size = max(0.01, round(lot_size, 2))  # Min 0.01 lot

            # Check margin requirement
            margin_required = entry_price * lot_size * contract_size / leverage
            if margin_required > equity * 0.9:  # Keep 10% free margin
                lot_size = 0.01  # Fall back to minimum

            position = {
                "direction": direction,
                "entry_price": entry_price,
                "entry_idx": bar_idx,
                "sl": sl,
                "tp": tp,
                "lot_size": lot_size,
                "convergence": level_data["convergence"],
                "independent_score": indep["score"],
                "limits_aligned": limits["limits_aligned"],
                "wave_number": wave_cache["wave_number"],
                "wave_phase": wave_cache.get("phase", "unknown"),
                "gann_level": level,
                "angle_direction": angle_dir_str,
                "angle_strength": angle_strength,
                "triangle_bonus": tri_bonus,
            }
            daily_trade_count += 1
            break  # Only one entry per bar

    # Results
    if not trades:
        print("  No trades generated!")
        return {"trades": 0, "equity": equity}

    n = len(trades)
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]
    win_rate = len(wins) / n

    net_pnls = [t.net_pnl for t in trades]
    avg_win = np.mean([t.net_pnl for t in wins]) if wins else 0
    avg_loss = np.mean([t.net_pnl for t in losses]) if losses else 0
    total_commission = sum(t.commission for t in trades)

    tp_exits = sum(1 for t in trades if t.exit_reason == "tp")
    sl_exits = sum(1 for t in trades if t.exit_reason == "sl")
    time_exits = sum(1 for t in trades if t.exit_reason == "time")

    hold_bars = [t.hold_bars for t in trades]

    # Trades per day
    first_day = trades[0].entry_time.date()
    last_day = trades[-1].entry_time.date()
    trading_days = max((last_day - first_day).days * 5 / 7, 1)
    trades_per_day = n / trading_days

    print(f"\n  === RESULTS ===")
    print(f"  Period: {trades[0].entry_time.date()} to {trades[-1].entry_time.date()}")
    print(f"  Total trades:      {n}")
    print(f"  Trades/day:        {trades_per_day:.1f}")
    print(f"  Win rate:          {win_rate:.1%} ({len(wins)}/{n})")
    print(f"  ")
    print(f"  Starting capital:  ${starting_capital:.2f}")
    print(f"  Final equity:      ${equity:.2f}")
    print(f"  Net P&L:           ${equity - starting_capital:.2f} ({(equity/starting_capital - 1)*100:.1f}%)")
    print(f"  Peak equity:       ${peak_equity:.2f}")
    print(f"  Max drawdown:      {max_drawdown:.1%}")
    print(f"  Total commission:  ${total_commission:.2f}")
    print(f"  ")
    print(f"  Avg win:           ${avg_win:.3f}")
    print(f"  Avg loss:          ${avg_loss:.3f}")
    print(f"  R:R actual:        {abs(avg_win/avg_loss):.2f}" if avg_loss else "  R:R: N/A")
    print(f"  Avg hold:          {np.mean(hold_bars):.0f} M5 bars ({np.mean(hold_bars)*5:.0f} min)")
    print(f"  ")
    print(f"  Exit reasons:      TP={tp_exits} ({tp_exits/n:.0%}), SL={sl_exits} ({sl_exits/n:.0%}), Time={time_exits} ({time_exits/n:.0%})")

    # By OLD convergence (for comparison)
    print(f"\n  BY OLD CONVERGENCE (additive):")
    for sc in sorted(set(t.convergence_score for t in trades)):
        sc_trades = [t for t in trades if t.convergence_score == sc]
        sc_wins = sum(1 for t in sc_trades if t.net_pnl > 0)
        sc_pnl = sum(t.net_pnl for t in sc_trades)
        print(f"    Score {sc}: {len(sc_trades)} trades, win={sc_wins/len(sc_trades):.0%}, net=${sc_pnl:.2f}")

    # By NEW independent convergence (Priority 1)
    print(f"\n  BY INDEPENDENT CONVERGENCE (7 factors, incl. planetary):")
    for sc in sorted(set(t.independent_score for t in trades)):
        sc_trades = [t for t in trades if t.independent_score == sc]
        sc_wins = sum(1 for t in sc_trades if t.net_pnl > 0)
        sc_pnl = sum(t.net_pnl for t in sc_trades)
        print(f"    Score {sc}/7: {len(sc_trades)} trades, win={sc_wins/len(sc_trades):.0%}, net=${sc_pnl:.2f}")

    # By 3-limit alignment (Priority 2)
    print(f"\n  BY 3-LIMIT ALIGNMENT (Hellcat):")
    for lim in sorted(set(t.limits_aligned for t in trades)):
        lim_trades = [t for t in trades if t.limits_aligned == lim]
        lim_wins = sum(1 for t in lim_trades if t.net_pnl > 0)
        lim_pnl = sum(t.net_pnl for t in lim_trades)
        print(f"    {lim}/3 limits: {len(lim_trades)} trades, win={lim_wins/len(lim_trades):.0%}, net=${lim_pnl:.2f}")

    # By wave phase (Priority 3)
    print(f"\n  BY WAVE PHASE:")
    for phase in sorted(set(t.wave_phase for t in trades)):
        ph_trades = [t for t in trades if t.wave_phase == phase]
        ph_wins = sum(1 for t in ph_trades if t.net_pnl > 0)
        ph_pnl = sum(t.net_pnl for t in ph_trades)
        print(f"    {phase}: {len(ph_trades)} trades, win={ph_wins/len(ph_trades):.0%}, net=${ph_pnl:.2f}")

    # By angle direction mode
    if use_angle_direction:
        print(f"\n  BY ANGLE DIRECTION:")
        for ad in sorted(set(t.angle_direction for t in trades)):
            ad_trades = [t for t in trades if t.angle_direction == ad]
            ad_wins = sum(1 for t in ad_trades if t.net_pnl > 0)
            ad_pnl = sum(t.net_pnl for t in ad_trades)
            print(f"    {ad}: {len(ad_trades)} trades, win={ad_wins/len(ad_trades):.0%}, net=${ad_pnl:.2f}")

        print(f"\n  BY ANGLE STRENGTH:")
        for st in sorted(set(t.angle_strength for t in trades)):
            st_trades = [t for t in trades if t.angle_strength == st]
            st_wins = sum(1 for t in st_trades if t.net_pnl > 0)
            st_pnl = sum(t.net_pnl for t in st_trades)
            print(f"    Strength {st}: {len(st_trades)} trades, win={st_wins/len(st_trades):.0%}, net=${st_pnl:.2f}")

        print(f"\n  BY TRIANGLE BONUS:")
        for tb in sorted(set(t.triangle_bonus for t in trades)):
            tb_trades = [t for t in trades if t.triangle_bonus == tb]
            tb_wins = sum(1 for t in tb_trades if t.net_pnl > 0)
            tb_pnl = sum(t.net_pnl for t in tb_trades)
            print(f"    Bonus {tb}: {len(tb_trades)} trades, win={tb_wins/len(tb_trades):.0%}, net=${tb_pnl:.2f}")

    # Combined: Independent 5+ AND 3 limits (with planetary = 7 max)
    premium = [t for t in trades if t.independent_score >= 5 and t.limits_aligned >= 3]
    if premium:
        pm_wins = sum(1 for t in premium if t.net_pnl > 0)
        pm_pnl = sum(t.net_pnl for t in premium)
        print(f"\n  PREMIUM SIGNALS (indep>=5 + 3 limits):")
        print(f"    {len(premium)} trades, win={pm_wins/len(premium):.0%}, net=${pm_pnl:.2f}")

    # Equity curve stats
    equity_curve = [starting_capital]
    running = starting_capital
    for t in trades:
        running += t.net_pnl
        equity_curve.append(running)
    eq = np.array(equity_curve)

    # Monthly breakdown
    print(f"\n  MONTHLY BREAKDOWN (first 12 months):")
    monthly = defaultdict(lambda: {"trades": 0, "pnl": 0, "wins": 0})
    for t in trades:
        key = t.entry_time.strftime("%Y-%m")
        monthly[key]["trades"] += 1
        monthly[key]["pnl"] += t.net_pnl
        if t.net_pnl > 0:
            monthly[key]["wins"] += 1

    for i, (month, data) in enumerate(sorted(monthly.items())):
        if i >= 12:
            print(f"    ... ({len(monthly) - 12} more months)")
            break
        wr = data["wins"] / data["trades"] if data["trades"] else 0
        print(f"    {month}: {data['trades']:3d} trades, win={wr:.0%}, pnl=${data['pnl']:.2f}")

    return {
        "total_trades": n,
        "trades_per_day": trades_per_day,
        "win_rate": win_rate,
        "starting_capital": starting_capital,
        "final_equity": equity,
        "net_pnl": equity - starting_capital,
        "max_drawdown": max_drawdown,
        "total_commission": total_commission,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_hold_m5": np.mean(hold_bars),
        "tp_exits": tp_exits,
        "sl_exits": sl_exits,
        "time_exits": time_exits,
        "equity_curve": equity_curve,
        "trades": trades,
    }
