"""
Gann Calibration Engine for Gold (XAUUSD).

NOT hypothesis testing. The masters are right.
This calibrates Gold-specific parameters and measures prediction quality.

Purpose:
  1. Find Gold's vibration constant (channel fitting)
  2. Measure which Sq9 degree offsets are strongest for Gold
  3. Measure time projection accuracy
  4. Find how convergence score relates to prediction quality
  5. Simulate Gann trades and measure what they give

Output:
  - Gold's calibrated parameters
  - Expected trade quality (pips, win rate, hold time)
  - Gaps filled: which formulas need adjustment for Gold
"""

import math
import numpy as np
import pandas as pd
from collections import defaultdict
from dataclasses import dataclass, field

from . import math_core as gann
from .swing_detector import detect_swings, swing_pairs, compute_atr
from .data_loader import resample_timeframe


@dataclass
class GannPrediction:
    """A single Gann prediction: price level + time + source factor."""
    price_level: float
    time_bar: int | None  # Predicted bar index (None = price-only)
    source: str           # Which Gann factor generated this
    degree: float         # Sq9 degree or 0
    convergence: int      # How many factors agree here


@dataclass
class GannTradeResult:
    """Result of a simulated Gann trade."""
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    direction: str        # 'long' or 'short'
    pips: float
    hold_bars: int
    convergence_score: int
    gann_target: float    # The Gann level we targeted
    hit_target: bool      # Did price reach the target?
    source: str           # Which Gann factor drove the entry


# ============================================================
# 1. VIBRATION CONSTANT CALIBRATION
# ============================================================

def calibrate_vibration(m1: pd.DataFrame) -> dict:
    """Find Gold's vibration constant by measuring channel tightness.

    Method: From each swing, build channels at width V. Measure what %
    of the NEXT swing's extremum falls within $tolerance of a V-multiple level.
    The V that captures the most next-swing endpoints = Gold's vibration.

    This is Ferro's method: the vibration creates the channel,
    the next swing ENDS at a channel boundary.
    """
    print("\n=== CALIBRATING VIBRATION CONSTANT ===")
    h4 = resample_timeframe(m1, "H4")
    h1 = resample_timeframe(m1, "H1")
    d1 = resample_timeframe(m1, "D1")

    # Multi-timeframe swing detection
    timeframes = {
        "H1": detect_swings(h1, atr_multiplier=2.5),
        "H4": detect_swings(h4, atr_multiplier=2.5),
        "D1": detect_swings(d1, atr_multiplier=2.5),
    }

    candidates = [7, 12, 18, 24, 36, 48, 52, 53, 60, 72, 96, 104, 108, 144]
    # Also test formula values
    for n in [1, 2, 3, 5, 7]:
        v = gann.vibration_constant(n)
        if v not in candidates:
            candidates.append(round(v, 1))

    results = {}
    for V in sorted(candidates):
        total_predictions = 0
        accurate_predictions = 0
        errors = []

        for tf_name, swings in timeframes.items():
            pairs = swing_pairs(swings)
            for pair in pairs:
                move = pair["price_move"]
                if move < 10:
                    continue
                total_predictions += 1

                # How close is the move to a multiple of V?
                if V > 0:
                    remainder = move % V
                    nearest_dist = min(remainder, V - remainder)
                    errors.append(nearest_dist)
                    # "Accurate" = within Ferro's tolerance of 2-3 units
                    if nearest_dist <= 3.0:
                        accurate_predictions += 1

        hit_rate = accurate_predictions / total_predictions if total_predictions else 0
        mean_error = np.mean(errors) if errors else 999
        median_error = np.median(errors) if errors else 999
        # Expected random hit rate: 2*3/V = 6/V
        expected_random = min(6.0 / V, 1.0) if V > 0 else 0
        lift = hit_rate / expected_random if expected_random > 0 else 0

        results[V] = {
            "hit_rate": hit_rate,
            "expected_random": expected_random,
            "lift": lift,
            "mean_error": mean_error,
            "median_error": median_error,
            "n": total_predictions,
            "hits": accurate_predictions,
        }

    # Rank by LIFT (actual/expected) — this controls for smaller V having more hits by chance
    ranked = sorted(results.items(), key=lambda x: x[1]["lift"], reverse=True)

    print(f"\n  {'V':>6s} {'Hit%':>7s} {'Expect':>7s} {'Lift':>6s} {'MedErr':>7s} {'N':>6s}")
    print(f"  {'-'*45}")
    for V, r in ranked[:15]:
        print(f"  {V:>6.1f} {r['hit_rate']:>7.1%} {r['expected_random']:>7.1%} {r['lift']:>6.2f}x {r['median_error']:>7.1f} {r['n']:>6d}")

    best_v = ranked[0][0]
    print(f"\n  >> Gold vibration constant = {best_v} (lift {ranked[0][1]['lift']:.2f}x over random)")

    return {"best_v": best_v, "all_results": dict(ranked[:15])}


