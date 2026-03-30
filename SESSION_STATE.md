# Session State — Gann Strategy v6.1
## Saved: 2026-03-30 (Session 10 — Triangle System + MT5 Validation)

---

## CRITICAL CORRECTION: SL/TP Was Inverted

### The Mistake
We used TP=$1.5 (small) with SL=$10 (big) to chase high WR. This is WRONG:
- Random walk with TP=$1.5, SL=$10 already gives 87% WR — no edge needed
- A 92% WR looks impressive but is mostly random walk baseline
- At 82% WR (MT5 real ticks), the EV is NEGATIVE: 0.82×$1.5 - 0.18×$10 = -$0.57/trade
- This is NOT how Gann traders work

### What Gann/Ferro/Hellcat Actually Say

**Gann Ch 5A**: "You can buy every time it rests on the 45-degree angle with a stop loss order 1, 2, or 3 cents UNDER the 45-degree angle."
→ SL = TIGHT, just below the supporting angle + lost motion ($2-3)

**Hellcat**: "Exit from triangle is always a MULTIPLE of the entry"
→ TP = MULTIPLE of entry distance, i.e., TP > SL

**Ferro**: Lost motion = ±$2-3. Price-time squaring accuracy = ±2 units.
→ SL = $2-3 (lost motion), TP = next crossing/level ($5-15)

**The Quant Mechanism**: "roughly the same as the initial impulse for building a Gann box"
→ TP = impulse size = much larger than lost motion

