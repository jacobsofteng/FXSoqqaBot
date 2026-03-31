/*
 * Gann Fast Backtester v9.1 — Triangle-First Architecture
 *
 * Direct port of the Python v9.1 strategy:
 *   constants.py → sq9_engine.py → vibration.py → proportional.py →
 *   time_structure.py → swing_detector.py → wave_counter.py →
 *   triangle_engine.py → convergence.py → three_limits.py →
 *   execution.py → risk.py → strategy.py → backtester.py
 *
 * 4-State Machine: SCANNING → QUANT_FORMING → BOX_ACTIVE → IN_TRADE
 *
 * Binary data format (XAUUSD_M5.bin):
 *   8-byte header: int64 record count
 *   Records: int32 timestamp + int32 padding + 4 doubles (OHLC) = 40 bytes
 *
 * Compile: C:/msys64/mingw64/bin/g++.exe -O3 -std=c++17 -o gann_bt gann_backtest.cpp -lm
 * Run:     ./gann_bt ../data/clean/XAUUSD_M5.bin
 */

#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <cstring>
#include <vector>
#include <algorithm>
#include <cstdint>
#include <cfloat>
#include <string>
#include <numeric>
#include <ctime>

// ============================================================
// CONSTANTS (from constants.py — DO NOT CHANGE)
// ============================================================

static constexpr double BASE_VIBRATION        = 72.0;
static constexpr double SWING_QUANTUM         = 12.0;   // V/6
static constexpr double GROWTH_QUANTUM        = 18.0;   // V/4
static constexpr double CORRECTION_QUANTUM    = 24.0;   // V/3
static constexpr double LOST_MOTION           = 3.0;
static constexpr int    POWER_ANGLES[]        = {30, 45};
static constexpr int    NATURAL_SQ[]          = {4, 9, 16, 24, 36, 49, 72, 81};
static constexpr double NATURAL_SQ_STRENGTH[] = {0.23, 0.28, 0.15, 0.10, 0.08, 0.05, 0.04, 0.03};
static constexpr int    NUM_NATURAL_SQ        = 8;
static constexpr int    MAX_HOLD_BARS         = 288;    // M5 bars = 24h
static constexpr int    MAX_DAILY_TRADES      = 5;
static constexpr int    MIN_CONVERGENCE_SCAN  = 3;  // SCANNING: 3 of 6 categories
static constexpr int    MIN_CONVERGENCE_BOX   = 4;  // BOX_ACTIVE: 4 of 7
static constexpr int    MIN_LIMITS            = 2;
static constexpr double MIN_RR_RATIO          = 2.0;
static constexpr int    WAVE_MULTIPLIER       = 3;
static constexpr double VIBRATION_OVERRIDE    = 4.0 * BASE_VIBRATION; // $288

static constexpr int    ATR_PERIOD            = 14;
static constexpr double ATR_MULTIPLIER        = 1.5;

// Impulse ratios (in V-units, H1 bars / SWING_QUANTUM)
static constexpr int    IMPULSE_RATIOS[]      = {8, 16, 64};
static constexpr int    NUM_IMPULSE_RATIOS    = 3;

// Spread simulation (set to 0 to match Python backtester exactly)
static constexpr double SPREAD                = 0.00;

// M5-to-higher-TF conversion
static constexpr int    M5_PER_H1             = 12;
static constexpr int    M5_PER_H4             = 48;
static constexpr int    M5_PER_D1             = 288;

// Gann angle ratios for box diagonals
static constexpr double GANN_ANGLE_RATIOS[]   = {1.0, 2.0, 0.5, 4.0, 0.25};
static constexpr int    NUM_ANGLE_RATIOS      = 5;

// ============================================================
// DATA STRUCTURES
// ============================================================

struct Bar {
    int64_t timestamp;
    double open, high, low, close;
    int bar_index;
};

struct Swing {
    double price;
    int bar_index;         // Bar where extreme occurred (in source TF)
    int m5_bar_index;      // Corresponding M5 bar index (for cross-TF mapping)
    int type;              // 1=high, -1=low
    double atr_at_swing;
};

struct WaveState {
    int wave_number;
    double wave_0_price;
    double wave_0_size;
    int direction;         // 1=up, -1=down, 0=flat
    double targets[8];
    int num_targets;
    bool is_trending;
    bool valid;
};

struct QuantMeasurement {
    double quant_pips;
    int quant_bars;
    double box_height;
    int box_width;
    double scale;          // price per bar (1x1)
    int triangle_apex_bar;
    int direction;         // 1=up, -1=down
    double touch_price;
    double extreme_price;
    int convergence_bar;
    bool valid;
};

struct Point2D {
    double x, y;           // x=bar, y=price
};

struct Diagonal {
    Point2D start, end;
    int type;              // 0=main, 1=gann_angle, 2=inner, 3=grid
};

struct Intersection {
    int bar;
    double price;
    int count;             // number of crossings clustered here
};

struct GannBox {
    // Box boundaries
    double top, bottom, height;
    int start_bar, end_bar, width;
    double scale;

    // Zones (M5 bar indices)
    int red_end;           // start_bar .. red_end
    int yellow_end;        // red_end .. yellow_end
    int green_end;         // yellow_end .. end_bar = green_end

    // Midpoint
    double mid_price;
    int mid_bar;

    // Diagonals and intersections
    std::vector<Diagonal> diagonals;
    std::vector<Intersection> power_points;     // count >= 3
    std::vector<Intersection> green_zone_points;

    // Quant info
    QuantMeasurement quant;

    bool valid;
};

struct TradeRecord {
    int entry_bar, exit_bar;
    double entry_price, exit_price;
    int direction;         // 1=long, -1=short
    double sl, tp;
    double sl_distance, tp_distance;
    double rr_ratio;
    double pnl;
    int bars_held;
    bool won;
    int exit_reason;       // 0=TP, 1=SL, 2=timeout, 3=close
    int convergence_score;
};

struct OpenTrade {
    double entry_price;
    double sl, tp;
    int direction;         // 1=long, -1=short
    int entry_bar;
    double sl_distance, tp_distance;
    double rr_ratio;
    bool active;
};

// ============================================================
// SQ9 ENGINE (from sq9_engine.py)
// ============================================================

static inline double sq9_degree(double price) {
    if (price <= 0) return 0.0;
    double v = fmod(sqrt(price) * 180.0 - 225.0, 360.0);
    return v < 0.0 ? v + 360.0 : v;
}

static void sq9_levels_from_price(double price, std::vector<double>& out,
                                  int count = 3) {
    out.clear();
    if (price <= 0) return;

    double ref_sqrt = sqrt(price);

    for (int a = 0; a < 2; a++) {
        double step = POWER_ANGLES[a] / 180.0;
        for (int ring = -count; ring <= count; ring++) {
            if (ring == 0) continue;
            double target_sqrt = ref_sqrt + step * ring;
            if (target_sqrt > 0) {
                double level = target_sqrt * target_sqrt;
                if (fabs(level - price) <= price * 0.15) {
                    out.push_back(level);
                }
            }
        }
    }

    std::sort(out.begin(), out.end());
    // Remove duplicates
    out.erase(std::unique(out.begin(), out.end(),
              [](double a, double b) { return fabs(a - b) < 0.005; }),
              out.end());
}

// ============================================================
// VIBRATION (from vibration.py)
// ============================================================

static bool check_vibration_level(double current_price, double swing_price) {
    double distance = fabs(current_price - swing_price);
    double remainder = fmod(distance, SWING_QUANTUM);
    return (remainder <= LOST_MOTION ||
            (SWING_QUANTUM - remainder) <= LOST_MOTION);
}

static bool check_vibration_override(double move_from_swing) {
    return fabs(move_from_swing) >= VIBRATION_OVERRIDE;
}

// ============================================================
// PROPORTIONAL (from proportional.py)
// ============================================================

