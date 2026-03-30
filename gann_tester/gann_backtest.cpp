/*
 * Gann Fast Backtester v2.0 — Honest Execution + Full Gann Scoring
 *
 * KEY FIXES vs v1.0:
 * 1. Next-bar entry: detect on bar[i-1], enter at bar[i].open (like MT5)
 * 2. Spread simulation: buy at open+spread, sell at open
 * 3. Pessimistic conflicts: when both SL & TP possible in same bar, SL wins
 * 4. NO breakeven stop: dishonest in bar-based testing
 * 5. Independent convergence scoring (7 factors, not additive)
 * 6. 3-Limit alignment system (Hellcat)
 * 7. Natural square timing filter
 * 8. Price-time squaring as quality score
 * 9. Score-based statistics output
 *
 * Compile: g++ -O3 -std=c++17 -o gann_bt gann_backtest.cpp -lm
 * Run:     ./gann_bt data.bin [params...]
 */

#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <cstring>
#include <vector>
#include <algorithm>
#include <cstdint>
#include <cfloat>

// ============================================================
// Data structures
// ============================================================

struct Bar {
    int64_t timestamp;
    double open, high, low, close;
};

struct Swing {
    double price;
    int barIndex;     // Bar where extreme occurred
    int confirmBar;   // Bar where swing was confirmed (availability gate)
    int type;         // 1=high, -1=low
};

struct GannLevel {
    double price;
    int convergence;
    bool hasSq9, hasVib, hasProp;
};

struct IndepScore {
    bool sq9_swing1;      // A: Sq9 from most recent swing
    bool sq9_swing2;      // B: Sq9 from 2nd most recent swing
    bool vibration;       // C: Vibration multiple of move
    bool proportional;    // D: Proportional level of swing range
    bool natural_square;  // E: Time from swing near natural square
    bool pt_squaring;     // F: Price-time Sq9 degree match
    bool trend_aligned;   // G: H1 direction matches trade
    int total() const {
        return sq9_swing1 + sq9_swing2 + vibration + proportional +
               natural_square + pt_squaring + trend_aligned;
    }
};

struct LimitCheck {
    bool limit1_pt;   // Price-by-Time (Sq9 degrees match)
    bool limit2_pp;   // Price-by-Price (at Gann level — always true if we got here)
    bool limit3_tt;   // Time-by-Time (duration matches natural square or proportion)
    int count() const { return limit1_pt + limit2_pp + limit3_tt; }
};

struct Trade {
    int entryBar, exitBar;
    double entryPrice, exitPrice;
    int direction;    // 1=long, -1=short
    double lotSize, pnl, commission, netPnl;
    double sl, tp;
    int exitReason;   // 0=tp, 1=sl, 2=time
    int convergence;
    int indepScore;
    int limitsAligned;
    int angleStrength;
    char angleDir[8];
};

// ============================================================
// ============================================================
// Wave Counting (Hellcat/FFM protocol)
// "wave(0) × (N+1) = wave(2N+1)" — Hellcat
// ============================================================

struct WaveResult {
    int waveNumber;        // Current wave in sequence (1-based)
    int direction;         // 1=long, -1=short, 0=neutral
    double confidence;     // 0.0 to 1.0
    int phase;             // 0=scenario, 1=transition, 2=legend
    double wave0Size;      // Size of dominant wave (sets targets)
    double expectedTarget; // wave_0_size * (N+1)
};

static WaveResult countWaves(const Swing* swings, int swingCount, int currentBar) {
    WaveResult r = {0, 0, 0.0, 0, 0.0, 0.0};
    if (swingCount < 4) return r;

    // Only use confirmed swings up to current bar
    int active = 0;
    for (int s = 0; s < swingCount; s++)
        if (swings[s].confirmBar <= currentBar) active = s + 1;
    if (active < 4) return r;

    // Get last 10 swings
    int start = active > 10 ? active - 10 : 0;
    int count = active - start;

    // Compute swing moves and find the largest (wave 0)
    double moves[20];
    double absMax = 0;
    int maxIdx = 0;
    for (int i = 0; i < count - 1; i++) {
        moves[i] = swings[start + i + 1].price - swings[start + i].price;
        if (fabs(moves[i]) > absMax) {
            absMax = fabs(moves[i]);
            maxIdx = i;
        }
    }
    if (absMax < 1.0) return r;

    r.wave0Size = absMax;
    int impulseDir = (moves[maxIdx] > 0) ? 1 : -1;  // impulse direction

    // Count waves AFTER wave 0
    int nAfter = (count - 1) - maxIdx - 1;
    if (nAfter < 0) nAfter = 0;

    // Count even waves exceeding wave 0 (for target formula)
    int nEvenExceeding = 0;
    for (int i = maxIdx + 1; i < count - 1; i++) {
        int waveNum = i - maxIdx;
        if (waveNum % 2 == 0 && fabs(moves[i]) > absMax)
            nEvenExceeding++;
    }
    r.expectedTarget = absMax * (nEvenExceeding + 1);

    // Current wave = next to form
    int currentWave = nAfter + 1;
    r.waveNumber = currentWave;

    // Phase and direction determination
    if (currentWave <= 5) {
        r.phase = 0;  // scenario
        if (currentWave % 2 == 1) {
            // Odd wave = impulse direction
            r.direction = impulseDir;
            r.confidence = 0.7 - (currentWave - 1) * 0.05;
        } else {
            // Even wave = correction (opposite)
            r.direction = -impulseDir;
            r.confidence = 0.5;
        }
    } else if (currentWave == 6) {
        r.phase = 1;  // transition — expect reversal
        r.direction = -impulseDir;
        r.confidence = 0.75;
    } else {
        r.phase = 2;  // legend — ABC correction
        int abcWave = currentWave - 6;
        if (abcWave % 2 == 1) {
            r.direction = -impulseDir;  // A or C
            r.confidence = 0.6;
        } else {
            r.direction = impulseDir;   // B
            r.confidence = 0.4;
        }
    }
    return r;
}

// ============================================================
// Triangle System — Angle line crossings (Hellcat/Ferro)
// "The main meaning of Gann's System is in that FIGURE which
//  nobody uses." — Hellcat
// ============================================================

struct AngleLine {
    double pivotPrice;
    int pivotH1Bar;
    int confirmH1Bar;
    int direction;       // 1=ascending (from low), -1=descending (from high)
    double slopePerH1;   // $ per H1 bar
    double ratio;        // angle ratio (0.5, 1.0, 2.0, 4.0)
    int importance;      // 1x1=10, 2x1=8, 1x2=7, 4x1=6
};

struct TriCrossing {
    double h1Bar;          // fractional H1 bar of crossing
    double price;          // price at crossing point
    int latestConfirmH1;   // max confirmBar of both parent angles
    int importance;        // sum of angle importances (max 20 for 1x1+1x1)
    double ascSlopePerH1;  // ascending angle's slope
    double descSlopePerH1; // descending angle's slope
};

// ============================================================
// Parameters
// ============================================================

struct Params {
    // Gann core
    double vibration = 72.0;
    double swingQuantum = 12.0;
    int minConvergence = 7;
    double lostMotion = 3.0;
    double touchTol = 2.0;

    // Independent scoring
    int minIndepScore = 4;    // Ferro: minimum 4 factors
    int minLimits = 2;        // At least 2 of 3 limits
    double scoreTol = 3.0;    // Tolerance for factor checks ($)
    double ptTol = 15.0;      // Price-time squaring degree tolerance
    int natSqTol = 2;         // Natural square bar tolerance

    // Angles
    bool useAngles = true;
    double h1Scale = 7.0;
    double d1Scale = 7.0;

    // Execution (HONEST)
    double spread = 0.30;     // ECN spread $
    double maxSlippage = 3.0; // Max entry offset from level
    int entryMode = 1;        // 0=next-bar open, 1=level price (limit order)
    int pessimistic = 1;      // 1=SL first when both possible, 0=TP first
    // NO trailBE — dishonest in bar testing

    // Risk
    double slDollars = 3.0;   // Tight SL at level (Gann: $2-3)
    double tpDollars = 10.0;  // Fallback TP
    double maxTPDist = 20.0;  // Cap TP distance
    double minRR = 1.0;       // Minimum reward:risk
    double slAtrMult = 0.0;   // If >0, SL = slAtrMult * ATR (overrides slDollars)
    double tpRatio = 0.0;     // If >0, TP = tpRatio * SL (overrides tpDollars)
    double riskPct = 0.02;
    double startCapital = 10000.0;
    int leverage = 500;

    // Filters
    bool filterFold = true;
    bool filterSpeed = true;
    bool filter4thTouch = true;
    int maxDailyTrades = 10;
    int maxHoldBars = 36;     // 3 hours on M5
    double atrMultiplier = 2.5;
    int atrPeriod = 14;
    int maxSwings = 10;

