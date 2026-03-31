//+------------------------------------------------------------------+
//| GannScalper.mq5 — v9.1c Calibrated Triangle-First Gann EA       |
//| FXSoqqaBot — XAUUSD on RoboForex ECN 1:500                       |
//| Calibrated 2026-03-31 on 17yr data (2009-2026)                    |
//+------------------------------------------------------------------+
#property copyright "FXSoqqaBot"
#property version   "9.11"
#property strict

//+------------------------------------------------------------------+
//| INPUT PARAMETERS (v9.1 Calibrated)                                |
//+------------------------------------------------------------------+
input int    InpMagic       = 91100;      // Magic number
input double InpRiskPct     = 0.02;       // Risk per trade (2%)
input double InpMaxSpread   = 0.50;       // Max spread ($)
input int    InpMaxDaily    = 5;          // Max trades per day
input int    InpMaxHold     = 288;        // Max hold (M5 bars)
input int    InpMinConvScan = 3;          // Min convergence SCANNING (3 of 6)
input int    InpMinConvBox  = 4;          // Min convergence BOX_ACTIVE (4 of 7)
input double InpMinRR       = 2.0;        // Min R:R ratio
input int    InpWaveMult    = 3;          // TP = quant * this
input double InpTrailAtR    = 2.0;        // Trail SL to breakeven at this R multiple

//+------------------------------------------------------------------+
//| GANN CONSTANTS (DO NOT CHANGE)                                    |
//+------------------------------------------------------------------+
#define V_BASE         72
#define V_QUANTUM      12
#define V_GROWTH       18
#define V_CORRECTION   24
#define LOST_MOTION    3.0
#define OVERRIDE_MULT  4
#define PRICE_PER_H4   6.0    // Gold natural rate for price-time squaring

const int NATURAL_SQ[] = {4, 9, 16, 24, 36, 49, 72, 81};
const double NAT_SQ_STR[] = {0.23, 0.28, 0.15, 0.10, 0.08, 0.05, 0.04, 0.03};
const int POWER_ANGLES[] = {30, 45};
const int IMPULSE_RATIOS[] = {8, 16, 64};

//+------------------------------------------------------------------+
//| STATE MACHINE                                                     |
//+------------------------------------------------------------------+
enum EState { STATE_SCANNING, STATE_QUANT, STATE_BOX, STATE_TRADE };
EState g_state = STATE_SCANNING;

//+------------------------------------------------------------------+
//| GLOBAL STATE                                                      |
//+------------------------------------------------------------------+
datetime g_lastBar_M5 = 0;
int      g_dailyTrades = 0;
datetime g_lastTradeDay = 0;

int      g_convBar = 0;
double   g_convPrice = 0;
int      g_m5_count = 0;
string   g_d1_direction = "flat";

// Active box
struct GannBox {
   double top, bottom, height, scale, midpoint;
   int    start_bar, end_bar, width, green_start;
   double quant_pips;
   int    quant_bars;
   string direction;
   double touch_price, extreme_price;
   bool   active;
};
GannBox g_box;

// Swing storage — bar_index is GLOBAL M5 counter (g_m5_count based)
struct SwingPoint {
   string type;
   double price;
   datetime time;
   int    bar_index;  // Global M5 bar index
   double atr;
};
SwingPoint g_swings_h1[];
SwingPoint g_swings_h4[];
SwingPoint g_swings_d1[];

// Wave state
struct WaveState {
   int    wave_number;
   double wave_0_price, wave_0_size;
   string direction;
   double targets[];
   bool   is_trending, valid;
};
WaveState g_wave;

// Trailing stop tracking
double g_trade_entry_price = 0;
double g_trade_sl_distance = 0;
bool   g_trailed_to_be = false;

//+------------------------------------------------------------------+
//| HELPER: Normalize price/lots                                      |
//+------------------------------------------------------------------+
double NormalizePrice(double price) {
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick == 0) return NormalizeDouble(price, _Digits);
   return NormalizeDouble(MathRound(price / tick) * tick, _Digits);
}

double NormalizeLots(double lots) {
   double min_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step == 0) step = 0.01;
   lots = MathFloor(lots / step) * step;
   return NormalizeDouble(MathMax(min_lot, MathMin(max_lot, lots)), 2);
}