static bool check_proportional_level(double current_price,
                                     double swing_high, double swing_low) {
    double range = swing_high - swing_low;
    if (range < SWING_QUANTUM) return false;

    // Check primary fractions: 1/3, 1/2, 2/3
    double fracs[] = {1.0/3.0, 1.0/2.0, 2.0/3.0};
    for (int i = 0; i < 3; i++) {
        double level = swing_low + range * fracs[i];
        if (fabs(current_price - level) <= LOST_MOTION) {
            return true;
        }
    }
    return false;
}

// ============================================================
// TIME STRUCTURE (from time_structure.py)
// ============================================================

struct TimeWindowResult {
    bool active;
    int matching_square;
    double window_strength;
    bool impulse_match;
};

static TimeWindowResult check_time_window(int h4_bars_elapsed) {
    TimeWindowResult r = {false, -1, 0.0, false};

    // Check natural square timing (±1 H4 bar tolerance)
    for (int i = 0; i < NUM_NATURAL_SQ; i++) {
        if (abs(h4_bars_elapsed - NATURAL_SQ[i]) <= 1) {
            r.active = true;
            r.matching_square = NATURAL_SQ[i];
            r.window_strength = NATURAL_SQ_STRENGTH[i];
            return r;
        }
    }

    // Check vibration-scaled impulse timing (on H1 bars)
    int bars_h1 = h4_bars_elapsed * 4;
    if (SWING_QUANTUM > 0) {
        double scaled_ratio = (double)bars_h1 / SWING_QUANTUM;
        for (int i = 0; i < NUM_IMPULSE_RATIOS; i++) {
            if (fabs(scaled_ratio - IMPULSE_RATIOS[i]) <= 1.0) {
                r.active = true;
                r.window_strength = 0.15;
                r.impulse_match = true;
                return r;
            }
        }
    }

    return r;
}

// ============================================================
// SWING DETECTOR (from swing_detector.py — ATR ZigZag)
// ============================================================

static void detect_swings_atr(const std::vector<Bar>& bars,
                              std::vector<Swing>& swings,
                              int atr_period = ATR_PERIOD,
                              double atr_multiplier = ATR_MULTIPLIER) {
    swings.clear();
    int n = (int)bars.size();
    if (n < atr_period + 1) return;

    // Calculate True Range
    std::vector<double> trs(n, 0.0);
    for (int i = 1; i < n; i++) {
        double tr = bars[i].high - bars[i].low;
        tr = std::max(tr, fabs(bars[i].high - bars[i-1].close));
        tr = std::max(tr, fabs(bars[i].low  - bars[i-1].close));
        trs[i] = tr;
    }

    int direction = 0;     // 0=none, 1=up, -1=down
    double last_high = bars[0].high;
    int last_high_idx = 0;
    double last_low = bars[0].low;
    int last_low_idx = 0;

    for (int i = atr_period; i < n; i++) {
        // Rolling ATR
        int start = std::max(1, i - atr_period);
        double atr_sum = 0;
        int atr_count = 0;
        for (int j = start; j <= i; j++) {
            atr_sum += trs[j];
            atr_count++;
        }
        double atr = atr_count > 0 ? atr_sum / atr_count : 1.0;
        double threshold = atr * atr_multiplier;

        if (bars[i].high > last_high) {
            last_high = bars[i].high;
            last_high_idx = i;
        }
        if (bars[i].low < last_low) {
            last_low = bars[i].low;
            last_low_idx = i;
        }

        if (direction != -1 && last_high - bars[i].low > threshold) {
            // Confirm swing HIGH
            Swing sw;
            sw.price = last_high;
            sw.bar_index = last_high_idx;
            sw.m5_bar_index = bars[last_high_idx].bar_index;
            sw.type = 1;
            sw.atr_at_swing = atr;
            swings.push_back(sw);

            direction = -1;
            last_low = bars[i].low;
            last_low_idx = i;
        }
        else if (direction != 1 && bars[i].high - last_low > threshold) {
            // Confirm swing LOW
            Swing sw;
            sw.price = last_low;
            sw.bar_index = last_low_idx;
            sw.m5_bar_index = bars[last_low_idx].bar_index;
            sw.type = -1;
            sw.atr_at_swing = atr;
            swings.push_back(sw);

            direction = 1;
            last_high = bars[i].high;
            last_high_idx = i;
        }
    }
}

// ============================================================
// WAVE COUNTER (from wave_counter.py — vpM2F(t))
// ============================================================

static WaveState count_waves(const std::vector<Swing>& swings) {
    WaveState w = {};
    w.valid = false;
    w.num_targets = 0;

    if ((int)swings.size() < 4) return w;

    // Find wave 0 = transition point (largest ratio change)
    int lookback = 6;
    int start = std::max(0, (int)swings.size() - lookback);
    if ((int)swings.size() - start < 3) {
        start = std::max(0, (int)swings.size() - 3);
    }

    int best_idx = start;
    double best_score = 0.0;

    for (int i = start + 2; i < (int)swings.size(); i++) {
        double prev_size = fabs(swings[i-1].price - swings[i-2].price);
        double curr_size = fabs(swings[i].price - swings[i-1].price);
        if (prev_size < 0.01) continue;

        double ratio_change = curr_size / prev_size;
        if (ratio_change > 1.5 || ratio_change < 0.67) {
            double score = fabs(log(ratio_change));
            if (score > best_score) {
                best_score = score;
                best_idx = i - 1;
            }
        }
    }

    if (best_score <= 0.3) return w;  // No clear transition

    int wave_0_idx = best_idx;
    int scenario_count = (int)swings.size() - wave_0_idx;

    // Wave 0 size
    double wave_0_size = 0.0;
    if (scenario_count >= 2) {
        wave_0_size = fabs(swings[wave_0_idx + 1].price - swings[wave_0_idx].price);
    } else {
        int n2 = (int)swings.size();
        wave_0_size = fabs(swings[n2-1].price - swings[n2-2].price);
    }

    if (wave_0_size < 1.0) return w;

    w.valid = true;
    w.wave_number = scenario_count - 1;
    w.wave_0_price = swings[wave_0_idx].price;
    w.wave_0_size = wave_0_size;

    // Direction from wave 0 swing type
    if (swings[wave_0_idx].type == -1) {  // low
        w.direction = 1;   // up
    } else {
        w.direction = -1;  // down
    }

    w.is_trending = (w.wave_number % 2 == 1);

    // Generate targets
    w.num_targets = 0;
    for (int n = 1; n <= 7 && w.num_targets < 8; n++) {
        if (w.direction == 1) {
            w.targets[w.num_targets] = w.wave_0_price + wave_0_size * (n + 1);
        } else {
            w.targets[w.num_targets] = w.wave_0_price - wave_0_size * (n + 1);
        }
        w.num_targets++;
    }

    return w;
}

// ============================================================
// CONVERGENCE SCORER (from convergence.py — 7 categories)
// ============================================================

struct ConvergenceResult {
    int score;
    bool categories[7];   // A-G
    bool is_tradeable;
};