    // Triangle system
    bool useTriangles = false;
    double triPriceTol = 5.0;     // $ tolerance for crossing price proximity
    int triBarTolH1 = 3;          // H1 bars tolerance for crossing timing
    int triMinImportance = 10;    // Min importance (1x1+1x1=20, 1x1+2x1=18)
    bool triConvGate = false;     // Also require convergence level nearby?
    bool geoSLTP = false;         // Use geometric SL/TP from triangle angles
    double triScale = 12.0;       // $/bar for 1x1 angle (H1: $7, M5: $0.58)
    int triMaxSwings = 20;        // Swings for triangle construction
    bool triM5 = false;           // Use M5 swings (scalping mode)
    double triM5AtrMult = 1.5;    // ATR multiplier for M5 swing detection
    int triTPMode = 0;            // 0=level TP, 1=next crossing TP, 2=best of both
    double triMinTPDist = 1.5;    // Min TP distance from entry
    bool fixedTP = false;         // Force TP to exactly tpDollars (ignore levels)
    bool filterMom = false;        // Momentum confirmation filter
    int momLookback = 6;           // Momentum lookback bars
    bool filterBounce = false;     // Bounce quality filter (wick confirmation)
    double penetration = 0.5;      // $ past level required for fill (adverse selection filter)
    bool noEntryBarTP = true;      // Skip entry-bar TP (honest for limit orders)

    // Gann time gating (Phase 2)
    int timeGate = 0;             // 0=off, 1=natural sq required, 2=natSq+PT required
    bool useD1 = false;           // D1 direction filter
    bool useWaves = false;        // Wave counting direction filter

    // Date range
    int64_t fromDate = 0;
    int64_t toDate = INT64_MAX;

    // Output
    bool verbose = false;     // Per-trade CSV output
};

// ============================================================
// Square of 9
// ============================================================

static inline double sq9Degree(double price) {
    if (price <= 0) return 0;
    double v = fmod(sqrt(price) * 180.0 - 225.0, 360.0);
    return v < 0 ? v + 360.0 : v;
}

static inline double sq9Add(double price, double deg) {
    double s = sqrt(fmax(price, 0.01)) + deg / 180.0;
    return s * s;
}

static inline double sq9Sub(double price, double deg) {
    double s = sqrt(fmax(price, 0.01)) - deg / 180.0;
    return s > 0 ? s * s : 0;
}

// ============================================================
// ATR computation
// ============================================================

static void computeATR(const Bar* bars, int n, int period, double* atr) {
    for (int i = 0; i < n; i++) atr[i] = 0;
    double sum = 0;
    for (int i = 1; i < n; i++) {
        double tr = bars[i].high - bars[i].low;
        double h_pc = fabs(bars[i].high - bars[i-1].close);
        double l_pc = fabs(bars[i].low - bars[i-1].close);
        if (h_pc > tr) tr = h_pc;
        if (l_pc > tr) tr = l_pc;
        if (i < period) {
            sum += tr;
            atr[i] = sum / i;
        } else if (i == period) {
            sum += tr;
            atr[i] = sum / period;
        } else {
            atr[i] = (atr[i-1] * (period - 1) + tr) / period;
        }
    }
}

// ============================================================
// Swing detection (ATR-based ZigZag with confirmBar)
// ============================================================

static int detectSwings(const Bar* bars, int n, const double* atr,
                        double multiplier, std::vector<Swing>& swings) {
    int state = 0;
    double ext = 0;
    int extIdx = 0;
    int atrPeriod = 14;

    for (int i = atrPeriod; i < n; i++) {
        double thresh = atr[i] * multiplier;
        if (thresh <= 0) continue;

        if (state == 0) {
            double rLow = 1e18, rHigh = -1e18;
            int rLowIdx = i, rHighIdx = i;
            int start = i > 20 ? i - 20 : atrPeriod;
            for (int j = start; j <= i; j++) {
                if (bars[j].low < rLow) { rLow = bars[j].low; rLowIdx = j; }
                if (bars[j].high > rHigh) { rHigh = bars[j].high; rHighIdx = j; }
            }
            if (bars[i].high - rLow >= thresh) {
                swings.push_back({rLow, rLowIdx, i, -1});
                state = 1; ext = bars[i].high; extIdx = i;
            } else if (rHigh - bars[i].low >= thresh) {
                swings.push_back({rHigh, rHighIdx, i, 1});
                state = -1; ext = bars[i].low; extIdx = i;
            }
        } else if (state == 1) {
            if (bars[i].high > ext) { ext = bars[i].high; extIdx = i; }
            if (ext - bars[i].low >= thresh) {
                if (swings.empty() || extIdx - swings.back().barIndex >= 3)
                    swings.push_back({ext, extIdx, i, 1});
                state = -1; ext = bars[i].low; extIdx = i;
            }
        } else {
            if (bars[i].low < ext) { ext = bars[i].low; extIdx = i; }
            if (bars[i].high - ext >= thresh) {
                if (swings.empty() || extIdx - swings.back().barIndex >= 3)
                    swings.push_back({ext, extIdx, i, -1});
                state = 1; ext = bars[i].high; extIdx = i;
            }
        }
    }
    return (int)swings.size();
}

// ============================================================
// H1 resampling (from M5 bars, group by every 12)
// ============================================================

static int resampleH1(const Bar* m5, int n, Bar* h1, int maxH1) {
    int count = 0;
    for (int i = 0; i < n && count < maxH1; i += 12) {
        int end = std::min(i + 12, n);
        h1[count].timestamp = m5[i].timestamp;
        h1[count].open = m5[i].open;
        h1[count].high = m5[i].high;
        h1[count].low = m5[i].low;
        h1[count].close = m5[end - 1].close;
        for (int j = i + 1; j < end; j++) {
            if (m5[j].high > h1[count].high) h1[count].high = m5[j].high;
            if (m5[j].low < h1[count].low) h1[count].low = m5[j].low;
        }
        count++;
    }
    return count;
}

// ============================================================
// Gann Level calculation (from H1 swings)
// ============================================================

static int calculateLevels(const Swing* swings, int swingCount, int fromSw,
                           double currentPrice, double vibQ,
                           GannLevel* levels, int maxLevels) {
    int count = 0;
    double clusterTol = 3.0;

    auto addLevel = [&](double price, bool sq9, bool vib, bool prop) {
        if (fabs(price - currentPrice) > 200) return;
        for (int i = 0; i < count; i++) {
            if (fabs(levels[i].price - price) <= clusterTol) {
                levels[i].convergence++;
                if (sq9) levels[i].hasSq9 = true;
                if (vib) levels[i].hasVib = true;
                if (prop) levels[i].hasProp = true;
                return;
            }
        }
        if (count < maxLevels) {
            levels[count] = {price, 1, sq9, vib, prop};
            count++;
        }
    };

    int start = fromSw > 0 ? fromSw : 0;
    for (int s = start; s < swingCount; s++) {
        double ref = swings[s].price;
        double degs[] = {30, 45, 60, 90, 120, 180};
        for (int d = 0; d < 6; d++) {
            addLevel(sq9Add(ref, degs[d]), true, false, false);
            addLevel(sq9Sub(ref, degs[d]), true, false, false);
        }
        for (int m = 1; m <= 9; m++) {
            addLevel(ref + m * vibQ, false, true, false);
            addLevel(ref - m * vibQ, false, true, false);
        }
    }
    for (int s = start; s < swingCount - 1; s++) {
        double hi = fmax(swings[s].price, swings[s + 1].price);
        double lo = fmin(swings[s].price, swings[s + 1].price);
        double rng = hi - lo;
        if (rng < 5) continue;
        double fracs[] = {0.125, 0.25, 0.333, 0.375, 0.5, 0.625, 0.667, 0.75, 0.875};
        for (int f = 0; f < 9; f++)
            addLevel(lo + rng * fracs[f], false, false, true);
    }
    std::sort(levels, levels + count, [](const GannLevel& a, const GannLevel& b) {
        return a.convergence > b.convergence;
    });
    return count;
}

// ============================================================
// Independent Convergence Scoring (7 factors)
// Ferro: "minimum 4 simultaneous mathematical indications"
// Hellcat: "5-6 factors = 85-96% probability"
// ============================================================

static bool checkSq9FromSwing(double entry, double swingPrice, double tol) {
    double degs[] = {30, 45, 60, 90, 120, 180};
    for (int d = 0; d < 6; d++) {
        if (fabs(sq9Add(swingPrice, degs[d]) - entry) <= tol) return true;
        if (fabs(sq9Sub(swingPrice, degs[d]) - entry) <= tol) return true;
    }
    return false;
}

static bool checkVibrationMultiple(double entry, double swingPrice, double vib, double tol) {
    double move = fabs(entry - swingPrice);
    if (move < 1.0) return false;
    double remainder = fmod(move, vib);
    return remainder <= tol || (vib - remainder) <= tol;
}

static bool checkProportional(double entry, double swingHigh, double swingLow, double tol) {
    double range = swingHigh - swingLow;
    if (range < 5) return false;
    double fracs[] = {0.25, 0.333, 0.5, 0.667, 0.75};
    for (int f = 0; f < 5; f++) {
        double level = swingLow + range * fracs[f];
        if (fabs(level - entry) <= tol) return true;
    }
    return false;
}

static bool checkNaturalSquareTiming(int barsFromSwing, int tolerance) {
    int squares[] = {4, 9, 16, 24, 36, 49, 72, 81};
    for (int s = 0; s < 8; s++) {
        if (abs(barsFromSwing - squares[s]) <= tolerance) return true;
    }
    return false;
}

