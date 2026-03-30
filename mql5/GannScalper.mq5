//+------------------------------------------------------------------+
//| GannScalper.mq5 — v9.1 Triangle-First Gann EA                    |
//| FXSoqqaBot — XAUUSD on RoboForex ECN 1:500                       |
//+------------------------------------------------------------------+
#property copyright "FXSoqqaBot"
#property version   "9.10"
#property strict

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                  |
//+------------------------------------------------------------------+
input int    InpMagic       = 91100;      // Magic number
input double InpRiskPct     = 0.02;       // Risk per trade (2%)
input double InpMaxSpread   = 0.50;       // Max spread ($)
input int    InpMaxDaily    = 5;          // Max trades per day
input int    InpMaxHold     = 288;        // Max hold (M5 bars)
input int    InpMinConv     = 4;          // Min convergence score
input int    InpMinLimits   = 2;          // Min limits count
input double InpMinRR       = 3.0;        // Min R:R ratio
input int    InpWaveMult    = 4;          // TP = quant * this

//+------------------------------------------------------------------+
//| GANN CONSTANTS (DO NOT CHANGE)                                    |
//+------------------------------------------------------------------+
#define V_BASE         72     // Base vibration
#define V_QUANTUM      12     // Swing quantum V/6
#define V_GROWTH       18     // Growth quantum V/4
#define V_CORRECTION   24     // Correction quantum V/3
#define LOST_MOTION    3.0    // Dollars +/-
#define CUBE_ROOT_STEP 52
#define OVERRIDE_MULT  4      // 4 x V = reversal threshold

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
datetime g_lastBar_H1 = 0;
datetime g_lastBar_D1 = 0;
int      g_dailyTrades = 0;
datetime g_lastTradeDay = 0;

// Convergence tracking
int      g_convBar = 0;
double   g_convPrice = 0;

// Active box
struct GannBox {
   double top;
   double bottom;
   int    start_bar;
   int    end_bar;
   int    width;
   double height;
   double scale;
   double midpoint;
   int    green_start;
   double quant_pips;
   int    quant_bars;
   string direction;  // "up" or "down"
   double touch_price;
   double extreme_price;
   bool   active;
};
GannBox g_box;

// Swing storage
struct SwingPoint {
   string type;     // "high" or "low"
   double price;
   datetime time;
   int    bar_index;
   double atr;
};

SwingPoint g_swings_h1[];
SwingPoint g_swings_h4[];
SwingPoint g_swings_d1[];

// Wave state
struct WaveState {
   int    wave_number;
   double wave_0_price;
   double wave_0_size;
   string direction;  // "up" or "down"
   double targets[];
   bool   is_trending;
   bool   valid;
};
WaveState g_wave;

string g_d1_direction = "flat";

// Bar counter for M5
int g_m5_count = 0;

//+------------------------------------------------------------------+
//| HELPER: Normalize price to tick size                              |
//+------------------------------------------------------------------+
double NormalizePrice(double price) {
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick == 0) return NormalizeDouble(price, _Digits);
   return NormalizeDouble(MathRound(price / tick) * tick, _Digits);
}

//+------------------------------------------------------------------+
//| HELPER: Normalize lot size                                        |
//+------------------------------------------------------------------+
double NormalizeLots(double lots) {
   double min_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step     = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step == 0) step = 0.01;
   lots = MathFloor(lots / step) * step;
   lots = MathMax(min_lot, MathMin(max_lot, lots));
   return NormalizeDouble(lots, 2);
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

//+------------------------------------------------------------------+
//| HELPER: Spread check                                              |
//+------------------------------------------------------------------+
bool IsSpreadAcceptable() {
   double spread = SymbolInfoDouble(_Symbol, SYMBOL_ASK) -
                   SymbolInfoDouble(_Symbol, SYMBOL_BID);
   return spread <= InpMaxSpread;
}

