## Project

**FXSoqqaBot**

A precision Gann trading bot for XAUUSD (Gold) on MetaTrader 5 via RoboForex ECN with 1:500 leverage. Uses price-time alignment (Sq9 price levels + natural square time cycles + price-time squaring) for high-conviction entries. Ships as an MQL5 EA for MT5 Strategy Tester and live trading.

**Core Edge:** Gann level convergence + limit order entry. Limit orders at exact Sq9/vibration/proportional convergence levels capture a 15% edge over random walk. Tight TP ($2-3), wide SL ($5-7), fade direction.

**Goal:** $20 → $100 with 4-6 trades/day.

**Status:** v6.0 Triangle System built. C++ tester shows **91-95% WR** (17yr backtest, tick-order-aware). Awaiting MT5 real-tick validation.

**CRITICAL:** Triangle crossing limit entry (triangle=1 entrymode=1). Market orders = 68% WR. Limit at triangle crossing = 91-95% WR.

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

### Strategy Flow (v6.0 — TRIANGLE SYSTEM)

1. **Swing Detection**: ATR-based ZigZag on H1 (atr_multiplier=2.5)
2. **Angle Lines**: From each H1 swing, 4 ascending (from lows) + 4 descending (from highs) at ratios 1x2, 1x1, 2x1, 4x1 with scale=$7/H1bar
3. **Triangle Crossings**: Where ascending meets descending angle (both must be confirmed before crossing)
4. **Convergence Gate**: Crossing price must also be near a Sq9/vibration/proportional convergence level (conv>=7)
5. **Limit Order**: BuyLimit/SellLimit at the crossing price (pre-computed prediction)
6. **Direction**: Bounce from crossing (bar close above → long, below → short)
7. **SL**: $10 from crossing price (wide, survives noise)
8. **TP**: $1.5 from crossing price (tight, 91%+ hit rate)
9. **Entry-bar check**: Tick-order-aware SL/TP on fill bar (pessimistic)

### Key Lessons Learned

| Lesson | Detail |
|--------|--------|
| **Triangle IS the edge** | Angle crossings give PRICE+TIME prediction. Convergence levels give only PRICE. |
| Triangle limit entry honest | Pre-computed crossing = genuine prediction, not retroactive level selection. |
| Scale=$7/H1bar for gold | Calibrated: outperforms theoretical V/6=$12. |
| ConvGate adds 3% WR | Requiring convergence level near crossing = double confirmation. |
| Tight TP=$1.5 pushes 90%+ | With SL=$10, random walk baseline is 87%. Triangle edge pushes to 91%+. |
| Scoring doesn't help | Independent convergence (7 factors), 3-Limits have zero WR correlation. |
| Stable across all periods | 90-94% WR from 2009 to 2026, all gold price ranges ($900-$3000). |
| Validate on real ticks | Run MT5 Strategy Tester with "Real ticks" to validate C++ findings. |

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

# Run Config A (94.7% WR — ultra-precise, few trades)
C:\temp\gann_bt.exe data/clean/XAUUSD_M5.bin triangle=1 triscale=7 tripricetol=5 tribartol=3 triminimp=14 triconvgate=1 minconv=7 sl=10 maxtp=1.5 maxhold=72 spread=0.30 entrymode=1

# Run Config B (91.4% WR — more trades)
C:\temp\gann_bt.exe data/clean/XAUUSD_M5.bin triangle=1 triscale=7 tripricetol=5 tribartol=3 triminimp=14 triconvgate=1 minconv=7 sl=10 maxtp=1.5 maxhold=72 spread=0.30 fold=0 speed=0 touch4th=0 entrymode=1

# Triangle params: triangle=1 triscale=N tripricetol=N tribartol=N triminimp=N triconvgate=0/1 entrymode=1
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

## Sources

- W.D. Gann Master Commodities Course (385 pages, 21 chapters) — primary authority
- Hellcat (385 forum posts) — triangle system, vibration formula, differential numerology
- Ferro (362 forum posts) — 10 postulates of the Law, price-time squaring, planetary system
- 17 years XAUUSD M1 data (2009-2026, 5.7M bars)