static bool checkPTSquaring(double entryPrice, double refSwingPrice, int barsFromSwing, double degTol) {
    if (barsFromSwing <= 0) return false;
    double priceDeg = sq9Degree(fabs(entryPrice - refSwingPrice));
    double timeDeg = sq9Degree((double)barsFromSwing);
    double diff = fabs(priceDeg - timeDeg);
    if (diff > 180) diff = 360 - diff;
    return diff <= degTol;
}

static IndepScore computeIndependentScore(
    double entry, const Swing* h1Swings, int validSw,
    int barsFromLastSwing, int h1Dir, int tradeDir, const Params& p)
{
    IndepScore sc = {};
    if (validSw < 2) return sc;

    // Find most recent and 2nd most recent swings
    int last = validSw - 1;
    int prev = validSw - 2;

    // A: Sq9 from most recent swing
    sc.sq9_swing1 = checkSq9FromSwing(entry, h1Swings[last].price, p.scoreTol);

    // B: Sq9 from 2nd most recent swing (independent evidence)
    sc.sq9_swing2 = checkSq9FromSwing(entry, h1Swings[prev].price, p.scoreTol);

    // C: Vibration multiple of move from recent swing
    sc.vibration = checkVibrationMultiple(entry, h1Swings[last].price, p.swingQuantum, p.scoreTol);

    // D: Proportional level of most recent swing pair range
    double hi = fmax(h1Swings[last].price, h1Swings[prev].price);
    double lo = fmin(h1Swings[last].price, h1Swings[prev].price);
    sc.proportional = checkProportional(entry, hi, lo, p.scoreTol);

    // E: Natural square timing (H1 bars from last swing)
    sc.natural_square = checkNaturalSquareTiming(barsFromLastSwing, p.natSqTol);

    // F: Price-time squaring
    sc.pt_squaring = checkPTSquaring(entry, h1Swings[last].price, barsFromLastSwing, p.ptTol);

    // G: H1 trend alignment
    sc.trend_aligned = (h1Dir != 0 && h1Dir == tradeDir);

    return sc;
}

// ============================================================
// 3-Limit Alignment (Hellcat: "when all three = 85-96%")
// ============================================================

static LimitCheck checkThreeLimits(
    double entry, const Swing* h1Swings, int validSw,
    int barsFromLastSwing, double vibration, const Params& p)
{
    LimitCheck lc = {};
    if (validSw < 2) { lc.limit2_pp = true; return lc; }

    int last = validSw - 1;
    int prev = validSw - 2;

    // Limit 1: Price-by-Time
    // Sq9 degree of price distance ≈ Sq9 degree of time elapsed
    lc.limit1_pt = checkPTSquaring(entry, h1Swings[last].price, barsFromLastSwing, p.ptTol);

    // Also check Gann angle ratios: price/time near 1:4, 1:2, 1:1, 2:1, 4:1
    if (!lc.limit1_pt && barsFromLastSwing > 0) {
        double priceMove = fabs(entry - h1Swings[last].price);
        double timeUnits = (double)barsFromLastSwing;
        double ratio = priceMove / timeUnits;
        double gannRatios[] = {0.25, 0.5, 1.0, 2.0, 4.0};
        for (int r = 0; r < 5; r++) {
            // Scale by h1Scale to normalize
            double scaledRatio = ratio / p.h1Scale;
            if (fabs(scaledRatio - gannRatios[r]) / gannRatios[r] < 0.15)
                { lc.limit1_pt = true; break; }
        }
    }

    // Limit 2: Price-by-Price (entry at a Gann level — always true at this point)
    lc.limit2_pp = true;

    // Limit 3: Time-by-Time
    // Duration matches natural square
    lc.limit3_tt = checkNaturalSquareTiming(barsFromLastSwing, p.natSqTol);

    // Also check proportional of prior swing duration
    if (!lc.limit3_tt && validSw >= 3) {
        int prevDuration = abs(h1Swings[last].barIndex - h1Swings[prev].barIndex);
        if (prevDuration > 0) {
            double propFracs[] = {0.5, 0.667, 1.0, 1.333, 1.5, 2.0};
            for (int f = 0; f < 6; f++) {
                int expected = (int)(prevDuration * propFracs[f]);
                if (abs(barsFromLastSwing - expected) <= p.natSqTol)
                    { lc.limit3_tt = true; break; }
            }
        }
    }

    return lc;
}

// ============================================================
// Angle direction
// ============================================================

struct DirResult {
    int direction;  // 1=long, -1=short, 0=neutral
    int strength;
};

static DirResult angleDirection(double price, int barIdx,
                                const Swing* swings, int swingCount,
                                double scale, double lostMotion) {
    DirResult r = {0, 0};
    if (swingCount < 2) return r;

    int lastLowIdx = -1, lastHighIdx = -1;
    double lastLowPrice = 0, lastHighPrice = 0;
    int lastLowBar = -1, lastHighBar = -1;

    for (int i = swingCount - 1; i >= 0 && i >= swingCount - 10; i--) {
        if (swings[i].type == -1 && lastLowIdx < 0) {
            lastLowIdx = i; lastLowPrice = swings[i].price; lastLowBar = swings[i].barIndex;
        }
        if (swings[i].type == 1 && lastHighIdx < 0) {
            lastHighIdx = i; lastHighPrice = swings[i].price; lastHighBar = swings[i].barIndex;
        }
        if (lastLowIdx >= 0 && lastHighIdx >= 0) break;
    }
    if (lastLowIdx < 0 && lastHighIdx < 0) return r;

    double ascPrice = (lastLowBar >= 0 && barIdx > lastLowBar) ?
        lastLowPrice + (barIdx - lastLowBar) * scale : 0;
    double descPrice = (lastHighBar >= 0 && barIdx > lastHighBar) ?
        lastHighPrice - (barIdx - lastHighBar) * scale : 1e18;

    if (lastLowBar > lastHighBar) {
        if (price >= ascPrice - lostMotion) r.direction = 1;
        else if (price <= descPrice + lostMotion) r.direction = -1;
        else r.direction = 1;
    } else {
        if (price <= descPrice + lostMotion) r.direction = -1;
        else if (price >= ascPrice - lostMotion) r.direction = 1;
        else r.direction = -1;
    }

    double ratios[] = {0.5, 1.0, 2.0, 4.0};
    int bull = 0, bear = 0;
    for (int ri = 0; ri < 4; ri++) {
        if (lastLowBar >= 0 && barIdx > lastLowBar) {
            double a = lastLowPrice + (barIdx - lastLowBar) * scale * ratios[ri];
            if (price > a - lostMotion) bull++;
        }
        if (lastHighBar >= 0 && barIdx > lastHighBar) {
            double d = lastHighPrice - (barIdx - lastHighBar) * scale * ratios[ri];
            if (price < d + lostMotion) bear++;
        }
    }
    r.strength = (r.direction == 1) ? bull : bear;
    return r;
}

// ============================================================
// Filters
// ============================================================

static bool filterFoldAtThird(const Bar* m5, int idx) {
    if (idx < 36) return true;
    double hi = -1e18, lo = 1e18;
    for (int i = idx - 36; i <= idx; i++) {
        if (m5[i].close > hi) hi = m5[i].close;
        if (m5[i].close < lo) lo = m5[i].close;
    }
    double rng = hi - lo;
    if (rng < 5) return true;
    double third = lo + rng / 3, twoThird = lo + rng * 2 / 3;
    int near = 0;
    for (int i = idx - 35; i < idx; i++) {
        if ((fabs(m5[i].close - third) < rng * 0.08 || fabs(m5[i].close - twoThird) < rng * 0.08) &&
            ((m5[i].close > m5[i - 1].close && m5[i + 1].close < m5[i].close) ||
             (m5[i].close < m5[i - 1].close && m5[i + 1].close > m5[i].close)))
            near++;
    }
    return near < 2;
}

static bool filterSpeedAccel(const Bar* m5, int idx) {
    if (idx < 24) return true;
    double first = fabs(m5[idx - 12].close - m5[idx - 24].close);
    double second = fabs(m5[idx].close - m5[idx - 12].close);
    if (first <= 0) return true;
    double speed = first / 12.0;
    double accel = speed * speed;
    double remSpeed = second / 12.0;
    return !(remSpeed > accel && accel > 0.5);
}

static bool filter4thTouch(const Bar* m5, int idx, double level, int dir, double tol) {
    if (idx < 144) return true;
    int touches = 0;
    for (int i = idx - 144; i < idx; i++)
        if (m5[i].low <= level + tol && m5[i].high >= level - tol) touches++;
    if (touches >= 3) {
        // 4th+ touch: only trade WITH the breakout, not against it
        if (dir == 1 && m5[idx].close < level) return false;
        if (dir == -1 && m5[idx].close > level) return false;
    }
    return true;
}

// Momentum confirmation: last N bars show movement in trade direction
static bool filterMomentum(const Bar* m5, int idx, int dir, int lookback) {
    if (idx < lookback + 1) return true;
    int bullBars = 0, bearBars = 0;
    for (int i = idx - lookback; i < idx; i++) {
        if (m5[i].close > m5[i].open) bullBars++;
        else if (m5[i].close < m5[i].open) bearBars++;
    }
    // For long: need some bearish bars approaching from above (dipping to crossing)
    // For short: need some bullish bars approaching from below (rising to crossing)
    if (dir == 1) return bearBars >= lookback / 3;  // price was falling to crossing
    else return bullBars >= lookback / 3;            // price was rising to crossing
}