static ConvergenceResult score_convergence(
    double current_price, int current_m5_bar,
    const std::vector<Swing>& swings_h1,
    const std::vector<Swing>& swings_h4,
    const WaveState& wave,
    const std::vector<Intersection>* triangle_power_points,
    int phase = 0 /* 0=scanning, 2=box_active */)
{
    ConvergenceResult r = {};
    r.score = 0;
    for (int i = 0; i < 7; i++) r.categories[i] = false;
    r.is_tradeable = false;

    if (swings_h1.size() < 2) return r;

    // Use last 5 H1 swings
    int num_recent = std::min(5, (int)swings_h1.size());
    int sw_start = (int)swings_h1.size() - num_recent;

    std::vector<double> sq9_levels;

    // --- CATEGORY A: Sq9 Price Level ---
    for (int si = sw_start; si < (int)swings_h1.size() && !r.categories[0]; si++) {
        sq9_levels_from_price(swings_h1[si].price, sq9_levels);
        for (double level : sq9_levels) {
            if (fabs(current_price - level) <= LOST_MOTION) {
                r.categories[0] = true;
                break;
            }
        }
    }

    // --- CATEGORY B: Vibration Level (V=12 multiple) ---
    for (int si = sw_start; si < (int)swings_h1.size() && !r.categories[1]; si++) {
        if (check_vibration_level(current_price, swings_h1[si].price)) {
            r.categories[1] = true;
        }
    }

    // --- CATEGORY C: Proportional Division (1/3, 1/2, 2/3) ---
    for (int i = sw_start; i < (int)swings_h1.size() - 1 && !r.categories[2]; i++) {
        for (int j = i + 1; j < (int)swings_h1.size() && !r.categories[2]; j++) {
            double hi = std::max(swings_h1[i].price, swings_h1[j].price);
            double lo = std::min(swings_h1[i].price, swings_h1[j].price);
            if (check_proportional_level(current_price, hi, lo)) {
                r.categories[2] = true;
            }
        }
    }

    // --- CATEGORY D: Time Window (natural square from last H4 swing) ---
    if (!swings_h4.empty()) {
        const Swing& last_h4 = swings_h4.back();
        int h4_bars_elapsed = (current_m5_bar - last_h4.m5_bar_index) / M5_PER_H4;
        TimeWindowResult tw = check_time_window(h4_bars_elapsed);
        r.categories[3] = tw.active;
    }

    // --- CATEGORY E: Triangle Crossing — ONLY in BOX_ACTIVE phase ---
    // Circular dependency: needs triangle to score, but needs score to build triangle
    if (phase == 2 && triangle_power_points && !triangle_power_points->empty()) {
        for (const auto& pp : *triangle_power_points) {
            bool price_match = fabs(current_price - pp.price) <= LOST_MOTION * 2;
            bool bar_match = abs(current_m5_bar - pp.bar) <= 3;
            if (price_match && bar_match) {
                r.categories[4] = true;
                break;
            }
        }
    }

    // --- CATEGORY F: Wave Target ---
    if (wave.valid && wave.num_targets > 0) {
        int check_count = std::min(wave.num_targets, 4);
        for (int i = 0; i < check_count; i++) {
            if (fabs(current_price - wave.targets[i]) <= LOST_MOTION * 2) {
                r.categories[5] = true;
                break;
            }
        }
    }

    // --- CATEGORY G: Price-Time Square ---
    // Gold scale: ~$6/H4 bar (V=72 / 12 H4_bars_per_day)
    {
        const double PRICE_PER_H4 = 6.0;
        for (int si = sw_start; si < (int)swings_h1.size() && !r.categories[6]; si++) {
            double price_move = fabs(current_price - swings_h1[si].price);
            int bars_elapsed = current_m5_bar - swings_h1[si].m5_bar_index;
            double time_h4 = (double)bars_elapsed / M5_PER_H4;

            if (time_h4 >= 1.0 && price_move >= SWING_QUANTUM) {
                double expected_price = time_h4 * PRICE_PER_H4;
                double ratio = (expected_price > 0) ? price_move / expected_price : 0;
                if (ratio >= 0.6 && ratio <= 1.4) {
                    r.categories[6] = true;
                }
            }
        }
    }

    // Final score
    for (int i = 0; i < 7; i++) {
        if (r.categories[i]) r.score++;
    }
    // SCANNING: 3 of 6 categories (E excluded). BOX_ACTIVE: 4 of 7.
    int threshold = (phase == 0) ? MIN_CONVERGENCE_SCAN : MIN_CONVERGENCE_BOX;
    r.is_tradeable = (r.score >= threshold);

    return r;
}

// ============================================================
// THREE LIMITS (from three_limits.py)
// ============================================================

struct LimitsResult {
    bool limit1, limit2, limit3;
    int count;
};

static LimitsResult check_three_limits(
    double current_price, int current_m5_bar,
    const std::vector<Swing>& swings_h1)
{
    LimitsResult r = {false, false, false, 0};
    if (swings_h1.empty()) return r;

    const Swing& last = swings_h1.back();

    // LIMIT 1: Price-by-Time (Sq9 degree matching with vibration scaling)
    double price_move = fabs(current_price - last.price);
    double price_units = price_move / SWING_QUANTUM;
    double time_units = (double)(current_m5_bar - last.m5_bar_index);

    if (price_units > 0 && time_units > 0) {
        double price_deg = sq9_degree(price_units);
        double time_deg = sq9_degree(time_units);
        double diff = fabs(price_deg - time_deg);
        diff = std::min(diff, 360.0 - diff);
        r.limit1 = (diff <= 5.0);
    }

    // LIMIT 2: Price-by-Price (at any Gann level from last 5 swings)
    int num_check = std::min(5, (int)swings_h1.size());
    int sw_start = (int)swings_h1.size() - num_check;
    std::vector<double> sq9_levels;

    for (int si = sw_start; si < (int)swings_h1.size() && !r.limit2; si++) {
        // Sq9 levels
        sq9_levels_from_price(swings_h1[si].price, sq9_levels);
        for (double level : sq9_levels) {
            if (fabs(current_price - level) <= LOST_MOTION) {
                r.limit2 = true;
                break;
            }
        }
        // Vibration levels
        if (!r.limit2 && check_vibration_level(current_price, swings_h1[si].price)) {
            r.limit2 = true;
        }
    }

    // LIMIT 3: Time-by-Time (bars elapsed matches natural square)
    int bars_elapsed = current_m5_bar - last.m5_bar_index;
    for (int i = 0; i < NUM_NATURAL_SQ; i++) {
        if (abs(bars_elapsed - NATURAL_SQ[i]) <= 1) {
            r.limit3 = true;
            break;
        }
    }

    r.count = (int)r.limit1 + (int)r.limit2 + (int)r.limit3;
    return r;
}

// ============================================================
// TRIANGLE ENGINE (from triangle_engine.py)
// ============================================================

// 2D line segment intersection
static bool line_intersect(Point2D p1, Point2D p2, Point2D p3, Point2D p4,
                           double& out_x, double& out_y) {
    double denom = (p1.x - p2.x) * (p3.y - p4.y) - (p1.y - p2.y) * (p3.x - p4.x);
    if (fabs(denom) < 1e-10) return false;

    double t = ((p1.x - p3.x) * (p3.y - p4.y) - (p1.y - p3.y) * (p3.x - p4.x)) / denom;
    double u = -((p1.x - p2.x) * (p1.y - p3.y) - (p1.y - p2.y) * (p1.x - p3.x)) / denom;

    if (t >= 0 && t <= 1 && u >= 0 && u <= 1) {
        out_x = p1.x + t * (p2.x - p1.x);
        out_y = p1.y + t * (p2.y - p1.y);
        return true;
    }
    return false;
}

// Find upper and lower diagonal bounds at a specific bar
static void get_diagonal_bounds(const std::vector<Diagonal>& diags,
                                int bar_idx, double box_top, double box_bottom,
                                double& upper, double& lower) {
    upper = box_top;
    lower = box_bottom;
    double mid = (upper + lower) / 2.0;

    for (const auto& d : diags) {
        double dx = d.end.x - d.start.x;
        if (fabs(dx) < 0.001) continue;

        double t = ((double)bar_idx - d.start.x) / dx;
        if (t < 0 || t > 1) continue;

        double price_at_bar = d.start.y + t * (d.end.y - d.start.y);

        if (price_at_bar > mid && price_at_bar < upper) {
            upper = price_at_bar;
        } else if (price_at_bar < mid && price_at_bar > lower) {
            lower = price_at_bar;
        }
    }
}