# ============================================================
# 2. SQ9 DEGREE ACCURACY PER OFFSET
# ============================================================

def calibrate_sq9_degrees(m1: pd.DataFrame) -> dict:
    """Measure which Sq9 degree offsets are strongest for Gold.

    From each swing endpoint, calculate Sq9 levels at all standard offsets.
    Measure how close the NEXT swing endpoint is to each projected level.
    Rank offsets by prediction accuracy.
    """
    print("\n=== CALIBRATING SQ9 DEGREE OFFSETS ===")
    h1 = resample_timeframe(m1, "H1")
    swings = detect_swings(h1, atr_multiplier=2.5)
    pairs = swing_pairs(swings)
    print(f"  {len(swings)} H1 swings, {len(pairs)} pairs")

    degree_offsets = [30, 45, 60, 72, 90, 108, 120, 135, 144, 150, 180,
                      210, 225, 240, 270, 300, 315, 330, 360]
    tolerance = 5.0  # Dollars — Ferro's +/-2 scaled for gold

    degree_scores = defaultdict(lambda: {"hits": 0, "total": 0, "errors": []})

    for i in range(len(pairs) - 1):
        ref_price = pairs[i]["start_price"]
        next_end = pairs[i + 1]["end_price"] if i + 1 < len(pairs) else None
        if next_end is None:
            continue

        for deg in degree_offsets:
            # Resistance (above)
            level_up = gann.sq9_add_degrees(ref_price, deg)
            err_up = abs(next_end - level_up)

            # Support (below)
            level_dn = gann.sq9_subtract_degrees(ref_price, deg)
            err_dn = abs(next_end - level_dn)

            best_err = min(err_up, err_dn)
            degree_scores[deg]["total"] += 1
            degree_scores[deg]["errors"].append(best_err)
            if best_err <= tolerance:
                degree_scores[deg]["hits"] += 1

    print(f"\n  {'Degree':>7s} {'Hit%':>7s} {'MedErr$':>8s} {'MeanErr$':>9s} {'N':>5s}")
    print(f"  {'-'*40}")
    ranked = sorted(degree_scores.items(),
                    key=lambda x: x[1]["hits"] / x[1]["total"] if x[1]["total"] else 0,
                    reverse=True)
    for deg, s in ranked:
        hr = s["hits"] / s["total"] if s["total"] else 0
        med = np.median(s["errors"]) if s["errors"] else 999
        mn = np.mean(s["errors"]) if s["errors"] else 999
        print(f"  {deg:>7d} {hr:>7.1%} {med:>8.1f} {mn:>9.1f} {s['total']:>5d}")

    top_degrees = [deg for deg, _ in ranked[:5]]
    print(f"\n  >> Top 5 Sq9 degrees for Gold: {top_degrees}")

    return {"degree_rankings": {d: s for d, s in ranked}, "top_degrees": top_degrees}


# ============================================================
# 3. TIME PROJECTION ACCURACY
# ============================================================

