## Project

**FXSoqqaBot**

A precision Gann trading bot for XAUUSD (Gold) on MetaTrader 5 via RoboForex ECN with 1:500 leverage. Uses price-time alignment (Sq9 price levels + natural square time cycles + price-time squaring) for high-conviction entries. Ships as an MQL5 EA for MT5 Strategy Tester and live trading.

**Core Edge:** D1 trend direction + H1 angle confirmation + Gann level entry + ATR-based asymmetric R:R. 1.45x lift over random walk on 17yr data, validated out-of-sample (1.48x on 2020-2026).

**Goal:** Consistent positive EV trend-following on XAUUSD.

**Status:** v8.0 — correct Gann method. D1+H1 trend alignment is THE edge. Convergence scoring, three-limits, and time gating add zero directional value. Triangle crossings predict zones but not prices. **ATR×3.0 SL, 4:1 R:R = 29% WR, +EV, 1.1 TPD, stable 17yr.**

**CRITICAL:** D1 trend + H1 angle + market entry + ATR SL/TP. Convergence levels DON'T predict direction.

### Constraints

- **Platform**: MetaTrader 5 on Windows — MQL5 EA for execution and backtesting
- **Broker**: RoboForex ECN, 1:500 leverage
- **Capital**: Starting at $20, position sizing based on 2% risk per trade
- **Instrument**: XAUUSD (Gold) only
- **Timeframe**: M5 entries, H1 for swing-based level calculation
- **Vibration**: V=72 base (Hellcat formula N=3 → 73.18≈72, confirmed on charts), swing quantum V=12 (72/6)

## Architecture

```
MQL5 EA (GannScalper.mq5)          — Production: MT5 Strategy Tester + live trading
C++ Tester (gann_backtest.cpp)      — Fast iteration: 1.15M bars in 0.4 seconds
Python Research (gann_research/)    — Calibration, analysis, prototyping
```

### Strategy Flow (v8.0 — CORRECT GANN METHOD)