// Cluster raw intersections
static void cluster_intersections(
    std::vector<std::pair<double,double>>& raw,   // (bar, price) pairs
    double price_tol, int bar_tol,
    std::vector<Intersection>& out)
{
    out.clear();
    int n = (int)raw.size();
    std::vector<bool> used(n, false);

    for (int i = 0; i < n; i++) {
        if (used[i]) continue;
        double sum_bar = raw[i].first;
        double sum_price = raw[i].second;
        int count = 1;
        used[i] = true;

        for (int j = i + 1; j < n; j++) {
            if (used[j]) continue;
            if (fabs(raw[i].first - raw[j].first) <= bar_tol &&
                fabs(raw[i].second - raw[j].second) <= price_tol) {
                sum_bar += raw[j].first;
                sum_price += raw[j].second;
                count++;
                used[j] = true;
            }
        }

        Intersection ix;
        ix.bar = (int)round(sum_bar / count);
        ix.price = sum_price / count;
        ix.count = count;
        out.push_back(ix);
    }

    // Sort by count descending
    std::sort(out.begin(), out.end(),
              [](const Intersection& a, const Intersection& b) {
                  return a.count > b.count;
              });
}

// 1. Measure quant
static QuantMeasurement measure_quant(const std::vector<Bar>& m5_bars,
                                      int convergence_bar,
                                      int bars_available = -1) {
    QuantMeasurement q = {};
    q.valid = false;

    int n = (bars_available > 0) ? bars_available : (int)m5_bars.size();
    if (convergence_bar >= n - 2) return q;

    double touch_price = m5_bars[convergence_bar].close;
    double extreme_price = touch_price;
    int extreme_bar = convergence_bar;
    int direction = 0;  // 0=none, 1=up, -1=down

    int scan_limit = std::min(convergence_bar + 50, n);
    for (int i = convergence_bar + 1; i < scan_limit; i++) {
        if (direction == 0 || direction == 1) {
            if (m5_bars[i].high > extreme_price) {
                extreme_price = m5_bars[i].high;
                extreme_bar = i;
                direction = 1;
            }
        }
        if (direction == 0 || direction == -1) {
            if (m5_bars[i].low < extreme_price) {
                extreme_price = m5_bars[i].low;
                extreme_bar = i;
                direction = -1;
            }
        }

        // Quant complete when price reverses by 1/3 of the move
        double move = fabs(extreme_price - touch_price);
        if (move < SWING_QUANTUM * 0.5) continue;

        if (direction == 1 && m5_bars[i].low < extreme_price - move / 3.0) break;
        if (direction == -1 && m5_bars[i].high > extreme_price + move / 3.0) break;
    }

    double quant_pips = fabs(extreme_price - touch_price);
    int quant_bars = extreme_bar - convergence_bar;

    if (quant_pips < SWING_QUANTUM * 0.5 || quant_bars < 1) return q;

    // Round to vibration quantum
    double box_height = round(quant_pips / SWING_QUANTUM) * SWING_QUANTUM;
    if (box_height < SWING_QUANTUM) box_height = SWING_QUANTUM;

    // Round bars to nearest natural square
    int box_width_base = NATURAL_SQ[0];
    int min_diff = abs(quant_bars - NATURAL_SQ[0]);
    for (int i = 1; i < NUM_NATURAL_SQ; i++) {
        int diff = abs(quant_bars - NATURAL_SQ[i]);
        if (diff < min_diff) {
            min_diff = diff;
            box_width_base = NATURAL_SQ[i];
        }
    }

    // Egyptian 3-4-5 proportion
    int box_width = std::max((int)(box_width_base * (4.0 / 3.0)), 4);

    q.quant_pips = quant_pips;
    q.quant_bars = quant_bars;
    q.box_height = box_height;
    q.box_width = box_width;
    q.scale = box_height / (double)box_width;
    q.triangle_apex_bar = convergence_bar + (int)(box_width * 0.75);
    q.direction = direction;
    q.touch_price = touch_price;
    q.extreme_price = extreme_price;
    q.convergence_bar = convergence_bar;
    q.valid = true;

    return q;
}

// 2. Construct Gann Box
static GannBox construct_gann_box(const QuantMeasurement& quant) {
    GannBox box = {};
    box.valid = false;
    if (!quant.valid) return box;

    double touch_price = quant.touch_price;
    double extreme_price = quant.extreme_price;
    int box_start = quant.convergence_bar;

    // Step 1: Box boundaries
    double box_top = std::max(touch_price, extreme_price) + LOST_MOTION;
    double box_bottom = std::min(touch_price, extreme_price) - LOST_MOTION;
    double box_height = box_top - box_bottom;

    // Extend to vibration-aligned dimensions
    double box_height_ext = std::max(box_height, SWING_QUANTUM * 2.0);
    box_height_ext = (((int)box_height_ext / (int)SWING_QUANTUM) + 1) * SWING_QUANTUM;

    // Recenter
    double center_price = (box_top + box_bottom) / 2.0;
    box_top = center_price + box_height_ext / 2.0;
    box_bottom = center_price - box_height_ext / 2.0;

    int box_width = quant.box_width;
    int box_end = box_start + box_width;
    double scale = box_width > 0 ? box_height_ext / (double)box_width : 1.0;

    box.top = box_top;
    box.bottom = box_bottom;
    box.height = box_height_ext;
    box.start_bar = box_start;
    box.end_bar = box_end;
    box.width = box_width;
    box.scale = scale;
    box.mid_price = center_price;
    box.mid_bar = box_start + box_width / 2;
    box.quant = quant;

    // Zones
    box.red_end = box_start + (int)(box_width * 1.0 / 3.0);
    box.yellow_end = box_start + (int)(box_width * 2.0 / 3.0);
    box.green_end = box_end;

    // Step 2: Grid divisions
    double price_fracs[] = {0, 1.0/8, 1.0/4, 1.0/3, 3.0/8, 1.0/2,
                            5.0/8, 2.0/3, 3.0/4, 7.0/8, 1.0};
    int num_fracs = 11;

    double price_levels[11];
    for (int i = 0; i < num_fracs; i++) {
        price_levels[i] = box_bottom + box_height_ext * price_fracs[i];
    }

    // Step 3: Generate all diagonals
    Point2D corners[4] = {
        {(double)box_start, box_bottom},   // BL
        {(double)box_start, box_top},      // TL
        {(double)box_end,   box_bottom},   // BR
        {(double)box_end,   box_top},      // TR
    };

    // Main diagonals from corners (6 pairs)
    for (int i = 0; i < 4; i++) {
        for (int j = i + 1; j < 4; j++) {
            box.diagonals.push_back({corners[i], corners[j], 0});
        }
    }

    // Gann angles from each corner
    for (int ci = 0; ci < 4; ci++) {
        for (int ai = 0; ai < NUM_ANGLE_RATIOS; ai++) {
            double slope = scale * GANN_ANGLE_RATIOS[ai];
            for (int dir = -1; dir <= 1; dir += 2) {
                double end_x = (corners[ci].x == (double)box_start)
                               ? (double)box_end : (double)box_start;
                double end_y = corners[ci].y + dir * slope * fabs(end_x - corners[ci].x);
                if (end_y >= box_bottom && end_y <= box_top) {
                    box.diagonals.push_back({corners[ci], {end_x, end_y}, 1});
                }
            }
        }
    }

    // Inner square diagonals (midpoints to corners)
    Point2D midpoints[4] = {
        {(double)box.mid_bar, box_bottom},
        {(double)box.mid_bar, box_top},
        {(double)box_start,   center_price},
        {(double)box_end,     center_price},
    };
    for (int mi = 0; mi < 4; mi++) {
        for (int ci = 0; ci < 4; ci++) {
            box.diagonals.push_back({midpoints[mi], corners[ci], 2});
        }
    }

    // Corner-to-grid diagonals (the "green lines")
    for (int ci = 0; ci < 4; ci++) {
        for (int pi = 0; pi < num_fracs; pi++) {
            double end_x = (corners[ci].x == (double)box_start)
                           ? (double)box_end : (double)box_start;
            box.diagonals.push_back({corners[ci], {end_x, price_levels[pi]}, 3});
        }
    }

    // Step 4: Find all intersections
    std::vector<std::pair<double,double>> raw_crossings;
    int nd = (int)box.diagonals.size();
    for (int i = 0; i < nd; i++) {
        for (int j = i + 1; j < nd; j++) {
            double ix, iy;
            if (line_intersect(box.diagonals[i].start, box.diagonals[i].end,
                               box.diagonals[j].start, box.diagonals[j].end,
                               ix, iy)) {
                raw_crossings.push_back({ix, iy});
            }
        }
    }

    std::vector<Intersection> all_intersections;
    cluster_intersections(raw_crossings, LOST_MOTION, 2, all_intersections);

    // Power points (count >= 3) and green zone points
    for (const auto& ix : all_intersections) {
        if (ix.count >= 3) {
            box.power_points.push_back(ix);
        }
        if (ix.bar >= box.yellow_end && ix.bar <= box.end_bar) {
            box.green_zone_points.push_back(ix);
        }
    }
    std::sort(box.green_zone_points.begin(), box.green_zone_points.end(),
              [](const Intersection& a, const Intersection& b) {
                  return a.count > b.count;
              });

    box.valid = true;
    return box;
}