//+------------------------------------------------------------------+
//| HELPER: IsNewBar for M5                                           |
//+------------------------------------------------------------------+
bool IsNewBar_M5() {
   datetime t = iTime(_Symbol, PERIOD_M5, 0);
   if(t == 0) return false;
   if(t != g_lastBar_M5) { g_lastBar_M5 = t; return true; }
   return false;
}

bool IsSpreadAcceptable() {
   return (SymbolInfoDouble(_Symbol, SYMBOL_ASK) -
           SymbolInfoDouble(_Symbol, SYMBOL_BID)) <= InpMaxSpread;
}

//+------------------------------------------------------------------+
//| HELPER: Position management                                       |
//+------------------------------------------------------------------+
bool HasOpenPosition() {
   for(int i = 0; i < PositionsTotal(); i++) {
      if(PositionGetSymbol(i) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return true;
   }
   return false;
}

ulong GetPositionTicket() {
   for(int i = 0; i < PositionsTotal(); i++) {
      if(PositionGetSymbol(i) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return PositionGetInteger(POSITION_TICKET);
   }
   return 0;
}

void ClosePositionByTicket(ulong ticket) {
   MqlTradeRequest request = {};
   MqlTradeResult result = {};

   if(!PositionSelectByTicket(ticket)) return;

   double volume = PositionGetDouble(POSITION_VOLUME);
   ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

   request.action = TRADE_ACTION_DEAL;
   request.position = ticket;
   request.symbol = _Symbol;
   request.volume = volume;
   request.deviation = 30;
   request.magic = InpMagic;

   if(type == POSITION_TYPE_BUY) {
      request.type = ORDER_TYPE_SELL;
      request.price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   } else {
      request.type = ORDER_TYPE_BUY;
      request.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   }

   long filling = SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_IOC) != 0)
      request.type_filling = ORDER_FILLING_IOC;
   else if((filling & SYMBOL_FILLING_FOK) != 0)
      request.type_filling = ORDER_FILLING_FOK;
   else
      request.type_filling = ORDER_FILLING_RETURN;

   if(!OrderSend(request, result))
      Print("Close FAILED: ", GetLastError(), " retcode=", result.retcode);
   else
      Print("Position closed: ticket=", ticket, " price=", result.price);
}

