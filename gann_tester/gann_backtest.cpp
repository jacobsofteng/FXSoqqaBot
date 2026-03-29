/*
 * Gann Fast Backtester — C++ single-file, all Gann logic
 * Reads binary M5 data, runs simulation, outputs JSON results.
 * Compile: g++ -O3 -o gann_backtest gann_backtest.cpp -lm
 * Run:     ./gann_backtest [data.bin] [params...]
 *
 * 1M+ bars in <2 seconds.
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
    int barIndex;
    int type;  // 1=high, -1=low
};

struct GannLevel {
    double price;
    int convergence;
    bool hasSq9, hasVib, hasProp;
};

struct GannAngle {
    double pivotPrice;
    int pivotBar;
    int direction;   // 1=ascending, -1=descending
    double ratio;
    double scale;
};

struct Trade {
    int entryBar, exitBar;
    double entryPrice, exitPrice;
    int direction;  // 1=long, -1=short
    double lotSize, pnl, commission, netPnl;
    double sl, tp;
    int exitReason;  // 0=tp, 1=sl, 2=time
    int convergence;
    int angleStrength;
    char angleDir[8];  // "long","short","fade"
};

// ============================================================
// Parameters (configurable from command line)
// ============================================================

struct Params {
    double vibration = 72.0;
    double swingQuantum = 12.0;
    int minConvergence = 3;
    double lostMotion = 3.0;
    double touchTol = 2.0;
    double m5Scale = 1.0;
    double h1Scale = 2.0;
    double d1Scale = 7.0;
    bool useAngles = true;
    bool requireMultiTF = true;
    double riskPct = 0.02;
    double slDollars = 10.0;
    double tpDollars = 23.0;
    int maxDailyTrades = 10;
    int maxHoldBars = 108;
    double minRR = 1.0;
    double atrMultiplier = 2.5;
    int atrPeriod = 14;
    int maxSwings = 10;
    bool filterFold = true;
    bool filterSpeed = true;
    bool filterPTSquare = false;
    bool filterTimeExpiry = true;
    bool filter4thTouch = true;
    double startCapital = 10000.0;
    int leverage = 500;
    // Date range (epoch seconds)
    int64_t fromDate = 0;
    int64_t toDate = INT64_MAX;
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
// Swing detection
// ============================================================

static int detectSwings(const Bar* bars, int n, const double* atr,
                        double multiplier, Swing* swings, int maxOut) {
    int count = 0;
    int state = 0;  // 0=init, 1=up, -1=down
    double ext = 0;
    int extIdx = 0;
    int atrPeriod = 14;

    for (int i = atrPeriod; i < n && count < maxOut; i++) {
        double thresh = atr[i] * multiplier;
        if (thresh <= 0) continue;

        if (state == 0) {
            // Initialize
            double rLow = 1e18, rHigh = -1e18;
            int rLowIdx = i, rHighIdx = i;
            int start = i > 20 ? i - 20 : atrPeriod;
            for (int j = start; j <= i; j++) {
                if (bars[j].low < rLow) { rLow = bars[j].low; rLowIdx = j; }
                if (bars[j].high > rHigh) { rHigh = bars[j].high; rHighIdx = j; }
            }
            if (bars[i].high - rLow >= thresh) {
                swings[count++] = {rLow, rLowIdx, -1};
                state = 1; ext = bars[i].high; extIdx = i;
            } else if (rHigh - bars[i].low >= thresh) {
                swings[count++] = {rHigh, rHighIdx, 1};
                state = -1; ext = bars[i].low; extIdx = i;
            }
        } else if (state == 1) {
            if (bars[i].high > ext) { ext = bars[i].high; extIdx = i; }
            if (ext - bars[i].low >= thresh) {
                if (count == 0 || extIdx - swings[count-1].barIndex >= 3)
                    swings[count++] = {ext, extIdx, 1};
                state = -1; ext = bars[i].low; extIdx = i;
            }
        } else {
            if (bars[i].low < ext) { ext = bars[i].low; extIdx = i; }
            if (bars[i].high - ext >= thresh) {
                if (count == 0 || extIdx - swings[count-1].barIndex >= 3)
                    swings[count++] = {ext, extIdx, -1};
                state = 1; ext = bars[i].high; extIdx = i;
            }
        }
    }
    return count;
}

// ============================================================
// Gann Level calculation
// ============================================================

static int calculateLevels(const Swing* swings, int swingCount, int fromSw,
                           double currentPrice, double vibQ,
                           GannLevel* levels, int maxLevels) {
    int count = 0;
    double clusterTol = 3.0;

    auto addLevel = [&](double price, bool sq9, bool vib, bool prop) {
        if (fabs(price - currentPrice) > 200) return;
        // Cluster check
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
        // Sq9 levels
        double degs[] = {30, 45, 60, 90, 120, 180};
        for (int d = 0; d < 6; d++) {
            addLevel(sq9Add(ref, degs[d]), true, false, false);
            addLevel(sq9Sub(ref, degs[d]), true, false, false);
        }
        // Vibration multiples
        for (int m = 1; m <= 9; m++) {
            addLevel(ref + m * vibQ, false, true, false);
            addLevel(ref - m * vibQ, false, true, false);
        }
    }

    // Proportional levels
    for (int s = start; s < swingCount - 1; s++) {
        double hi = fmax(swings[s].price, swings[s+1].price);
        double lo = fmin(swings[s].price, swings[s+1].price);
        double rng = hi - lo;
        if (rng < 5) continue;
        double fracs[] = {0.125, 0.25, 0.333, 0.375, 0.5, 0.625, 0.667, 0.75, 0.875};
        for (int f = 0; f < 9; f++)
            addLevel(lo + rng * fracs[f], false, false, true);
    }

    // Sort by convergence desc
    std::sort(levels, levels + count, [](const GannLevel& a, const GannLevel& b) {
        return a.convergence > b.convergence;
    });
    return count;
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

    // Find most recent high and low swings
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

    // 1x1 angles
    double ascPrice = (lastLowBar >= 0) ? lastLowPrice + (barIdx - lastLowBar) * scale : 0;
    double descPrice = (lastHighBar >= 0) ? lastHighPrice - (barIdx - lastHighBar) * scale : 1e18;

    // Most recent swing determines primary bias
    if (lastLowBar > lastHighBar) {
        // Last swing was LOW → lean long
        if (price >= ascPrice - lostMotion) r.direction = 1;
        else if (price <= descPrice + lostMotion) r.direction = -1;
        else r.direction = 1;
    } else {
        if (price <= descPrice + lostMotion) r.direction = -1;
        else if (price >= ascPrice - lostMotion) r.direction = 1;
        else r.direction = -1;
    }

    // Count strength
    double ratios[] = {0.5, 1.0, 2.0, 4.0};
    int bull = 0, bear = 0;
    for (int ri = 0; ri < 4; ri++) {
        if (lastLowBar >= 0) {
            double a = lastLowPrice + (barIdx - lastLowBar) * scale * ratios[ri];
            if (price > a - lostMotion) bull++;
        }
        if (lastHighBar >= 0) {
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
            ((m5[i].close > m5[i-1].close && m5[i+1].close < m5[i].close) ||
             (m5[i].close < m5[i-1].close && m5[i+1].close > m5[i].close)))
            near++;
    }
    return near < 2;
}

static bool filterSpeedAccel(const Bar* m5, int idx) {
    if (idx < 24) return true;
    double first = fabs(m5[idx-12].close - m5[idx-24].close);
    double second = fabs(m5[idx].close - m5[idx-12].close);
    if (first <= 0) return true;
    double speed = first / 12.0;
    double accel = speed * speed;
    double remSpeed = second / 12.0;
    return !(remSpeed > accel && accel > 0.5);
}

static bool filterPTSquare(double entry, double ref, int barsRef) {
    if (barsRef <= 0) return true;
    double pd = sq9Degree(fabs(entry - ref));
    double td = sq9Degree((double)barsRef);
    double diff = fabs(pd - td);
    if (diff > 180) diff = 360 - diff;
    return diff <= 15.0;
}

static bool filterTimeExpiry(int barsRef) { return barsRef <= 81; }

static bool filter4thTouch(const Bar* m5, int idx, double level, int dir, double tol) {
    if (idx < 144) return true;
    int touches = 0;
    for (int i = idx - 144; i < idx; i++)
        if (m5[i].low <= level + tol && m5[i].high >= level - tol) touches++;
    if (touches >= 3) {
        if (dir == 1 && m5[idx].close < level) return false;
        if (dir == -1 && m5[idx].close > level) return false;
    }
    return true;
}

// ============================================================
// Angle-based SL
// ============================================================

static double angleSL(int dir, double entry, int barIdx,
                      const Swing* swings, int swingCount,
                      double scale, double lostMotion, double fallback) {
    double best = 0;
    double bestDist = 1e18;
    double ratios[] = {0.25, 0.5, 1.0, 2.0};

    for (int s = swingCount - 1; s >= 0 && s >= swingCount - 10; s--) {
        for (int r = 0; r < 4; r++) {
            double ap;
            if (dir == 1 && swings[s].type == -1) {
                ap = swings[s].price + (barIdx - swings[s].barIndex) * scale * ratios[r];
                if (ap < entry + lostMotion) {
                    double d = entry - ap;
                    if (d >= 0 && d < bestDist) { bestDist = d; best = ap; }
                }
            }
            if (dir == -1 && swings[s].type == 1) {
                ap = swings[s].price - (barIdx - swings[s].barIndex) * scale * ratios[r];
                if (ap > entry - lostMotion) {
                    double d = ap - entry;
                    if (d >= 0 && d < bestDist) { bestDist = d; best = ap; }
                }
            }
        }
    }

    if (best > 0) {
        double sl = (dir == 1) ? best - lostMotion : best + lostMotion;
        if ((dir == 1 && sl < entry) || (dir == -1 && sl > entry)) return sl;
    }
    return (dir == 1) ? entry - fallback : entry + fallback;
}

// ============================================================
// Main simulation
// ============================================================

struct Results {
    int totalTrades;
    int wins, losses;
    double finalEquity, maxDD, peakEquity;
    int tpExits, slExits, timeExits;
    double totalCommission;
    double avgWin, avgLoss;
    std::vector<Trade> trades;
};

static Results runBacktest(const Bar* m5, int n, const Params& p) {
    Results res = {};
    res.finalEquity = p.startCapital;
    res.peakEquity = p.startCapital;
    double equity = p.startCapital;

    // Compute ATR on M5
    double* atr = new double[n];
    computeATR(m5, n, p.atrPeriod, atr);

    // Detect swings on M5 (need enough to cover the full dataset)
    int maxSw = 50000;
    Swing* allSwings = new Swing[maxSw];
    int swingCount = detectSwings(m5, n, atr, p.atrMultiplier, allSwings, maxSw);
    fprintf(stderr, "  M5 Swings detected: %d\n", swingCount);

    // Pre-detect H1 and D1 swings for direction
    // H1 = every 12th M5 bar, D1 = every 288th
    int h1Count = n / 12 + 1;
    Bar* h1 = new Bar[h1Count];
    int h1N = 0;
    for (int i = 0; i < n; i += 12) {
        int end = std::min(i + 12, n);
        h1[h1N].timestamp = m5[i].timestamp;
        h1[h1N].open = m5[i].open;
        h1[h1N].high = m5[i].high;
        h1[h1N].low = m5[i].low;
        h1[h1N].close = m5[end-1].close;
        for (int j = i+1; j < end; j++) {
            if (m5[j].high > h1[h1N].high) h1[h1N].high = m5[j].high;
            if (m5[j].low < h1[h1N].low) h1[h1N].low = m5[j].low;
        }
        h1N++;
    }
    double* h1Atr = new double[h1N];
    computeATR(h1, h1N, p.atrPeriod, h1Atr);
    Swing* h1Swings = new Swing[5000];
    int h1SwCount = detectSwings(h1, h1N, h1Atr, p.atrMultiplier, h1Swings, 5000);
    fprintf(stderr, "  H1 swings: %d, H1 bars: %d\n", h1SwCount, h1N);

    // Level + angle caches
    GannLevel levels[500];
    int levelCount = 0;
    int cacheCounter = 0;
    int dailyTrades = 0;
    int64_t currentDay = 0;

    // Active position
    bool hasPos = false;
    Trade pos = {};

    for (int i = 60; i < n; i++) {
        // Date filter
        if (m5[i].timestamp < p.fromDate || m5[i].timestamp > p.toDate) continue;

        // Daily reset
        int64_t day = m5[i].timestamp / 86400;
        if (day != currentDay) { currentDay = day; dailyTrades = 0; }

        // Check position exit
        if (hasPos) {
            bool hitSL = false, hitTP = false;
            double exitPrice = 0;
            int exitReason = -1;

            if (pos.direction == 1) {
                if (m5[i].low <= pos.sl) { hitSL = true; exitPrice = pos.sl; }
                else if (m5[i].high >= pos.tp) { hitTP = true; exitPrice = pos.tp; }
            } else {
                if (m5[i].high >= pos.sl) { hitSL = true; exitPrice = pos.sl; }
                else if (m5[i].low <= pos.tp) { hitTP = true; exitPrice = pos.tp; }
            }

            int held = i - pos.entryBar;
            if (!hitSL && !hitTP && held >= p.maxHoldBars) {
                exitPrice = m5[i].close; exitReason = 2;
            } else if (hitTP) exitReason = 0;
            else if (hitSL) exitReason = 1;
            else continue;

            double pnlPerOz = (pos.direction == 1) ? exitPrice - pos.entryPrice : pos.entryPrice - exitPrice;
            double gross = pnlPerOz * pos.lotSize * 100.0;
            double comm = 0.06 * (pos.lotSize / 0.01) * 2;
            double net = gross - comm;

            equity += net;
            if (equity > res.peakEquity) res.peakEquity = equity;
            double dd = (res.peakEquity - equity) / res.peakEquity;
            if (dd > res.maxDD) res.maxDD = dd;

            pos.exitBar = i; pos.exitPrice = exitPrice; pos.exitReason = exitReason;
            pos.pnl = gross; pos.commission = comm; pos.netPnl = net;
            res.trades.push_back(pos);
            res.totalTrades++;
            if (net > 0) { res.wins++; res.avgWin += net; res.tpExits += (exitReason == 0); }
            else { res.losses++; res.avgLoss += net; res.slExits += (exitReason == 1); }
            if (exitReason == 2) res.timeExits++;
            res.totalCommission += comm;

            hasPos = false;
            continue;
        }

        if (dailyTrades >= p.maxDailyTrades) continue;

        // Update levels every 12 bars
        cacheCounter++;
        if (cacheCounter >= 12 || levelCount == 0) {
            cacheCounter = 0;
            // Find relevant swings (use H1 swings)
            int fromSw = h1SwCount > p.maxSwings ? h1SwCount - p.maxSwings : 0;
            // Filter swings up to current H1 bar
            int curH1 = i / 12;
            int validSw = 0;
            for (int s = 0; s < h1SwCount; s++)
                if (h1Swings[s].barIndex <= curH1) validSw = s + 1;

            if (validSw >= 3) {
                fromSw = validSw > p.maxSwings ? validSw - p.maxSwings : 0;
                levelCount = calculateLevels(h1Swings, validSw, fromSw,
                    m5[i].close, p.swingQuantum, levels, 500);
            }
        }

        if (levelCount == 0) continue;

        // Get H1 angle direction
        int curH1 = i / 12;
        int validH1Sw = 0;
        for (int s = 0; s < h1SwCount; s++)
            if (h1Swings[s].barIndex <= curH1) validH1Sw = s + 1;

        DirResult h1Dir = {0, 0};
        if (p.useAngles && validH1Sw >= 2)
            h1Dir = angleDirection(m5[i].close, curH1, h1Swings, validH1Sw, p.h1Scale, p.lostMotion);

        // Reference swing
        int lastSwIdx = validH1Sw - 1;
        if (lastSwIdx < 0) continue;
        double refPrice = h1Swings[lastSwIdx].price;
        int barsFromRef = std::max(1, (curH1 - h1Swings[lastSwIdx].barIndex));

        // Scan levels
        for (int lv = 0; lv < levelCount; lv++) {
            double level = levels[lv].price;
            if (levels[lv].convergence < p.minConvergence) continue;

            // Touch check
            if (!(m5[i].low <= level + p.touchTol && m5[i].high >= level - p.touchTol))
                continue;

            // Direction
            int direction = 0;
            int strength = 0;
            const char* dirStr = "fade";

            if (p.useAngles && h1Dir.direction != 0) {
                direction = h1Dir.direction;
                strength = h1Dir.strength;
                dirStr = (direction == 1) ? "long" : "short";
            } else {
                // Fade fallback
                direction = (m5[i-1].close < level) ? -1 : 1;
                dirStr = "fade";
            }

            double entry = level + (direction == 1 ? 0.5 : -0.5);

            // Filters
            if (p.filterFold && !filterFoldAtThird(m5, i)) continue;
            if (p.filterSpeed && !filterSpeedAccel(m5, i)) continue;
            if (p.filterPTSquare && !filterPTSquare(entry, refPrice, barsFromRef)) continue;
            if (p.filterTimeExpiry && !filterTimeExpiry(barsFromRef)) continue;
            if (p.filter4thTouch && !filter4thTouch(m5, i, level, direction, p.touchTol)) continue;

            // TP: next Gann level
            double tp = 0;
            for (int j = 0; j < levelCount; j++) {
                double lp = levels[j].price;
                double dist = fabs(lp - entry);
                if (dist < 3.0 || dist > 150.0) continue;
                if (direction == 1 && lp > entry && (tp == 0 || lp < tp)) tp = lp;
                if (direction == -1 && lp < entry && (tp == 0 || lp > tp)) tp = lp;
            }
            if (tp == 0) tp = entry + direction * p.tpDollars;

            // SL: angle-based
            double sl;
            if (p.useAngles && validH1Sw >= 2)
                sl = angleSL(direction, entry, curH1, h1Swings, validH1Sw,
                             p.h1Scale, p.lostMotion, p.slDollars);
            else
                sl = entry - direction * p.slDollars;

            // R:R check
            double slDist = fabs(entry - sl);
            double tpDist = fabs(tp - entry);
            if (slDist < 1.0 || tpDist < 3.0) continue;
            if (tpDist / slDist < p.minRR) continue;

            // Position sizing
            double risk = equity * p.riskPct;
            double lot = risk / (slDist * 100.0);
            if (lot < 0.01) lot = 0.01;
            lot = floor(lot * 100) / 100.0;

            pos.entryBar = i;
            pos.entryPrice = entry;
            pos.direction = direction;
            pos.lotSize = lot;
            pos.sl = sl;
            pos.tp = tp;
            pos.convergence = levels[lv].convergence;
            pos.angleStrength = strength;
            strncpy(pos.angleDir, dirStr, 7);
            hasPos = true;
            dailyTrades++;
            break;
        }
    }

    res.finalEquity = equity;
    if (res.wins > 0) res.avgWin /= res.wins;
    if (res.losses > 0) res.avgLoss /= res.losses;

    delete[] atr;
    delete[] allSwings;
    delete[] h1;
    delete[] h1Atr;
    delete[] h1Swings;
    return res;
}

// ============================================================
// Main
// ============================================================

static void parseParam(Params& p, const char* arg) {
    char key[64]; double val;
    if (sscanf(arg, "%63[^=]=%lf", key, &val) == 2) {
        if (!strcmp(key, "vibration")) p.vibration = val;
        else if (!strcmp(key, "quantum")) p.swingQuantum = val;
        else if (!strcmp(key, "minconv")) p.minConvergence = (int)val;
        else if (!strcmp(key, "m5scale")) p.m5Scale = val;
        else if (!strcmp(key, "h1scale")) p.h1Scale = val;
        else if (!strcmp(key, "d1scale")) p.d1Scale = val;
        else if (!strcmp(key, "angles")) p.useAngles = val > 0;
        else if (!strcmp(key, "multitf")) p.requireMultiTF = val > 0;
        else if (!strcmp(key, "sl")) p.slDollars = val;
        else if (!strcmp(key, "tp")) p.tpDollars = val;
        else if (!strcmp(key, "risk")) p.riskPct = val / 100.0;
        else if (!strcmp(key, "maxdaily")) p.maxDailyTrades = (int)val;
        else if (!strcmp(key, "maxhold")) p.maxHoldBars = (int)val;
        else if (!strcmp(key, "minrr")) p.minRR = val;
        else if (!strcmp(key, "fold")) p.filterFold = val > 0;
        else if (!strcmp(key, "speed")) p.filterSpeed = val > 0;
        else if (!strcmp(key, "ptsquare")) p.filterPTSquare = val > 0;
        else if (!strcmp(key, "timeexpiry")) p.filterTimeExpiry = val > 0;
        else if (!strcmp(key, "touch4th")) p.filter4thTouch = val > 0;
        else if (!strcmp(key, "capital")) p.startCapital = val;
        else if (!strcmp(key, "leverage")) p.leverage = (int)val;
        else if (!strcmp(key, "from")) p.fromDate = (int64_t)val;
        else if (!strcmp(key, "to")) p.toDate = (int64_t)val;
    }
}

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
    fprintf(stderr, "Loaded. Range: %lld to %lld\n", (long long)bars[0].timestamp, (long long)bars[barCount-1].timestamp);

    // Run backtest
    Results res = runBacktest(bars, (int)barCount, p);

    // Output results
    double winRate = res.totalTrades > 0 ? (double)res.wins / res.totalTrades : 0;
    double rr = res.avgLoss != 0 ? fabs(res.avgWin / res.avgLoss) : 0;

    // Count trading days
    int64_t firstDay = 0, lastDay = 0;
    if (!res.trades.empty()) {
        firstDay = bars[res.trades.front().entryBar].timestamp / 86400;
        lastDay = bars[res.trades.back().entryBar].timestamp / 86400;
    }
    int tradingDays = std::max(1, (int)(lastDay - firstDay));
    double tradesPerDay = (double)res.totalTrades / tradingDays;

    printf("{\n");
    printf("  \"total_trades\": %d,\n", res.totalTrades);
    printf("  \"wins\": %d,\n", res.wins);
    printf("  \"losses\": %d,\n", res.losses);
    printf("  \"win_rate\": %.4f,\n", winRate);
    printf("  \"rr_ratio\": %.2f,\n", rr);
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
    printf("  \"angle_long\": %d, \"angle_long_win\": %d,\n", angleLong, angleLongWin);
    printf("  \"angle_short\": %d, \"angle_short_win\": %d,\n", angleShort, angleShortWin);
    printf("  \"fade_trades\": %d, \"fade_win\": %d,\n", fadeTrades, fadeWin);

    // Params echo
    printf("  \"params\": {\"angles\": %s, \"minconv\": %d, \"h1scale\": %.1f, \"fold\": %s, \"speed\": %s, \"ptsquare\": %s}\n",
           p.useAngles ? "true" : "false", p.minConvergence, p.h1Scale,
           p.filterFold ? "true" : "false", p.filterSpeed ? "true" : "false",
           p.filterPTSquare ? "true" : "false");
    printf("}\n");

    delete[] bars;
    return 0;
}