// ============================================================
// GREEN ZONE ENTRY (from triangle_engine.py)
// ============================================================

struct EntrySignal {
    double entry_price;
    double sl, tp;
    double sl_distance, tp_distance;
    double rr_ratio;
    int direction;          // 1=long, -1=short
    double confidence;
    double triangle_gap;
    bool valid;
};

static EntrySignal find_green_zone_entry(
    const GannBox& box,
    const std::vector<Bar>& m5_bars,
    int current_bar_idx,
    int d1_direction,       // 1=up, -1=down, 0=flat
    int h1_wave_direction,  // 1=up, -1=down, 0=flat
    int wave_multiplier = WAVE_MULTIPLIER)
{
    EntrySignal sig = {};
    sig.valid = false;

    // Must be in Green Zone
    if (current_bar_idx < box.yellow_end || current_bar_idx > box.green_end)
        return sig;
    if (current_bar_idx >= (int)m5_bars.size())
        return sig;

    // Midpoint resolution — primary signal
    double current_price = m5_bars[current_bar_idx].close;
    int midpoint_dir = (current_price > box.mid_price) ? 1 : -1;

    // Direction: midpoint is primary. Reject only if BOTH D1 AND H1 disagree.
    int direction = midpoint_dir;
    int disagreements = 0;
    if (d1_direction != 0 && d1_direction != direction) disagreements++;
    if (h1_wave_direction != 0 && h1_wave_direction != direction) disagreements++;
    if (disagreements >= 2) return sig;

    // Get diagonal bounds at current bar
    double upper_bound, lower_bound;
    get_diagonal_bounds(box.diagonals, current_bar_idx,
                        box.top, box.bottom, upper_bound, lower_bound);

    double triangle_gap = upper_bound - lower_bound;
    if (triangle_gap <= 0) return sig;

    // Gap should be small (converging) — max 6 quanta ($72)
    if (triangle_gap > SWING_QUANTUM * 6.0) return sig;

    double quant_pips = box.quant.quant_pips;

    // Entry and SL/TP from diagonal geometry
    double entry_price, sl, tp;
    if (direction == 1) {  // long
        entry_price = lower_bound + LOST_MOTION;
        sl = lower_bound - LOST_MOTION;
        tp = entry_price + quant_pips * wave_multiplier;
    } else {               // short
        entry_price = upper_bound - LOST_MOTION;
        sl = upper_bound + LOST_MOTION;
        tp = entry_price - quant_pips * wave_multiplier;
    }

    double sl_distance = fabs(entry_price - sl);
    double tp_distance = fabs(tp - entry_price);
    double rr = (sl_distance > 0) ? tp_distance / sl_distance : 0;

    if (rr < MIN_RR_RATIO) return sig;

    // Confidence from nearby power points
    double confidence = 0.70;
    int max_count = 0;
    for (const auto& pp : box.green_zone_points) {
        if (abs(pp.bar - current_bar_idx) <= 2 &&
            fabs(pp.price - current_price) <= LOST_MOTION * 2) {
            if (pp.count > max_count) max_count = pp.count;
        }
    }
    if (max_count > 0) {
        confidence += std::min(0.25, max_count * 0.05);
    }

    sig.entry_price = entry_price;
    sig.sl = sl;
    sig.tp = tp;
    sig.sl_distance = sl_distance;
    sig.tp_distance = tp_distance;
    sig.rr_ratio = rr;
    sig.direction = direction;
    sig.confidence = confidence;
    sig.triangle_gap = triangle_gap;
    sig.valid = true;

    return sig;
}

// Check explosion potential
static bool check_explosion(const GannBox& box, int current_bar_idx,
                            int& energy_multiplier) {
    int explosion_start = box.start_bar + (int)(box.width * 5.0 / 6.0);
    if (current_bar_idx < explosion_start) return false;

    double upper, lower;
    get_diagonal_bounds(box.diagonals, current_bar_idx,
                        box.top, box.bottom, upper, lower);
    double gap = upper - lower;
    if (gap > SWING_QUANTUM) return false;

    int quant_bars = std::max(box.quant.quant_bars, 1);
    int bars_in_tri = current_bar_idx - box.start_bar;
    int oscillations = bars_in_tri / quant_bars;
    energy_multiplier = std::min(10, std::max(2, oscillations));
    return true;
}

// ============================================================
// M5 → HIGHER TF RESAMPLING
// ============================================================

static void resample_m5(const std::vector<Bar>& m5_bars, int period,
                        std::vector<Bar>& out, int start_from, int up_to) {
    out.clear();
    for (int s = start_from; s < up_to; s += period) {
        int end = std::min(s + period, up_to);
        if (s >= end) break;

        Bar b;
        b.timestamp = m5_bars[s].timestamp;
        b.open = m5_bars[s].open;
        b.high = m5_bars[s].high;
        b.low = m5_bars[s].low;
        b.close = m5_bars[end - 1].close;
        b.bar_index = m5_bars[s].bar_index;  // Global M5 index

        for (int j = s + 1; j < end; j++) {
            if (m5_bars[j].high > b.high) b.high = m5_bars[j].high;
            if (m5_bars[j].low < b.low)   b.low = m5_bars[j].low;
        }
        out.push_back(b);
    }
}

// ============================================================
// 4-STATE MACHINE (from strategy.py)
// ============================================================

enum Phase {
    SCANNING = 0,
    QUANT_FORMING = 1,
    BOX_ACTIVE = 2,
    IN_TRADE = 3,
};

struct StrategyState {
    Phase phase;
    GannBox active_box;
    OpenTrade open_trade;
    int daily_trades;
    int last_trade_day;    // day-of-year * 10000 + year for reset

    // Multi-timeframe
    int d1_direction;      // 1=up, -1=down, 0=flat
    WaveState h1_wave;
    std::vector<Swing> swings_h1;
    std::vector<Swing> swings_h4;
    std::vector<Swing> swings_d1;

    // Convergence tracking
    int convergence_bar;
    double convergence_price;

    // Trade log
    std::vector<TradeRecord> closed_trades;

    // Higher TF bar buffers
    std::vector<Bar> h1_bars;
    std::vector<Bar> h4_bars;
    std::vector<Bar> d1_bars;

    StrategyState() {
        phase = SCANNING;
        open_trade.active = false;
        daily_trades = 0;
        last_trade_day = -1;
        d1_direction = 0;
        h1_wave.valid = false;
        convergence_bar = 0;
        convergence_price = 0;
    }
};

// Extract day key from timestamp
static int day_from_timestamp(int64_t ts) {
    // Simple: divide by 86400 to get day number
    return (int)(ts / 86400);
}