def calibrate_time_projection(m1: pd.DataFrame) -> dict:
    """Find which time projection method best predicts Gold swing durations.

    Tests:
    A. Impulse progression: 72, 96, 144, 192, 576, 768 hours
    B. Natural squares: 4, 9, 16, 24, 36, 49, 72, 81 bars
    C. Proportional: 1/3, 1/2, 2/3, 3/4 of prior swing duration
    D. Impulse exhaustion: T = pi * price_range / scale
    E. Legend:Scenario: next = prior / ratio
    """
    print("\n=== CALIBRATING TIME PROJECTIONS ===")
    h1 = resample_timeframe(m1, "H1")
    h4 = resample_timeframe(m1, "H4")

    results = {}

    # A. Fixed impulse hours
    print("\n  A. Fixed Impulse Hours:")
    h1_swings = detect_swings(h1, atr_multiplier=2.5)
    h1_pairs = swing_pairs(h1_swings)
    durations_h1 = [p["duration_bars"] for p in h1_pairs if p["duration_bars"] > 5]

    impulse_targets = gann.IMPULSE_HOURS  # [72, 96, 144, 192, 576, 768]
    for target in impulse_targets:
        hits = sum(1 for d in durations_h1 if abs(d - target) <= target * 0.07)
        print(f"    {target:>4d}h: {hits}/{len(durations_h1)} ({hits/len(durations_h1):.1%})")
    results["impulse_hours"] = {t: sum(1 for d in durations_h1 if abs(d - t) <= t * 0.07)
                                 for t in impulse_targets}

    # B. Natural squares (H4 bars)
    print("\n  B. Natural Squares (H4 bars):")
    h4_swings = detect_swings(h4, atr_multiplier=2.5)
    h4_pairs = swing_pairs(h4_swings)
    durations_h4 = [p["duration_bars"] for p in h4_pairs if p["duration_bars"] > 3]

    for ns in gann.NATURAL_SQUARES:
        hits = sum(1 for d in durations_h4 if abs(d - ns) <= 2)
        total = len(durations_h4)
        print(f"    {ns:>4d} bars: {hits}/{total} ({hits/total:.1%})" if total else f"    {ns}: no data")
    results["natural_squares"] = {ns: sum(1 for d in durations_h4 if abs(d - ns) <= 2)
                                   for ns in gann.NATURAL_SQUARES}

    # C. Proportional of prior swing
    print("\n  C. Proportional Divisions (next = fraction of prior):")
    fractions = [1/4, 1/3, 1/2, 2/3, 3/4, 1.0, 4/3, 3/2, 2.0, 3.0]
    frac_hits = defaultdict(int)
    total_pairs = 0
    for i in range(len(h1_pairs) - 1):
        prior_dur = h1_pairs[i]["duration_bars"]
        next_dur = h1_pairs[i + 1]["duration_bars"]
        if prior_dur < 5 or next_dur < 5:
            continue
        total_pairs += 1
        ratio = next_dur / prior_dur
        for f in fractions:
            if abs(ratio - f) <= 0.08:
                frac_hits[f"{f:.3f}"] += 1

    for f in fractions:
        key = f"{f:.3f}"
        cnt = frac_hits.get(key, 0)
        print(f"    {key}: {cnt}/{total_pairs} ({cnt/total_pairs:.1%})" if total_pairs else "")
    results["proportional"] = dict(frac_hits)
    results["proportional_total"] = total_pairs

    # D. Impulse exhaustion: T = pi * price / scale
    print("\n  D. Impulse Exhaustion (T = pi * P / scale):")
    best_scale_hits = 0
    best_scale = 0
    for scale in [1, 2, 3, 5, 7, 10, 14, 20, 36, 52, 72]:
        hits = 0
        total = 0
        for pair in h1_pairs:
            if pair["price_move"] < 10 or pair["duration_bars"] < 5:
                continue
            total += 1
            predicted = math.pi * pair["price_move"] / scale
            if abs(predicted - pair["duration_bars"]) / pair["duration_bars"] <= 0.10:
                hits += 1
        if hits > best_scale_hits:
            best_scale_hits = hits
            best_scale = scale
        if total > 0:
            print(f"    scale={scale:>3d}: {hits}/{total} ({hits/total:.1%})")
    results["exhaustion_best_scale"] = best_scale
    results["exhaustion_best_hits"] = best_scale_hits

    # E. Legend:Scenario ratio search
    print("\n  E. Legend:Scenario Ratio (actual distribution):")
    ratios = []
    for i in range(len(h1_pairs) - 1):
        d1 = h1_pairs[i]["duration_bars"]
        d2 = h1_pairs[i + 1]["duration_bars"]
        if d1 > 5 and d2 > 5:
            ratios.append(d1 / d2)
    if ratios:
        rarr = np.array(ratios)
        print(f"    Mean ratio:   {rarr.mean():.2f}")
        print(f"    Median ratio: {np.median(rarr):.2f}")
        print(f"    Mode region:  {np.percentile(rarr, 25):.2f} - {np.percentile(rarr, 75):.2f}")
        # What fraction are near common ratios?
        for target_ratio in [1.0, 1.5, 2.0, 3.0, 4.0]:
            near = sum(1 for r in ratios if abs(r - target_ratio) <= target_ratio * 0.2)
            print(f"    Near {target_ratio:.1f}:1 = {near}/{len(ratios)} ({near/len(ratios):.1%})")
    results["legend_scenario_ratios"] = ratios

    return results


# ============================================================
# 4. CONVERGENCE SCORE vs PREDICTION QUALITY
# ============================================================