### The Correct Approach
- **SL = TIGHT**: $2-3 from the triangle crossing (lost motion = Gann's "2-2.5 units")
  - For LONG: SL = crossing_price - lost_motion ($2-3)
  - For SHORT: SL = crossing_price + lost_motion ($2-3)
- **TP = WIDE**: Next triangle crossing, next angle level, or box edge ($5-15)
  - "Exit from triangle is always a MULTIPLE of the entry"
  - TP at next convergence level in direction
  - Or TP at proportional level (1/3, 1/2, 2/3 of swing range)
- **R:R = 2:1 to 5:1** (favorable, not inverted)
- **Expected WR = 50-65%** but with favorable R:R → POSITIVE EV

### Why This Makes Sense
At the triangle crossing point, Gann angles predict the exact reversal. If the prediction is correct:
- Price bounces and reaches the TP ($5-15 away) — WIN with large profit
- If wrong, price passes through the crossing by more than lost motion — LOSE with small loss ($2-3)
- Even at 50% WR: EV = 0.5×$10 - 0.5×$3 = +$3.50/trade

---

## What Was Proven (Still Valid)

### Triangle System Works
1. **Triangle crossings detect real price+time reversal points** — confirmed
2. **M5 swings for scalping frequency** — 7+ trades/day in C++
3. **ConvGate improves quality** — double confirmation (triangle + convergence)
4. **Scale=$1.0/M5bar (=$12/H1bar)** for gold — optimal
5. **importance >= 14** — 1x1+1x1 crossings are strongest
6. **MT5 real ticks validation**: 1,185 trades, 82.2% WR (with inverted R:R)
7. **MAX_SWINGS bug fixed** — swing detection now works after array fills

### MT5 vs C++ Gap Analysis
| Metric | C++ | MT5 Real Ticks |
|--------|-----|----------------|
| Trades (3yr) | ~10,800 | 1,185 |
| WR (TP=$1.5, SL=$10) | 92.6% | 82.2% |
| Gap | — | -10.4% |

Gap sources:
- C++ checks all bars simultaneously; EA has one pending limit at a time
- MT5 real ticks have slippage on limit fills
- EA filters (fold/speed) ON by default, C++ had them OFF
- MT5 may cancel/reject orders during market close

---

## Architecture (Still Valid)

### Triangle System Flow
1. **M5 Swing Detection**: ATR-based ZigZag on M5 (atr_mult=1.5)
2. **Angle Lines**: 4 ascending + 4 descending from each swing (1x2, 1x1, 2x1, 4x1)
3. **Crossings**: Where ascending meets descending (both confirmed before crossing time)
4. **ConvGate**: Crossing price near a Sq9/vibration/proportional convergence level
5. **Limit Entry**: At the crossing price (pre-computed prediction)

### What Needs to Change (SL/TP)
6. **SL = lost motion ($2-3) from crossing price** ← CHANGE
7. **TP = next Gann level or crossing in direction ($5-15)** ← CHANGE
8. **Direction**: bounce from crossing (bar close above → long, below → short)

---

## Next Session — Pick Up Here

### Priority 1: Implement Correct SL/TP (Gann-style)
In C++ tester (`gann_backtest.cpp`):
1. Change SL from fixed $10 to lost_motion $2-3 from crossing price
2. Change TP from fixed $1.5 to:
   - Next convergence level in trade direction (findTP function exists)
   - OR next triangle crossing in direction
   - OR proportional of last swing ($5-15 typical)
3. Set minRR=1.5 (require R:R >= 1.5:1)
4. Test: expect 50-65% WR but POSITIVE EV

### Priority 2: Geometric SL/TP from Triangle Structure
Use the `geoSLTP=1` parameter (already implemented but untested with correct values):
- SL from opposing angle trajectory + lost motion
- TP from next crossing or angle projection
- This is Gann Ch 5A: "stop loss 1-3 cents under the 45-degree angle"

### Priority 3: Increase MT5 Trade Frequency
Current: EA places ONE limit at a time → misses most crossings.
Options:
- Allow multiple simultaneous pending orders
- Or: check all crossings on each bar and enter at market when price touches one
- Match C++ behavior more closely

### Priority 4: Remove Filters for M5 Triangle Mode
The fold/speed/4thtouch filters were designed for H1 convergence levels.
For M5 triangle scalping, they reduce trade count without improving quality.
Set InpFilterFold=false, InpFilterSpeed=false, InpFilter4thTouch=false.

---

## Compile & Run

```bash
# Compile C++ tester
cp gann_tester/gann_backtest.cpp /c/temp/ && C:/msys64/usr/bin/bash.exe -lc "C:/msys64/mingw64/bin/g++.exe -O3 -std=c++17 -o /c/temp/gann_bt.exe /c/temp/gann_backtest.cpp"

# CORRECT R:R: tight SL=$3, wide TP, Gann-style
/c/temp/gann_bt.exe data/clean/XAUUSD_M5.bin triangle=1 m5tri=1 triscale=1.0 tripricetol=5 tribartol=24 triminimp=14 triconvgate=1 minconv=7 sl=3 tp=10 maxtp=15 maxhold=72 spread=0.30 minrr=1.5 fold=0 speed=0 touch4th=0 entrymode=1

# WRONG (what we tested before — DO NOT USE):
# sl=10 maxtp=1.5 → inverted R:R, fake high WR from random walk baseline
```

---

## Key Files

| File | Purpose |
|------|---------|
| `gann_tester/gann_backtest.cpp` | C++ tester with triangle system (M5+H1) |
| `MQL5/Experts/GannScalper.mq5` | EA v6.1 with M5 triangle scalping, debug logging |
| `gann_research/gann_angles.py` | angle_based_sl/tp functions — THE CORRECT APPROACH |
| `GANN_METHOD_ANALYSIS.md` | Ferro/Hellcat decoded methods |
| `GANN_ESOTERIC_RESEARCH.md` | Planetary, Maya, Bible numerology for future timing |

## Constants

- **Triangle scale**: $1.0/M5bar = $12/H1bar (V/6 for gold)
- **Angle ratios**: 1x2 (0.5), 1x1 (1.0), 2x1 (2.0), 4x1 (4.0)
- **Lost motion**: $2-3 (Gann: "2-2.5 units") = THE SL
- **Convergence gate**: min 7
- **M5 ATR multiplier**: 1.5 for swing detection