// Bounce quality: the fill bar should show rejection (wick in trade direction)
static bool filterBounceQuality(const Bar* m5, int idx, int dir, double crossPrice) {
    double body = fabs(m5[idx].close - m5[idx].open);
    double range = m5[idx].high - m5[idx].low;
    if (range < 0.1) return false;  // doji = skip

    if (dir == 1) {
        // Long: want lower wick (dipped to crossing, bounced up)
        double lowerWick = fmin(m5[idx].open, m5[idx].close) - m5[idx].low;
        return lowerWick >= range * 0.3;  // at least 30% of bar is lower wick
    } else {
        // Short: want upper wick (rose to crossing, bounced down)
        double upperWick = m5[idx].high - fmax(m5[idx].open, m5[idx].close);
        return upperWick >= range * 0.3;
    }
}

// ============================================================
// TP calculation
// ============================================================

static double findTP(int dir, double entry, const GannLevel* levels, int levelCount,
                     double maxDist, double fallbackTP, int minConvForTP = 2) {
    double best = 0;
    for (int j = 0; j < levelCount; j++) {
        double lp = levels[j].price;
        double dist = fabs(lp - entry);
        if (dist < 3.0 || dist > maxDist) continue;
        if (levels[j].convergence < minConvForTP) continue;  // skip noise levels
        if (dir == 1 && lp > entry && (best == 0 || lp < best)) best = lp;
        if (dir == -1 && lp < entry && (best == 0 || lp > best)) best = lp;
    }
    return (best != 0) ? best : entry + dir * fmin(fallbackTP, maxDist);
}

// Find TP from next triangle crossing in trade direction
// Hellcat: "Exit from triangle is always a MULTIPLE of the entry"
static double findTriTP(int dir, double entry, int curBar,
                        const TriCrossing* crossings, int crossCount,
                        double minDist, double maxDist) {
    double best = 0;
    double bestDist = 1e18;
    for (int c = 0; c < crossCount; c++) {
        double cp = crossings[c].price;
        double dist = (dir == 1) ? cp - entry : entry - cp;
        if (dist < minDist || dist > maxDist) continue;
        // Must be a future crossing (after current bar)
        if (crossings[c].h1Bar <= (double)curBar) continue;
        if (dist < bestDist) {
            bestDist = dist;
            best = cp;
        }
    }
    return best;
}

// ============================================================
// Triangle System — Angle construction & crossing detection
// ============================================================

static int buildAngleLines(const Swing* swings, int from, int to, double scale,
                           AngleLine* lines, int maxLines) {
    static const double ratios[] = {0.5, 1.0, 2.0, 4.0};
    static const int importances[] = {7, 10, 8, 6};  // 1x2, 1x1, 2x1, 4x1
    int nR = 4;
    int count = 0;

    for (int s = from; s < to && count + nR <= maxLines; s++) {
        int dir = (swings[s].type == -1) ? 1 : -1;
        for (int r = 0; r < nR; r++) {
            lines[count].pivotPrice = swings[s].price;
            lines[count].pivotH1Bar = swings[s].barIndex;
            lines[count].confirmH1Bar = swings[s].confirmBar;
            lines[count].direction = dir;
            lines[count].slopePerH1 = scale * ratios[r];
            lines[count].ratio = ratios[r];
            lines[count].importance = importances[r];
            count++;
        }
    }
    return count;
}

static int findTriCrossings(const AngleLine* lines, int lineCount,
                            int minH1, int maxH1, double minPrice, double maxPrice,
                            TriCrossing* crossings, int maxCross) {
    int count = 0;

    for (int a = 0; a < lineCount; a++) {
        if (lines[a].direction != 1) continue;
        for (int d = 0; d < lineCount; d++) {
            if (lines[d].direction != -1) continue;
            if (lines[a].pivotH1Bar == lines[d].pivotH1Bar) continue;

            double denom = lines[a].slopePerH1 + lines[d].slopePerH1;
            if (denom < 0.01) continue;

            double numer = lines[d].pivotPrice - lines[a].pivotPrice
                         + lines[a].slopePerH1 * lines[a].pivotH1Bar
                         + lines[d].slopePerH1 * lines[d].pivotH1Bar;
            double crossBar = numer / denom;

            if (crossBar < minH1 || crossBar > maxH1) continue;

            double crossPrice = lines[a].pivotPrice +
                lines[a].slopePerH1 * (crossBar - lines[a].pivotH1Bar);
            if (crossPrice < minPrice || crossPrice > maxPrice) continue;

            int latestConf = std::max(lines[a].confirmH1Bar, lines[d].confirmH1Bar);
            if (latestConf >= (int)crossBar) continue;

            if (count >= maxCross) return count;
            crossings[count].h1Bar = crossBar;
            crossings[count].price = crossPrice;
            crossings[count].latestConfirmH1 = latestConf;
            crossings[count].importance = lines[a].importance + lines[d].importance;
            crossings[count].ascSlopePerH1 = lines[a].slopePerH1;
            crossings[count].descSlopePerH1 = lines[d].slopePerH1;
            count++;
        }
    }
    // Sort by importance descending
    std::sort(crossings, crossings + count,
        [](const TriCrossing& a, const TriCrossing& b) {
            return a.importance > b.importance;
        });
    return count;
}

// ============================================================
// Main simulation — HONEST execution
// ============================================================

struct Results {
    int totalTrades;
    int wins, losses;
    double finalEquity, maxDD, peakEquity;
    int tpExits, slExits, timeExits;
    double totalCommission;
    double avgWin, avgLoss;
    std::vector<Trade> trades;
    // Score breakdown
    int scoreTradesArr[8] = {};  // index = score (0-7)
    int scoreWinsArr[8] = {};
};