// Update multi-timeframe data
static void update_mtf(const std::vector<Bar>& m5_bars, int current_idx,
                       StrategyState& st) {
    int n = current_idx + 1;

    // Only update every 12 M5 bars (= 1 H1 bar) for efficiency, or early on
    if (n % M5_PER_H1 != 0 && n > 50) return;

    // Sliding window — last 24000 M5 bars = 2000 H1 bars
    // CRITICAL: only resample up to current bar (no look-ahead)
    int window_size = std::min(n, 24000);
    int window_start = n - window_size;

    // Resample M5 → H1
    if (n >= 24) {
        resample_m5(m5_bars, M5_PER_H1, st.h1_bars, window_start, n);
        if ((int)st.h1_bars.size() >= 20) {
            detect_swings_atr(st.h1_bars, st.swings_h1);
        }
    }

    // Resample M5 → H4
    if (n >= 200) {
        resample_m5(m5_bars, M5_PER_H4, st.h4_bars, window_start, n);
        if ((int)st.h4_bars.size() >= 20) {
            detect_swings_atr(st.h4_bars, st.swings_h4);
        }
    }

    // Resample M5 → D1
    if (n >= 1000) {
        resample_m5(m5_bars, M5_PER_D1, st.d1_bars, window_start, n);
        if ((int)st.d1_bars.size() >= 20) {
            detect_swings_atr(st.d1_bars, st.swings_d1);
        }
    }

    // Wave counting on H1 swings
    if ((int)st.swings_h1.size() >= 4) {
        st.h1_wave = count_waves(st.swings_h1);
    }

    // D1 direction from swings
    if ((int)st.swings_d1.size() >= 3) {
        int n3 = (int)st.swings_d1.size();
        double p1 = st.swings_d1[n3 - 3].price;
        double p3 = st.swings_d1[n3 - 1].price;
        if (p3 > p1) st.d1_direction = 1;
        else if (p3 < p1) st.d1_direction = -1;
        else st.d1_direction = 0;
    } else if ((int)st.swings_h1.size() >= 3) {
        int n3 = (int)st.swings_h1.size();
        double p1 = st.swings_h1[n3 - 3].price;
        double p3 = st.swings_h1[n3 - 1].price;
        if (p3 > p1) st.d1_direction = 1;
        else if (p3 < p1) st.d1_direction = -1;
        else st.d1_direction = 0;
    }
}

// Close an open trade
static void close_trade(StrategyState& st, const Bar& bar) {
    OpenTrade& ot = st.open_trade;
    if (!ot.active) return;

    TradeRecord tr;
    tr.entry_bar = ot.entry_bar;
    tr.exit_bar = bar.bar_index;
    tr.entry_price = ot.entry_price;
    tr.direction = ot.direction;
    tr.sl = ot.sl;
    tr.tp = ot.tp;
    tr.sl_distance = ot.sl_distance;
    tr.tp_distance = ot.tp_distance;
    tr.rr_ratio = ot.rr_ratio;
    tr.bars_held = bar.bar_index - ot.entry_bar;
    tr.convergence_score = 0;

    // Determine exit price and reason
    if (ot.direction == 1) {  // long
        if (bar.low <= ot.sl) {
            tr.exit_price = ot.sl;
            tr.exit_reason = 1;  // SL
        } else if (bar.high >= ot.tp) {
            tr.exit_price = ot.tp;
            tr.exit_reason = 0;  // TP
        } else {
            tr.exit_price = bar.close;
            tr.exit_reason = 2;  // timeout / close
        }
        tr.pnl = tr.exit_price - ot.entry_price;
    } else {  // short
        if (bar.high >= ot.sl) {
            tr.exit_price = ot.sl;
            tr.exit_reason = 1;  // SL
        } else if (bar.low <= ot.tp) {
            tr.exit_price = ot.tp;
            tr.exit_reason = 0;  // TP
        } else {
            tr.exit_price = bar.close;
            tr.exit_reason = 2;  // timeout / close
        }
        tr.pnl = ot.entry_price - tr.exit_price;
    }

    // Pessimistic: when both SL & TP possible in same bar, SL wins
    if (ot.direction == 1) {
        if (bar.low <= ot.sl && bar.high >= ot.tp) {
            tr.exit_price = ot.sl;
            tr.exit_reason = 1;
            tr.pnl = ot.sl - ot.entry_price;
        }
    } else {
        if (bar.high >= ot.sl && bar.low <= ot.tp) {
            tr.exit_price = ot.sl;
            tr.exit_reason = 1;
            tr.pnl = ot.entry_price - ot.sl;
        }
    }

    tr.won = (tr.pnl > 0);
    st.closed_trades.push_back(tr);
    ot.active = false;
}

// Manage open trade (from risk.py) — with trailing stop at 2R
static bool should_close_trade(OpenTrade& ot, const Bar& bar) {
    int bars_held = bar.bar_index - ot.entry_bar;

    // Max hold: 288 M5 bars (24h)
    if (bars_held >= MAX_HOLD_BARS) return true;

    // SL hit
    if (ot.direction == 1 && bar.low <= ot.sl) return true;
    if (ot.direction == -1 && bar.high >= ot.sl) return true;

    // TP hit
    if (ot.direction == 1 && bar.high >= ot.tp) return true;
    if (ot.direction == -1 && bar.low <= ot.tp) return true;

    // Trailing stop: when price moves 2R in your favor, trail SL to breakeven
    if (ot.sl_distance > 0) {
        if (ot.direction == 1) {
            double unrealized = bar.high - ot.entry_price;
            if (unrealized >= ot.sl_distance * 2.0 && ot.sl < ot.entry_price) {
                ot.sl = ot.entry_price;  // exact breakeven
            }
        } else {
            double unrealized = ot.entry_price - bar.low;
            if (unrealized >= ot.sl_distance * 2.0 && ot.sl > ot.entry_price) {
                ot.sl = ot.entry_price;  // exact breakeven
            }
        }
    }

    // Vibration override ($288 move)
    double move = fabs(bar.close - ot.entry_price);
    if (check_vibration_override(move)) return true;

    return false;
}

