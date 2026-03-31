# CLAUDE.md — FXSoqqaBot v9.1

## Project

**FXSoqqaBot** — A precision Gann trading bot for XAUUSD (Gold) on MetaTrader 5 via RoboForex ECN with 1:500 leverage. Uses a Triangle-First architecture where Gann math detects convergence zones, the quant mechanism defines the trading box, and entries happen only in the Green Zone with tiny SL and large TP.

**Target:** 50-70% WR with 6:1 to 20:1 R:R (not 29% WR with 4:1 like v8.0)

## v9.1 Calibrated Parameters (from full 17yr backtest 2009-2026)

```
CONVERGENCE:
- Min convergence (SCANNING): 3 (of 6 categories: A-D, F, G — no E)
- Min convergence (BOX_ACTIVE): 4 (of 7 categories: A-G)
- Category E (Triangle) excluded from SCANNING (circular dependency)
- Category G uses Gold-specific scaling: PRICE_PER_H4 = $6

QUANT:
- Quant window: 50 bars (M5)
- Min quant size: $6 (half quantum)
- Quant reversal fraction: 0.33

BOX:
- Box width: from Egyptian 3-4-5 proportion (quant_bars × 4/3)
- Green zone start: 67% of box width

DIRECTION:
- Midpoint is primary signal
- Reject only if BOTH D1 and H1 actively disagree with midpoint
- D1 flat or H1 flat: midpoint decides alone

ENTRY:
- Entry at diagonal boundary + lost motion ($3)
- Max diagonal gap: $72 (6 quanta)
- Min R:R: 2.0:1

SL/TP:
- SL: opposite diagonal boundary + lost motion = $6 fixed
- TP: quant_pips × 3 (wave multiplier = 3)
- Trailing stop: at 2R favorable, trail SL to exact breakeven
- Max hold: 288 M5 bars (24 hours)
- Max daily trades: 5

RESULTS (full backtest):
  TRAIN (2009-2019): 1,474 trades, 0.57/day, WR=40.9%, R:R=2.12, EV=$1.44, DD=1.4%
  TEST  (2020-2026): 2,336 trades, 1.62/day, WR=36.9%, R:R=2.98, EV=$2.35, DD=1.0%
  Test outperforms train (not overfit)
```

---

## Architecture Documents (READ IN THIS ORDER)

| File | What it is | When to read |
|------|-----------|-------------|
| `GANN_STRATEGY_V9_SPEC.md` | All math modules: Sq9, vibration, proportional divisions, time structure, swing detection, wave counting, convergence scoring, three-limit alignment. Every formula with Python code. Gold constants. | Read FIRST. This is the math library spec. |
| `GANN_TRIANGLE_RECONSTRUCTION.md` | The Triangle system: quant measurement, Gann Box construction, diagonal intersection engine, Green Zone entry, explosion detection, precision SL/TP. The 4-state machine (Scanning→Quant→Box→Trade). | Read SECOND. This is the trading strategy spec. |
| `MQL5_EA_DEVELOPMENT_GUIDE.md` | How to write the MT5 EA without breaking everything. Bar indexing, new-bar detection, order execution, spread handling, porting checklist. Complete EA skeleton. | Read THIRD. Follow this when writing any MQL5 code. |

**Do NOT read** `docs/reference/GANN_METHOD_ANALYSIS.md` unless explicitly asked. It's raw research notes that have been superseded by the three specs above.

---

## Constraints

- **Platform**: MetaTrader 5 on Windows — MQL5 EA for execution and backtesting
- **Broker**: RoboForex ECN, 1:500 leverage
- **Capital**: Starting at $20, position sizing based on 2% risk per trade
- **Instrument**: XAUUSD (Gold) only
- **Execution timeframe**: M5 bars (entries), H1 for wave counting and levels, H4 for time structure, D1 for trend direction
- **Language**: Python for research/backtesting, C++17 for fast backtesting, MQL5 for production EA

## Gold Constants (DO NOT CHANGE)

```
Base vibration V = 72
Swing quantum V/6 = 12  (strongest H1 signal)
Growth quantum V/4 = 18  (price grows by quarters)
Correction quantum V/3 = 24  (price corrects by thirds)
Cube root step = 52
Master time number = 52
Lost motion = ±$3
Power Sq9 angles = 30° and 45° ONLY
Natural square timing (H4 bars) = 4, 9, 16, 24, 36, 49, 72, 81
```

## Key Files