static Results runBacktest(const Bar* m5, int n, const Params& p) {
    Results res = {};
    res.finalEquity = p.startCapital;
    res.peakEquity = p.startCapital;
    double equity = p.startCapital;

    // ATR on M5
    double* atr = new double[n];
    computeATR(m5, n, p.atrPeriod, atr);

    // H1 resampling
    int h1Max = n / 12 + 10;
    Bar* h1 = new Bar[h1Max];
    int h1N = resampleH1(m5, n, h1, h1Max);
    fprintf(stderr, "  H1 bars: %d\n", h1N);

    // H1 ATR + swings
    double* h1Atr = new double[h1N];
    computeATR(h1, h1N, p.atrPeriod, h1Atr);
    std::vector<Swing> h1Swings;
    int h1SwCount = detectSwings(h1, h1N, h1Atr, p.atrMultiplier, h1Swings);
    fprintf(stderr, "  H1 swings: %d\n", h1SwCount);

    // D1 resampling (24 H1 bars = 288 M5 bars per D1 bar)
    int d1Max = h1N / 24 + 10;
    Bar* d1 = new Bar[d1Max];
    int d1N = 0;
    double* d1Atr = nullptr;
    std::vector<Swing> d1Swings;
    int d1SwCount = 0;
    if (p.useD1) {
        for (int j = 0; j < h1N && d1N < d1Max; j += 24) {
            int end = std::min(j + 24, h1N);
            d1[d1N].timestamp = h1[j].timestamp;
            d1[d1N].open = h1[j].open;
            d1[d1N].high = h1[j].high;
            d1[d1N].low = h1[j].low;
            d1[d1N].close = h1[end - 1].close;
            for (int k = j + 1; k < end; k++) {
                if (h1[k].high > d1[d1N].high) d1[d1N].high = h1[k].high;
                if (h1[k].low < d1[d1N].low) d1[d1N].low = h1[k].low;
            }
            d1N++;
        }
        d1Atr = new double[d1N];
        computeATR(d1, d1N, p.atrPeriod, d1Atr);
        d1SwCount = detectSwings(d1, d1N, d1Atr, p.atrMultiplier, d1Swings);
        fprintf(stderr, "  D1 bars: %d, D1 swings: %d\n", d1N, d1SwCount);
    }

    // Level cache
    GannLevel levels[500];
    int levelCount = 0;
    int cacheCounter = 0;
    int dailyTrades = 0;
    int64_t currentDay = 0;

    // Active position
    bool hasPos = false;
    Trade pos = {};
    int lastExitBar = -2;  // No re-entry on same bar as exit

    // Triangle system state
    AngleLine triLines[400];
    int triLineCount = 0;
    TriCrossing triCross[10000];
    int triCrossCount = 0;
    int lastTriSwCount = -1;

    // M5 swings for scalping triangles
    std::vector<Swing> m5Swings;
    int m5SwCount = 0;
    if (p.useTriangles && p.triM5) {
        m5SwCount = detectSwings(m5, n, atr, p.triM5AtrMult, m5Swings);
        fprintf(stderr, "  M5 swings for triangles: %d\n", m5SwCount);
    }

    // Verbose header
    if (p.verbose)
        fprintf(stderr, "bar,dir,entry,sl,tp,conv,iscore,limits,exit_reason,exit_price,pnl\n");

    for (int i = 62; i < n; i++) {
        if (m5[i].timestamp < p.fromDate || m5[i].timestamp > p.toDate) continue;

        int64_t day = m5[i].timestamp / 86400;
        if (day != currentDay) { currentDay = day; dailyTrades = 0; }

        // ============ EXIT LOGIC — MT5-realistic tick simulation ============
        // Bar OHLC = bid prices. Spread modeled on SHORT exits.
        // Tick order: Bullish bar (C>O): O→L→H→C. Bearish (C<O): O→H→L→C.
        // This matches MT5 "Every tick" modeling.
        if (hasPos) {
            double exitPrice = 0;
            int exitReason = -1;
            bool isBullish = m5[i].close >= m5[i].open;

            if (pos.direction == 1) {
                // LONG: SL at bid low, TP at bid high
                if (m5[i].open <= pos.sl) {
                    exitPrice = m5[i].open; exitReason = 1; // gap SL
                } else if (m5[i].open >= pos.tp) {
                    exitPrice = pos.tp; exitReason = 0; // gap TP
                } else {
                    bool canHitSL = m5[i].low <= pos.sl;
                    bool canHitTP = m5[i].high >= pos.tp;
                    if (canHitSL && canHitTP) {
                        // Bullish: O→L→H→C → SL(low) tested first
                        // Bearish: O→H→L→C → TP(high) tested first
                        if (isBullish) { exitPrice = pos.sl; exitReason = 1; }
                        else           { exitPrice = pos.tp; exitReason = 0; }
                    } else if (canHitSL) { exitPrice = pos.sl; exitReason = 1; }
                    else if (canHitTP) { exitPrice = pos.tp; exitReason = 0; }
                }
            } else {
                // SHORT: SL at ask high (bid.high + spread), TP at ask low (bid.low + spread)
                double askHigh = m5[i].high + p.spread;
                double askLow  = m5[i].low + p.spread;
                double askOpen = m5[i].open + p.spread;
                if (askOpen >= pos.sl) {
                    exitPrice = askOpen; exitReason = 1; // gap SL
                } else if (askOpen <= pos.tp) {
                    exitPrice = pos.tp; exitReason = 0; // gap TP
                } else {
                    bool canHitSL = askHigh >= pos.sl;
                    bool canHitTP = askLow <= pos.tp;
                    if (canHitSL && canHitTP) {
                        // Bullish: O→L→H → TP(low) first, then SL(high)
                        // Bearish: O→H→L → SL(high) first, then TP(low)
                        if (isBullish) { exitPrice = pos.tp; exitReason = 0; }
                        else           { exitPrice = pos.sl; exitReason = 1; }
                    } else if (canHitSL) { exitPrice = pos.sl; exitReason = 1; }
                    else if (canHitTP) { exitPrice = pos.tp; exitReason = 0; }
                }
            }

            // Time exit
            int held = i - pos.entryBar;
            if (exitReason < 0 && held >= p.maxHoldBars) {
                exitPrice = m5[i].close;
                exitReason = 2;
            }

            if (exitReason >= 0) {
                double pnlPerOz = (pos.direction == 1) ? exitPrice - pos.entryPrice
                                                        : pos.entryPrice - exitPrice;
                double gross = pnlPerOz * pos.lotSize * 100.0;
                double comm = 0.06 * (pos.lotSize / 0.01) * 2;
                // Spread is now modeled in entry price (buy at ask) and exit checks (short at ask)
                double net = gross - comm;

                equity += net;
                if (equity > res.peakEquity) res.peakEquity = equity;
                double dd = (res.peakEquity - equity) / res.peakEquity;
                if (dd > res.maxDD) res.maxDD = dd;

                pos.exitBar = i;
                pos.exitPrice = exitPrice;
                pos.exitReason = exitReason;
                pos.pnl = gross;
                pos.commission = comm;
                pos.netPnl = net;
                res.trades.push_back(pos);
                res.totalTrades++;
                res.totalCommission += comm;

                // Score tracking
                int sc = std::min(pos.indepScore, 7);
                res.scoreTradesArr[sc]++;

                if (net > 0) {
                    res.wins++;
                    res.avgWin += net;
                    if (exitReason == 0) res.tpExits++;
                    res.scoreWinsArr[sc]++;
                } else {
                    res.losses++;
                    res.avgLoss += net;
                    if (exitReason == 1) res.slExits++;
                }
                if (exitReason == 2) res.timeExits++;

                if (p.verbose)
                    fprintf(stderr, "%d,%s,%.2f,%.2f,%.2f,%d,%d,%d,%d,%.2f,%.2f\n",
                            pos.entryBar, pos.angleDir, pos.entryPrice, pos.sl, pos.tp,
                            pos.convergence, pos.indepScore, pos.limitsAligned,
                            exitReason, exitPrice, net);

                lastExitBar = i;
                hasPos = false;
            }
            continue;
        }

        // ============ ENTRY LOGIC (NEXT-BAR) ============
        if (dailyTrades >= p.maxDailyTrades) continue;
        if (i <= lastExitBar) continue;
        if (i < 2) continue;

        int curH1 = i / 12;

        // Update levels periodically (needed for both modes)
        cacheCounter++;
        if (cacheCounter >= 12 || levelCount == 0) {
            cacheCounter = 0;
            int validSw = 0;
            for (int s = 0; s < h1SwCount; s++)
                if (h1Swings[s].confirmBar <= curH1) validSw = s + 1;
            if (validSw >= 3) {
                int fromSw = validSw > p.maxSwings ? validSw - p.maxSwings : 0;
                levelCount = calculateLevels(h1Swings.data(), validSw, fromSw,
                    m5[i].close, p.swingQuantum, levels, 500);
            }
        }

        // Count valid H1 swings
        int validH1Sw = 0;
        for (int s = 0; s < h1SwCount; s++)
            if (h1Swings[s].confirmBar <= curH1) validH1Sw = s + 1;
        if (validH1Sw < 3) continue;

        // ============ TRIANGLE ENTRY MODE ============
        if (p.useTriangles) {
            if (p.triM5) {
                // M5 SCALPING MODE: use M5 swings for angle construction
                // Count confirmed M5 swings (confirmBar <= current M5 bar)
                int validM5Sw = 0;
                for (int s = 0; s < m5SwCount; s++)
                    if (m5Swings[s].confirmBar <= i) validM5Sw = s + 1;

                // Recompute when swing set changes
                if (validM5Sw != lastTriSwCount && validM5Sw >= 3) {
                    lastTriSwCount = validM5Sw;
                    int fromSw = validM5Sw > p.triMaxSwings ? validM5Sw - p.triMaxSwings : 0;
                    triLineCount = buildAngleLines(m5Swings.data(), fromSw, validM5Sw,
                                                   p.triScale, triLines, 400);
                    triCrossCount = findTriCrossings(triLines, triLineCount,
                        i - 200, i + 500,
                        m5[i].close - 200, m5[i].close + 200,
                        triCross, 10000);
                }
            } else {
                // H1 MODE: use H1 swings (original)
                if (validH1Sw != lastTriSwCount) {
                    lastTriSwCount = validH1Sw;
                    int fromSw = validH1Sw > p.triMaxSwings ? validH1Sw - p.triMaxSwings : 0;
                    triLineCount = buildAngleLines(h1Swings.data(), fromSw, validH1Sw,
                                                   p.triScale, triLines, 400);
                    triCrossCount = findTriCrossings(triLines, triLineCount,
                        curH1 - 20, curH1 + 100,
                        m5[i].close - 300, m5[i].close + 300,
                        triCross, 10000);
                }
            }

            // Current bar index in the swing's timeframe
            int curBar = p.triM5 ? i : curH1;

            // Find best crossing near current price+time
            int bestCross = -1;
            int bestImp = 0;

            for (int c = 0; c < triCrossCount; c++) {
                if (triCross[c].latestConfirmH1 >= curBar) continue;

                double barDist = fabs(triCross[c].h1Bar - (double)curBar);
                if (barDist > p.triBarTolH1) continue;

                double priceDist = fabs(triCross[c].price - m5[i-1].close);
                if (priceDist > p.triPriceTol) continue;

                if (triCross[c].importance < p.triMinImportance) continue;

                // Optional: require convergence level nearby
                if (p.triConvGate && levelCount > 0) {
                    bool hasConv = false;
                    for (int lv = 0; lv < levelCount; lv++) {
                        if (levels[lv].convergence >= p.minConvergence &&
                            fabs(levels[lv].price - triCross[c].price) <= 5.0) {
                            hasConv = true; break;
                        }
                    }
                    if (!hasConv) continue;
                }

                if (triCross[c].importance > bestImp) {
                    bestImp = triCross[c].importance;
                    bestCross = c;
                }
            }

            if (bestCross < 0) continue; // No triangle signal

            double crossPrice = triCross[bestCross].price;
            int direction;
            double entry;

            if (p.entryMode == 1) {
                // TRIANGLE LIMIT MODE — MT5-honest:
                // BuyLimit triggers on ASK, not Bid. Bar OHLC = Bid.
                // So BuyLimit fills when Ask <= crossPrice, i.e. Bid <= crossPrice - spread
                // SellLimit triggers on Bid >= crossPrice.
                // Also require PENETRATION past the level (not just touch) to model
                // that fills at exact level are adversely selected.
                double penetration = p.penetration;
                if (m5[i-1].close > crossPrice)
                    direction = 1;   // approaching from above → buy limit below
                else
                    direction = -1;  // approaching from below → sell limit above

                if (direction == 1) {
                    // BuyLimit: Ask must reach crossPrice → Bid must reach crossPrice - spread
                    // Plus penetration to model adverse selection filter
                    if (m5[i].low > crossPrice - p.spread - penetration) continue;
                    entry = crossPrice + p.spread; // fill at Ask = crossPrice
                } else {
                    // SellLimit: Bid must reach crossPrice
                    // Plus penetration
                    if (m5[i].high < crossPrice + penetration) continue;
                    entry = crossPrice; // fill at Bid = crossPrice
                }
            } else {
                // MARKET MODE: detect touch on bar[i-1], enter at bar[i].open
                bool touchedLevel = m5[i-1].low <= crossPrice + p.touchTol &&
                                    m5[i-1].high >= crossPrice - p.touchTol;
                if (!touchedLevel) continue;

                if (m5[i-1].close > crossPrice)
                    direction = 1;
                else
                    direction = -1;

                entry = (direction == 1) ? m5[i].open + p.spread : m5[i].open;

                if (fabs(entry - crossPrice) > p.maxSlippage + 2.0) continue;
            }

            // SL/TP
            double sl, tp;
            if (p.geoSLTP) {
                // Geometric SL: opposing angle slope × time buffer + lost motion
                // After the crossing, angles diverge. SL = where the opposing angle goes.
                // Use 1 H1 bar (12 M5 bars) of divergence as baseline
                if (direction == 1) {
                    // Long: SL below descending angle trajectory
                    double descAt = crossPrice - triCross[bestCross].descSlopePerH1 * 0.5;
                    sl = descAt - p.lostMotion;
                } else {
                    double ascAt = crossPrice + triCross[bestCross].ascSlopePerH1 * 0.5;
                    sl = ascAt + p.lostMotion;
                }
                // Ensure SL is at least $2 from entry
                double slDist = fabs(entry - sl);
                if (slDist < 2.0) sl = entry - direction * 2.0;
            } else {
                sl = entry - direction * p.slDollars;
            }

            // TP: pick best target based on triTPMode
            if (p.fixedTP) {
                tp = entry + direction * p.tpDollars;
            } else {
                double tpLevel = findTP(direction, entry, levels, levelCount, p.maxTPDist, p.tpDollars);
                double tpCross = findTriTP(direction, entry, curBar, triCross, triCrossCount,
                                            p.triMinTPDist, p.maxTPDist);

                if (p.triTPMode == 0) {
                    tp = tpLevel;  // Level-based TP (convergence levels)
                } else if (p.triTPMode == 1) {
                    tp = (tpCross != 0) ? tpCross : tpLevel;  // Next crossing, fallback to level
                } else {
                    // Mode 2: closest of crossing or level
                    if (tpCross != 0 && (fabs(tpCross - entry) < fabs(tpLevel - entry)))
                        tp = tpCross;
                    else
                        tp = tpLevel;
                }
            }

            double tpDist = fabs(tp - entry);
            double slDist = fabs(entry - sl);

            // Cap TP distance
            if (tpDist > p.maxTPDist) tp = entry + direction * p.maxTPDist;
            tpDist = fabs(tp - entry);

            if (slDist < 1.0 || tpDist < p.triMinTPDist) continue;
            if (tpDist / slDist < p.minRR) continue;

            // Filters
            if (p.filterFold && !filterFoldAtThird(m5, i-1)) continue;
            if (p.filterSpeed && !filterSpeedAccel(m5, i-1)) continue;
            if (p.filterMom && !filterMomentum(m5, i, direction, p.momLookback)) continue;
            if (p.filterBounce && !filterBounceQuality(m5, i, direction, crossPrice)) continue;

            // Position sizing
            double risk = equity * p.riskPct;
            double lot = risk / (slDist * 100.0);
            if (lot < 0.01) lot = 0.01;
            lot = floor(lot * 100) / 100.0;

            // Open position
            pos.entryBar = i + 1;  // SL/TP checks from next bar
            pos.entryPrice = entry;
            pos.direction = direction;
            pos.lotSize = lot;
            pos.sl = sl;
            pos.tp = tp;
            pos.convergence = bestImp;
            pos.indepScore = triCross[bestCross].importance;
            pos.limitsAligned = 0;
            pos.angleStrength = 0;
            strncpy(pos.angleDir, "tri", 7);
            pos.angleDir[7] = '\0';

            // ENTRY-BAR CHECK — semi-honest:
            // Keep entry-bar TP only on favorable bars (high comes AFTER fill):
            //   BuyLimit on bullish bar: O→L(fill)→H→C → TP at H is valid
            //   SellLimit on bearish bar: O→H(fill)→L→C → TP at L is valid
            // Skip entry-bar TP on unfavorable bars (high/low before fill).
            // When noEntryBarTP=1, skip ALL entry-bar TP (most pessimistic).
            if (p.entryMode == 1) {
                bool isBullish = m5[i].close >= m5[i].open;
                bool entryBarSL = false, entryBarTP = false;
                if (direction == 1) {
                    entryBarSL = m5[i].low <= sl;
                    if (!p.noEntryBarTP && isBullish && !entryBarSL)
                        entryBarTP = m5[i].high >= tp;  // bullish+buy: H after fill at L
                } else {
                    entryBarSL = (m5[i].high + p.spread) >= sl;
                    if (!p.noEntryBarTP && !isBullish && !entryBarSL)
                        entryBarTP = (m5[i].low + p.spread) <= tp;  // bearish+sell: L after fill at H
                }
                // On unfavorable bars (buy on bearish, sell on bullish):
                // High/low happened before fill → neither SL nor TP achievable on entry bar.
                if (entryBarSL) {
                    // Pessimistic: SL hit on entry bar
                    double pnlPerOz = (direction == 1) ? sl - entry : entry - sl;
                    double gross = pnlPerOz * lot * 100.0;
                    double comm = 0.06 * (lot / 0.01) * 2;
                    double net = gross - comm;
                    equity += net;
                    if (equity > res.peakEquity) res.peakEquity = equity;
                    double dd = (res.peakEquity - equity) / res.peakEquity;
                    if (dd > res.maxDD) res.maxDD = dd;
                    pos.exitBar = i; pos.exitPrice = sl; pos.exitReason = 1;
                    pos.pnl = gross; pos.commission = comm; pos.netPnl = net;
                    res.trades.push_back(pos);
                    res.totalTrades++; res.losses++; res.slExits++;
                    res.avgLoss += net; res.totalCommission += comm;
                    int sc = std::min(pos.indepScore, 7);
                    res.scoreTradesArr[sc]++;
                    lastExitBar = i;
                    continue; // Already exited
                }
                if (entryBarTP && !entryBarSL) {
                    // TP hit on entry bar (only if no SL conflict)
                    double pnlPerOz = (direction == 1) ? tp - entry : entry - tp;
                    double gross = pnlPerOz * lot * 100.0;
                    double comm = 0.06 * (lot / 0.01) * 2;
                    double net = gross - comm;
                    equity += net;
                    if (equity > res.peakEquity) res.peakEquity = equity;
                    double dd = (res.peakEquity - equity) / res.peakEquity;
                    if (dd > res.maxDD) res.maxDD = dd;
                    pos.exitBar = i; pos.exitPrice = tp; pos.exitReason = 0;
                    pos.pnl = gross; pos.commission = comm; pos.netPnl = net;
                    res.trades.push_back(pos);
                    res.totalTrades++; res.wins++; res.tpExits++;
                    res.avgWin += net; res.totalCommission += comm;
                    int sc = std::min(pos.indepScore, 7);
                    res.scoreTradesArr[sc]++; res.scoreWinsArr[sc]++;
                    lastExitBar = i;
                    continue;
                }
            }

            hasPos = true;
            dailyTrades++;
            continue; // Skip level-based entry
        }

        // ============ ORIGINAL LEVEL-BASED ENTRY ============
        if (levelCount == 0) continue;

        int touchBar = (p.entryMode == 1) ? i : i - 1;

        DirResult h1Dir = {0, 0};
        if (p.useAngles && validH1Sw >= 2)
            h1Dir = angleDirection(m5[i].close, curH1, h1Swings.data(), validH1Sw,
                                   p.h1Scale, p.lostMotion);

        // D1 direction filter: skip if D1 trend disagrees
        DirResult d1Dir = {0, 0};
        if (p.useD1 && d1SwCount >= 2) {
            int curD1 = curH1 / 24;
            int validD1Sw = 0;
            for (int s = 0; s < d1SwCount; s++)
                if (d1Swings[s].confirmBar <= curD1) validD1Sw = s + 1;
            if (validD1Sw >= 2)
                d1Dir = angleDirection(m5[i].close, curD1, d1Swings.data(), validD1Sw,
                                       p.d1Scale, p.lostMotion);
        }

        int lastSwIdx = validH1Sw - 1;
        double refPrice = h1Swings[lastSwIdx].price;
        int barsFromRef = std::max(1, curH1 - h1Swings[lastSwIdx].barIndex);

        // Scan levels for touch on bar[i-1]
        for (int lv = 0; lv < levelCount; lv++) {
            double level = levels[lv].price;
            if (levels[lv].convergence < p.minConvergence) continue;

            // Touch check on completed bar (bar[i-1])
            if (!(m5[touchBar].low <= level + p.touchTol &&
                  m5[touchBar].high >= level - p.touchTol))
                continue;

            // Direction: bounce from approach side, confirmed by H1 angles
            int direction = 0;
            int strength = 0;
            const char* dirStr = "fade";
            int dirBar = (p.entryMode == 1) ? i - 1 : i - 2;
            if (dirBar < 0) continue;

            // Step 1: determine bounce direction from approach side
            // Price above level = approaching support = bounce UP (long)
            // Price below level = approaching resistance = bounce DOWN (short)
            int fadeDir = (m5[dirBar].close > level) ? 1 : -1;

            // Step 2: H1 angles must AGREE with bounce direction
            if (p.useAngles && h1Dir.direction != 0) {
                if (h1Dir.direction != fadeDir) continue;  // conflict → skip
                direction = fadeDir;
                strength = h1Dir.strength;
                dirStr = (direction == 1) ? "long" : "short";
            } else if (p.useAngles && h1Dir.direction == 0) {
                continue;  // neutral angle → skip (no clear trend)
            } else {
                direction = fadeDir;
                dirStr = "fade";
            }

            // Step 3: D1 direction must AGREE (if enabled)
            if (p.useD1 && d1Dir.direction != 0 && d1Dir.direction != direction) continue;

            // Step 4: Wave counting direction (if enabled)
            if (p.useWaves && validH1Sw >= 4) {
                WaveResult wave = countWaves(h1Swings.data(), h1SwCount, curH1);
                if (wave.direction != 0 && wave.confidence >= 0.5 &&
                    wave.direction != direction) continue;
            }

            // Entry price — always market entry at next bar open (matches MT5)
            double entry;
            if (p.entryMode == 1) {
                entry = level; // limit order (idealized)
            } else {
                // MARKET: BUY at ask (open + spread), SELL at bid (open)
                entry = (direction == 1) ? m5[i].open + p.spread : m5[i].open;
            }

            // Slippage guard
            if (p.entryMode == 0 && fabs(entry - level) > p.maxSlippage) continue;

            // BOUNCE CONFIRMATION: touch bar must close on the fade side
            // For LONG: bar touched level from above, close must be ABOVE level (bounced up)
            // For SHORT: bar touched level from below, close must be BELOW level (bounced down)
            if (p.entryMode == 0) {
                bool bounced = (direction == 1 && m5[touchBar].close > level) ||
                               (direction == -1 && m5[touchBar].close < level);
                if (!bounced) continue;
            }

            // ---- INDEPENDENT CONVERGENCE SCORING ----
            IndepScore iscore = computeIndependentScore(
                entry, h1Swings.data(), validH1Sw, barsFromRef,
                h1Dir.direction, direction, p);

            if (iscore.total() < p.minIndepScore) continue;

            // ---- 3-LIMIT ALIGNMENT ----
            LimitCheck limits = checkThreeLimits(
                entry, h1Swings.data(), validH1Sw, barsFromRef, p.vibration, p);

            if (limits.count() < p.minLimits) continue;

            // ---- FILTERS ----
            if (p.filterFold && !filterFoldAtThird(m5, touchBar)) continue;
            if (p.filterSpeed && !filterSpeedAccel(m5, touchBar)) continue;
            if (p.filter4thTouch && !filter4thTouch(m5, touchBar, level, direction, p.touchTol))
                continue;
            if (p.filterBounce && !filterBounceQuality(m5, touchBar, direction, level)) continue;

            // ---- TIME GATE (Phase 2) ----
            if (p.timeGate >= 1 && !checkNaturalSquareTiming(barsFromRef, p.natSqTol)) continue;
            if (p.timeGate >= 2 && !checkPTSquaring(entry, refPrice, barsFromRef, p.ptTol)) continue;

            // ---- SL / TP ----
            double slDist_calc, tpDist_calc;
            if (p.slAtrMult > 0 && atr[i] > 0.1) {
                // ATR-based SL/TP — auto-adapts to volatility
                slDist_calc = p.slAtrMult * atr[i];
                tpDist_calc = (p.tpRatio > 0) ? p.tpRatio * slDist_calc : p.tpDollars;
            } else {
                slDist_calc = p.slDollars;
                tpDist_calc = p.tpDollars;
            }
            double sl = entry - direction * slDist_calc;
            double tp;
            if (p.fixedTP || p.slAtrMult > 0) {
                tp = entry + direction * tpDist_calc;
            } else {
                tp = findTP(direction, entry, levels, levelCount, p.maxTPDist, tpDist_calc);
            }

            double slDist = fabs(entry - sl);
            double tpDist = fabs(tp - entry);
            if (slDist < 1.0 || tpDist < 2.0) continue;
            if (tpDist / slDist < p.minRR) continue;

            // ---- POSITION SIZING ----
            double risk = equity * p.riskPct;
            double lot = risk / (slDist * 100.0);
            if (lot < 0.01) lot = 0.01;
            lot = floor(lot * 100) / 100.0;

            // ---- OPEN POSITION ----
            // Exit checking starts from NEXT bar (i+1) for both modes
            // This matches MT5: entry happens at bar open, then next tick/bar checks SL/TP
            pos.entryBar = i + 1;
            pos.entryPrice = entry;
            pos.direction = direction;
            pos.lotSize = lot;
            pos.sl = sl;
            pos.tp = tp;
            pos.convergence = levels[lv].convergence;
            pos.indepScore = iscore.total();
            pos.limitsAligned = limits.count();
            pos.angleStrength = strength;
            strncpy(pos.angleDir, dirStr, 7);
            pos.angleDir[7] = '\0';
            hasPos = true;
            dailyTrades++;
            break;
        }
    }

    res.finalEquity = equity;
    if (res.wins > 0) res.avgWin /= res.wins;
    if (res.losses > 0) res.avgLoss /= res.losses;

    delete[] atr;
    delete[] h1;
    delete[] h1Atr;
    delete[] d1;
    if (d1Atr) delete[] d1Atr;
    return res;
}