def calibrate_convergence(m1: pd.DataFrame, vibration: float = 72.0) -> dict:
    """Measure how convergence score relates to next-swing accuracy.

    At each swing, count Gann factors that converge.
    Measure: does higher score = more predictable next swing?
    """
    print(f"\n=== CALIBRATING CONVERGENCE (V={vibration}) ===")
    h1 = resample_timeframe(m1, "H1")
    d1 = resample_timeframe(m1, "D1")

    swings = detect_swings(h1, atr_multiplier=2.5)
    pairs = swing_pairs(swings)
    print(f"  {len(swings)} H1 swings, {len(pairs)} pairs")

    score_data = defaultdict(list)  # score -> [next_move, ...]

    for i in range(2, len(pairs) - 1):
        curr = pairs[i]
        prev = pairs[i - 1]
        prev2 = pairs[i - 2]
        nxt = pairs[i + 1]

        price = curr["end_price"]
        prev_price = prev["end_price"]
        move = curr["price_move"]
        next_move = nxt["price_move"]
        duration = curr["duration_bars"]

        score = 0

        # Factor 1: Sq9 level from prior swing
        for deg in [90, 180, 270, 360]:
            lvl_up = gann.sq9_add_degrees(prev_price, deg)
            lvl_dn = gann.sq9_subtract_degrees(prev_price, deg)
            if min(abs(price - lvl_up), abs(price - lvl_dn)) <= 5.0:
                score += 1
                break

        # Factor 2: Proportional retracement
        prior_range = prev["price_move"]
        if prior_range > 10:
            retrace = move / prior_range
            for frac in [1/3, 1/2, 2/3, 3/4]:
                if abs(retrace - frac) < 0.06:
                    score += 1
                    break

        # Factor 3: Vibration multiple
        if move > 10 and vibration > 0:
            rem = move % vibration
            if min(rem, vibration - rem) <= 4.0:
                score += 1

        # Factor 4: Natural square timing
        for ns in gann.NATURAL_SQUARES:
            if abs(duration - ns) <= 2:
                score += 1
                break

        # Factor 5: Price-time squaring
        if move > 1 and duration > 1:
            p_deg = gann.price_to_sq9_degree(move)
            t_deg = gann.price_to_sq9_degree(duration)
            diff = abs(p_deg - t_deg)
            diff = min(diff, 360 - diff)
            if diff <= 15:
                score += 1

        score_data[score].append({
            "next_move": next_move,
            "next_duration": nxt["duration_bars"],
            "price": price,
        })

    print(f"\n  {'Score':>5s} {'Count':>6s} {'Avg Next$':>10s} {'Med Next$':>10s} {'Avg Duration':>13s}")
    print(f"  {'-'*50}")
    for sc in sorted(score_data.keys()):
        entries = score_data[sc]
        moves = [e["next_move"] for e in entries]
        durs = [e["next_duration"] for e in entries]
        print(f"  {sc:>5d} {len(entries):>6d} {np.mean(moves):>10.1f} {np.median(moves):>10.1f} {np.mean(durs):>13.1f}h")

    return {"score_data": {k: len(v) for k, v in score_data.items()}}


# ============================================================
# 5. SIMULATED GANN TRADES
# ============================================================