| File | Purpose |
|------|---------|
| `gann_research/constants.py` | All Gold constants |
| `gann_research/sq9_engine.py` | Square of 9 conversions and level generation |
| `gann_research/vibration.py` | Vibration levels, override detection |
| `gann_research/proportional.py` | Proportional divisions, fold detection |
| `gann_research/time_structure.py` | Natural squares, impulse timing, intraday windows |
| `gann_research/swing_detector.py` | ATR ZigZag for H1, H4, D1 |
| `gann_research/wave_counter.py` | Wave counting (vpM2F(t) protocol) |
| `gann_research/triangle_engine.py` | Quant measurement + Gann Box + diagonal intersections |
| `gann_research/convergence.py` | 7-category independent scoring |
| `gann_research/three_limits.py` | 3-limit alignment with vibration-scaled Limit 1 |
| `gann_research/execution.py` | Green Zone entry logic, SL/TP calculation |
| `gann_research/risk.py` | Position sizing |
| `gann_research/strategy.py` | 4-state machine: process_bar() main loop |
| `gann_research/backtester.py` | Backtest framework with train/test split |
| `gann_research/diagnose.py` | Diagnostic funnel runner (convergence/quant/box/green/exit analysis) |
| `gann_research/data_loader.py` | Load M1 CSV/parquet, resample |
| `gann_tester/gann_backtest.cpp` | C++ fast backtester |
| `mql5/GannScalper.mq5` | Production MT5 EA |
| `data/clean/XAUUSD_M5.bin` | Binary M5 data (1.15M bars, 2009-2026) |
| `data/clean/XAUUSD_M1_clean.parquet` | Full M1 parquet (5.7M bars) |

## Development Tools

| Tool | Purpose |
|------|---------|
| **Python + uv** | Research, calibration, backtesting |
| **g++ (msys2)** | Compile C++ tester: `C:/msys64/mingw64/bin/g++.exe -O3 -std=c++17` |
| **MetaEditor** | Compile MQL5 EA (F7 in MT5) |
| **MT5 Strategy Tester** | Production backtesting (Ctrl+R in MT5) |

## MT5 Paths

- **Terminal**: `C:\Program Files\RoboForex MT5 Terminal\terminal64.exe`
- **MetaEditor**: `C:\Program Files\RoboForex MT5 Terminal\metaeditor64.exe`
- **MQL5 Data**: `C:\Users\Windows 11\AppData\Roaming\MetaQuotes\Terminal\5FFA568149E88FCD5B44D926DCFEAA79\MQL5\`
- **EA Location**: `MQL5\Experts\GannScalper.mq5`

---

## CRITICAL RULES

### Rule 1: Triangle-First Architecture
The Triangle IS the trading framework. Convergence, Sq9, vibration — these are the DETECTION layer that tells you where a triangle will form. The actual trade happens ONLY inside the Green Zone of an active triangle. Never enter "at a Gann level" without a triangle.

### Rule 2: SL From Geometry, Not ATR
SL = opposite diagonal boundary of the triangle at the entry bar + lost motion ($3). This gives $6 SL. TP = quant × 3 (wave multiplier). R:R typically 1.5:1 to 6:1, minimum 2:1. Trailing stop at 2R moves SL to breakeven. If your SL is larger than $10 on Gold, something is wrong.

### Rule 3: Independent Convergence Categories
Each of the 7 convergence categories scores MAX 1 point. Never count two Sq9 angles from the same swing as two separate confirmations. Score 0-7. Minimum 3 in SCANNING (6 categories, excluding E). Minimum 4 in BOX_ACTIVE (all 7). Category E (Triangle) creates circular dependency in SCANNING — exclude it.

### Rule 4: Time Is Greater Than Price
The time structure (natural squares, impulse timing, intraday windows) determines WHEN things happen. Price levels determine WHERE. Both must align. If time says "not yet," do not trade regardless of how perfect the price level looks.

### Rule 5: MQL5 Is Not C++
Read `MQL5_EA_DEVELOPMENT_GUIDE.md` before writing ANY MQL5 code. The top 3 killers: (1) Missing IsNewBar() = 50 trades per bar instead of 1. (2) Using rates[0] = look-ahead bias on forming bar. (3) Missing fill policy / price normalization = silent order rejection.

### Rule 6: Validate C++ vs MQL5 Output
The EA must produce the SAME trade sequence as the C++ backtester on the same data. Export both trade lists and compare. Any mismatch = a porting bug. Use the 15-point porting checklist in the MQL5 guide.

### Rule 7: Implementation Order
Build modules in this order. Each must have unit tests before moving to the next:
1. constants.py → sq9_engine.py → vibration.py → proportional.py → time_structure.py
2. swing_detector.py → wave_counter.py
3. triangle_engine.py (quant + box + intersections + zones)
4. convergence.py → three_limits.py → execution.py → risk.py
5. strategy.py (4-state machine) → backtester.py
6. gann_backtest.cpp (C++ port for fast optimization)
7. GannScalper.mq5 (MT5 EA, follow MQL5 guide strictly)

### Rule 8: No Shortcuts on the EA
The MQL5 EA must include: IsNewBar() detection, proper CopyRates with ArraySetAsSeries, error handling on every OrderSend, spread checking, SL/TP normalization, fill policy detection, daily trade counter reset, max hold management, and comprehensive logging. Use the complete EA skeleton from the MQL5 guide as the starting point.