// ============================================================
// Parameter parsing
// ============================================================

static void parseParam(Params& p, const char* arg) {
    char key[64]; double val;
    if (sscanf(arg, "%63[^=]=%lf", key, &val) == 2) {
        if (!strcmp(key, "vibration")) p.vibration = val;
        else if (!strcmp(key, "quantum")) p.swingQuantum = val;
        else if (!strcmp(key, "minconv")) p.minConvergence = (int)val;
        else if (!strcmp(key, "m5scale")) p.h1Scale = val; // legacy alias
        else if (!strcmp(key, "h1scale")) p.h1Scale = val;
        else if (!strcmp(key, "d1scale")) p.d1Scale = val;
        else if (!strcmp(key, "angles")) p.useAngles = val > 0;
        else if (!strcmp(key, "sl")) p.slDollars = val;
        else if (!strcmp(key, "tp")) p.tpDollars = val;
        else if (!strcmp(key, "maxtp")) p.maxTPDist = val;
        else if (!strcmp(key, "risk")) p.riskPct = val / 100.0;
        else if (!strcmp(key, "maxdaily")) p.maxDailyTrades = (int)val;
        else if (!strcmp(key, "maxhold")) p.maxHoldBars = (int)val;
        else if (!strcmp(key, "minrr")) p.minRR = val;
        else if (!strcmp(key, "fold")) p.filterFold = val > 0;
        else if (!strcmp(key, "speed")) p.filterSpeed = val > 0;
        else if (!strcmp(key, "touch4th")) p.filter4thTouch = val > 0;
        else if (!strcmp(key, "capital")) p.startCapital = val;
        else if (!strcmp(key, "leverage")) p.leverage = (int)val;
        else if (!strcmp(key, "spread")) p.spread = val;
        else if (!strcmp(key, "maxslip")) p.maxSlippage = val;
        else if (!strcmp(key, "from")) p.fromDate = (int64_t)val;
        else if (!strcmp(key, "to")) p.toDate = (int64_t)val;
        else if (!strcmp(key, "minscore")) p.minIndepScore = (int)val;
        else if (!strcmp(key, "minlimits")) p.minLimits = (int)val;
        else if (!strcmp(key, "pttol")) p.ptTol = val;
        else if (!strcmp(key, "nattol")) p.natSqTol = (int)val;
        else if (!strcmp(key, "scoretol")) p.scoreTol = val;
        else if (!strcmp(key, "verbose")) p.verbose = val > 0;
        else if (!strcmp(key, "entrymode")) p.entryMode = (int)val;
        else if (!strcmp(key, "pessimistic")) p.pessimistic = (int)val;
        // Triangle system
        else if (!strcmp(key, "triangle")) p.useTriangles = val > 0;
        else if (!strcmp(key, "tripricetol")) p.triPriceTol = val;
        else if (!strcmp(key, "tribartol")) p.triBarTolH1 = (int)val;
        else if (!strcmp(key, "triminimp")) p.triMinImportance = (int)val;
        else if (!strcmp(key, "triconvgate")) p.triConvGate = val > 0;
        else if (!strcmp(key, "geosltp")) p.geoSLTP = val > 0;
        else if (!strcmp(key, "triscale")) p.triScale = val;
        else if (!strcmp(key, "trimaxsw")) p.triMaxSwings = (int)val;
        else if (!strcmp(key, "m5tri")) p.triM5 = val > 0;
        else if (!strcmp(key, "m5triatr")) p.triM5AtrMult = val;
        else if (!strcmp(key, "tritpmode")) p.triTPMode = (int)val;
        else if (!strcmp(key, "trimintpdist")) p.triMinTPDist = val;
        else if (!strcmp(key, "fixedtp")) p.fixedTP = val > 0;
        else if (!strcmp(key, "filtermom")) p.filterMom = val > 0;
        else if (!strcmp(key, "momlb")) p.momLookback = (int)val;
        else if (!strcmp(key, "filterbounce")) p.filterBounce = val > 0;
        else if (!strcmp(key, "penetration")) p.penetration = val;
        else if (!strcmp(key, "noentrybartp")) p.noEntryBarTP = val > 0;
        // Gann time gating (Phase 2)
        else if (!strcmp(key, "timegate")) p.timeGate = (int)val;
        else if (!strcmp(key, "d1")) p.useD1 = val > 0;
        else if (!strcmp(key, "waves")) p.useWaves = val > 0;
        // ATR-based SL/TP
        else if (!strcmp(key, "slatr")) p.slAtrMult = val;
        else if (!strcmp(key, "tpratio")) p.tpRatio = val;
    }
}