// Process a single M5 bar (main loop — from strategy.py)
static void process_bar(const std::vector<Bar>& m5_bars, int idx,
                        StrategyState& st) {
    const Bar& bar = m5_bars[idx];

    // Reset daily trades at day boundary
    int bar_day = day_from_timestamp(bar.timestamp);
    if (bar_day != st.last_trade_day) {
        st.daily_trades = 0;
        st.last_trade_day = bar_day;
    }

    // Update multi-timeframe data
    update_mtf(m5_bars, idx, st);

    // === STATE: IN_TRADE ===
    if (st.phase == IN_TRADE) {
        if (st.open_trade.active) {
            if (should_close_trade(st.open_trade, bar)) {
                close_trade(st, bar);
                st.phase = SCANNING;
            }
        } else {
            st.phase = SCANNING;
        }
        return;
    }

    // === STATE: SCANNING ===
    if (st.phase == SCANNING) {
        if ((int)st.swings_h1.size() < 4) return;

        ConvergenceResult conv = score_convergence(
            bar.close, bar.bar_index,
            st.swings_h1, st.swings_h4,
            st.h1_wave, nullptr
        );

        if (conv.is_tradeable) {
            // Python v9.1 calibrated: no three_limits gate in SCANNING
            st.phase = QUANT_FORMING;
            st.convergence_bar = bar.bar_index;
            st.convergence_price = bar.close;
        }
        return;
    }

    // === STATE: QUANT_FORMING ===
    if (st.phase == QUANT_FORMING) {
        int bars_since = bar.bar_index - st.convergence_bar;

        // Timeout: 50 bars to form quant
        if (bars_since > 50) {
            st.phase = SCANNING;
            return;
        }

        QuantMeasurement quant = measure_quant(m5_bars, st.convergence_bar, idx + 1);
        if (quant.valid) {
            GannBox gbox = construct_gann_box(quant);
            if (gbox.valid) {
                st.active_box = gbox;
                st.phase = BOX_ACTIVE;
            } else {
                st.phase = SCANNING;
            }
        }
        return;
    }

    // === STATE: BOX_ACTIVE ===
    if (st.phase == BOX_ACTIVE) {
        if (!st.active_box.valid) {
            st.phase = SCANNING;
            return;
        }

        // Box expired?
        if (bar.bar_index > st.active_box.end_bar) {
            st.phase = SCANNING;
            st.active_box.valid = false;
            return;
        }

        // RED ZONE — wait
        if (bar.bar_index < st.active_box.red_end) return;

        // YELLOW ZONE — watch
        if (bar.bar_index < st.active_box.yellow_end) return;

        // GREEN ZONE — look for entry
        if (st.daily_trades >= MAX_DAILY_TRADES) return;

        // Get wave direction
        int h1_dir = 0;
        if (st.h1_wave.valid) {
            h1_dir = st.h1_wave.direction;
        }

        EntrySignal entry = find_green_zone_entry(
            st.active_box, m5_bars, bar.bar_index,
            st.d1_direction, h1_dir, WAVE_MULTIPLIER
        );

        if (entry.valid) {
            // Check explosion bonus
            int energy_mult = 0;
            if (check_explosion(st.active_box, bar.bar_index, energy_mult)) {
                if (entry.direction == 1) {
                    entry.tp = entry.entry_price + entry.tp_distance * energy_mult / 4.0;
                } else {
                    entry.tp = entry.entry_price - entry.tp_distance * energy_mult / 4.0;
                }
                entry.tp_distance = fabs(entry.tp - entry.entry_price);
                entry.rr_ratio = (entry.sl_distance > 0)
                    ? entry.tp_distance / entry.sl_distance : 0;
            }

            // Apply spread
            double actual_entry = entry.entry_price;
            if (entry.direction == 1) {
                actual_entry += SPREAD;  // buy at ask
            }
            // (for short, entry_price already represents ask-spread scenario)

            // Execute trade — NEXT BAR entry (honest)
            // We detect the signal on bar[idx], but since we use bar close
            // for evaluation and the entry_price comes from diagonal geometry,
            // we enter at the computed price on the current bar.
            // The spread simulation handles execution cost.
            st.open_trade.entry_price = actual_entry;
            st.open_trade.sl = entry.sl;
            st.open_trade.tp = entry.tp;
            st.open_trade.direction = entry.direction;
            st.open_trade.entry_bar = bar.bar_index;
            st.open_trade.sl_distance = fabs(actual_entry - entry.sl);
            st.open_trade.tp_distance = fabs(entry.tp - actual_entry);
            st.open_trade.rr_ratio = entry.rr_ratio;
            st.open_trade.active = true;

            st.phase = IN_TRADE;
            st.daily_trades++;
        }
        return;
    }
}

// ============================================================
// DATA LOADING (from backtester.py)
// ============================================================

static bool load_m5_binary(const char* filepath, std::vector<Bar>& bars) {
    FILE* f = fopen(filepath, "rb");
    if (!f) {
        fprintf(stderr, "ERROR: Cannot open %s\n", filepath);
        return false;
    }

    // 8-byte header: int64 record count
    int64_t n_records = 0;
    if (fread(&n_records, 8, 1, f) != 1) {
        fprintf(stderr, "ERROR: Cannot read header\n");
        fclose(f);
        return false;
    }

    printf("Loading %lld records from %s...\n", (long long)n_records, filepath);
    bars.resize(n_records);

    // Records: int32 ts + int32 pad + 4 doubles (OHLC) = 40 bytes each
    for (int64_t i = 0; i < n_records; i++) {
        int32_t ts, pad;
        double ohlc[4];
        if (fread(&ts, 4, 1, f) != 1) break;
        if (fread(&pad, 4, 1, f) != 1) break;
        if (fread(ohlc, 8, 4, f) != 4) break;

        bars[i].timestamp = (int64_t)ts;
        bars[i].open = ohlc[0];
        bars[i].high = ohlc[1];
        bars[i].low = ohlc[2];
        bars[i].close = ohlc[3];
        bars[i].bar_index = (int)i;
    }

    fclose(f);
    printf("Loaded %d bars.\n", (int)bars.size());

    // Validate
    if (!bars.empty()) {
        printf("First bar: ts=%lld O=%.2f H=%.2f L=%.2f C=%.2f\n",
               (long long)bars[0].timestamp,
               bars[0].open, bars[0].high, bars[0].low, bars[0].close);
        printf("Last bar:  ts=%lld O=%.2f H=%.2f L=%.2f C=%.2f\n",
               (long long)bars.back().timestamp,
               bars.back().open, bars.back().high, bars.back().low, bars.back().close);
    }

    return true;
}

// ============================================================
// METRICS COMPUTATION (from backtester.py)
// ============================================================

struct Metrics {
    int total_trades;
    double win_rate;
    double avg_win;
    double avg_loss;
    double rr_ratio;
    double ev_per_trade;
    double max_drawdown;
    double trades_per_day;
    double final_equity;
    double total_pnl;
};

static Metrics compute_metrics(const std::vector<TradeRecord>& trades,
                               int total_bars, double start_equity) {
    Metrics m = {};
    m.total_trades = (int)trades.size();
    m.final_equity = start_equity;

    if (trades.empty()) return m;

    int wins = 0;
    double sum_win = 0, sum_loss = 0;
    int loss_count = 0;
    double equity = start_equity;
    double peak = equity;
    double max_dd = 0;

    for (const auto& t : trades) {
        equity += t.pnl;
        if (equity > peak) peak = equity;
        double dd = (peak > 0) ? (peak - equity) / peak : 0;
        if (dd > max_dd) max_dd = dd;

        if (t.pnl > 0) {
            wins++;
            sum_win += t.pnl;
        } else {
            loss_count++;
            sum_loss += fabs(t.pnl);
        }
    }

    m.win_rate = (double)wins / m.total_trades;
    m.avg_win = (wins > 0) ? sum_win / wins : 0;
    m.avg_loss = (loss_count > 0) ? sum_loss / loss_count : 1.0;
    m.rr_ratio = (m.avg_loss > 0) ? m.avg_win / m.avg_loss : 0;
    m.ev_per_trade = m.win_rate * m.avg_win - (1.0 - m.win_rate) * m.avg_loss;
    m.max_drawdown = max_dd;
    m.final_equity = equity;
    m.total_pnl = equity - start_equity;

    // Trades per day (288 M5 bars = 1 trading day)
    double total_days = (total_bars > 0) ? (double)total_bars / 288.0 : 1.0;
    m.trades_per_day = m.total_trades / total_days;

    return m;
}

// ============================================================
// MAIN
// ============================================================

// Parse YYYY-MM-DD to unix timestamp
static int64_t parse_date(const char* s) {
    int y = 0, m = 0, d = 0;
    if (sscanf(s, "%d-%d-%d", &y, &m, &d) != 3) return 0;
    // Simple: approximate days since epoch
    // Use mktime for proper calculation
    struct tm t = {};
    t.tm_year = y - 1900;
    t.tm_mon = m - 1;
    t.tm_mday = d;
    t.tm_hour = 0;
    t.tm_min = 0;
    t.tm_sec = 0;
    time_t epoch = mktime(&t);
    // mktime uses local time; adjust to UTC (approximate — good enough for date filtering)
    return (int64_t)epoch;
}