//+------------------------------------------------------------------+
//| HELPER: Has open position with our magic                          |
//+------------------------------------------------------------------+
bool HasOpenPosition() {
   for(int i = 0; i < PositionsTotal(); i++) {
      if(PositionGetSymbol(i) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| HELPER: Close position by ticket                                  |
//+------------------------------------------------------------------+
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
//| SQ9 ENGINE: Price to degree                                       |
//+------------------------------------------------------------------+
double PriceToSq9Degree(double price) {
   if(price <= 0) return 0;
   double deg = MathMod(MathSqrt(price) * 180.0 - 225.0, 360.0);
   if(deg < 0) deg += 360.0;
   return deg;
}

//+------------------------------------------------------------------+
//| SQ9: Generate levels from price at degree offsets                 |
//+------------------------------------------------------------------+
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
            if(MathAbs(level - price) <= price * 0.15) {
               if(count < 20) {
                  levels[count] = level;
                  count++;
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| ATR calculation                                                   |
//+------------------------------------------------------------------+
double CalculateATR(const MqlRates &rates[], int period, int start_idx) {
   double sum = 0;
   for(int i = start_idx; i < start_idx + period; i++) {
      double tr = MathMax(rates[i].high - rates[i].low,
                 MathMax(MathAbs(rates[i].high - rates[i+1].close),
                         MathAbs(rates[i].low - rates[i+1].close)));
      sum += tr;
   }
   return sum / period;
}

//+------------------------------------------------------------------+
//| SWING DETECTION: ATR ZigZag on MqlRates                           |
//+------------------------------------------------------------------+
void DetectSwings(const MqlRates &rates[], int n_bars,
                  SwingPoint &swings[], int atr_period = 14,
                  double atr_mult = 1.5) {
   ArrayResize(swings, 0);
   if(n_bars < atr_period + 2) return;

   // rates[0] = newest, rates[n-1] = oldest (ArraySetAsSeries)
   // Process from oldest to newest: i from n-1 down to 0
   // But we need chronological order, so reverse:

   string direction = "";
   double last_high = rates[n_bars - 1].high;
   int last_high_idx = n_bars - 1;
   double last_low = rates[n_bars - 1].low;
   int last_low_idx = n_bars - 1;

   for(int i = n_bars - 1 - atr_period; i >= 1; i--) {
      // ATR at this bar
      double atr = CalculateATR(rates, atr_period, i);
      double threshold = atr * atr_mult;

      if(rates[i].high > last_high) {
         last_high = rates[i].high;
         last_high_idx = i;
      }
      if(rates[i].low < last_low) {
         last_low = rates[i].low;
         last_low_idx = i;
      }

      if(direction != "down" && last_high - rates[i].low > threshold) {
         int sz = ArraySize(swings);
         ArrayResize(swings, sz + 1);
         swings[sz].type = "high";
         swings[sz].price = last_high;
         swings[sz].time = rates[last_high_idx].time;
         swings[sz].bar_index = last_high_idx;
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
         swings[sz].bar_index = last_low_idx;
         swings[sz].atr = atr;
         direction = "up";
         last_high = rates[i].high;
         last_high_idx = i;
      }
   }
}

//+------------------------------------------------------------------+
//| CONVERGENCE: 7-category independent scoring                       |
//+------------------------------------------------------------------+
int ScoreConvergence(double price, int bar_idx, datetime bar_time,
                     const SwingPoint &swings_h1[], int n_h1,
                     const SwingPoint &swings_h4[], int n_h4) {
   if(n_h1 < 2) return 0;

   int score = 0;
   int recent_start = MathMax(0, n_h1 - 5);

   // --- A: Sq9 level ---
   for(int s = recent_start; s < n_h1; s++) {
      double levels[];
      int count;
      Sq9LevelsFromPrice(swings_h1[s].price, levels, count);
      for(int j = 0; j < count; j++) {
         if(MathAbs(price - levels[j]) <= LOST_MOTION) {
            score++;
            s = n_h1; // break outer
            break;
         }
      }
   }

   // --- B: Vibration level ---
   for(int s = recent_start; s < n_h1; s++) {
      double dist = MathAbs(price - swings_h1[s].price);
      double rem = MathMod(dist, (double)V_QUANTUM);
      if(rem <= LOST_MOTION || (V_QUANTUM - rem) <= LOST_MOTION) {
         score++;
         break;
      }
   }

   // --- C: Proportional division ---
   for(int i = recent_start; i < n_h1 - 1; i++) {
      bool found = false;
      for(int j = i + 1; j < n_h1; j++) {
         double hi = MathMax(swings_h1[i].price, swings_h1[j].price);
         double lo = MathMin(swings_h1[i].price, swings_h1[j].price);
         if(hi - lo < V_QUANTUM) continue;
         double range = hi - lo;
         double thirds[] = {lo + range/3.0, lo + range/2.0, lo + range*2.0/3.0};
         for(int k = 0; k < 3; k++) {
            if(MathAbs(price - thirds[k]) <= LOST_MOTION) {
               score++;
               found = true;
               break;
            }
         }
         if(found) break;
      }
      if(found) break;
   }

   // --- D: Time window (natural square) ---
   if(n_h4 >= 1) {
      int last_h4_bar = swings_h4[n_h4 - 1].bar_index;
      int h4_elapsed = (bar_idx - last_h4_bar) / 48;
      for(int k = 0; k < ArraySize(NATURAL_SQ); k++) {
         if(MathAbs(h4_elapsed - NATURAL_SQ[k]) <= 1) {
            score++;
            break;
         }
      }
      // Impulse check
      if(score == 0) {
         int h1_bars = h4_elapsed * 4;
         double ratio = (double)h1_bars / V_QUANTUM;
         for(int k = 0; k < 3; k++) {
            if(MathAbs(ratio - IMPULSE_RATIOS[k]) <= 1.0) {
               score++;
               break;
            }
         }
      }
   }

   // --- E: Triangle (if active box) ---
   if(g_box.active) {
      if(bar_idx >= g_box.green_start && bar_idx <= g_box.end_bar) {
         if(MathAbs(price - g_box.midpoint) <= LOST_MOTION * 3)
            score++;
      }
   }

   // --- F: Wave target ---
   if(g_wave.valid && ArraySize(g_wave.targets) > 0) {
      for(int k = 0; k < MathMin(4, ArraySize(g_wave.targets)); k++) {
         if(MathAbs(price - g_wave.targets[k]) <= LOST_MOTION * 2) {
            score++;
            break;
         }
      }
   }

   // --- G: Price-time square ---
   if(n_h1 >= 1) {
      double pmove = MathAbs(price - swings_h1[n_h1-1].price);
      double p_units = pmove / V_QUANTUM;
      double t_units = (double)(bar_idx - swings_h1[n_h1-1].bar_index) / 12.0;
      if(t_units > 0 && MathAbs(p_units - t_units) <= 2.0)
         score++;
   }

   return score;
}

//+------------------------------------------------------------------+
//| QUANT MEASUREMENT                                                 |
//+------------------------------------------------------------------+
bool MeasureQuant(const MqlRates &m5[], int conv_idx, int n_bars) {
   // conv_idx is in reversed indexing (0=newest)
   double touch_price = m5[conv_idx].close;
   double extreme_price = touch_price;
   int extreme_bar = conv_idx;
   string dir = "";

   int scan_limit = MathMax(1, conv_idx - 50);
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
   int qbars = conv_idx - extreme_bar;

   if(qpips < V_QUANTUM * 0.5 || qbars < 1) return false;

   // Round to quantum
   double box_h = MathRound(qpips / V_QUANTUM) * V_QUANTUM;
   if(box_h < V_QUANTUM) box_h = V_QUANTUM;

   // Round bars to nearest natural square
   int best_sq = 4;
   int best_diff = 9999;
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

   Print("Box built: $", DoubleToString(g_box.bottom, 2), "-$",
         DoubleToString(g_box.top, 2),
         " bars ", g_box.start_bar, "-", g_box.end_bar,
         " quant=$", DoubleToString(qpips, 1));

   return true;
}

//+------------------------------------------------------------------+
//| GREEN ZONE ENTRY                                                  |
//+------------------------------------------------------------------+
bool FindGreenZoneEntry(double current_price, double &entry_price,
                        double &sl, double &tp, string &trade_dir) {
   if(!g_box.active) return false;
   if(g_m5_count < g_box.green_start || g_m5_count > g_box.end_bar)
      return false;

   // Midpoint resolution
   string mid_dir = (current_price > g_box.midpoint) ? "long" : "short";

   // D1 direction mapping
   string d1_mapped = "flat";
   if(g_d1_direction == "up") d1_mapped = "long";
   else if(g_d1_direction == "down") d1_mapped = "short";

   // H1 wave direction mapping
   string h1_mapped = "flat";
   if(g_wave.valid) {
      if(g_wave.direction == "up") h1_mapped = "long";
      else if(g_wave.direction == "down") h1_mapped = "short";
   }

   if(d1_mapped == "flat") return false;

   // All directions must agree
   if(mid_dir != d1_mapped || mid_dir != h1_mapped) return false;

   trade_dir = mid_dir;

   // Simplified diagonal bounds (use linear interpolation of box)
   double t_frac = (double)(g_m5_count - g_box.start_bar) / g_box.width;
   double converge = (1.0 - t_frac) * g_box.height;
   double upper = g_box.midpoint + converge / 2.0;
   double lower = g_box.midpoint - converge / 2.0;
   double gap = upper - lower;

   if(gap <= 0 || gap > V_QUANTUM * 4) return false;

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

   Print("Green zone entry: ", trade_dir, " @$", DoubleToString(entry_price, 2),
         " SL=$", DoubleToString(sl, 2),
         " TP=$", DoubleToString(tp, 2),
         " R:R=", DoubleToString(rr, 1));

   return true;
}

//+------------------------------------------------------------------+
//| Calculate position size (2% risk)                                 |
//+------------------------------------------------------------------+
double CalculateLots(double sl_distance) {
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk = balance * InpRiskPct;

   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_size == 0 || tick_value == 0) return NormalizeLots(0.01);

   double value_per_lot_per_dollar = tick_value / tick_size;
   double lots = risk / (sl_distance * value_per_lot_per_dollar);

   return NormalizeLots(lots);
}

//+------------------------------------------------------------------+
//| Open trade with full error handling                               |
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
   request.comment = "GannScalper v9.1";

   if(type == ORDER_TYPE_BUY)
      request.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   else
      request.price = SymbolInfoDouble(_Symbol, SYMBOL_BID);

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

   // Validate SL/TP distance
   int stop_level = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double min_dist = stop_level * _Point;
   if(MathAbs(request.price - request.sl) < min_dist ||
      MathAbs(request.tp - request.price) < min_dist) {
      Print("SL/TP too close to entry. stop_level=", stop_level,
            " min_dist=", DoubleToString(min_dist, _Digits));
      return false;
   }

   // Check margin
   double margin_req;
   if(!OrderCalcMargin(type, _Symbol, lots, request.price, margin_req)) {
      Print("Cannot calculate margin");
      return false;
   }
   if(margin_req > AccountInfoDouble(ACCOUNT_MARGIN_FREE)) {
      Print("Insufficient margin: need=", DoubleToString(margin_req, 2),
            " free=", DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2));
      return false;
   }

   if(!OrderSend(request, result)) {
      Print("OrderSend FAILED: err=", GetLastError(),
            " retcode=", result.retcode,
            " price=", DoubleToString(request.price, _Digits),
            " sl=", DoubleToString(request.sl, _Digits),
            " tp=", DoubleToString(request.tp, _Digits),
            " lots=", DoubleToString(request.volume, 2));
      return false;
   }

   if(result.retcode != TRADE_RETCODE_DONE &&
      result.retcode != TRADE_RETCODE_PLACED) {
      Print("Trade REJECTED: retcode=", result.retcode);
      return false;
   }

   Print("TRADE OPENED: ticket=", result.order,
         " price=", DoubleToString(result.price, _Digits),
         " sl=", DoubleToString(request.sl, _Digits),
         " tp=", DoubleToString(request.tp, _Digits));
   return true;
}

//+------------------------------------------------------------------+
//| Manage open positions (max hold, fold, override)                  |
//+------------------------------------------------------------------+
void ManagePositions() {
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      if(PositionGetSymbol(i) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      ulong ticket = PositionGetInteger(POSITION_TICKET);
      datetime open_time = (datetime)PositionGetInteger(POSITION_TIME);

      // Max hold
      int bars_held = Bars(_Symbol, PERIOD_M5, open_time, TimeCurrent());
      if(bars_held >= InpMaxHold) {
         Print("Max hold reached (", bars_held, " bars). Closing.");
         ClosePositionByTicket(ticket);
         continue;
      }

      // 4x vibration override
      double entry_price = PositionGetDouble(POSITION_PRICE_OPEN);
      double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
      double move = MathAbs(current_price - entry_price);
      if(move >= OVERRIDE_MULT * V_BASE) {
         Print("4x vibration override ($", DoubleToString(move, 2), "). Closing.");
         ClosePositionByTicket(ticket);
      }
   }
}

//+------------------------------------------------------------------+
//| Update swing detection on higher timeframes                       |
//+------------------------------------------------------------------+
void UpdateSwings() {
   // H1 swings
   MqlRates h1[];
   ArraySetAsSeries(h1, true);
   int h1_count = CopyRates(_Symbol, PERIOD_H1, 0, 200, h1);
   if(h1_count >= 50)
      DetectSwings(h1, h1_count, g_swings_h1, 14, 1.5);

   // H4 swings
   MqlRates h4[];
   ArraySetAsSeries(h4, true);
   int h4_count = CopyRates(_Symbol, PERIOD_H4, 0, 100, h4);
   if(h4_count >= 30)
      DetectSwings(h4, h4_count, g_swings_h4, 14, 1.5);

   // D1 swings
   MqlRates d1[];
   ArraySetAsSeries(d1, true);
   int d1_count = CopyRates(_Symbol, PERIOD_D1, 0, 60, d1);
   if(d1_count >= 20) {
      DetectSwings(d1, d1_count, g_swings_d1, 14, 1.5);

      // D1 direction from last 3 swings
      int n_d1 = ArraySize(g_swings_d1);
      if(n_d1 >= 3) {
         if(g_swings_d1[n_d1-1].price > g_swings_d1[n_d1-3].price)
            g_d1_direction = "up";
         else if(g_swings_d1[n_d1-1].price < g_swings_d1[n_d1-3].price)
            g_d1_direction = "down";
         else
            g_d1_direction = "flat";
      }
   }

   // Wave counting (simplified)
   int n_h1 = ArraySize(g_swings_h1);
   g_wave.valid = false;
   if(n_h1 >= 4) {
      // Find wave 0 (largest recent swing)
      int lookback = MathMin(6, n_h1 - 1);
      int start = n_h1 - lookback;
      double best_score = 0;
      int best_idx = start;

      for(int i = start + 2; i < n_h1; i++) {
         double prev_size = MathAbs(g_swings_h1[i-1].price - g_swings_h1[i-2].price);
         double curr_size = MathAbs(g_swings_h1[i].price - g_swings_h1[i-1].price);
         if(prev_size == 0) continue;
         double ratio = curr_size / prev_size;
         if(ratio > 1.5 || ratio < 0.67) {
            double s = MathAbs(MathLog(ratio));
            if(s > best_score) { best_score = s; best_idx = i - 1; }
         }
      }

      if(best_score > 0.3) {
         g_wave.wave_0_price = g_swings_h1[best_idx].price;
         int scenario_len = n_h1 - best_idx;
         g_wave.wave_number = scenario_len - 1;

         if(scenario_len >= 2)
            g_wave.wave_0_size = MathAbs(g_swings_h1[best_idx+1].price -
                                          g_swings_h1[best_idx].price);
         else
            g_wave.wave_0_size = MathAbs(g_swings_h1[n_h1-1].price -
                                          g_swings_h1[n_h1-2].price);

         g_wave.direction = (g_swings_h1[best_idx].type == "low") ? "up" : "down";
         g_wave.is_trending = (g_wave.wave_number % 2 == 1);

         // Generate targets
         ArrayResize(g_wave.targets, 7);
         for(int k = 0; k < 7; k++) {
            if(g_wave.direction == "up")
               g_wave.targets[k] = g_wave.wave_0_price + g_wave.wave_0_size * (k + 2);
            else
               g_wave.targets[k] = g_wave.wave_0_price - g_wave.wave_0_size * (k + 2);
         }
         g_wave.valid = true;
      }
   }
}

//+------------------------------------------------------------------+
//| Print symbol info                                                 |
//+------------------------------------------------------------------+
void PrintSymbolInfo() {
   Print("=== Symbol: ", _Symbol, " ===");
   Print("Point: ", _Point, " Digits: ", _Digits);
   Print("Tick Size: ", SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE));
   Print("Min Lot: ", SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN),
         " Step: ", SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP));
   Print("Stop Level: ", SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL));
   Print("Contract Size: ", SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE));
}

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit() {
   if(StringFind(_Symbol, "XAU") < 0 && StringFind(_Symbol, "GOLD") < 0)
      Print("WARNING: EA designed for XAUUSD, running on ", _Symbol);

   PrintSymbolInfo();

   // Force load multi-timeframe data
   double d;
   d = iClose(_Symbol, PERIOD_H1, 0);
   d = iClose(_Symbol, PERIOD_H4, 0);
   d = iClose(_Symbol, PERIOD_D1, 0);

   g_state = STATE_SCANNING;
   g_box.active = false;

   Print("GannScalper v9.1 initialized. Magic=", InpMagic);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   Print("GannScalper stopped. Reason=", reason,
         " Trades today=", g_dailyTrades);
}