// ============================================================
// Main
// ============================================================

int main(int argc, char* argv[]) {
    const char* dataFile = "data/clean/XAUUSD_M5.bin";
    Params p;

    for (int i = 1; i < argc; i++) {
        if (argv[i][0] != '-' && strchr(argv[i], '=') == nullptr)
            dataFile = argv[i];
        else
            parseParam(p, argv[i]);
    }

    // Load binary data
    FILE* f = fopen(dataFile, "rb");
    if (!f) { fprintf(stderr, "Cannot open %s\n", dataFile); return 1; }

    int64_t barCount;
    fread(&barCount, sizeof(int64_t), 1, f);
    fprintf(stderr, "Loading %lld M5 bars...\n", (long long)barCount);

    Bar* bars = new Bar[barCount];
    for (int64_t i = 0; i < barCount; i++) {
        fread(&bars[i].timestamp, sizeof(int64_t), 1, f);
        fread(&bars[i].open, sizeof(double), 1, f);
        fread(&bars[i].high, sizeof(double), 1, f);
        fread(&bars[i].low, sizeof(double), 1, f);
        fread(&bars[i].close, sizeof(double), 1, f);
    }
    fclose(f);
    fprintf(stderr, "Loaded. Range: %lld to %lld\n",
            (long long)bars[0].timestamp, (long long)bars[barCount - 1].timestamp);

    // Run backtest
    Results res = runBacktest(bars, (int)barCount, p);

    // Output JSON
    double winRate = res.totalTrades > 0 ? (double)res.wins / res.totalTrades : 0;
    double rr = res.avgLoss != 0 ? fabs(res.avgWin / res.avgLoss) : 0;

    int64_t firstDay = 0, lastDay = 0;
    if (!res.trades.empty()) {
        firstDay = bars[res.trades.front().entryBar].timestamp / 86400;
        lastDay = bars[res.trades.back().entryBar].timestamp / 86400;
    }
    int tradingDays = std::max(1, (int)(lastDay - firstDay));
    double tradesPerDay = (double)res.totalTrades / tradingDays;

    // EV calculation
    double evPerTrade = 0;
    if (res.totalTrades > 0) {
        double totalNet = 0;
        for (auto& t : res.trades) totalNet += t.netPnl;
        evPerTrade = totalNet / res.totalTrades;
    }

    printf("{\n");
    printf("  \"version\": \"2.0-honest\",\n");
    printf("  \"total_trades\": %d,\n", res.totalTrades);
    printf("  \"wins\": %d,\n", res.wins);
    printf("  \"losses\": %d,\n", res.losses);
    printf("  \"win_rate\": %.4f,\n", winRate);
    printf("  \"rr_ratio\": %.2f,\n", rr);
    printf("  \"ev_per_trade\": %.4f,\n", evPerTrade);
    printf("  \"trades_per_day\": %.2f,\n", tradesPerDay);
    printf("  \"start_capital\": %.2f,\n", p.startCapital);
    printf("  \"final_equity\": %.2f,\n", res.finalEquity);
    printf("  \"max_drawdown\": %.4f,\n", res.maxDD);
    printf("  \"peak_equity\": %.2f,\n", res.peakEquity);
    printf("  \"tp_exits\": %d,\n", res.tpExits);
    printf("  \"sl_exits\": %d,\n", res.slExits);
    printf("  \"time_exits\": %d,\n", res.timeExits);
    printf("  \"total_commission\": %.2f,\n", res.totalCommission);
    printf("  \"avg_win\": %.4f,\n", res.avgWin);
    printf("  \"avg_loss\": %.4f,\n", res.avgLoss);

    // Direction breakdown
    int angleLong = 0, angleShort = 0, fadeTrades = 0;
    int angleLongWin = 0, angleShortWin = 0, fadeWin = 0;
    for (auto& t : res.trades) {
        if (!strcmp(t.angleDir, "long")) { angleLong++; if (t.netPnl > 0) angleLongWin++; }
        else if (!strcmp(t.angleDir, "short")) { angleShort++; if (t.netPnl > 0) angleShortWin++; }
        else { fadeTrades++; if (t.netPnl > 0) fadeWin++; }
    }
    printf("  \"angle_long\": %d, \"angle_long_wr\": %.4f,\n",
           angleLong, angleLong > 0 ? (double)angleLongWin / angleLong : 0);
    printf("  \"angle_short\": %d, \"angle_short_wr\": %.4f,\n",
           angleShort, angleShort > 0 ? (double)angleShortWin / angleShort : 0);
    printf("  \"fade_trades\": %d, \"fade_wr\": %.4f,\n",
           fadeTrades, fadeTrades > 0 ? (double)fadeWin / fadeTrades : 0);

    // Score breakdown
    printf("  \"score_breakdown\": {\n");
    for (int s = 0; s <= 7; s++) {
        if (res.scoreTradesArr[s] > 0) {
            double swr = (double)res.scoreWinsArr[s] / res.scoreTradesArr[s];
            printf("    \"%d\": {\"trades\": %d, \"wins\": %d, \"wr\": %.4f}%s\n",
                   s, res.scoreTradesArr[s], res.scoreWinsArr[s], swr,
                   s < 7 && res.scoreTradesArr[s + 1] > 0 ? "," : "");
        }
    }
    printf("  },\n");

    // Limits breakdown
    int limTrades[4] = {}, limWins[4] = {};
    for (auto& t : res.trades) {
        int lc = std::min(t.limitsAligned, 3);
        limTrades[lc]++;
        if (t.netPnl > 0) limWins[lc]++;
    }
    printf("  \"limits_breakdown\": {\n");
    for (int l = 0; l <= 3; l++) {
        if (limTrades[l] > 0) {
            printf("    \"%d\": {\"trades\": %d, \"wins\": %d, \"wr\": %.4f}%s\n",
                   l, limTrades[l], limWins[l],
                   (double)limWins[l] / limTrades[l],
                   l < 3 && limTrades[l + 1] > 0 ? "," : "");
        }
    }
    printf("  },\n");

    // Params echo
    printf("  \"params\": {\n");
    printf("    \"angles\": %s, \"minconv\": %d, \"h1scale\": %.1f,\n",
           p.useAngles ? "true" : "false", p.minConvergence, p.h1Scale);
    printf("    \"sl\": %.1f, \"tp\": %.1f, \"maxtp\": %.1f, \"minrr\": %.1f,\n",
           p.slDollars, p.tpDollars, p.maxTPDist, p.minRR);
    printf("    \"minscore\": %d, \"minlimits\": %d, \"pttol\": %.1f, \"nattol\": %d,\n",
           p.minIndepScore, p.minLimits, p.ptTol, p.natSqTol);
    printf("    \"spread\": %.2f, \"maxslip\": %.1f,\n", p.spread, p.maxSlippage);
    printf("    \"fold\": %s, \"speed\": %s, \"touch4th\": %s,\n",
           p.filterFold ? "true" : "false", p.filterSpeed ? "true" : "false",
           p.filter4thTouch ? "true" : "false");
    printf("    \"entrymode\": %d, \"pessimistic\": %d,\n", p.entryMode, p.pessimistic);
    printf("    \"triangle\": %s, \"triscale\": %.1f, \"tripricetol\": %.1f, \"tribartol\": %d, \"triminimp\": %d, \"geosltp\": %s\n",
           p.useTriangles ? "true" : "false", p.triScale, p.triPriceTol, p.triBarTolH1, p.triMinImportance,
           p.geoSLTP ? "true" : "false");
    printf("  }\n");
    printf("}\n");

    delete[] bars;
    return 0;
}