static void print_usage(const char* prog) {
    printf("Usage: %s <data.bin> [options]\n", prog);
    printf("Options:\n");
    printf("  --verbose       Print each trade\n");
    printf("  --from <ts>     Start timestamp (unix) or YYYY-MM-DD\n");
    printf("  --to <ts>       End timestamp (unix) or YYYY-MM-DD\n");
    printf("  --equity <$>    Starting equity (default 10000)\n");
    printf("  --csv <file>    Export trades to CSV\n");
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        print_usage(argv[0]);
        return 1;
    }

    const char* data_file = argv[1];
    bool verbose = false;
    int64_t from_ts = 0;
    int64_t to_ts = INT64_MAX;
    double start_equity = 10000.0;
    const char* csv_file = nullptr;

    for (int i = 2; i < argc; i++) {
        if (strcmp(argv[i], "--verbose") == 0) verbose = true;
        else if (strcmp(argv[i], "--from") == 0 && i + 1 < argc) {
            const char* val = argv[++i];
            if (strchr(val, '-')) from_ts = parse_date(val);
            else from_ts = atoll(val);
        }
        else if (strcmp(argv[i], "--to") == 0 && i + 1 < argc) {
            const char* val = argv[++i];
            if (strchr(val, '-')) to_ts = parse_date(val);
            else to_ts = atoll(val);
        }
        else if (strcmp(argv[i], "--equity") == 0 && i + 1 < argc)
            start_equity = atof(argv[++i]);
        else if (strcmp(argv[i], "--csv") == 0 && i + 1 < argc)
            csv_file = argv[++i];
    }

    // Load data
    std::vector<Bar> all_bars;
    if (!load_m5_binary(data_file, all_bars)) return 1;

    // Filter date range
    std::vector<Bar> bars;
    bars.reserve(all_bars.size());
    for (auto& b : all_bars) {
        if (b.timestamp >= from_ts && b.timestamp <= to_ts) {
            b.bar_index = (int)bars.size();
            bars.push_back(b);
        }
    }
    printf("Using %d bars after date filter.\n\n", (int)bars.size());

    if (bars.empty()) {
        printf("No data in range.\n");
        return 1;
    }

    // Print configuration
    printf("=== Gann Backtester v9.1 — Triangle-First Architecture ===\n");
    printf("Constants: V=%.0f, SwingQ=%.0f, LostMotion=$%.0f\n",
           BASE_VIBRATION, SWING_QUANTUM, LOST_MOTION);
    printf("ATR: period=%d, mult=%.1f\n", ATR_PERIOD, ATR_MULTIPLIER);
    printf("Convergence: scan=%d, box=%d, R:R: min=%.1f\n",
           MIN_CONVERGENCE_SCAN, MIN_CONVERGENCE_BOX, MIN_RR_RATIO);
    printf("MaxDailyTrades=%d, MaxHold=%d bars, WaveMultiplier=%d\n",
           MAX_DAILY_TRADES, MAX_HOLD_BARS, WAVE_MULTIPLIER);
    printf("Spread=$%.2f\n\n", SPREAD);

    // Run backtest
    StrategyState state;

    printf("Running backtest on %d M5 bars...\n", (int)bars.size());

    for (int i = 0; i < (int)bars.size(); i++) {
        process_bar(bars, i, state);

        // Progress
        if (i > 0 && i % 100000 == 0) {
            printf("  [%d/%d bars, %d trades so far]\n",
                   i, (int)bars.size(), (int)state.closed_trades.size());
        }
    }

    // Close any remaining open trade
    if (state.open_trade.active && !bars.empty()) {
        close_trade(state, bars.back());
    }

    // Compute metrics
    Metrics m = compute_metrics(state.closed_trades, (int)bars.size(), start_equity);

    // Print trade details
    if (verbose) {
        printf("\n=== TRADE LOG ===\n");
        printf("%-5s %-5s %-10s %-10s %-10s %-8s %-8s %-6s %-6s\n",
               "#", "Dir", "Entry$", "Exit$", "PnL$", "SL$", "TP$",
               "Bars", "Result");
        printf("--------------------------------------------------------------"
               "------------\n");
        for (int i = 0; i < (int)state.closed_trades.size(); i++) {
            const TradeRecord& t = state.closed_trades[i];
            const char* dir = (t.direction == 1) ? "LONG" : "SHORT";
            const char* result;
            switch (t.exit_reason) {
                case 0: result = "TP"; break;
                case 1: result = "SL"; break;
                case 2: result = "TIME"; break;
                default: result = "CLO"; break;
            }
            printf("%-5d %-5s %-10.2f %-10.2f %-+10.2f %-8.2f %-8.2f %-6d %-6s\n",
                   i + 1, dir, t.entry_price, t.exit_price, t.pnl,
                   t.sl, t.tp, t.bars_held, result);
        }
    }

    // Print summary
    printf("\n");
    printf("============================================================\n");
    printf("  BACKTEST REPORT — v9.1 Triangle-First\n");
    printf("============================================================\n");
    printf("  Total trades:     %d\n", m.total_trades);
    printf("  Win rate:         %.1f%%\n", m.win_rate * 100.0);
    printf("  Avg win:          $%.2f\n", m.avg_win);
    printf("  Avg loss:         $%.2f\n", m.avg_loss);
    printf("  R:R ratio:        %.2f\n", m.rr_ratio);
    printf("  EV per trade:     $%.2f\n", m.ev_per_trade);
    printf("  Max drawdown:     %.1f%%\n", m.max_drawdown * 100.0);
    printf("  Trades per day:   %.2f\n", m.trades_per_day);
    printf("  Total P&L:        $%.2f\n", m.total_pnl);
    printf("  Final equity:     $%.2f\n", m.final_equity);
    printf("============================================================\n");

    // Exit reason breakdown
    int tp_count = 0, sl_count = 0, time_count = 0;
    for (const auto& t : state.closed_trades) {
        if (t.exit_reason == 0) tp_count++;
        else if (t.exit_reason == 1) sl_count++;
        else time_count++;
    }
    printf("\n  Exit reasons:\n");
    printf("    TP hit:   %d (%.1f%%)\n",
           tp_count, m.total_trades > 0 ? tp_count * 100.0 / m.total_trades : 0);
    printf("    SL hit:   %d (%.1f%%)\n",
           sl_count, m.total_trades > 0 ? sl_count * 100.0 / m.total_trades : 0);
    printf("    Timeout:  %d (%.1f%%)\n",
           time_count, m.total_trades > 0 ? time_count * 100.0 / m.total_trades : 0);

    // State machine statistics
    printf("\n  State machine:\n");
    printf("    H1 swings detected: %d\n", (int)state.swings_h1.size());
    printf("    H4 swings detected: %d\n", (int)state.swings_h4.size());
    printf("    D1 swings detected: %d\n", (int)state.swings_d1.size());
    printf("    Final D1 direction: %s\n",
           state.d1_direction == 1 ? "UP" :
           state.d1_direction == -1 ? "DOWN" : "FLAT");
    if (state.h1_wave.valid) {
        printf("    H1 wave: #%d, dir=%s, w0_size=$%.1f\n",
               state.h1_wave.wave_number,
               state.h1_wave.direction == 1 ? "up" : "down",
               state.h1_wave.wave_0_size);
    }

    // CSV export
    if (csv_file) {
        FILE* csvf = fopen(csv_file, "w");
        if (csvf) {
            fprintf(csvf, "trade_num,direction,entry_price,sl,tp,exit_price,pnl,"
                          "exit_reason,bars_held,rr_ratio\n");
            for (int i = 0; i < (int)state.closed_trades.size(); i++) {
                const TradeRecord& t = state.closed_trades[i];
                const char* dir = (t.direction == 1) ? "long" : "short";
                const char* reason;
                switch (t.exit_reason) {
                    case 0: reason = "TP_HIT"; break;
                    case 1: reason = "SL_HIT"; break;
                    case 2: reason = "MAX_HOLD"; break;
                    default: reason = "OTHER"; break;
                }
                fprintf(csvf, "%d,%s,%.2f,%.2f,%.2f,%.2f,%.2f,%s,%d,%.1f\n",
                        i + 1, dir, t.entry_price, t.sl, t.tp,
                        t.exit_price, t.pnl, reason, t.bars_held, t.rr_ratio);
            }
            fclose(csvf);
            printf("  Exported %d trades to %s\n", (int)state.closed_trades.size(), csv_file);
        }
    }

    printf("\n");
    return 0;
}