def simulate_gann_trades(m1: pd.DataFrame, vibration: float = 72.0) -> dict:
    """Simulate actual Gann trades and measure what they give.

    Strategy:
    - Enter when convergence score >= 2
    - Direction: determined by swing structure (continuation after correction)
    - Target: next Gann level (Sq9 or vibration multiple)
    - Stop: prior swing extremum (Gann's natural stop)
    - Hold: until target hit, stop hit, or max_bars elapsed

    Measures: pips per trade, win rate, avg hold time, reward:risk
    """
    print(f"\n=== SIMULATING GANN TRADES (V={vibration}) ===")
    h1 = resample_timeframe(m1, "H1")
    swings = detect_swings(h1, atr_multiplier=2.5)
    pairs = swing_pairs(swings)
    print(f"  {len(swings)} H1 swings, {len(pairs)} pairs")

    closes = h1["close"].values
    highs = h1["high"].values
    lows = h1["low"].values
    times = h1.index

    trades = []
    min_convergence = 2

    for i in range(3, len(pairs) - 1):
        curr = pairs[i]
        prev = pairs[i - 1]

        price = curr["end_price"]
        move = curr["price_move"]
        duration = curr["duration_bars"]
        entry_idx = int(curr["end_idx"])

        if entry_idx >= len(closes) - 50:
            continue

        # Calculate convergence score
        score = 0
        prev_price = prev["end_price"]

        for deg in [90, 180, 270, 360]:
            lvl_up = gann.sq9_add_degrees(prev_price, deg)
            lvl_dn = gann.sq9_subtract_degrees(prev_price, deg)
            if min(abs(price - lvl_up), abs(price - lvl_dn)) <= 5.0:
                score += 1
                break

        prior_range = prev["price_move"]
        if prior_range > 10:
            retrace = move / prior_range
            for frac in [1/3, 1/2, 2/3, 3/4]:
                if abs(retrace - frac) < 0.06:
                    score += 1
                    break

        if move > 10 and vibration > 0:
            rem = move % vibration
            if min(rem, vibration - rem) <= 4.0:
                score += 1

        for ns in gann.NATURAL_SQUARES:
            if abs(duration - ns) <= 2:
                score += 1
                break

        if score < min_convergence:
            continue

        # Determine direction: if last swing was down (low), we go long; if up (high), short
        if curr["end_type"] == "low":
            direction = "long"
        else:
            direction = "short"

        entry_price = closes[entry_idx]

        # Calculate target: next Sq9 level + vibration level in our direction
        targets = []
        for deg in [45, 90, 120, 180]:
            if direction == "long":
                targets.append(gann.sq9_add_degrees(entry_price, deg))
            else:
                targets.append(gann.sq9_subtract_degrees(entry_price, deg))

        # Vibration levels
        for mult in [1, 2, 3]:
            if direction == "long":
                targets.append(entry_price + mult * vibration)
            else:
                targets.append(entry_price - mult * vibration)

        # Pick nearest target that gives at least $10 move
        if direction == "long":
            valid_targets = sorted([t for t in targets if t > entry_price + 10])
        else:
            valid_targets = sorted([t for t in targets if t < entry_price - 10], reverse=True)

        if not valid_targets:
            continue
        target = valid_targets[0]

        # Stop: at the swing extremum we entered from + small buffer
        if direction == "long":
            stop = price - 5.0  # Swing low minus $5 buffer
        else:
            stop = price + 5.0  # Swing high plus $5 buffer

        # Simulate the trade bar by bar
        max_hold = 200  # Max hold time in H1 bars
        exit_price = None
        exit_idx = None
        exit_reason = None

        for j in range(entry_idx + 1, min(entry_idx + max_hold, len(closes))):
            if direction == "long":
                if lows[j] <= stop:
                    exit_price = stop
                    exit_idx = j
                    exit_reason = "stop"
                    break
                if highs[j] >= target:
                    exit_price = target
                    exit_idx = j
                    exit_reason = "target"
                    break
            else:
                if highs[j] >= stop:
                    exit_price = stop
                    exit_idx = j
                    exit_reason = "stop"
                    break
                if lows[j] <= target:
                    exit_price = target
                    exit_idx = j
                    exit_reason = "target"
                    break

        if exit_price is None:
            # Time exit
            exit_idx = min(entry_idx + max_hold, len(closes) - 1)
            exit_price = closes[exit_idx]
            exit_reason = "time"

        if direction == "long":
            pips = exit_price - entry_price
        else:
            pips = entry_price - exit_price

        trades.append(GannTradeResult(
            entry_time=times[entry_idx],
            exit_time=times[exit_idx],
            entry_price=entry_price,
            exit_price=exit_price,
            direction=direction,
            pips=pips,
            hold_bars=exit_idx - entry_idx,
            convergence_score=score,
            gann_target=target,
            hit_target=(exit_reason == "target"),
            source=exit_reason,
        ))

    # Analyze trades
    if not trades:
        print("  No trades generated!")
        return {"trades": 0}

    pips_arr = np.array([t.pips for t in trades])
    hold_arr = np.array([t.hold_bars for t in trades])
    wins = sum(1 for t in trades if t.pips > 0)
    targets_hit = sum(1 for t in trades if t.hit_target)

    total = len(trades)
    win_rate = wins / total
    avg_pips = pips_arr.mean()
    avg_win = pips_arr[pips_arr > 0].mean() if wins > 0 else 0
    avg_loss = pips_arr[pips_arr <= 0].mean() if (total - wins) > 0 else 0
    avg_hold = hold_arr.mean()

    print(f"\n  TRADE RESULTS (convergence >= {min_convergence}):")
    print(f"  Total trades:    {total}")
    print(f"  Win rate:        {win_rate:.1%} ({wins}/{total})")
    print(f"  Target hit rate: {targets_hit/total:.1%} ({targets_hit}/{total})")
    print(f"  Avg pips/trade:  ${avg_pips:.1f}")
    print(f"  Avg winner:      ${avg_win:.1f}")
    print(f"  Avg loser:       ${avg_loss:.1f}")
    print(f"  R:R ratio:       {abs(avg_win/avg_loss):.2f}" if avg_loss != 0 else "  R:R: N/A")
    print(f"  Avg hold time:   {avg_hold:.0f} H1 bars")
    print(f"  Total P&L:       ${pips_arr.sum():.1f}")

    # By convergence score
    print(f"\n  BY CONVERGENCE SCORE:")
    for sc in sorted(set(t.convergence_score for t in trades)):
        sc_trades = [t for t in trades if t.convergence_score == sc]
        sc_pips = [t.pips for t in sc_trades]
        sc_wins = sum(1 for p in sc_pips if p > 0)
        print(f"    Score {sc}: {len(sc_trades)} trades, win={sc_wins/len(sc_trades):.0%}, avg=${np.mean(sc_pips):.1f}")

    # By direction
    for d in ["long", "short"]:
        d_trades = [t for t in trades if t.direction == d]
        if d_trades:
            d_pips = [t.pips for t in d_trades]
            d_wins = sum(1 for p in d_pips if p > 0)
            print(f"\n  {d.upper()}: {len(d_trades)} trades, win={d_wins/len(d_trades):.0%}, avg=${np.mean(d_pips):.1f}, total=${sum(d_pips):.1f}")

    return {
        "total_trades": total,
        "win_rate": win_rate,
        "target_hit_rate": targets_hit / total,
        "avg_pips": avg_pips,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "rr_ratio": abs(avg_win / avg_loss) if avg_loss != 0 else 0,
        "avg_hold_bars": avg_hold,
        "total_pnl": pips_arr.sum(),
        "trades": trades,
    }


