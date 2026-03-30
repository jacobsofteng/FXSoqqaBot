# MQL5 EA Development Guide
## Porting from C++ Backtester to MT5 Strategy Tester — Without Breaking Everything

**Problem:** The C++ backtester processes bars sequentially with clean data and produces great results. The agent ports the logic to MQL5, compiles fine, but the EA produces garbage in MT5 Strategy Tester — wrong trades, missed entries, impossible fills, crashes, or just flat equity.

**Root cause:** MQL5 is NOT C++. It looks like C++ but has completely different execution semantics, data access patterns, and timing guarantees. This document covers every single trap.

---

## TABLE OF CONTENTS

1. [Execution Model: The #1 Difference](#1-execution-model)
2. [Bar Indexing: Everything Is Backwards](#2-bar-indexing)
3. [New Bar Detection: You Must Implement This](#3-new-bar-detection)
4. [Multi-Timeframe Data Access](#4-multi-timeframe-data)
5. [Order Execution: The 15 Ways It Fails](#5-order-execution)
6. [Strategy Tester Modes](#6-tester-modes)
7. [Spread and Slippage](#7-spread-and-slippage)
8. [Account Types: Netting vs Hedging](#8-account-types)
9. [Symbol Properties You Must Query](#9-symbol-properties)
10. [Time and Session Handling](#10-time-and-sessions)
11. [Proper EA Skeleton](#11-ea-skeleton)
12. [Porting Checklist: C++ to MQL5](#12-porting-checklist)
13. [Common Compiler Errors](#13-compiler-errors)
14. [Debugging in Strategy Tester](#14-debugging)
15. [Complete Working EA Template](#15-complete-template)

---

## 1. EXECUTION MODEL: THE #1 DIFFERENCE

### C++ Backtester (How it works)

```cpp
// C++ backtester: simple sequential loop
for (int i = 0; i < num_bars; i++) {
    Bar bar = bars[i];           // Access bar by sequential index
    check_signals(bar);          // Check entry conditions
    update_trades(bar);          // Manage open positions
}
// Every bar is processed EXACTLY ONCE in order
```

### MQL5 EA (How it ACTUALLY works)

```mql5
// MQL5: OnTick() fires on EVERY TICK, not every bar
void OnTick() {
    // This fires 5-50 times PER BAR depending on volatility
    // If you check signals here without new-bar detection,
    // you will enter 5-50 trades per bar instead of 1
    
    // Bar data is accessed with REVERSED indexing:
    // [0] = current (forming) bar — NOT COMPLETE
    // [1] = last completed bar
    // [N] = N bars ago
    
    // Multi-timeframe data might not be available yet
    // Orders can fail for 15+ different reasons
    // Spread changes tick to tick
}
```

**THIS IS WHY YOUR EA FAILS.** The C++ tester processes each bar once. The MQL5 EA processes each tick (dozens per bar). Without new-bar detection, every signal fires multiple times.

---

## 2. BAR INDEXING: EVERYTHING IS BACKWARDS

### C++ Backtester

```cpp
// C++ bars: index 0 = oldest, index N = newest (chronological)
bars[0]     // First bar in history
bars[100]   // 101st bar
bars[N-1]   // Most recent bar

// Sequential forward loop
for (int i = lookback; i < num_bars; i++) {
    double close = bars[i].close;
    double prev_close = bars[i-1].close;
}
```

### MQL5 (REVERSED)

```mql5
// MQL5 bars: index 0 = CURRENT (newest), index N = N bars ago (oldest)
// iClose(symbol, timeframe, 0)  = current bar close (STILL FORMING!)
// iClose(symbol, timeframe, 1)  = last COMPLETED bar close
// iClose(symbol, timeframe, N)  = N bars ago

// To get the same data as C++ bars[i] and bars[i-1]:
double close = iClose(_Symbol, PERIOD_M5, 1);      // Last completed bar
double prev_close = iClose(_Symbol, PERIOD_M5, 2);  // Two bars ago

// CRITICAL: NEVER use index 0 for signal generation!
// Bar[0] is STILL FORMING — its high, low, and close CHANGE with every tick.
// Using bar[0] in your C++ tester means you had future data (look-ahead bias).
// In MQL5, ALWAYS use bar[1] minimum for completed data.
```

### The CopyRates Pattern (Preferred)

```mql5
// Instead of iClose/iOpen/iHigh/iLow one by one, use CopyRates for bulk access
MqlRates rates[];
ArraySetAsSeries(rates, true);  // CRITICAL: makes [0]=newest, [1]=previous

// Copy last 200 M5 bars
int copied = CopyRates(_Symbol, PERIOD_M5, 0, 200, rates);
if (copied < 200) {
    Print("Not enough history: ", copied);
    return;  // DO NOT proceed with partial data
}

// Now: rates[0] = current forming bar
//      rates[1] = last completed bar
//      rates[199] = 199 bars ago

// For signal generation, loop starting from index 1:
for (int i = 1; i < copied; i++) {
    double close = rates[i].close;    // Completed bar
    double high = rates[i].high;
    double low = rates[i].low;
    datetime time = rates[i].time;
}
```

### CONVERSION RULE

```
C++ index i (from start)  →  MQL5 index (total_bars - 1 - i)
C++ bars[i].close         →  rates[total_copied - 1 - i].close

// Or simpler: just reverse your loop direction
// C++:   for (i = lookback; i < N; i++)
// MQL5:  for (i = N-1; i >= 1; i--)  // Stop at 1, not 0!
```

---

## 3. NEW BAR DETECTION: YOU MUST IMPLEMENT THIS

Without this, your EA fires signals on every tick (dozens per bar).

```mql5
// Global variable to track the last bar time
datetime g_lastBarTime = 0;

bool IsNewBar(ENUM_TIMEFRAMES tf = PERIOD_M5) {
    datetime currentBarTime = iTime(_Symbol, tf, 0);
    
    if (currentBarTime == 0) return false;  // Data not ready
    
    if (currentBarTime != g_lastBarTime) {
        g_lastBarTime = currentBarTime;
        return true;
    }
    return false;
}

void OnTick() {
    // ALWAYS check for new bar first
    if (!IsNewBar(PERIOD_M5)) return;
    
    // Now this code runs ONCE per M5 bar — same as C++ backtester
    ProcessBar();
}
```

**For multi-timeframe:** Track each timeframe separately.

```mql5
datetime g_lastBar_M5 = 0;
datetime g_lastBar_H1 = 0;
datetime g_lastBar_H4 = 0;
datetime g_lastBar_D1 = 0;

bool IsNewBar_M5()  { return CheckNewBar(PERIOD_M5, g_lastBar_M5); }
bool IsNewBar_H1()  { return CheckNewBar(PERIOD_H1, g_lastBar_H1); }
bool IsNewBar_H4()  { return CheckNewBar(PERIOD_H4, g_lastBar_H4); }
bool IsNewBar_D1()  { return CheckNewBar(PERIOD_D1, g_lastBar_D1); }

bool CheckNewBar(ENUM_TIMEFRAMES tf, datetime &lastTime) {
    datetime current = iTime(_Symbol, tf, 0);
    if (current == 0) return false;
    if (current != lastTime) {
        lastTime = current;
        return true;
    }
    return false;
}
```

---

## 4. MULTI-TIMEFRAME DATA ACCESS

### The Problem

In C++ backtester, you resample M1→M5→H1→H4→D1 yourself with perfect alignment. In MQL5, you call `CopyRates(_Symbol, PERIOD_H1, ...)` — but in the Strategy Tester, **higher timeframe data may not be synchronized** with the current tick.

### The Solution

```mql5
// ALWAYS check that you got enough data
MqlRates h1_rates[];
ArraySetAsSeries(h1_rates, true);

int h1_copied = CopyRates(_Symbol, PERIOD_H1, 0, 100, h1_rates);
if (h1_copied < 100) {
    Print("H1 data not ready, got: ", h1_copied);
    return;  // Wait for next tick
}

// ALWAYS check that the H1 bar is actually complete
// h1_rates[0] is the CURRENT H1 bar (still forming)
// h1_rates[1] is the last COMPLETED H1 bar
// For D1 trend, use d1_rates[1], NEVER d1_rates[0]

MqlRates d1_rates[];
ArraySetAsSeries(d1_rates, true);
int d1_copied = CopyRates(_Symbol, PERIOD_D1, 0, 30, d1_rates);
if (d1_copied < 30) return;

// D1 trend from COMPLETED bars only
double d1_close_1 = d1_rates[1].close;
double d1_close_2 = d1_rates[2].close;
bool d1_uptrend = d1_close_1 > d1_close_2;
```

### Strategy Tester: Force Data Availability

In EA properties, add multi-timeframe indicators or calls in `OnInit()` to force MT5 to load the data:

```mql5
int OnInit() {
    // Force MT5 to load higher timeframe data in Strategy Tester
    // Just accessing them once is enough
    double dummy;
    dummy = iClose(_Symbol, PERIOD_H1, 0);
    dummy = iClose(_Symbol, PERIOD_H4, 0);
    dummy = iClose(_Symbol, PERIOD_D1, 0);
    
    return INIT_SUCCEEDED;
}
```

---

## 5. ORDER EXECUTION: THE 15 WAYS IT FAILS

### C++ Backtester (Instant, Always Succeeds)

```cpp
// C++ backtester: trade always fills
if (signal == LONG) {
    open_trade(LONG, entry_price, sl, tp, lot_size);
    // Done. Always works. No errors.
}
```

### MQL5 (Can Fail for 15+ Reasons)

```mql5
bool OpenTrade(ENUM_ORDER_TYPE type, double sl, double tp, double lots) {
    MqlTradeRequest request = {};
    MqlTradeResult result = {};
    
    // === FILL EVERY FIELD. Missing fields = silent failure. ===
    request.action = TRADE_ACTION_DEAL;  // Market order
    request.symbol = _Symbol;
    request.volume = lots;
    request.type = type;
    request.deviation = 30;  // Max slippage in points (NOT pips!)
    request.magic = 123456;  // EA identifier
    request.comment = "GannScalper";
    
    // === PRICE: Must use current Ask or Bid, NOT a calculated price ===
    if (type == ORDER_TYPE_BUY) {
        request.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
    } else {
        request.price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    }
    
    // === SL/TP: Must be normalized to tick size ===
    double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    request.sl = MathRound(sl / tick_size) * tick_size;
    request.tp = MathRound(tp / tick_size) * tick_size;
    
    // === FILL POLICY: Depends on broker ===
    // RoboForex ECN typically uses IOC (Immediate Or Cancel)
    long filling = SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
    if ((filling & SYMBOL_FILLING_IOC) != 0)
        request.type_filling = ORDER_FILLING_IOC;
    else if ((filling & SYMBOL_FILLING_FOK) != 0)
        request.type_filling = ORDER_FILLING_FOK;
    else
        request.type_filling = ORDER_FILLING_RETURN;
    
    // === SEND ORDER ===
    if (!OrderSend(request, result)) {
        Print("OrderSend FAILED: ", GetLastError(), 
              " retcode=", result.retcode,
              " price=", request.price,
              " sl=", request.sl, " tp=", request.tp,
              " lots=", request.volume);
        return false;
    }
    
    // === CHECK RESULT ===
    if (result.retcode != TRADE_RETCODE_DONE && 
        result.retcode != TRADE_RETCODE_PLACED) {
        Print("Trade REJECTED: retcode=", result.retcode);
        return false;
    }
    
    Print("Trade OPENED: ticket=", result.order, 
          " price=", result.price,
          " sl=", request.sl, " tp=", request.tp);
    return true;
}
```

### Common Failure Reasons and Fixes

```
retcode 10013 (TRADE_RETCODE_INVALID_STOPS):
  → SL/TP too close to current price
  → FIX: Check minimum stop level:
    int stop_level = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
    double min_distance = stop_level * _Point;
    // SL and TP must be at least min_distance from entry price

retcode 10014 (TRADE_RETCODE_INVALID_VOLUME):
  → Lot size wrong (too small, too large, or wrong step)
  → FIX: Normalize lots:
    double min_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
    double max_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
    double lot_step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
    lots = MathMax(min_lot, MathMin(max_lot, 
           MathFloor(lots / lot_step) * lot_step));

retcode 10016 (TRADE_RETCODE_INVALID_PRICE):
  → Price not current or not normalized
  → FIX: Always use live Ask/Bid, normalize to tick_size

retcode 10019 (TRADE_RETCODE_NO_MONEY):
  → Insufficient margin
  → FIX: Check margin before trading:
    double margin_required;
    if (!OrderCalcMargin(type, _Symbol, lots, price, margin_required))
        return false;
    if (margin_required > AccountInfoDouble(ACCOUNT_MARGIN_FREE))
        return false;

retcode 10006 (TRADE_RETCODE_REJECT):
  → Broker rejected (spread too wide, market closed, etc.)
  → FIX: Check spread and market hours before sending

retcode 10004 (TRADE_RETCODE_REQUOTE):
  → Price changed during execution
  → FIX: Increase deviation, or retry with new price
```

---

## 6. STRATEGY TESTER MODES

### Every Tick (Most Accurate, Slowest)

```
OnTick() fires on every simulated tick.
Ticks are generated from M1 OHLC data.
Use this mode for final validation.

WARNING: Even "Every Tick" generates SYNTHETIC ticks from M1 data.
Real tick data requires "Every Tick Based on Real Ticks" mode
and downloading tick data first (Settings → Tick data).
```

### 1 Minute OHLC (Good Balance)

```
OnTick() fires 4 times per M1 bar (Open, High, Low, Close).
Much faster than Every Tick.
Good for development iteration.

WARNING: If your entry logic depends on intra-bar price movement,
results will differ from Every Tick mode.
```

### Open Prices Only (Fastest, Least Accurate)

```
OnTick() fires ONCE per bar at the Open price.
Fastest mode — use for parameter optimization.

CRITICAL: Your EA must ONLY use completed bar data (index >= 1).
If you read bar[0].close, it equals bar[0].open in this mode.
SL/TP may not trigger correctly within bars.

This mode is ONLY valid if your EA:
1. Uses IsNewBar() pattern (processes once per bar)
2. Reads only completed bars (index >= 1)
3. Uses market orders (not limit orders that need intra-bar fills)
```

### Recommended Workflow

```
1. Develop with "1 Minute OHLC" (fast iteration)
2. Validate with "Every Tick Based on Real Ticks" (accuracy)
3. Optimize parameters with "Open Prices Only" (speed)
4. Final check with "Every Tick Based on Real Ticks" again
```

### Data Quality

```mql5
// In OnInit(), check data quality
int OnInit() {
    // Ensure we have enough history
    int bars_m5 = Bars(_Symbol, PERIOD_M5);
    int bars_h1 = Bars(_Symbol, PERIOD_H1);
    int bars_d1 = Bars(_Symbol, PERIOD_D1);
    
    Print("Available bars: M5=", bars_m5, " H1=", bars_h1, " D1=", bars_d1);
    
    if (bars_m5 < 1000 || bars_h1 < 200 || bars_d1 < 30) {
        Print("ERROR: Insufficient history data!");
        return INIT_FAILED;
    }
    
    return INIT_SUCCEEDED;
}
```

---

## 7. SPREAD AND SLIPPAGE

### C++ Backtester

```cpp
// C++ backtester typically uses a fixed spread
double spread = 0.30;  // Fixed $0.30

double entry_price = bar.close;
double actual_entry = entry_price + spread / 2;  // Simple adjustment
```

### MQL5 (Spread Is Variable)

```mql5
// Spread changes every tick!
double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
double spread_points = ask - bid;  // In price terms, NOT points

// For Gold (XAUUSD), spread is in dollars
// Typical: $0.15 - $0.50 during active hours
// Can spike to $2-5 during news/low liquidity

// CRITICAL: Check spread before entering
double max_spread = 0.50;  // $0.50 max acceptable spread
if (spread_points > max_spread) {
    Print("Spread too wide: $", spread_points);
    return;  // Skip this entry
}

// When opening BUY: you pay ASK (higher)
// When opening SELL: you pay BID (lower)
// Your SL/TP are checked against BID (for buys) or ASK (for sells)

// SL for BUY is triggered when BID <= SL (not when ASK <= SL)
// SL for SELL is triggered when ASK >= SL (not when BID >= SL)
// This means your EFFECTIVE SL includes the spread!
```

### Matching C++ Spread Model

```mql5
// To match your C++ tester's fixed spread model:
input double InpMaxSpread = 0.50;  // Max spread to trade

bool IsSpreadAcceptable() {
    double spread = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - 
                    SymbolInfoDouble(_Symbol, SYMBOL_BID);
    return spread <= InpMaxSpread;
}
```

---

## 8. ACCOUNT TYPES: NETTING VS HEDGING

### RoboForex ECN

RoboForex offers BOTH netting and hedging accounts. Check which one you have.

```mql5
// Check account type in OnInit()
ENUM_ACCOUNT_MARGIN_MODE mode = 
    (ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE);

if (mode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING) {
    Print("Hedging account - can have multiple positions per symbol");
} else if (mode == ACCOUNT_MARGIN_MODE_EXCHANGE || 
           mode == ACCOUNT_MARGIN_MODE_RETAIL_NETTING) {
    Print("Netting account - only ONE position per symbol");
}
```

### Netting Account (ONE Position Per Symbol)

```mql5
// If you open BUY 0.01, then open BUY 0.01 again,
// you DON'T get 2 positions. You get 1 position of 0.02.
// If you open SELL 0.01 while holding BUY 0.01,
// the BUY is CLOSED (net to 0), not a new position.

// To close a position on netting account:
// Open an opposite order of the same volume
void ClosePosition() {
    if (!PositionSelect(_Symbol)) return;
    
    double volume = PositionGetDouble(POSITION_VOLUME);
    ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
    
    MqlTradeRequest request = {};
    MqlTradeResult result = {};
    
    request.action = TRADE_ACTION_DEAL;
    request.symbol = _Symbol;
    request.volume = volume;
    request.deviation = 30;
    request.magic = 123456;
    
    if (type == POSITION_TYPE_BUY) {
        request.type = ORDER_TYPE_SELL;
        request.price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    } else {
        request.type = ORDER_TYPE_BUY;
        request.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
    }
    
    // Fill policy
    request.type_filling = ORDER_FILLING_IOC;
    
    OrderSend(request, result);
}
```

### Hedging Account (Multiple Positions)

```mql5
// Close a specific position by ticket
void ClosePositionByTicket(ulong ticket) {
    MqlTradeRequest request = {};
    MqlTradeResult result = {};
    
    request.action = TRADE_ACTION_DEAL;
    request.position = ticket;  // CRITICAL: specify the ticket
    request.symbol = _Symbol;
    
    if (!PositionSelectByTicket(ticket)) return;
    
    double volume = PositionGetDouble(POSITION_VOLUME);
    ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
    
    request.volume = volume;
    request.deviation = 30;
    request.magic = 123456;
    
    if (type == POSITION_TYPE_BUY) {
        request.type = ORDER_TYPE_SELL;
        request.price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    } else {
        request.type = ORDER_TYPE_BUY;
        request.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
    }
    
    request.type_filling = ORDER_FILLING_IOC;
    OrderSend(request, result);
}
```

---

## 9. SYMBOL PROPERTIES YOU MUST QUERY

Never hardcode these. They differ between brokers and can change.

```mql5
void PrintSymbolInfo() {
    Print("=== Symbol Properties for ", _Symbol, " ===");
    Print("Point: ", _Point);  // Minimum price change (e.g., 0.01 for Gold)
    Print("Digits: ", _Digits);  // Decimal places (e.g., 2 for Gold)
    Print("Tick Size: ", SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE));
    Print("Tick Value: ", SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE));
    Print("Min Lot: ", SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN));
    Print("Max Lot: ", SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX));
    Print("Lot Step: ", SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP));
    Print("Contract Size: ", SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE));
    Print("Stop Level: ", SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL), " points");
    Print("Freeze Level: ", SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL), " points");
    Print("Spread: ", SymbolInfoInteger(_Symbol, SYMBOL_SPREAD), " points");
    Print("Swap Long: ", SymbolInfoDouble(_Symbol, SYMBOL_SWAP_LONG));
    Print("Swap Short: ", SymbolInfoDouble(_Symbol, SYMBOL_SWAP_SHORT));
}

// For Gold on RoboForex ECN typically:
// Point = 0.01
// Digits = 2
// Tick Size = 0.01
// Min Lot = 0.01
// Lot Step = 0.01
// Contract Size = 100 (100 oz per lot)
// Stop Level = 0 or 10 points (varies)
```

### Normalizing Prices

```mql5
// ALWAYS normalize prices before using in orders
double NormalizePrice(double price) {
    double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    if (tick == 0) return NormalizeDouble(price, _Digits);
    return NormalizeDouble(MathRound(price / tick) * tick, _Digits);
}

// ALWAYS normalize lot size
double NormalizeLots(double lots) {
    double min_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
    double max_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
    double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
    
    lots = MathFloor(lots / step) * step;  // Round DOWN to step
    lots = MathMax(min_lot, MathMin(max_lot, lots));
    return NormalizeDouble(lots, 2);
}
```

---

## 10. TIME AND SESSION HANDLING

### Time Zones in MT5

```mql5
// MT5 server time is BROKER-DEPENDENT
// RoboForex uses UTC+2 (or UTC+3 during DST)
// This is NOT UTC!

datetime server_time = TimeCurrent();         // Broker server time
datetime local_time = TimeLocal();            // Your PC time
datetime gmt_time = TimeGMT();               // UTC/GMT time

// For consistent time calculations, ALWAYS convert to UTC
// Or use bar timestamps which are in server time

// CRITICAL: When your C++ tester uses UTC timestamps,
// and your EA uses server time, all time comparisons will be off by 2-3 hours!
```

### Checking Market Hours

```mql5
bool IsMarketOpen() {
    MqlDateTime dt;
    TimeCurrent(dt);
    
    // Gold trades nearly 24h but has a 1h break
    // Typically closed: 22:00-23:00 server time (varies by broker)
    // Also closed on weekends
    
    if (dt.day_of_week == 0 || dt.day_of_week == 6) return false;  // Weekend
    
    // Check if trading is allowed right now
    return SymbolInfoInteger(_Symbol, SYMBOL_TRADE_MODE) == SYMBOL_TRADE_MODE_FULL;
}
```

### Session Start Detection (for intraday windows)

```mql5
// Find today's session extremum (high/low of first N bars)
double GetSessionExtremumHigh(int first_n_bars = 12) {
    // 12 M5 bars = first hour of trading
    MqlRates rates[];
    ArraySetAsSeries(rates, true);
    
    // Get today's bars
    datetime today_start = iTime(_Symbol, PERIOD_D1, 0);
    int bars_today = Bars(_Symbol, PERIOD_M5, today_start, TimeCurrent());
    
    if (bars_today < first_n_bars) first_n_bars = bars_today;
    
    CopyRates(_Symbol, PERIOD_M5, 0, bars_today, rates);
    
    double high = 0;
    // Start from the earliest bar today, take first N
    for (int i = bars_today - 1; i >= MathMax(0, bars_today - first_n_bars); i--) {
        if (rates[i].high > high) high = rates[i].high;
    }
    return high;
}
```

---

## 11. PROPER EA SKELETON

```mql5
//+------------------------------------------------------------------+
//| EA Skeleton — Correct Structure                                    |
//+------------------------------------------------------------------+
#property copyright "FXSoqqaBot"
#property version   "9.10"
#property strict

// === INPUT PARAMETERS ===
input int    InpMagic       = 123456;     // Magic number
input double InpRiskPct     = 0.02;       // Risk per trade (2%)
input double InpMaxSpread   = 0.50;       // Max spread ($)
input int    InpMaxDaily    = 5;          // Max trades per day
input int    InpMaxHold     = 288;        // Max hold (M5 bars)

// === GLOBAL STATE ===
datetime g_lastBar_M5 = 0;
datetime g_lastBar_H1 = 0;
datetime g_lastBar_D1 = 0;
int      g_dailyTrades = 0;
datetime g_lastTradeDay = 0;

//+------------------------------------------------------------------+
int OnInit() {
    // Validate symbol
    if (_Symbol != "XAUUSD" && _Symbol != "XAUUSDm" && _Symbol != "GOLD") {
        Print("WARNING: EA designed for XAUUSD, running on ", _Symbol);
    }
    
    // Print symbol info for debugging
    PrintSymbolInfo();
    
    // Force load multi-timeframe data
    double d;
    d = iClose(_Symbol, PERIOD_H1, 0);
    d = iClose(_Symbol, PERIOD_H4, 0);
    d = iClose(_Symbol, PERIOD_D1, 0);
    
    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
    Print("EA stopped. Reason: ", reason);
}

//+------------------------------------------------------------------+
void OnTick() {
    // === STEP 1: New bar detection ===
    if (!IsNewBar_M5()) return;
    
    // === STEP 2: Reset daily counter ===
    ResetDailyCounter();
    
    // === STEP 3: Check prerequisites ===
    if (!IsMarketOpen()) return;
    if (!IsSpreadAcceptable()) return;
    
    // === STEP 4: Load data ===
    MqlRates m5[], h1[], d1[];
    if (!LoadData(m5, h1, d1)) return;
    
    // === STEP 5: Manage open positions ===
    ManagePositions(m5);
    
    // === STEP 6: Check for new entries ===
    if (g_dailyTrades >= InpMaxDaily) return;
    if (HasOpenPosition()) return;
    
    // === STEP 7: Generate signals ===
    int signal = GenerateSignal(m5, h1, d1);
    
    // === STEP 8: Execute trade ===
    if (signal != 0) {
        ExecuteTrade(signal, m5, h1);
    }
}

//+------------------------------------------------------------------+
bool IsNewBar_M5() {
    datetime t = iTime(_Symbol, PERIOD_M5, 0);
    if (t == 0) return false;
    if (t != g_lastBar_M5) { g_lastBar_M5 = t; return true; }
    return false;
}

//+------------------------------------------------------------------+
void ResetDailyCounter() {
    datetime today = iTime(_Symbol, PERIOD_D1, 0);
    if (today != g_lastTradeDay) {
        g_lastTradeDay = today;
        g_dailyTrades = 0;
    }
}

//+------------------------------------------------------------------+
bool LoadData(MqlRates &m5[], MqlRates &h1[], MqlRates &d1[]) {
    ArraySetAsSeries(m5, true);
    ArraySetAsSeries(h1, true);
    ArraySetAsSeries(d1, true);
    
    int m5_count = CopyRates(_Symbol, PERIOD_M5, 0, 500, m5);
    int h1_count = CopyRates(_Symbol, PERIOD_H1, 0, 200, h1);
    int d1_count = CopyRates(_Symbol, PERIOD_D1, 0, 60, d1);
    
    if (m5_count < 300 || h1_count < 50 || d1_count < 20) {
        Print("Insufficient data: M5=", m5_count, " H1=", h1_count, " D1=", d1_count);
        return false;
    }
    return true;
}

//+------------------------------------------------------------------+
bool HasOpenPosition() {
    for (int i = 0; i < PositionsTotal(); i++) {
        if (PositionGetSymbol(i) == _Symbol) {
            if (PositionGetInteger(POSITION_MAGIC) == InpMagic) {
                return true;
            }
        }
    }
    return false;
}

//+------------------------------------------------------------------+
// ManagePositions: Check max hold, fold detection, etc.
void ManagePositions(const MqlRates &m5[]) {
    for (int i = PositionsTotal() - 1; i >= 0; i--) {
        if (PositionGetSymbol(i) != _Symbol) continue;
        if (PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
        
        ulong ticket = PositionGetInteger(POSITION_TICKET);
        datetime open_time = (datetime)PositionGetInteger(POSITION_TIME);
        
        // Max hold check
        int bars_held = Bars(_Symbol, PERIOD_M5, open_time, TimeCurrent());
        if (bars_held >= InpMaxHold) {
            Print("Max hold reached (", bars_held, " bars). Closing ticket ", ticket);
            ClosePositionByTicket(ticket);
        }
    }
}

//+------------------------------------------------------------------+
int GenerateSignal(const MqlRates &m5[], const MqlRates &h1[], 
                   const MqlRates &d1[]) {
    // YOUR GANN STRATEGY LOGIC HERE
    // Use m5[1] for last completed M5 bar (NOT m5[0]!)
    // Use h1[1] for last completed H1 bar
    // Use d1[1] for last completed D1 bar
    //
    // Return: +1 for BUY, -1 for SELL, 0 for no signal
    
    return 0;  // Placeholder
}

//+------------------------------------------------------------------+
void ExecuteTrade(int signal, const MqlRates &m5[], const MqlRates &h1[]) {
    ENUM_ORDER_TYPE type = (signal > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
    
    // Calculate SL and TP from your Gann system
    double entry = (type == ORDER_TYPE_BUY) ? 
                   SymbolInfoDouble(_Symbol, SYMBOL_ASK) :
                   SymbolInfoDouble(_Symbol, SYMBOL_BID);
    
    // PLACEHOLDER: Replace with your triangle-based SL/TP
    double atr = CalculateATR(m5, 14);
    double sl_distance = atr * 2.0;
    double tp_distance = sl_distance * 4.0;
    
    double sl, tp;
    if (type == ORDER_TYPE_BUY) {
        sl = NormalizePrice(entry - sl_distance);
        tp = NormalizePrice(entry + tp_distance);
    } else {
        sl = NormalizePrice(entry + sl_distance);
        tp = NormalizePrice(entry - tp_distance);
    }
    
    // Validate SL/TP distance
    int stop_level = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
    double min_dist = stop_level * _Point;
    if (MathAbs(entry - sl) < min_dist || MathAbs(tp - entry) < min_dist) {
        Print("SL/TP too close. min_dist=", min_dist);
        return;
    }
    
    // Calculate position size
    double lots = CalculateLots(sl_distance);
    
    if (OpenTrade(type, sl, tp, lots)) {
        g_dailyTrades++;
    }
}

//+------------------------------------------------------------------+
double CalculateATR(const MqlRates &rates[], int period) {
    double sum = 0;
    for (int i = 1; i <= period; i++) {
        double tr = MathMax(rates[i].high - rates[i].low,
                   MathMax(MathAbs(rates[i].high - rates[i+1].close),
                           MathAbs(rates[i].low - rates[i+1].close)));
        sum += tr;
    }
    return sum / period;
}

//+------------------------------------------------------------------+
double CalculateLots(double sl_distance) {
    double balance = AccountInfoDouble(ACCOUNT_BALANCE);
    double risk = balance * InpRiskPct;
    
    // For Gold: 1 lot = 100 oz, $1 move = $100 per lot
    double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
    double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    
    if (tick_size == 0 || tick_value == 0) return 0.01;
    
    double value_per_lot_per_dollar = tick_value / tick_size;
    double lots = risk / (sl_distance * value_per_lot_per_dollar);
    
    return NormalizeLots(lots);
}
```

---

## 12. PORTING CHECKLIST: C++ TO MQL5

Use this checklist every time you port logic from the C++ backtester:

```
□ 1. Bar indexing reversed
     C++: bars[i] (oldest=0)  →  MQL5: rates[N-1-i] or use ArraySetAsSeries
     
□ 2. New bar detection added
     C++: loop processes each bar once  →  MQL5: OnTick + IsNewBar()
     
□ 3. Bar[0] never used for signals
     C++: bars[current] is complete  →  MQL5: rates[0] is FORMING, use rates[1]
     
□ 4. All prices normalized
     NormalizePrice() before every OrderSend
     NormalizeLots() before every OrderSend
     
□ 5. Fill policy set correctly
     Query SYMBOL_FILLING_MODE, use IOC/FOK/RETURN
     
□ 6. Spread checked before entry
     Variable spread in MQL5, not fixed like C++
     
□ 7. SL/TP validated against stop level
     SymbolInfoInteger(SYMBOL_TRADE_STOPS_LEVEL)
     
□ 8. Multi-timeframe data loaded and verified
     CopyRates returns actual count, check it
     
□ 9. Magic number set on all orders
     Filter positions by magic in ManagePositions
     
□ 10. Error handling on every OrderSend
      Log retcode, GetLastError(), all request fields
      
□ 11. Account type checked (netting vs hedging)
      Closing logic differs completely
      
□ 12. Time zone aligned
      C++ uses UTC?  MT5 uses broker time (UTC+2/3)
      
□ 13. Max hold uses Bars() count, not bar index subtraction
      Bar indices reset, use time-based counting
      
□ 14. Daily trade counter resets on new D1 bar
      Not on midnight UTC (unless broker is UTC)
      
□ 15. Strategy Tester mode matches assumptions
      "Open Prices Only" = bar[0].close equals bar[0].open
```

---

## 13. COMMON COMPILER ERRORS

```
// ERROR: 'ArraySetAsSeries' - wrong parameters count
// FIX: Must be called BEFORE CopyRates, not after
MqlRates rates[];
ArraySetAsSeries(rates, true);  // FIRST
CopyRates(_Symbol, PERIOD_M5, 0, 100, rates);  // THEN

// ERROR: 'OrderSend' - function not found
// FIX: You're mixing MQL4 and MQL5 syntax
// MQL4: OrderSend(symbol, type, lots, price, slippage, sl, tp)
// MQL5: Uses MqlTradeRequest/MqlTradeResult structures

// ERROR: 'implicit conversion from number to string'
// FIX: MQL5 doesn't auto-convert. Use explicit:
Print("Value: " + DoubleToString(price, _Digits));
// Or use comma syntax:
Print("Value: ", price);

// ERROR: constant expression required for array size
// FIX: MQL5 allows dynamic arrays, but NOT as function-local fixed arrays
// BAD:  double arr[variable_size];
// GOOD: double arr[];  ArrayResize(arr, variable_size);

// ERROR: 'struct' has no member named 'xxx'
// FIX: MqlRates uses .time, .open, .high, .low, .close, .tick_volume, .spread
// NOT: .volume (use .tick_volume or .real_volume)
```

---

## 14. DEBUGGING IN STRATEGY TESTER

```mql5
// === ALWAYS add comprehensive logging ===

// In OnInit:
Print("=== EA Started ===");
Print("Account: ", AccountInfoString(ACCOUNT_COMPANY));
Print("Balance: ", AccountInfoDouble(ACCOUNT_BALANCE));
Print("Leverage: 1:", AccountInfoInteger(ACCOUNT_LEVERAGE));
PrintSymbolInfo();

// In signal generation:
#ifdef _DEBUG
Print("Bar ", TimeToString(m5[1].time), 
      " O=", m5[1].open, " H=", m5[1].high,
      " L=", m5[1].low, " C=", m5[1].close);
Print("D1 direction: ", (d1_uptrend ? "UP" : "DOWN"));
Print("Convergence score: ", score);
#endif

// Use the Visual Mode in Strategy Tester
// It shows the chart with trade arrows
// Enable "Journal" tab to see Print() output

// To conditionally compile debug logging:
// #define _DEBUG at the top of the file
// Remove it for production (avoids log spam)
```

### Visual Mode Tips

```
1. In Strategy Tester, check "Visual mode"
2. Slow down the playback speed
3. Watch for:
   - Are entries happening at the right bars?
   - Is SL/TP being placed correctly?
   - Are trades being closed at max hold?
   - Is the daily counter resetting?
4. Check the "Results" tab for trade-by-trade breakdown
5. Check the "Graph" tab for equity curve
6. Export results to compare with C++ backtester output
```

---

## 15. COMPLETE WORKING EA TEMPLATE

The full working GannScalper.mq5 skeleton is in Section 11 above. To implement the v9.1 triangle strategy:

### What Goes in GenerateSignal()

```mql5
int GenerateSignal(const MqlRates &m5[], const MqlRates &h1[], 
                   const MqlRates &d1[]) {
    // 1. Compute D1 direction from d1[1], d1[2], d1[3]
    //    (swings from completed D1 bars)
    
    // 2. Compute H1 wave count from h1[1..N]
    //    (last 50-100 completed H1 bars)
    
    // 3. Score convergence at m5[1].close
    //    (7 independent categories)
    
    // 4. If convergence >= 4 AND no active box:
    //    → Start quant measurement (set state)
    //    → Return 0 (no trade yet)
    
    // 5. If active box exists:
    //    → Check which zone we're in
    //    → If Green Zone + all directions agree:
    //      → Calculate diagonal bounds at current bar
    //      → Determine entry, SL (opposite diagonal), TP (quant multiple)
    //      → Return +1 or -1
    
    // 6. Otherwise return 0
    
    return 0;
}
```

### State Management Between Ticks

```mql5
// MQL5 EAs persist state in global variables between OnTick() calls
// Use global variables for strategy state:

enum ENUM_STRATEGY_STATE {
    STATE_SCANNING,
    STATE_QUANT_FORMING,
    STATE_BOX_ACTIVE,
    STATE_IN_TRADE
};

ENUM_STRATEGY_STATE g_state = STATE_SCANNING;

// Box state
double g_box_top = 0, g_box_bottom = 0;
int    g_box_start_bar = 0, g_box_end_bar = 0;
double g_quant_pips = 0;
int    g_quant_bars = 0;
int    g_convergence_bar = 0;

// These persist across OnTick() calls automatically
// They reset when the EA is restarted
```

---

## FINAL NOTES

### The #1 Rule

**Your EA must produce the SAME trade sequence as your C++ backtester on the same data.** If it doesn't, there's a bug in the port, NOT a "difference between testers."

To verify:
1. Run C++ backtester on 2024 data, export trade list (entry time, price, direction, SL, TP)
2. Run EA in MT5 Strategy Tester on same 2024 data with "Every Tick" mode
3. Compare trade lists — they should match within spread/slippage tolerance
4. Any mismatch = a porting bug to find and fix

### Common Reasons for Mismatch

```
1. Bar[0] used instead of bar[1] → look-ahead bias in C++ not in MQL5
2. Missing IsNewBar() → multiple entries per bar in MQL5
3. Time zone offset → entries shifted by 2-3 hours
4. Fixed vs variable spread → different entries near spread-sensitive levels
5. SL/TP normalization → orders rejected that C++ assumed would fill
6. Netting account → second trade closes first instead of adding
7. H1/D1 bar not yet complete → different trend reading
8. Integer division in C++ vs double in MQL5 → rounding differences
```

Fix each one systematically. When the trade lists match, you're done.