//+------------------------------------------------------------------+
//| OnTick — MAIN LOOP                                                |
//+------------------------------------------------------------------+
void OnTick() {
   // STEP 1: New bar detection — process ONCE per M5 bar only
   if(!IsNewBar_M5()) return;
   g_m5_count++;

   // STEP 2: Reset daily counter
   datetime today = iTime(_Symbol, PERIOD_D1, 0);
   if(today != g_lastTradeDay) {
      g_lastTradeDay = today;
      g_dailyTrades = 0;
   }

   // STEP 3: Prerequisites
   if(!IsSpreadAcceptable()) return;

   // STEP 4: Load M5 data
   MqlRates m5[];
   ArraySetAsSeries(m5, true);
   int m5_count = CopyRates(_Symbol, PERIOD_M5, 0, 500, m5);
   if(m5_count < 300) return;

   double current_price = m5[1].close;  // Last COMPLETED bar

   // STEP 5: Update swings every 12 bars (1 H1 bar)
   if(g_m5_count % 12 == 0)
      UpdateSwings();

   // STEP 6: Manage open positions
   ManagePositions();

   // === STATE MACHINE ===

   // IN_TRADE: handled by SL/TP/ManagePositions
   if(g_state == STATE_TRADE) {
      if(!HasOpenPosition()) {
         g_state = STATE_SCANNING;
         g_box.active = false;
      }
      return;
   }

   // SCANNING: look for convergence
   if(g_state == STATE_SCANNING) {
      int n_h1 = ArraySize(g_swings_h1);
      int n_h4 = ArraySize(g_swings_h4);
      if(n_h1 < 4) return;

      int score = ScoreConvergence(current_price, g_m5_count,
                                    m5[1].time, g_swings_h1, n_h1,
                                    g_swings_h4, n_h4);

      if(score >= InpMinConv) {
         g_state = STATE_QUANT;
         g_convBar = g_m5_count;
         g_convPrice = current_price;
         Print("Convergence detected: score=", score, " price=$",
               DoubleToString(current_price, 2));
      }
      return;
   }

   // QUANT_FORMING: measure initial impulse
   if(g_state == STATE_QUANT) {
      int bars_since = g_m5_count - g_convBar;
      if(bars_since > 20) {
         g_state = STATE_SCANNING;
         return;
      }

      if(MeasureQuant(m5, bars_since + 1, m5_count)) {
         g_state = STATE_BOX;
         Print("Quant measured. Box active.");
      }
      return;
   }

   // BOX_ACTIVE: wait for green zone, then enter
   if(g_state == STATE_BOX) {
      if(!g_box.active || g_m5_count > g_box.end_bar) {
         g_state = STATE_SCANNING;
         g_box.active = false;
         return;
      }

      if(g_m5_count < g_box.green_start) return;  // Not in green zone yet

      if(g_dailyTrades >= InpMaxDaily) return;
      if(HasOpenPosition()) return;

      double entry_price, sl, tp;
      string trade_dir;

      if(FindGreenZoneEntry(current_price, entry_price, sl, tp, trade_dir)) {
         double sl_dist = MathAbs(entry_price - sl);
         double lots = CalculateLots(sl_dist);

         ENUM_ORDER_TYPE type = (trade_dir == "long") ?
                                 ORDER_TYPE_BUY : ORDER_TYPE_SELL;

         if(OpenTrade(type, sl, tp, lots)) {
            g_dailyTrades++;
            g_state = STATE_TRADE;
            Print("Entered trade #", g_dailyTrades, " today");
         }
      }
      return;
   }
}
//+------------------------------------------------------------------+