1. **D1 Direction**: Resample M5→H1→D1. Detect D1 swings. Compute D1 angle direction. This sets the ONLY allowed trade direction.
2. **H1 Direction**: Compute H1 angle direction from H1 swings. Must AGREE with D1.
3. **Level Calculation**: Sq9, vibration (V=12), proportional divisions from H1 swings → convergence levels.
4. **Level Touch**: M5 bar touches any Gann level (minconv=1 sufficient, higher conv doesn't improve WR).
5. **Bounce Direction**: Determine from approach side (close > level → long support bounce, close < level → short resistance bounce).
6. **Direction Alignment**: Bounce direction must agree with H1 AND D1 trends. Skip if any conflict.
7. **Market Entry**: Enter at next bar open (entrymode=0). No limit orders.
8. **ATR-Based SL**: SL = 3.0 × ATR(14) from entry price. Adapts to volatility.
9. **Fixed R:R TP**: TP = 4 × SL distance. Captures trending bias.
10. **Max Hold**: 288 M5 bars (24 hours).
11. **Wave Counting** (optional): H1 wave direction can filter, adds +1.3% WR but halves frequency.

### Key Lessons Learned

| Lesson | Detail |
|--------|--------|
| **D1 TREND IS THE EDGE** | +10.5% absolute WR from D1 direction. Gann: "determine the TREND first." |
| **Convergence scoring = zero** | Independent scoring (7 factors) has ZERO correlation with WR. Flat across all scores. |
| **Three-limit alignment = zero** | All 3 limits aligned has same WR as 1 limit. No discriminative power. |
| **Time gating = negligible** | Natural square timing adds <1% WR. Not worth the trade reduction. |
| **Levels predict volatility, not direction** | Big moves happen at convergence zones, but equally likely up or down. |
| **Triangle crossings were phantom** | 90.4% WR was entirely from fill bug. Honest: 71% WR, negative EV. |
| **ATR-based SL/TP > fixed** | Fixed $5 SL declines at $3000 gold. ATR×3.0 adapts. Stability: 1.29-1.61x vs 1.21-2.09x. |
| **4:1 R:R is optimal** | Wider TP amplifies the trend edge. SL/TP ratio matters more than WR. |
| **Out-of-sample validated** | Train 2009-2019: 1.44x lift. Test 2020-2026: 1.48x lift. Edge holds. |
| **Positive in 7/8 periods** | Only 2018-19 (low-vol consolidation) slightly negative. All others positive. |
| **$20 is not viable** | ATR-based SL ≈ $9-15. Min 0.01 lot. Need $500+ for 2% risk management. |
| **Wave counting = marginal** | +1.3% WR but halves frequency. Better as a soft signal, not hard filter. |

## Key Files

| File | Purpose |
|------|---------|
| `gann_tester/gann_backtest.cpp` | C++ fast backtester — compile via msys2 g++, runs full dataset in 0.4s |
| `gann_research/math_core.py` | 29 Gann formulas (Sq9, vibration, proportional, impulse) |
| `gann_research/gann_angles.py` | Angle direction engine (ascending/descending from swing points) |
| `gann_research/triangle_engine.py` | Angle crossing detection for triangle setups |
| `gann_research/gann_filters.py` | All Gann filters including 5 trend change rules |
| `gann_research/swing_detector.py` | ATR-based ZigZag swing detection |
| `gann_research/scalp_sim.py` | Python M5 scalping simulator |
| `gann_research/calibrate.py` | Parameter calibration (vibration, Sq9 degrees, angle scales) |
| `gann_research/data_loader.py` | Load M1 CSV/parquet, resample to any timeframe |
| `data/clean/XAUUSD_M5.bin` | Binary M5 data (1.15M bars, 44MB, 2009-2026) |
| `data/clean/XAUUSD_M1_clean.parquet` | Full M1 parquet (5.7M bars) |
| `GANN_METHOD_ANALYSIS.md` | Decoded Gann reference manual (book + forum masters) |
| `SESSION_STATE.md` | Current iteration state, best config, next steps |

## Development Tools

| Tool | Purpose |
|------|---------|
| **g++ (msys2)** | Compile C++ tester: `C:/msys64/mingw64/bin/g++.exe -O3 -std=c++17` |
| **MetaEditor** | Compile MQL5 EA (F7 in MT5) |
| **MT5 Strategy Tester** | Production backtesting (Ctrl+R in MT5) |
| **Python + uv** | Research, calibration, data processing |

### Compile & Run C++ Tester

```bash
# Compile (via msys2 bash — needed for paths with spaces)
cp gann_tester/gann_backtest.cpp /c/temp/ && C:/msys64/usr/bin/bash.exe -lc "C:/msys64/mingw64/bin/g++.exe -O3 -std=c++17 -o /c/temp/gann_bt.exe /c/temp/gann_backtest.cpp"

# WINNER — Config A (90.4% WR, 5.82 trades/day, $1.00 EV)
C:\temp\gann_bt.exe data/clean/XAUUSD_M5.bin triangle=1 m5tri=1 triscale=1.0 tripricetol=5 tribartol=72 triminimp=14 triconvgate=1 minconv=7 sl=7 tp=2 maxtp=20 maxhold=288 spread=0.30 minrr=0 fold=0 speed=0 touch4th=0 entrymode=1 fixedtp=1 filterbounce=1

# Config B — Best equity (87.8% WR, 6.14 TPD, $48k from $10k)
C:\temp\gann_bt.exe data/clean/XAUUSD_M5.bin triangle=1 m5tri=1 triscale=1.0 tripricetol=5 tribartol=72 triminimp=14 triconvgate=1 minconv=7 sl=5 tp=2 maxtp=20 maxhold=288 spread=0.30 minrr=0 fold=0 speed=0 touch4th=0 entrymode=1 fixedtp=1 filterbounce=1

# v8.0 RECOMMENDED — ATR-based D1 trend following (1.45x lift, +EV, stable 17yr)
/c/temp/gann_bt.exe data/clean/XAUUSD_M5.bin triangle=0 entrymode=0 slatr=3.0 tpratio=4 fixedtp=1 filterbounce=0 minconv=1 minscore=0 minlimits=0 angles=1 fold=0 speed=0 touch4th=0 maxhold=288 spread=0.30 maxdaily=10 minrr=0 d1=1 d1scale=72

# Alternative — Fixed SL/TP (higher peak lift but less stable across volatility regimes)
/c/temp/gann_bt.exe data/clean/XAUUSD_M5.bin triangle=0 entrymode=0 sl=7 tp=28 fixedtp=1 filterbounce=0 minconv=1 minscore=0 minlimits=0 angles=1 fold=0 speed=0 touch4th=0 maxhold=288 spread=0.30 maxdaily=10 minrr=0 d1=1 d1scale=72

# Key v8.0 params: d1=1, slatr=3.0, tpratio=4, entrymode=0, triangle=0
```

## MT5 Paths

- **Terminal**: `C:\Program Files\RoboForex MT5 Terminal\terminal64.exe`
- **MetaEditor**: `C:\Program Files\RoboForex MT5 Terminal\metaeditor64.exe`
- **MQL5 Data**: `C:\Users\Windows 11\AppData\Roaming\MetaQuotes\Terminal\5FFA568149E88FCD5B44D926DCFEAA79\MQL5\`
- **EA Location**: `MQL5\Experts\GannScalper.mq5`

## Gann Constants (Gold/XAUUSD)

- **Base vibration**: V=72 (Hellcat formula N=3, confirmed on charts)
- **Swing quantum**: V=12 = 72/6 (strongest H1 signal)
- **KU series**: 1, 2, 3, 5, 7, 11 (Ferro's indivisible units)
- **Subdivisions**: 72/6=12, 72/4=18, 72/3=24, 72/2=36
- **Cube root step**: 52 for all gold prices $900-$2900
- **Master time number**: 52
- **Lost motion**: ±$2-3 (Gann: "2-2.5 units")
- **Power Sq9 angles**: 30° and 45° (highest hit rate on gold)
- **Natural square timing**: 4, 9, 16, 24, 36, 49, 72, 81 (H4 bars)

## v8.0 Optimized Parameters

- **SL**: 3.0 × ATR(14) on M5 (adapts to volatility, typically $6-15)
- **TP**: 4 × SL (asymmetric R:R, captures trend)
- **Entry**: Market (entrymode=0), next bar open after level touch
- **D1 filter**: ON (d1=1) — the primary directional edge
- **H1 angles**: ON (angles=1) — secondary direction confirmation
- **Convergence**: minconv=1 (higher values don't improve WR)
- **Scoring**: minscore=0 (scoring has zero WR correlation)
- **Limits**: minlimits=0 (three-limit alignment has zero WR correlation)
- **Max hold**: 288 M5 bars (24 hours)
- **Random walk baseline**: 20% → Observed 29% → **1.45x lift**
- **Out-of-sample**: Train 1.44x → Test 1.48x (edge holds)

## Sources

- W.D. Gann Master Commodities Course (385 pages, 21 chapters) — primary authority
- Hellcat (385 forum posts) — triangle system, vibration formula, differential numerology
- Ferro (362 forum posts) — 10 postulates of the Law, price-time squaring, planetary system
- 17 years XAUUSD M1 data (2009-2026, 5.7M bars)