# ============================================================
# 6. FILL GAPS: What formulas need adjustment for Gold?
# ============================================================

def analyze_gaps(m1: pd.DataFrame) -> dict:
    """Analyze specific formula gaps from GANN_METHOD_ANALYSIS.md.

    Tests:
    - Cube root step: does step=104 still hold for current gold prices?
    - Even/odd degree system: do both need to converge?
    - Speed/acceleration: find the right scaling for gold
    - Price reduction: mod 1000 vs other methods
    """
    print("\n=== ANALYZING FORMULA GAPS ===")
    d1 = resample_timeframe(m1, "D1")
    h1 = resample_timeframe(m1, "H1")

    results = {}

    # Gap 1: Cube root step at different price ranges
    print("\n  1. CUBE ROOT STEP across gold price ranges:")
    price_ranges = {
        "1050-1200 (2015-2016)": (1050, 1200),
        "1200-1400 (2017-2019)": (1200, 1400),
        "1400-2100 (2020-2024)": (1400, 2100),
        "2100-2900 (2024-2026)": (2100, 2900),
    }
    for label, (pmin, pmax) in price_ranges.items():
        for test_price in [pmin, (pmin + pmax) // 2, pmax]:
            cr_val = test_price ** (1/3)
            step = round(cr_val / 52) * 52
            if step == 0:
                step = 52
            cr = test_price ** (1/3)
            print(f"    {test_price:>5d}: cube_root={cr:.2f}, step={step} (nearest 52-multiple)")
    results["cube_root_steps"] = {p: round(p**(1/3) / 52) * 52 or 52 for p in [1100, 1300, 1500, 1800, 2000, 2500, 2800]}

    # Gap 2: What price reduction works for gold at different levels?
    print("\n  2. GOLD PRICE REDUCTION methods:")
    test_prices = [1050.5, 1267.3, 1375.0, 1520.8, 1771.2, 2072.5, 2400.0, 2750.0]
    for p in test_prices:
        mod1000 = gann.reduce_gold_price(p)
        mod100 = int(p) % 100
        last2 = int(p) % 100
        sq9_deg = gann.price_to_sq9_degree(p)
        sq9_deg_reduced = gann.price_to_sq9_degree(mod1000)
        print(f"    ${p:>7.1f}: mod1000={mod1000:>4d}, mod100={mod100:>3d}, Sq9 deg={sq9_deg:>6.1f}, reduced Sq9={sq9_deg_reduced:>6.1f}")

    # Gap 3: Find actual swing speed/acceleration patterns for gold
    print("\n  3. SPEED / ACCELERATION patterns (H1):")
    swings = detect_swings(h1, atr_multiplier=2.5)
    pairs = swing_pairs(swings)
    speeds = []
    for pair in pairs:
        if pair["duration_bars"] > 5 and pair["price_move"] > 5:
            speed = pair["price_move"] / pair["duration_bars"]
            speeds.append({
                "speed": speed,
                "move": pair["price_move"],
                "duration": pair["duration_bars"],
                "accel": speed ** 2,
            })

    if speeds:
        speed_vals = [s["speed"] for s in speeds]
        print(f"    Speed ($/H1 bar): mean={np.mean(speed_vals):.2f}, median={np.median(speed_vals):.2f}")
        print(f"    Range: {min(speed_vals):.2f} to {max(speed_vals):.2f}")
        print(f"    Accel (speed^2):  mean={np.mean([s['accel'] for s in speeds]):.2f}")

        # Test the stop rule: when remaining_speed > acceleration, did it stop?
        stop_correct = 0
        stop_total = 0
        for i in range(len(pairs) - 1):
            if pairs[i]["duration_bars"] < 10 or pairs[i]["price_move"] < 10:
                continue
            initial_speed = pairs[i]["price_move"] / pairs[i]["duration_bars"]
            accel = initial_speed ** 2

            # Check the last portion of the swing
            half_dur = pairs[i]["duration_bars"] // 2
            if half_dur < 3:
                continue
            # Approximate: remaining move ≈ price_move/2, remaining time ≈ duration/2
            # (rough, since we don't have bar-by-bar data in swing pairs)
            remaining_speed = (pairs[i]["price_move"] * 0.3) / (pairs[i]["duration_bars"] * 0.2)
            stop_total += 1
            if remaining_speed > accel:
                # Theory says it should stop — did the next swing go the other way?
                if i + 1 < len(pairs):
                    did_stop = pairs[i + 1]["start_type"] != pairs[i]["start_type"]
                    if did_stop:
                        stop_correct += 1

        if stop_total > 0:
            print(f"\n    Speed>Accel stop rule: {stop_correct}/{stop_total} correct ({stop_correct/stop_total:.1%})")
    results["speed_stats"] = speeds[:10] if speeds else []

    return results


# ============================================================
# MASTER CALIBRATION RUNNER
# ============================================================

def calibrate_angle_scales(m1: pd.DataFrame, vibration: float = 72.0) -> dict:
    """Empirically find the best $/bar scale for Gann 1x1 angles per timeframe.

    Uses V=72 base vibration and its subdivisions as candidates.
    For each TF, draws 1x1 angles from swings and measures what %
    of trend bars stay on the correct side of the angle.

    Gann Ch 5A: "As long as the market stays above the 45-degree angle,
    it is in a strong position."
    """
    from .gann_angles import calibrate_scale, LOST_MOTION

    print("\n=== CALIBRATING GANN ANGLE SCALES ===")

    # Candidates based on V=72 subdivisions and KU series
    # V/72=1, V/36=2, V/24=3, V/12=6, V/6=12, V/4=18, V/3=24, V/2=36, V=72
    candidates = [0.5, 1.0, 2.0, 3.0, 5.0, 6.0, 7.0, 12.0, 18.0, 24.0, 36.0, 72.0]

    timeframes = ["M5", "H1", "H4", "D1"]
    results = {}

    for tf in timeframes:
        print(f"\n  {tf}:")
        resampled = resample_timeframe(m1, tf)
        if len(resampled) < 100:
            print(f"    Too few bars ({len(resampled)}), skipping")
            continue

        swings = detect_swings(resampled, atr_multiplier=2.5)
        if len(swings) < 6:
            print(f"    Too few swings ({len(swings)}), skipping")
            continue

        cal = calibrate_scale(swings, resampled, candidates=candidates, vibration=vibration)
        best = cal["best_scale"]
        best_info = cal["scores"].get(best, {})

        results[tf] = {
            "best_scale": best,
            "mean_pct": best_info.get("mean_pct_correct", 0),
            "all_scores": cal["scores"],
        }

        # Print top 5 candidates
        sorted_scores = sorted(
            cal["scores"].items(),
            key=lambda x: x[1]["score"],
            reverse=True,
        )[:5]
        for scale_val, info in sorted_scores:
            print(f"    scale=${scale_val:>5.1f}/bar: "
                  f"{info['mean_pct_correct']:.1%} correct side "
                  f"(score={info['score']:.3f}, "
                  f"up={info['n_upswings']}, dn={info['n_downswings']})")

        print(f"    >>> Best: ${best}/bar")

    return results


def run_calibration(m1_train: pd.DataFrame, m1_test: pd.DataFrame) -> dict:
    """Run full calibration on train set, validate key findings on test set."""

    print("\n" + "=" * 70)
    print("  GANN CALIBRATION FOR GOLD (XAUUSD)")
    print("  Train: 2015-2019 | Validate: 2020-2026")
    print("=" * 70)

    all_results = {}

    # 1. Vibration constant
    print("\n" + "=" * 60)
    print("  PHASE 1: VIBRATION CONSTANT")
    print("=" * 60)
    print("\n--- TRAIN SET ---")
    vib_train = calibrate_vibration(m1_train)
    print("\n--- TEST SET (validation) ---")
    vib_test = calibrate_vibration(m1_test)
    all_results["vibration"] = {"train": vib_train, "test": vib_test}

    best_v = vib_train["best_v"]

    # 2. Sq9 degree accuracy
    print("\n" + "=" * 60)
    print("  PHASE 2: SQ9 DEGREE CALIBRATION")
    print("=" * 60)
    print("\n--- TRAIN SET ---")
    sq9_train = calibrate_sq9_degrees(m1_train)
    print("\n--- TEST SET ---")
    sq9_test = calibrate_sq9_degrees(m1_test)
    all_results["sq9"] = {"train": sq9_train, "test": sq9_test}

    # 3. Time projections
    print("\n" + "=" * 60)
    print("  PHASE 3: TIME PROJECTION CALIBRATION")
    print("=" * 60)
    print("\n--- TRAIN SET ---")
    time_train = calibrate_time_projection(m1_train)
    print("\n--- TEST SET ---")
    time_test = calibrate_time_projection(m1_test)
    all_results["time"] = {"train": time_train, "test": time_test}

    # 4. Convergence scoring
    print("\n" + "=" * 60)
    print("  PHASE 4: CONVERGENCE CALIBRATION")
    print("=" * 60)
    print("\n--- TRAIN SET ---")
    conv_train = calibrate_convergence(m1_train, vibration=best_v)
    print("\n--- TEST SET ---")
    conv_test = calibrate_convergence(m1_test, vibration=best_v)
    all_results["convergence"] = {"train": conv_train, "test": conv_test}

    # 5. Trade simulation
    print("\n" + "=" * 60)
    print("  PHASE 5: TRADE SIMULATION")
    print("=" * 60)
    print("\n--- TRAIN SET ---")
    trades_train = simulate_gann_trades(m1_train, vibration=best_v)
    print("\n--- TEST SET ---")
    trades_test = simulate_gann_trades(m1_test, vibration=best_v)
    all_results["trades"] = {"train": trades_train, "test": trades_test}

    # 6. Formula gaps
    print("\n" + "=" * 60)
    print("  PHASE 6: FORMULA GAPS ANALYSIS")
    print("=" * 60)
    print("\n--- FULL DATASET ---")
    import pandas as pd
    full = pd.concat([m1_train, m1_test])
    gaps = analyze_gaps(full)
    all_results["gaps"] = gaps

    # Final summary
    print("\n" + "=" * 70)
    print("  CALIBRATION SUMMARY")
    print("=" * 70)
    print(f"\n  Gold Vibration Constant: {best_v}")
    print(f"    Train lift: {vib_train['all_results'].get(best_v, {}).get('lift', 'N/A')}")
    print(f"    Test lift:  {vib_test['all_results'].get(best_v, {}).get('lift', 'N/A')}")

    if sq9_train.get("top_degrees"):
        print(f"\n  Top Sq9 Degrees: {sq9_train['top_degrees']}")

    if trades_train.get("total_trades"):
        print(f"\n  Trade Quality (Train):")
        print(f"    Trades: {trades_train['total_trades']}")
        print(f"    Win rate: {trades_train['win_rate']:.1%}")
        print(f"    Avg pips: ${trades_train['avg_pips']:.1f}")
        print(f"    R:R: {trades_train['rr_ratio']:.2f}")

    if trades_test.get("total_trades"):
        print(f"\n  Trade Quality (Test):")
        print(f"    Trades: {trades_test['total_trades']}")
        print(f"    Win rate: {trades_test['win_rate']:.1%}")
        print(f"    Avg pips: ${trades_test['avg_pips']:.1f}")
        print(f"    R:R: {trades_test['rr_ratio']:.2f}")

    return all_results
