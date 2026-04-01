# MT5 Skill — Compile, Test, and Read Results

You are an MT5 automation skill. Parse the user's arguments to determine which action(s) to perform.

## Arguments: $ARGUMENTS

## Paths (FIXED)

```
TERMINAL    = C:\Program Files\RoboForex MT5 Terminal\terminal64.exe
METAEDITOR  = C:\Program Files\RoboForex MT5 Terminal\MetaEditor64.exe
MQL5_DATA   = C:\Users\Windows 11\AppData\Roaming\MetaQuotes\Terminal\5FFA568149E88FCD5B44D926DCFEAA79\MQL5
EA_DIR      = ${MQL5_DATA}\Experts
TESTER_DIR  = ...\Terminal\5FFA568149E88FCD5B44D926DCFEAA79\Tester
TESTER_LOGS = ${TESTER_DIR}\logs
PROJECT     = C:\Users\Windows 11\Desktop\FXSoqqaBot
REPORTS_DIR = C:\Program Files\RoboForex MT5 Terminal\reports
```

## Helper Script

The file `mt5_tools.py` in the project root handles all MT5 automation. Use it via Python.

## Actions

### 1. COMPILE

**Trigger:** arguments contain "compile", a .mq5 filename, or no explicit action with just a filename.

Run:
```bash
python mt5_tools.py compile [EA_NAME]
```

- Default EA: `GannScalper`
- If user says "v92": `GannScalperV92`
- The script copies .mq5 from `mql5/` to EA_DIR, runs MetaEditor via PowerShell `Start-Process -Wait`, reads the UTF-16 compile.log
- Report: "0 errors, 0 warnings" = success; show errors/warnings otherwise

### 2. TEST

**Trigger:** arguments contain "test", "backtest", "run", date ranges, or parameter overrides.

Run:
```bash
python mt5_tools.py test [options...]
```

Options (passed as arguments):
- `ea=GannScalperV92` or just `v92` — which EA
- `2020.01.01 2026.03.28` — date range (from to)
- `visual` — enable visual mode
- `model=0` — tick model (0=every tick, 1=1min OHLC, 2=open prices, 4=real ticks)
- `deposit=100` — starting balance
- `from_date=2024.01.01` — explicit from date
- `to_date=2025.01.01` — explicit to date
- `optimization=2` — optimization mode (0=single, 1=slow, 2=genetic)
- `shutdown=0` — keep MT5 open after test
- Any `InpXxx=value` — EA input parameter override

Examples:
```bash
python mt5_tools.py test
python mt5_tools.py test v92 2024.01.01 2025.01.01
python mt5_tools.py test deposit=100 model=0 InpMaxDaily=10 InpMinRR=3.0
python mt5_tools.py test visual shutdown=0
```

The script generates `mt5_test.ini`, launches MT5 with `/config:`, and waits for completion.

**IMPORTANT**: The test can take 1-10 minutes depending on model and date range. Use `timeout=600000` on the Bash call.

### 3. RESULTS

**Trigger:** arguments contain "results", "report", "log", "check".

Run:
```bash
python mt5_tools.py results
```

The script:
- Reads the most recent file in `Tester/logs/` (UTF-16 encoded)
- Reads the most recent `.htm` report in the reports directory
- Extracts key metrics: Total Trades, Win Rate, Profit Factor, Expected Payoff, Drawdown, Sharpe

Present results in a clean summary to the user.

### 4. OPEN

**Trigger:** arguments contain "open", "launch", "start" without test/compile context.

```bash
python mt5_tools.py open
```

### 5. COMPILE + TEST

**Trigger:** arguments contain both "compile" and "test", or user says "compile and test".

1. First run compile: `python mt5_tools.py compile [EA]`
2. Check for 0 errors
3. If success, proceed with test: `python mt5_tools.py test [options...]`
4. If compilation failed, show errors and DO NOT run the test

## EA Input Parameters Reference

### GannScalper v9.1
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| InpMagic | int | 91100 | Magic number |
| InpRiskPct | double | 0.02 | Risk per trade |
| InpMaxSpread | double | 0.50 | Max spread ($) |
| InpMaxDaily | int | 5 | Max trades/day |
| InpMaxHold | int | 288 | Max hold (M5 bars) |
| InpMinConvScan | int | 3 | Min convergence SCANNING |
| InpMinConvBox | int | 4 | Min convergence BOX |
| InpMinRR | double | 2.0 | Min R:R ratio |
| InpWaveMult | int | 3 | TP = quant * this |
| InpTrailAtR | double | 2.0 | Trail at R multiple |

### GannScalperV92
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| InpMaxSpreadH1 | double | 0.50 | Max spread H1 ($) |
| InpMaxSpreadM15 | double | 0.30 | Max spread M15 ($) |
| InpMaxDaily | int | 5 | Max trades/day |
| InpMaxHold | int | 288 | Max hold (M5 bars) |
| InpMinConvScan | int | 3 | Min convergence SCANNING |
| InpMinConvBox | int | 4 | Min convergence BOX |
| InpMinRR | double | 2.0 | Min R:R ratio |
| InpWaveMultH1 | int | 3 | TP multiplier H1 |
| InpWaveMultM15 | int | 3 | TP multiplier M15 |
| InpTrailAtR | double | 2.0 | Trail at R multiple |
| InpEnableM15 | bool | true | Enable M15 scale |

## Usage Examples

- `/mt5 compile` — Compile GannScalper.mq5
- `/mt5 compile v92` — Compile GannScalperV92.mq5
- `/mt5 test` — Run backtest with defaults (XAUUSD M5, 2020-2026, real ticks, $20)
- `/mt5 test 2024.01.01 2024.12.31` — Test specific date range
- `/mt5 test v92 deposit=100 model=0` — Test v9.2 with $100, every tick
- `/mt5 test InpMaxDaily=10 InpMinRR=3.0` — Test with custom params
- `/mt5 test visual shutdown=0` — Visual test (keep MT5 open)
- `/mt5 compile test` — Compile then test
- `/mt5 compile test v92 2024.01.01 2025.01.01` — Compile v9.2 then test
- `/mt5 results` — Show latest test results
- `/mt5 open` — Just launch MT5

## Notes

- MetaEditor requires `PowerShell Start-Process -Wait` to block properly (it's a GUI app)
- Compile log is UTF-16 encoded
- Tester logs are UTF-16 encoded
- The .ini file uses UTF-8 (works on this system)
- MT5 terminal blocks until the test completes when using `Start-Process -Wait`
- Reports go to `C:\Program Files\RoboForex MT5 Terminal\reports\`
- Always copy .mq5 from project to EA_DIR before compiling (project is source of truth)