//+------------------------------------------------------------------+
//| Modify SL on existing position (for trailing stop)                |
//+------------------------------------------------------------------+
bool ModifySL(ulong ticket, double new_sl) {
   MqlTradeRequest request = {};
   MqlTradeResult result = {};

   if(!PositionSelectByTicket(ticket)) return false;

   request.action = TRADE_ACTION_SLTP;
   request.position = ticket;
   request.symbol = _Symbol;
   request.sl = NormalizePrice(new_sl);
   request.tp = PositionGetDouble(POSITION_TP);

   if(!OrderSend(request, result)) {
      Print("ModifySL FAILED: ", GetLastError());
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| SQ9 ENGINE                                                        |
//+------------------------------------------------------------------+
double PriceToSq9Degree(double price) {
   if(price <= 0) return 0;
   double deg = MathMod(MathSqrt(price) * 180.0 - 225.0, 360.0);
   if(deg < 0) deg += 360.0;
   return deg;
}

void Sq9LevelsFromPrice(double price, double &levels[], int &count) {
   count = 0;
   ArrayResize(levels, 20);
   double ref_sqrt = MathSqrt(price);

   for(int a = 0; a < 2; a++) {
      double step_val = POWER_ANGLES[a] / 180.0;
      for(int ring = -3; ring <= 3; ring++) {
         if(ring == 0) continue;
         double target_sqrt = ref_sqrt + step_val * ring;
         if(target_sqrt > 0) {
            double level = target_sqrt * target_sqrt;
            if(MathAbs(level - price) <= price * 0.15 && count < 20) {
               levels[count++] = level;
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| SWING DETECTION on CopyRates data                                 |
//| Converts reversed CopyRates indices to global M5 bar count        |
//+------------------------------------------------------------------+
void DetectSwings(const MqlRates &rates[], int n_bars, int tf_m5_factor,
                  SwingPoint &swings[], int atr_period = 14,
                  double atr_mult = 1.5) {
   ArrayResize(swings, 0);
   if(n_bars < atr_period + 2) return;

   // rates[0]=newest, rates[n-1]=oldest. Process oldest→newest.
   string direction = "";
   double last_high = rates[n_bars - 1].high;
   int last_high_idx = n_bars - 1;
   double last_low = rates[n_bars - 1].low;
   int last_low_idx = n_bars - 1;

   for(int i = n_bars - 1 - atr_period; i >= 1; i--) {
      // ATR at this bar
      double atr_sum = 0;
      for(int j = i; j < i + atr_period && j < n_bars - 1; j++) {
         double tr = MathMax(rates[j].high - rates[j].low,
                    MathMax(MathAbs(rates[j].high - rates[j+1].close),
                            MathAbs(rates[j].low - rates[j+1].close)));
         atr_sum += tr;
      }
      double atr = atr_sum / atr_period;
      double threshold = atr * atr_mult;

      if(rates[i].high > last_high) { last_high = rates[i].high; last_high_idx = i; }
      if(rates[i].low < last_low)   { last_low = rates[i].low; last_low_idx = i; }

      if(direction != "down" && last_high - rates[i].low > threshold) {
         int sz = ArraySize(swings);
         ArrayResize(swings, sz + 1);
         swings[sz].type = "high";
         swings[sz].price = last_high;
         swings[sz].time = rates[last_high_idx].time;
         // Convert reversed index to global M5 count
         swings[sz].bar_index = g_m5_count - last_high_idx * tf_m5_factor;
         swings[sz].atr = atr;
         direction = "down";
         last_low = rates[i].low;
         last_low_idx = i;
      }
      else if(direction != "up" && rates[i].high - last_low > threshold) {
         int sz = ArraySize(swings);
         ArrayResize(swings, sz + 1);
         swings[sz].type = "low";
         swings[sz].price = last_low;
         swings[sz].time = rates[last_low_idx].time;
         swings[sz].bar_index = g_m5_count - last_low_idx * tf_m5_factor;
         swings[sz].atr = atr;
         direction = "up";
         last_high = rates[i].high;
         last_high_idx = i;
      }
   }
}

//+------------------------------------------------------------------+
//| CONVERGENCE: 7 categories, phase-dependent threshold              |
//+------------------------------------------------------------------+
int ScoreConvergence(double price, int bar_idx,
                     const SwingPoint &sh1[], int nh1,
                     const SwingPoint &sh4[], int nh4,
                     bool in_box_phase) {
   if(nh1 < 2) return 0;

   int score = 0;
   int rs = MathMax(0, nh1 - 5);

   // A: Sq9 level
   bool catA = false;
   for(int s = rs; s < nh1 && !catA; s++) {
      double levels[]; int count;
      Sq9LevelsFromPrice(sh1[s].price, levels, count);
      for(int j = 0; j < count; j++) {
         if(MathAbs(price - levels[j]) <= LOST_MOTION) { catA = true; break; }
      }
   }
   if(catA) score++;

   // B: Vibration level
   bool catB = false;
   for(int s = rs; s < nh1 && !catB; s++) {
      double rem = MathMod(MathAbs(price - sh1[s].price), (double)V_QUANTUM);
      if(rem <= LOST_MOTION || (V_QUANTUM - rem) <= LOST_MOTION) catB = true;
   }
   if(catB) score++;

   // C: Proportional division
   bool catC = false;
   for(int i = rs; i < nh1 - 1 && !catC; i++) {
      for(int j = i + 1; j < nh1 && !catC; j++) {
         double hi = MathMax(sh1[i].price, sh1[j].price);
         double lo = MathMin(sh1[i].price, sh1[j].price);
         if(hi - lo < V_QUANTUM) continue;
         double range = hi - lo;
         double fracs[] = {1.0/3.0, 1.0/2.0, 2.0/3.0};
         for(int k = 0; k < 3; k++) {
            if(MathAbs(price - (lo + range * fracs[k])) <= LOST_MOTION) {
               catC = true; break;
            }
         }
      }
   }
   if(catC) score++;

   // D: Time window (natural square)
   bool catD = false;
   if(nh4 >= 1) {
      int h4_elapsed = (bar_idx - sh4[nh4-1].bar_index) / 48;
      for(int k = 0; k < ArraySize(NATURAL_SQ); k++) {
         if(MathAbs(h4_elapsed - NATURAL_SQ[k]) <= 1) { catD = true; break; }
      }
      if(!catD) {
         int h1_bars = h4_elapsed * 4;
         double ratio = (double)h1_bars / V_QUANTUM;
         for(int k = 0; k < 3; k++) {
            if(MathAbs(ratio - IMPULSE_RATIOS[k]) <= 1.0) { catD = true; break; }
         }
      }
   }
   if(catD) score++;

   // E: Triangle crossing — ONLY in BOX_ACTIVE phase
   if(in_box_phase && g_box.active) {
      if(bar_idx >= g_box.green_start && bar_idx <= g_box.end_bar) {
         if(MathAbs(price - g_box.midpoint) <= LOST_MOTION * 3)
            score++;
      }
   }

   // F: Wave target
   bool catF = false;
   if(g_wave.valid && ArraySize(g_wave.targets) > 0) {
      for(int k = 0; k < MathMin(4, ArraySize(g_wave.targets)); k++) {
         if(MathAbs(price - g_wave.targets[k]) <= LOST_MOTION * 2) {
            catF = true; break;
         }
      }
   }
   if(catF) score++;

   // G: Price-time square (Gold scaling: $6/H4 bar)
   bool catG = false;
   for(int s = rs; s < nh1 && !catG; s++) {
      double pmove = MathAbs(price - sh1[s].price);
      int elapsed = bar_idx - sh1[s].bar_index;
      double time_h4 = (double)elapsed / 48.0;
      if(time_h4 >= 1.0 && pmove >= V_QUANTUM) {
         double expected = time_h4 * PRICE_PER_H4;
         double r = (expected > 0) ? pmove / expected : 0;
         if(r >= 0.6 && r <= 1.4) catG = true;
      }
   }
   if(catG) score++;

   return score;
}

//+------------------------------------------------------------------+
//| QUANT MEASUREMENT                                                 |
//+------------------------------------------------------------------+
bool MeasureQuant(const MqlRates &m5[], int bars_since_conv, int n_bars) {
   // In CopyRates reversed indexing, conv was at index bars_since_conv+1
   int conv_idx = bars_since_conv + 1;
   if(conv_idx >= n_bars - 2) return false;

   double touch_price = m5[conv_idx].close;
   double extreme_price = touch_price;
   int extreme_bar = conv_idx;
   string dir = "";

   // Scan from conv toward present (decreasing index = forward in time)
   int scan_limit = MathMax(1, conv_idx - 50);
   // CRITICAL: also limit to not go past current bar (idx=1 = last completed)
   scan_limit = MathMax(scan_limit, 1);

   for(int i = conv_idx - 1; i >= scan_limit; i--) {
      if(dir == "" || dir == "up") {
         if(m5[i].high > extreme_price) {
            extreme_price = m5[i].high;
            extreme_bar = i;
            dir = "up";
         }
      }
      if(dir == "" || dir == "down") {
         if(m5[i].low < extreme_price) {
            extreme_price = m5[i].low;
            extreme_bar = i;
            dir = "down";
         }
      }

      double move = MathAbs(extreme_price - touch_price);
      if(move < V_QUANTUM * 0.5) continue;

      if(dir == "up" && m5[i].low < extreme_price - move / 3.0) break;
      if(dir == "down" && m5[i].high > extreme_price + move / 3.0) break;
   }

   double qpips = MathAbs(extreme_price - touch_price);
   int qbars = conv_idx - extreme_bar;  // positive

   if(qpips < V_QUANTUM * 0.5 || qbars < 1) return false;

   // Round to quantum
   double box_h = MathRound(qpips / V_QUANTUM) * V_QUANTUM;
   if(box_h < V_QUANTUM) box_h = V_QUANTUM;

   // Round bars to nearest natural square
   int best_sq = 4, best_diff = 9999;
   for(int k = 0; k < ArraySize(NATURAL_SQ); k++) {
      int d = MathAbs(qbars - NATURAL_SQ[k]);
      if(d < best_diff) { best_diff = d; best_sq = NATURAL_SQ[k]; }
   }
   int box_w = MathMax(4, (int)(best_sq * 4.0 / 3.0));

   // Build box
   double btop = MathMax(touch_price, extreme_price) + LOST_MOTION;
   double bbot = MathMin(touch_price, extreme_price) - LOST_MOTION;
   double bh = btop - bbot;
   double bh_ext = MathMax(bh, V_QUANTUM * 2.0);
   bh_ext = ((int)(bh_ext / V_QUANTUM) + 1) * V_QUANTUM;
   double center = (btop + bbot) / 2.0;

   g_box.top = center + bh_ext / 2.0;
   g_box.bottom = center - bh_ext / 2.0;
   g_box.start_bar = g_m5_count;
   g_box.end_bar = g_m5_count + box_w;
   g_box.width = box_w;
   g_box.height = bh_ext;
   g_box.scale = bh_ext / box_w;
   g_box.midpoint = center;
   g_box.green_start = g_m5_count + (int)(box_w * 2.0 / 3.0);
   g_box.quant_pips = qpips;
   g_box.quant_bars = qbars;
   g_box.direction = dir;
   g_box.touch_price = touch_price;
   g_box.extreme_price = extreme_price;
   g_box.active = true;

   Print("Box: $", DoubleToString(g_box.bottom,2), "-$",
         DoubleToString(g_box.top,2), " w=", box_w,
         " green@", g_box.green_start, " quant=$", DoubleToString(qpips,1));
   return true;
}

//+------------------------------------------------------------------+
//| GREEN ZONE ENTRY — Calibrated direction logic                     |
//+------------------------------------------------------------------+
bool FindGreenZoneEntry(double current_price, double &entry_price,
                        double &sl, double &tp, string &trade_dir) {
   if(!g_box.active) return false;
   if(g_m5_count < g_box.green_start || g_m5_count > g_box.end_bar)
      return false;

   // Midpoint is PRIMARY direction signal
   string mid_dir = (current_price > g_box.midpoint) ? "long" : "short";

   // D1/H1 can reject only if BOTH disagree
   string d1_mapped = "flat";
   if(g_d1_direction == "up") d1_mapped = "long";
   else if(g_d1_direction == "down") d1_mapped = "short";

   string h1_mapped = "flat";
   if(g_wave.valid) {
      if(g_wave.direction == "up") h1_mapped = "long";
      else if(g_wave.direction == "down") h1_mapped = "short";
   }

   int disagreements = 0;
   if(d1_mapped != "flat" && d1_mapped != mid_dir) disagreements++;
   if(h1_mapped != "flat" && h1_mapped != mid_dir) disagreements++;
   if(disagreements >= 2) return false;

   trade_dir = mid_dir;

   // Simplified diagonal bounds (linear convergence)
   double t_frac = (double)(g_m5_count - g_box.start_bar) / g_box.width;
   double converge = (1.0 - t_frac) * g_box.height;
   double upper = g_box.midpoint + converge / 2.0;
   double lower = g_box.midpoint - converge / 2.0;
   double gap = upper - lower;

   if(gap <= 0 || gap > V_QUANTUM * 6) return false;  // 6 quanta = $72

   double qpips = g_box.quant_pips;

   if(trade_dir == "long") {
      entry_price = NormalizePrice(lower + LOST_MOTION);
      sl = NormalizePrice(lower - LOST_MOTION);
      tp = NormalizePrice(entry_price + qpips * InpWaveMult);
   } else {
      entry_price = NormalizePrice(upper - LOST_MOTION);
      sl = NormalizePrice(upper + LOST_MOTION);
      tp = NormalizePrice(entry_price - qpips * InpWaveMult);
   }

   double sl_dist = MathAbs(entry_price - sl);
   double tp_dist = MathAbs(tp - entry_price);
   double rr = (sl_dist > 0) ? tp_dist / sl_dist : 0;

   if(rr < InpMinRR) return false;

   Print("Entry: ", trade_dir, " @$", DoubleToString(entry_price,2),
         " SL=$", DoubleToString(sl,2), " TP=$", DoubleToString(tp,2),
         " R:R=", DoubleToString(rr,1));
   return true;
}

//+------------------------------------------------------------------+
//| Calculate lot size                                                |
//+------------------------------------------------------------------+
double CalculateLots(double sl_distance) {
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk = balance * InpRiskPct;
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_size == 0 || tick_value == 0) return NormalizeLots(0.01);
   double lots = risk / (sl_distance * (tick_value / tick_size));
   return NormalizeLots(lots);
}

//+------------------------------------------------------------------+
//| Open trade with error handling                                    |
//+------------------------------------------------------------------+
bool OpenTrade(ENUM_ORDER_TYPE type, double sl, double tp, double lots) {
   MqlTradeRequest request = {};
   MqlTradeResult result = {};

   request.action = TRADE_ACTION_DEAL;
   request.symbol = _Symbol;
   request.volume = lots;
   request.type = type;
   request.deviation = 30;
   request.magic = InpMagic;
   request.comment = "GannScalper v9.1c";

   request.price = (type == ORDER_TYPE_BUY) ?
      SymbolInfoDouble(_Symbol, SYMBOL_ASK) :
      SymbolInfoDouble(_Symbol, SYMBOL_BID);

   request.sl = NormalizePrice(sl);
   request.tp = NormalizePrice(tp);

   // Fill policy
   long filling = SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_IOC) != 0)
      request.type_filling = ORDER_FILLING_IOC;
   else if((filling & SYMBOL_FILLING_FOK) != 0)
      request.type_filling = ORDER_FILLING_FOK;
   else
      request.type_filling = ORDER_FILLING_RETURN;

   // Validate stops
   int stop_level = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double min_dist = stop_level * _Point;
   if(MathAbs(request.price - request.sl) < min_dist ||
      MathAbs(request.tp - request.price) < min_dist) {
      Print("SL/TP too close. stop_level=", stop_level);
      return false;
   }

   // Check margin
   double margin_req;
   if(!OrderCalcMargin(type, _Symbol, lots, request.price, margin_req)) return false;
   if(margin_req > AccountInfoDouble(ACCOUNT_MARGIN_FREE)) {
      Print("Insufficient margin");
      return false;
   }

   if(!OrderSend(request, result)) {
      Print("OrderSend FAILED: err=", GetLastError(), " retcode=", result.retcode);
      return false;
   }
   if(result.retcode != TRADE_RETCODE_DONE && result.retcode != TRADE_RETCODE_PLACED) {
      Print("Trade REJECTED: retcode=", result.retcode);
      return false;
   }

   Print("OPENED: ticket=", result.order, " @$", DoubleToString(result.price, _Digits));
   return true;
}

//+------------------------------------------------------------------+
//| Manage open positions: max hold, trailing stop, vibration override |
//+------------------------------------------------------------------+
void ManagePositions() {
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      if(PositionGetSymbol(i) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      ulong ticket = PositionGetInteger(POSITION_TICKET);
      datetime open_time = (datetime)PositionGetInteger(POSITION_TIME);
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double current = PositionGetDouble(POSITION_PRICE_CURRENT);
      ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      double current_sl = PositionGetDouble(POSITION_SL);

      // Max hold
      int bars_held = Bars(_Symbol, PERIOD_M5, open_time, TimeCurrent());
      if(bars_held >= InpMaxHold) {
         Print("Max hold (", bars_held, " bars). Closing.");
         ClosePositionByTicket(ticket);
         continue;
      }

      // Vibration override ($288 move)
      double move = MathAbs(current - entry);
      if(move >= OVERRIDE_MULT * V_BASE) {
         Print("Vibration override ($", DoubleToString(move,2), "). Closing.");
         ClosePositionByTicket(ticket);
         continue;
      }

      // Trailing stop: at InpTrailAtR × SL_distance, move SL to breakeven
      if(g_trade_sl_distance > 0 && !g_trailed_to_be) {
         double unrealized = 0;
         if(type == POSITION_TYPE_BUY)
            unrealized = current - entry;
         else
            unrealized = entry - current;

         if(unrealized >= g_trade_sl_distance * InpTrailAtR) {
            double new_sl = entry;  // exact breakeven
            if(type == POSITION_TYPE_BUY && current_sl < entry) {
               if(ModifySL(ticket, new_sl)) {
                  Print("Trailed SL to breakeven: $", DoubleToString(new_sl,2));
                  g_trailed_to_be = true;
               }
            }
            else if(type == POSITION_TYPE_SELL && current_sl > entry) {
               if(ModifySL(ticket, new_sl)) {
                  Print("Trailed SL to breakeven: $", DoubleToString(new_sl,2));
                  g_trailed_to_be = true;
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Update swings and wave counting                                   |
//+------------------------------------------------------------------+
void UpdateSwings() {
   // H1 swings
   MqlRates h1[];
   ArraySetAsSeries(h1, true);
   int h1_count = CopyRates(_Symbol, PERIOD_H1, 0, 200, h1);
   if(h1_count >= 50)
      DetectSwings(h1, h1_count, 12, g_swings_h1, 14, 1.5);

   // H4 swings
   MqlRates h4[];
   ArraySetAsSeries(h4, true);
   int h4_count = CopyRates(_Symbol, PERIOD_H4, 0, 100, h4);
   if(h4_count >= 30)
      DetectSwings(h4, h4_count, 48, g_swings_h4, 14, 1.5);

   // D1 swings + direction
   MqlRates d1[];
   ArraySetAsSeries(d1, true);
   int d1_count = CopyRates(_Symbol, PERIOD_D1, 0, 60, d1);
   if(d1_count >= 20) {
      DetectSwings(d1, d1_count, 288, g_swings_d1, 14, 1.5);
      int nd1 = ArraySize(g_swings_d1);
      if(nd1 >= 3) {
         if(g_swings_d1[nd1-1].price > g_swings_d1[nd1-3].price)
            g_d1_direction = "up";
         else if(g_swings_d1[nd1-1].price < g_swings_d1[nd1-3].price)
            g_d1_direction = "down";
         else g_d1_direction = "flat";
      }
   }

   // Wave counting
   int nh1 = ArraySize(g_swings_h1);
   g_wave.valid = false;
   if(nh1 >= 4) {
      int lookback = MathMin(6, nh1 - 1);
      int start = nh1 - lookback;
      double best_score = 0;
      int best_idx = start;

      for(int i = start + 2; i < nh1; i++) {
         double prev_sz = MathAbs(g_swings_h1[i-1].price - g_swings_h1[i-2].price);
         double curr_sz = MathAbs(g_swings_h1[i].price - g_swings_h1[i-1].price);
         if(prev_sz == 0) continue;
         double ratio = curr_sz / prev_sz;
         if(ratio > 1.5 || ratio < 0.67) {
            double s = MathAbs(MathLog(ratio));
            if(s > best_score) { best_score = s; best_idx = i - 1; }
         }
      }

      if(best_score > 0.3) {
         g_wave.wave_0_price = g_swings_h1[best_idx].price;
         int scenario_len = nh1 - best_idx;
         g_wave.wave_number = scenario_len - 1;

         g_wave.wave_0_size = (scenario_len >= 2) ?
            MathAbs(g_swings_h1[best_idx+1].price - g_swings_h1[best_idx].price) :
            MathAbs(g_swings_h1[nh1-1].price - g_swings_h1[nh1-2].price);

         g_wave.direction = (g_swings_h1[best_idx].type == "low") ? "up" : "down";
         g_wave.is_trending = (g_wave.wave_number % 2 == 1);

         ArrayResize(g_wave.targets, 7);
         for(int k = 0; k < 7; k++) {
            g_wave.targets[k] = (g_wave.direction == "up") ?
               g_wave.wave_0_price + g_wave.wave_0_size * (k + 2) :
               g_wave.wave_0_price - g_wave.wave_0_size * (k + 2);
         }
         g_wave.valid = true;
      }
   }
}

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit() {
   if(StringFind(_Symbol, "XAU") < 0 && StringFind(_Symbol, "GOLD") < 0)
      Print("WARNING: EA designed for XAUUSD, running on ", _Symbol);

   Print("=== GannScalper v9.1c Calibrated ===");
   Print("Convergence: scan=", InpMinConvScan, " box=", InpMinConvBox);
   Print("R:R min=", InpMinRR, " WaveMult=", InpWaveMult, " Trail@", InpTrailAtR, "R");
   Print("Point=", _Point, " Digits=", _Digits,
         " TickSize=", SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE));

   // Force load MTF data
   iClose(_Symbol, PERIOD_H1, 0);
   iClose(_Symbol, PERIOD_H4, 0);
   iClose(_Symbol, PERIOD_D1, 0);

   g_state = STATE_SCANNING;
   g_box.active = false;
   g_wave.valid = false;

   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   Print("GannScalper stopped. Reason=", reason, " DailyTrades=", g_dailyTrades);
}

//+------------------------------------------------------------------+
//| OnTick — MAIN LOOP                                                |
//+------------------------------------------------------------------+
void OnTick() {
   // STEP 1: New M5 bar only
   if(!IsNewBar_M5()) return;
   g_m5_count++;

   // STEP 2: Daily reset
   datetime today = iTime(_Symbol, PERIOD_D1, 0);
   if(today != g_lastTradeDay) {
      g_lastTradeDay = today;
      g_dailyTrades = 0;
   }

   // STEP 3: Spread check
   if(!IsSpreadAcceptable()) return;

   // STEP 4: Load last completed M5 bar
   MqlRates m5[];
   ArraySetAsSeries(m5, true);
   int m5_count = CopyRates(_Symbol, PERIOD_M5, 0, 500, m5);
   if(m5_count < 100) return;

   double current_price = m5[1].close;  // Last COMPLETED bar

   // STEP 5: Update swings periodically
   if(g_m5_count % 12 == 0)
      UpdateSwings();

   // STEP 6: Manage open positions
   ManagePositions();

   // === STATE MACHINE ===

   if(g_state == STATE_TRADE) {
      if(!HasOpenPosition()) {
         g_state = STATE_SCANNING;
         g_box.active = false;
         g_trailed_to_be = false;
      }
      return;
   }

   if(g_state == STATE_SCANNING) {
      int nh1 = ArraySize(g_swings_h1);
      int nh4 = ArraySize(g_swings_h4);
      if(nh1 < 4) return;

      int score = ScoreConvergence(current_price, g_m5_count,
                                    g_swings_h1, nh1, g_swings_h4, nh4,
                                    false);  // not in box phase

      if(score >= InpMinConvScan) {
         g_state = STATE_QUANT;
         g_convBar = g_m5_count;
         g_convPrice = current_price;
         Print("Convergence: score=", score, " @$", DoubleToString(current_price,2));
      }
      return;
   }

   if(g_state == STATE_QUANT) {
      int bars_since = g_m5_count - g_convBar;
      if(bars_since > 50) {  // 50-bar timeout
         g_state = STATE_SCANNING;
         return;
      }

      if(MeasureQuant(m5, bars_since, m5_count)) {
         g_state = STATE_BOX;
      }
      return;
   }

   if(g_state == STATE_BOX) {
      if(!g_box.active || g_m5_count > g_box.end_bar) {
         g_state = STATE_SCANNING;
         g_box.active = false;
         return;
      }

      if(g_m5_count < g_box.green_start) return;

      if(g_dailyTrades >= InpMaxDaily) return;
      if(HasOpenPosition()) return;

      double entry_price, sl, tp;
      string trade_dir;

      if(FindGreenZoneEntry(current_price, entry_price, sl, tp, trade_dir)) {
         double sl_dist = MathAbs(entry_price - sl);
         double lots = CalculateLots(sl_dist);

         ENUM_ORDER_TYPE type = (trade_dir == "long") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;

         if(OpenTrade(type, sl, tp, lots)) {
            g_dailyTrades++;
            g_state = STATE_TRADE;
            g_trade_entry_price = entry_price;
            g_trade_sl_distance = sl_dist;
            g_trailed_to_be = false;
            Print("Trade #", g_dailyTrades, " today");
         }
      }
      return;
   }
}
//+------------------------------------------------------------------+
