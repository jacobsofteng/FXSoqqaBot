# Session State — Gann Strategy v8.0 (CORRECT METHOD)
## Saved: 2026-03-30 (Session 12 — Correct Gann Approach)

---

## KEY DISCOVERY: What Gann's Method Actually Predicts

### Convergence Levels Predict VOLATILITY, Not Direction
The Sq9, vibration, proportional, and convergence scoring systems predict where BIG moves happen — but NOT which direction. WR is flat (~random) across all convergence scores (3 through 7) and all three-limit alignments (1 through 3).

### The Edge Comes From TREND Direction
Gann's #1 rule: "Determine the TREND on weekly and monthly charts first."

| Component | WR Contribution | Notes |
|-----------|----------------|-------|
| **D1 trend direction** | **+10.5%** absolute | The dominant factor |
| H1 angle confirmation | +1.4% | Requires agreement with D1 |
| Level touch (any level) | +3.6% | Entry timing, not directional |
| Convergence scoring | 0% | No WR correlation at all |
| Three-limit alignment | 0% | No WR correlation |
| Time gating (nat sq) | ~0% | Minimal WR improvement |
| Wave counting | +1.3% | But halves trade frequency |

### Bugs Fixed in v8.0
1. `fixedTP` now works for level-based entries (was triangle-only)
2. Bounce filter applied to level entries (was triangle-only)
3. Direction logic: bounce direction first, H1 angles confirm (was: H1 overrides)
4. `findTP` filters by convergence (was: picked noise levels)
5. Added D1 direction filter, wave counting, ATR-based SL/TP, time gate

---

## Current Best: D1 Trend + ATR-Based SL/TP

### Strategy Summary
1. **D1 direction**: Only trade WITH the daily trend
2. **H1 angle confirmation**: H1 trend must agree with D1
3. **Level touch**: Enter at market when price touches any Gann level
4. **Bounce direction**: Fade from approach side, confirmed by H1+D1
5. **ATR-based SL/TP**: SL = 3.0 × ATR(14), TP = 4 × SL

### 17-Year Results (2009-2026)

| Config | WR | Random | Lift | EV/trade | TPD | Trades |
|--------|-----|--------|------|----------|-----|--------|
| **ATR×3.0 ratio=4 (recommended)** | 29.1% | 20.0% | **1.45x** | +$158.6 | 1.12 | 6982 |
| Fixed SL=5 TP=20 | 30.5% | 20.0% | 1.53x | +$179.4 | 1.15 | 7130 |
| Fixed SL=10 TP=40 | 42.3% | 20.0% | 2.11x | +$197.5 | 0.70 | 4332 |
| Fixed SL=7 TP=28 | 35.7% | 20.0% | 1.78x | +$202.4 | 0.88 | 5477 |

### Train/Test Validation (ATR×3.0 ratio=4)
| Period | WR | Lift | EV | TPD |
|--------|------|------|-----|------|
| **Train (2009-2019)** | 28.8% | 1.44x | +$93.2 | 1.13 |
| **Test (2020-2026)** | 29.5% | **1.48x** | +$194.1 | 1.11 |

### Yearly Stability (ATR-based — narrowest variance)
| Period | WR | Lift | EV |
|--------|------|------|-----|
| 2010-11 | 29.3% | 1.47x | +$130 |
| 2012-13 | 29.0% | 1.45x | +$89 |
| 2014-15 | 30.1% | 1.50x | +$99 |
| 2016-17 | 29.2% | 1.46x | +$89 |
| 2018-19 | 25.7% | 1.29x | -$25 |
| 2020-21 | 32.2% | 1.61x | +$318 |
| 2022-23 | 28.1% | 1.40x | +$68 |
| 2024-25 | 27.8% | 1.39x | +$102 |

**Positive in 7 of 8 periods.** Only 2018-19 (low-vol consolidation) is slightly negative.

---

## What Doesn't Work (Confirmed)

| Component | Finding |
|-----------|---------|
| Convergence scoring (7 factors) | Zero WR correlation across all scores |
| Three-limit alignment | Zero WR correlation across all limit counts |
| Time gating (natural squares) | <1% WR improvement |
| Triangle angle crossings | 71% WR but negative EV (levels predict zones, not prices) |
| Bounce quality filter | No WR improvement on level entries |
| SL=$3 (Gann's lost motion) | Too tight — below random at all TP |
| Fixed SL in volatile markets | Edge declines as gold price rises |

---

## Practical Constraints

### $20 Starting Capital
- ATR on M5 ≈ $3-5 → SL = 3×ATR ≈ $9-15
- Minimum 0.01 lot → SL cost = $9-15 per trade
- **$20 cannot survive even 2 consecutive losses**
- **Minimum capital for 2% risk: ~$500-750**

### Trade Frequency
- ATR-based config: **1.0-1.2 trades/day** (below 4-6 target)
- Can increase to ~2 TPD with lower convergence but no WR improvement

---

## Compile & Run (v8.0)

```bash
# Compile
cp gann_tester/gann_backtest.cpp /c/temp/ && C:/msys64/usr/bin/bash.exe -lc "C:/msys64/mingw64/bin/g++.exe -O3 -std=c++17 -o /c/temp/gann_bt.exe /c/temp/gann_backtest.cpp"

# RECOMMENDED: ATR-based, D1 trend following
/c/temp/gann_bt.exe data/clean/XAUUSD_M5.bin triangle=0 entrymode=0 slatr=3.0 tpratio=4 fixedtp=1 filterbounce=0 minconv=1 minscore=0 minlimits=0 angles=1 fold=0 speed=0 touch4th=0 maxhold=288 spread=0.30 maxdaily=10 minrr=0 d1=1 d1scale=72

# Alternative: Fixed SL/TP (simpler, works well on stable-vol periods)
/c/temp/gann_bt.exe data/clean/XAUUSD_M5.bin triangle=0 entrymode=0 sl=7 tp=28 fixedtp=1 filterbounce=0 minconv=1 minscore=0 minlimits=0 angles=1 fold=0 speed=0 touch4th=0 maxhold=288 spread=0.30 maxdaily=10 minrr=0 d1=1 d1scale=72

# New params: d1=0/1, d1scale=N, timegate=0/1/2, waves=0/1, slatr=N, tpratio=N
```

## Key Files
| File | Purpose |
|------|---------|
| `gann_tester/gann_backtest.cpp` | C++ tester v8.0 — D1 direction, wave counting, ATR SL/TP |
| `SESSION_STATE.md` | This file |
