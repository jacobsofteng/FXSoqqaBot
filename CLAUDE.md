## Project

**FXSoqqaBot**

A pure Gann trading bot for XAUUSD (Gold) on MetaTrader 5 via RoboForex ECN with 1:500 leverage. Uses W.D. Gann's geometric angles for direction, Square of 9 for price levels, and convergence scoring for entry quality. Ships as an MQL5 EA for MT5 Strategy Tester and live trading.

**Core Edge:** Gann angle direction from H1 swing structure replaces random fade logic. Price above ascending 1x1 from last swing low = LONG. Below descending 1x1 from last swing high = SHORT. Combined with Sq9/vibration/proportional level convergence and Gann filters (fold at 1/3, 4th-time-through, speed/acceleration).

**Current Best:** 75.3% win rate, 2.2 trades/day, 8.4% max drawdown (2020-2022 test, validated on 2015-2019 train at 71%).

### Constraints

- **Platform**: MetaTrader 5 on Windows — MQL5 EA for execution and backtesting
- **Broker**: RoboForex ECN, 1:500 leverage
- **Capital**: Starting at $20, position sizing based on 2% risk per trade
- **Instrument**: XAUUSD (Gold) only
- **Timeframe**: M5 entries, H1/D1 for angle direction
- **Vibration**: V=72 base (Hellcat formula N=3 → 73.18≈72, confirmed on charts), swing quantum V=12 (72/6)

## Architecture

```
MQL5 EA (GannScalper.mq5)          — Production: MT5 Strategy Tester + live trading
C++ Tester (gann_backtest.cpp)      — Fast iteration: 1.15M bars in 0.4 seconds
Python Research (gann_research/)    — Calibration, analysis, prototyping
```

### Strategy Flow

1. **Swing Detection**: ATR-based ZigZag on H1 (atr_multiplier=2.5)
2. **Gann Levels**: Sq9 (30/45/60/90/120/180°) + vibration multiples (V=12) + proportional (1/8-7/8) from last 10 H1 swings, clustered at $3 tolerance
3. **Direction**: H1 Gann angle (1x1 at $7/bar scale from most recent swing), D1 confirmation
4. **Entry**: M5 bar touches Gann level with convergence >= 10, direction agrees with H1 angle
5. **Filters**: Fold at 1/3, speed/acceleration, time expiry, 4th-time-through (CRITICAL)
6. **SL**: $5 (angle-based with fallback), **TP**: Next Gann level, **Max hold**: 36 M5 bars (3h)

### Optimal Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| h1scale | 7.0 | $/bar for H1 1x1 angle (calibrated empirically) |
| minconv | 10 | Minimum Gann level convergence |
| sl | 5.0 | Stop loss dollars |
| minrr | 0.5 | Minimum risk:reward ratio |
| maxhold | 36 | Max M5 bars to hold (3 hours) |
| fold | ON | Fold at 1/3 filter |
| speed | ON | Speed/acceleration filter |
| touch4th | ON | 4th-time-through filter (removes it = WR drops 70%→54%) |
| ptsquare | OFF | Price-time squaring (too restrictive, kills 80% of trades) |

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
C:/msys64/usr/bin/bash.exe -lc "C:/msys64/mingw64/bin/g++.exe -O3 -std=c++17 -o /c/temp/gann_bt.exe /c/temp/gann_backtest.cpp"

# Run (outputs JSON)
C:\temp\gann_bt.exe data/clean/XAUUSD_M5.bin from=1577836800 to=1672531200 angles=1 minconv=10 sl=5 h1scale=7

# Key parameters: angles=0/1 minconv=N h1scale=N sl=N tp=N minrr=N maxhold=N fold=0/1 speed=0/1 ptsquare=0/1 touch4th=0/1
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
