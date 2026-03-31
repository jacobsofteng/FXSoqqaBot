//+------------------------------------------------------------------+
//| GannScalperV92.mq5 — v9.2 Multi-Scale + Auto-Scaling            |
//| FXSoqqaBot — XAUUSD on RoboForex ECN 1:500                       |
//| Changes: Parallel boxes, H1+M15, tier-based lot sizing            |
//+------------------------------------------------------------------+
#property copyright "FXSoqqaBot"
#property version   "9.20"
#property strict

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                  |
//+------------------------------------------------------------------+
input double InpMaxSpreadH1  = 0.50;     // Max spread H1 ($)
input double InpMaxSpreadM15 = 0.30;     // Max spread M15 ($)
input int    InpMaxDaily     = 5;        // Max trades per day
input int    InpMaxHold      = 288;      // Max hold (M5 bars)
input int    InpMinConvScan  = 3;        // Min convergence SCANNING (3 of 6)
input int    InpMinConvBox   = 4;        // Min convergence BOX_ACTIVE (4 of 7)
input double InpMinRR        = 2.0;      // Min R:R ratio
input int    InpWaveMultH1   = 3;        // TP multiplier H1
input int    InpWaveMultM15  = 3;        // TP multiplier M15
input double InpTrailAtR     = 2.0;      // Trail SL to breakeven at R multiple
input bool   InpEnableM15    = true;     // Enable M15 scale

//+------------------------------------------------------------------+
//| GANN CONSTANTS (DO NOT CHANGE)                                    |
//+------------------------------------------------------------------+
#define V_BASE         72
#define V_QUANTUM      12
#define V_QUANTUM_M15  6
#define V_GROWTH       18
#define V_CORRECTION   24
#define LOST_MOTION_H1  3.0
#define LOST_MOTION_M15 2.0
#define OVERRIDE_MULT  4
#define PRICE_PER_H4   6.0

const int NATURAL_SQ[] = {4, 9, 16, 24, 36, 49, 72, 81};
const double NAT_SQ_STR[] = {0.23, 0.28, 0.15, 0.10, 0.08, 0.05, 0.04, 0.03};
const int POWER_ANGLES[] = {30, 45};
const int IMPULSE_RATIOS[] = {8, 16, 64};

//+------------------------------------------------------------------+
//| MAGIC NUMBERS                                                     |
//+------------------------------------------------------------------+
#define MAGIC_H1   123456
#define MAGIC_M15  123457

//+------------------------------------------------------------------+
//| BOX STATE (parallel tracking)                                     |
//+------------------------------------------------------------------+
struct GannBox {
   double top, bottom, height, scale_ppb, midpoint;
   int    start_bar, end_bar, width, green_start;
   double quant_pips;
   int    quant_bars;
   string direction;
   double touch_price, extreme_price;
};

struct BoxState {
   int    state;             // 0=QUANT_FORMING, 1=BOX_ACTIVE, 2=DONE
   int    convergence_bar;
   double convergence_price;
   int    convergence_score;
   GannBox box;
   bool   has_box;
};

#define MAX_H1_BOXES  3
#define MAX_M15_BOXES 3
#define MAX_TOTAL_OPEN 3

BoxState g_h1Boxes[MAX_H1_BOXES];
BoxState g_m15Boxes[MAX_M15_BOXES];
int      g_numH1Boxes = 0;
int      g_numM15Boxes = 0;

//+------------------------------------------------------------------+
//| GLOBAL STATE                                                      |
//+------------------------------------------------------------------+
datetime g_lastBar_M5 = 0;
int      g_dailyTrades = 0;
datetime g_lastTradeDay = 0;
int      g_m5_count = 0;
string   g_d1_direction = "flat";
string   g_h1_wave_direction = "flat";

// Swing storage
struct SwingPoint {
   string type;
   double price;
   datetime time;
   int    bar_index;
   double atr;
};
SwingPoint g_swings_h1[];
SwingPoint g_swings_h4[];
SwingPoint g_swings_d1[];
SwingPoint g_swings_m15[];

// Wave state
struct WaveState {
   int    wave_number;
   double wave_0_price, wave_0_size;
   string direction;
   double targets[];
   bool   is_trending, valid;
};
WaveState g_wave_h1;
WaveState g_wave_m15;

// Per-trade trailing state (indexed by ticket)
struct TradeTrail {
   ulong  ticket;
   double entry_price;
   double sl_distance;
   bool   trailed_to_be;
   int    magic;
};
TradeTrail g_trails[];

// Drawdown protection
double g_peakBalance = 0;
bool   g_drawdownMode = false;

//+------------------------------------------------------------------+
//| HELPERS                                                           |
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

bool IsNewBar_M5() {
   datetime t = iTime(_Symbol, PERIOD_M5, 0);
   if(t == 0) return false;
   if(t != g_lastBar_M5) { g_lastBar_M5 = t; return true; }
   return false;
}

int CountByMagic(int magic) {
   int count = 0;
   for(int i = 0; i < PositionsTotal(); i++) {
      if(PositionGetSymbol(i) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == magic)
         count++;
   }
   return count;
}

int CountAllPositions() {
   return CountByMagic(MAGIC_H1) + CountByMagic(MAGIC_M15);
}

//+------------------------------------------------------------------+
//| AUTO-SCALING LOT SIZE (Change 3)                                  |
//+------------------------------------------------------------------+
double GetLotSize(string scale) {
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double min_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double lot_step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double max_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(lot_step == 0) lot_step = 0.01;

   double lots = min_lot;

   if(scale == "H1") {
      if      (balance >= 5000) lots = 0.40;
      else if (balance >= 3000) lots = 0.25;
      else if (balance >= 1500) lots = 0.15;
      else if (balance >= 800)  lots = 0.08;
      else if (balance >= 500)  lots = 0.05;
      else if (balance >= 300)  lots = 0.03;
      else if (balance >= 150)  lots = 0.02;
      else                      lots = 0.01;
   }
   else if(scale == "M15") {
      if      (balance >= 4000) lots = 0.35;
      else if (balance >= 2500) lots = 0.20;
      else if (balance >= 1200) lots = 0.12;
      else if (balance >= 700)  lots = 0.08;
      else if (balance >= 400)  lots = 0.05;
      else if (balance >= 200)  lots = 0.03;
      else if (balance >= 100)  lots = 0.02;
      else                      lots = 0.01;
   }

   // Drawdown protection
   if(balance > g_peakBalance) {
      g_peakBalance = balance;
      g_drawdownMode = false;
   }
   if(balance < g_peakBalance * 0.70 && !g_drawdownMode) {
      g_drawdownMode = true;
      Print("DRAWDOWN PROTECTION ON. Peak:", g_peakBalance, " Now:", balance);
   }
   if(g_drawdownMode && balance > g_peakBalance * 0.90) {
      g_drawdownMode = false;
      Print("DRAWDOWN PROTECTION OFF. Recovered to:", balance);
   }
   if(g_drawdownMode) {
      lots = MathFloor((lots / 2.0) / lot_step) * lot_step;
      lots = MathMax(min_lot, lots);
   }

   // Normalize
   lots = MathFloor(lots / lot_step) * lot_step;
   lots = MathMax(min_lot, MathMin(max_lot, lots));

   // Margin safety
   double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double margin_required;
   if(OrderCalcMargin(ORDER_TYPE_BUY, _Symbol, lots, price, margin_required)) {
      double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      while(lots > min_lot && margin_required > free_margin * 0.5) {
         lots -= lot_step;
         lots = MathMax(min_lot, lots);
         OrderCalcMargin(ORDER_TYPE_BUY, _Symbol, lots, price, margin_required);
      }
   }

   return NormalizeDouble(lots, 2);
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
            if(MathAbs(level - price) <= price * 0.15 && count < 20)
               levels[count++] = level;
         }
      }
   }
}

//+------------------------------------------------------------------+
//| SWING DETECTION                                                   |
//+------------------------------------------------------------------+
void DetectSwings(const MqlRates &rates[], int n_bars, int tf_m5_factor,
                  SwingPoint &swings[], int atr_period = 14,
                  double atr_mult = 1.5) {
   ArrayResize(swings, 0);
   if(n_bars < atr_period + 2) return;

   string direction = "";
   double last_high = rates[n_bars - 1].high;
   int last_high_idx = n_bars - 1;
   double last_low = rates[n_bars - 1].low;
   int last_low_idx = n_bars - 1;

   for(int i = n_bars - 1 - atr_period; i >= 1; i--) {
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
//| CONVERGENCE: 7 categories, scale-aware                            |
//+------------------------------------------------------------------+
int ScoreConvergence(double price, int bar_idx,
                     const SwingPoint &swings[], int n_swings,
                     const SwingPoint &sh4[], int nh4,
                     double vib_quantum, double lost_motion,
                     bool in_box_phase, const GannBox &box, bool box_valid) {
   if(n_swings < 2) return 0;

   int score = 0;
   int rs = MathMax(0, n_swings - 5);

   // A: Sq9 level
   bool catA = false;
   for(int s = rs; s < n_swings && !catA; s++) {
      double levels[]; int count;
      Sq9LevelsFromPrice(swings[s].price, levels, count);
      for(int j = 0; j < count; j++)
         if(MathAbs(price - levels[j]) <= lost_motion) { catA = true; break; }
   }
   if(catA) score++;

   // B: Vibration level
   bool catB = false;
   for(int s = rs; s < n_swings && !catB; s++) {
      double rem = MathMod(MathAbs(price - swings[s].price), vib_quantum);
      if(rem <= lost_motion || (vib_quantum - rem) <= lost_motion) catB = true;
   }
   if(catB) score++;

   // C: Proportional division
   bool catC = false;
   for(int i = rs; i < n_swings - 1 && !catC; i++) {
      for(int j = i + 1; j < n_swings && !catC; j++) {
         double hi = MathMax(swings[i].price, swings[j].price);
         double lo = MathMin(swings[i].price, swings[j].price);
         if(hi - lo < vib_quantum) continue;
         double range = hi - lo;
         double fracs[] = {1.0/3.0, 1.0/2.0, 2.0/3.0};
         for(int k = 0; k < 3; k++)
            if(MathAbs(price - (lo + range * fracs[k])) <= lost_motion) {
               catC = true; break;
            }
      }
   }
   if(catC) score++;

   // D: Time window
   bool catD = false;
   if(nh4 >= 1) {
      int h4_elapsed = (bar_idx - sh4[nh4-1].bar_index) / 48;
      for(int k = 0; k < ArraySize(NATURAL_SQ); k++)
         if(MathAbs(h4_elapsed - NATURAL_SQ[k]) <= 1) { catD = true; break; }
      if(!catD) {
         int h1_bars = h4_elapsed * 4;
         double ratio = (double)h1_bars / vib_quantum;
         for(int k = 0; k < 3; k++)
            if(MathAbs(ratio - IMPULSE_RATIOS[k]) <= 1.0) { catD = true; break; }
      }
   }
   if(catD) score++;

   // E: Triangle crossing (BOX_ACTIVE only)
   if(in_box_phase && box_valid) {
      if(bar_idx >= box.green_start && bar_idx <= box.end_bar)
         if(MathAbs(price - box.midpoint) <= lost_motion * 3)
            score++;
   }

   // F: Wave target
   bool catF = false;
   WaveState &wave = (vib_quantum == V_QUANTUM) ? g_wave_h1 : g_wave_m15;
   if(wave.valid && ArraySize(wave.targets) > 0) {
      for(int k = 0; k < MathMin(4, ArraySize(wave.targets)); k++)
         if(MathAbs(price - wave.targets[k]) <= lost_motion * 2) {
            catF = true; break;
         }
   }
   if(catF) score++;

   // G: Price-time square
   bool catG = false;
   for(int s = rs; s < n_swings && !catG; s++) {
      double pmove = MathAbs(price - swings[s].price);
      int elapsed = bar_idx - swings[s].bar_index;
      double time_h4 = (double)elapsed / 48.0;
      if(time_h4 >= 1.0 && pmove >= vib_quantum) {
         double expected = time_h4 * PRICE_PER_H4;
         double r = (expected > 0) ? pmove / expected : 0;
         if(r >= 0.6 && r <= 1.4) catG = true;
      }
   }
   if(catG) score++;

   return score;
}

//+------------------------------------------------------------------+
//| QUANT MEASUREMENT (scale-aware)                                   |
//+------------------------------------------------------------------+
bool MeasureQuant(const MqlRates &m5[], int bars_since_conv, int n_bars,
                  double vib_quantum, int quant_window,
                  GannBox &out_box) {
   int conv_idx = bars_since_conv + 1;
   if(conv_idx >= n_bars - 2) return false;

   double touch_price = m5[conv_idx].close;
   double extreme_price = touch_price;
   int extreme_bar = conv_idx;
   string dir = "";

   int scan_limit = MathMax(1, conv_idx - quant_window);
   scan_limit = MathMax(scan_limit, 1);

   for(int i = conv_idx - 1; i >= scan_limit; i--) {
      if(dir == "" || dir == "up") {
         if(m5[i].high > extreme_price) {
            extreme_price = m5[i].high; extreme_bar = i; dir = "up";
         }
      }
      if(dir == "" || dir == "down") {
         if(m5[i].low < extreme_price) {
            extreme_price = m5[i].low; extreme_bar = i; dir = "down";
         }
      }

      double move = MathAbs(extreme_price - touch_price);
      if(move < vib_quantum * 0.5) continue;
      if(dir == "up" && m5[i].low < extreme_price - move / 3.0) break;
      if(dir == "down" && m5[i].high > extreme_price + move / 3.0) break;
   }

   double qpips = MathAbs(extreme_price - touch_price);
   int qbars = conv_idx - extreme_bar;
   if(qpips < vib_quantum * 0.5 || qbars < 1) return false;

   double box_h = MathRound(qpips / vib_quantum) * vib_quantum;
   if(box_h < vib_quantum) box_h = vib_quantum;

   int best_sq = 4, best_diff = 9999;
   for(int k = 0; k < ArraySize(NATURAL_SQ); k++) {
      int d = MathAbs(qbars - NATURAL_SQ[k]);
      if(d < best_diff) { best_diff = d; best_sq = NATURAL_SQ[k]; }
   }
   int box_w = MathMax(4, (int)(best_sq * 4.0 / 3.0));

   double btop = MathMax(touch_price, extreme_price) + LOST_MOTION_H1;
   double bbot = MathMin(touch_price, extreme_price) - LOST_MOTION_H1;
   double bh = btop - bbot;
   double bh_ext = MathMax(bh, vib_quantum * 2.0);
   bh_ext = ((int)(bh_ext / vib_quantum) + 1) * vib_quantum;
   double center = (btop + bbot) / 2.0;

   out_box.top = center + bh_ext / 2.0;
   out_box.bottom = center - bh_ext / 2.0;
   out_box.start_bar = g_m5_count;
   out_box.end_bar = g_m5_count + box_w;
   out_box.width = box_w;
   out_box.height = bh_ext;
   out_box.scale_ppb = bh_ext / box_w;
   out_box.midpoint = center;
   out_box.green_start = g_m5_count + (int)(box_w * 2.0 / 3.0);
   out_box.quant_pips = qpips;
   out_box.quant_bars = qbars;
   out_box.direction = dir;
   out_box.touch_price = touch_price;
   out_box.extreme_price = extreme_price;

   return true;
}

//+------------------------------------------------------------------+
//| GREEN ZONE ENTRY (scale-aware)                                    |
//+------------------------------------------------------------------+
bool FindGreenZoneEntry(const GannBox &box, double current_price,
                        double lost_motion, int wave_mult,
                        double max_gap,
                        double &entry_price, double &sl, double &tp,
                        string &trade_dir) {
   if(g_m5_count < box.green_start || g_m5_count > box.end_bar)
      return false;

   // Midpoint direction
   string mid_dir = (current_price > box.midpoint) ? "long" : "short";

   // D1/H1 rejection
   string d1_mapped = "flat";
   if(g_d1_direction == "up") d1_mapped = "long";
   else if(g_d1_direction == "down") d1_mapped = "short";

   string h1_mapped = "flat";
   if(g_wave_h1.valid) {
      if(g_wave_h1.direction == "up") h1_mapped = "long";
      else if(g_wave_h1.direction == "down") h1_mapped = "short";
   }

   int disagreements = 0;
   if(d1_mapped != "flat" && d1_mapped != mid_dir) disagreements++;
   if(h1_mapped != "flat" && h1_mapped != mid_dir) disagreements++;
   if(disagreements >= 2) return false;

   trade_dir = mid_dir;

   // Simplified diagonal bounds
   double t_frac = (double)(g_m5_count - box.start_bar) / box.width;
   double converge = (1.0 - t_frac) * box.height;
   double upper = box.midpoint + converge / 2.0;
   double lower = box.midpoint - converge / 2.0;
   double gap = upper - lower;

   if(gap <= 0 || gap > max_gap) return false;

   if(trade_dir == "long") {
      entry_price = NormalizePrice(lower + lost_motion);
      sl = NormalizePrice(lower - lost_motion);
      tp = NormalizePrice(entry_price + box.quant_pips * wave_mult);
   } else {
      entry_price = NormalizePrice(upper - lost_motion);
      sl = NormalizePrice(upper + lost_motion);
      tp = NormalizePrice(entry_price - box.quant_pips * wave_mult);
   }

   double sl_dist = MathAbs(entry_price - sl);
   double tp_dist = MathAbs(tp - entry_price);
   double rr = (sl_dist > 0) ? tp_dist / sl_dist : 0;

   if(rr < InpMinRR) return false;
   return true;
}

//+------------------------------------------------------------------+
//| Open trade with scale-specific magic and lot sizing               |
//+------------------------------------------------------------------+
bool OpenTrade(ENUM_ORDER_TYPE type, double sl, double tp,
               string scale, double entry_price, double sl_dist) {
   double lots = GetLotSize(scale);
   int magic = (scale == "H1") ? MAGIC_H1 : MAGIC_M15;

   MqlTradeRequest request = {};
   MqlTradeResult result = {};

   request.action = TRADE_ACTION_DEAL;
   request.symbol = _Symbol;
   request.volume = lots;
   request.type = type;
   request.deviation = 30;
   request.magic = magic;
   request.comment = "GannV92 " + scale;

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
      Print("SL/TP too close for ", scale);
      return false;
   }

   // Check margin
   double margin_req;
   if(!OrderCalcMargin(type, _Symbol, lots, request.price, margin_req)) return false;
   if(margin_req > AccountInfoDouble(ACCOUNT_MARGIN_FREE)) {
      Print("Insufficient margin for ", scale);
      return false;
   }

   if(!OrderSend(request, result)) {
      Print("OrderSend FAILED: err=", GetLastError());
      return false;
   }
   if(result.retcode != TRADE_RETCODE_DONE && result.retcode != TRADE_RETCODE_PLACED) {
      Print("Trade REJECTED: retcode=", result.retcode);
      return false;
   }

   // Track trailing state
   int sz = ArraySize(g_trails);
   ArrayResize(g_trails, sz + 1);
   g_trails[sz].ticket = result.order;
   g_trails[sz].entry_price = entry_price;
   g_trails[sz].sl_distance = sl_dist;
   g_trails[sz].trailed_to_be = false;
   g_trails[sz].magic = magic;

   Print("OPENED ", scale, ": ticket=", result.order, " lots=", lots,
         " @$", DoubleToString(result.price, _Digits));
   return true;
}

//+------------------------------------------------------------------+
//| Manage open positions                                             |
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
   if(!OrderSend(request, result)) return false;
   return true;
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
   request.magic = (int)PositionGetInteger(POSITION_MAGIC);
   request.type = (type == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   request.price = (type == POSITION_TYPE_BUY) ?
      SymbolInfoDouble(_Symbol, SYMBOL_BID) :
      SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   long filling = SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_IOC) != 0)
      request.type_filling = ORDER_FILLING_IOC;
   else if((filling & SYMBOL_FILLING_FOK) != 0)
      request.type_filling = ORDER_FILLING_FOK;
   else
      request.type_filling = ORDER_FILLING_RETURN;

   if(!OrderSend(request, result))
      Print("Close FAILED: ", GetLastError());
}

void ManagePositions() {
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      if(PositionGetSymbol(i) != _Symbol) continue;
      int magic = (int)PositionGetInteger(POSITION_MAGIC);
      if(magic != MAGIC_H1 && magic != MAGIC_M15) continue;

      ulong ticket = PositionGetInteger(POSITION_TICKET);
      datetime open_time = (datetime)PositionGetInteger(POSITION_TIME);
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double current = PositionGetDouble(POSITION_PRICE_CURRENT);
      ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      double current_sl = PositionGetDouble(POSITION_SL);

      // Max hold
      int bars_held = Bars(_Symbol, PERIOD_M5, open_time, TimeCurrent());
      if(bars_held >= InpMaxHold) {
         Print("Max hold. Closing ", (magic == MAGIC_H1 ? "H1" : "M15"), " ticket=", ticket);
         ClosePositionByTicket(ticket);
         continue;
      }

      // Vibration override
      double move = MathAbs(current - entry);
      if(move >= OVERRIDE_MULT * V_BASE) {
         Print("Vibration override. Closing ticket=", ticket);
         ClosePositionByTicket(ticket);
         continue;
      }

      // Trailing stop
      int trail_idx = -1;
      for(int t = 0; t < ArraySize(g_trails); t++)
         if(g_trails[t].ticket == ticket) { trail_idx = t; break; }

      if(trail_idx >= 0 && g_trails[trail_idx].sl_distance > 0
         && !g_trails[trail_idx].trailed_to_be) {
         double unrealized = (type == POSITION_TYPE_BUY) ?
            current - entry : entry - current;

         if(unrealized >= g_trails[trail_idx].sl_distance * InpTrailAtR) {
            bool should_trail = false;
            if(type == POSITION_TYPE_BUY && current_sl < entry)
               should_trail = true;
            else if(type == POSITION_TYPE_SELL && current_sl > entry)
               should_trail = true;

            if(should_trail && ModifySL(ticket, entry)) {
               g_trails[trail_idx].trailed_to_be = true;
               Print("Trailed to BE: ticket=", ticket);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Update swings and wave counting                                   |
//+------------------------------------------------------------------+
void UpdateSwings() {
   // H1
   MqlRates h1[];
   ArraySetAsSeries(h1, true);
   int h1_count = CopyRates(_Symbol, PERIOD_H1, 0, 200, h1);
   if(h1_count >= 50)
      DetectSwings(h1, h1_count, 12, g_swings_h1, 14, 1.5);

   // H4
   MqlRates h4[];
   ArraySetAsSeries(h4, true);
   int h4_count = CopyRates(_Symbol, PERIOD_H4, 0, 100, h4);
   if(h4_count >= 30)
      DetectSwings(h4, h4_count, 48, g_swings_h4, 14, 1.5);

   // D1
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

   // M15
   if(InpEnableM15) {
      MqlRates m15[];
      ArraySetAsSeries(m15, true);
      int m15_count = CopyRates(_Symbol, PERIOD_M15, 0, 500, m15);
      if(m15_count >= 50)
         DetectSwings(m15, m15_count, 3, g_swings_m15, 14, 1.0);
   }

   // Wave counting H1
   CountWaves(g_swings_h1, g_wave_h1);
   g_h1_wave_direction = g_wave_h1.valid ? g_wave_h1.direction : "flat";

   // Wave counting M15
   if(InpEnableM15)
      CountWaves(g_swings_m15, g_wave_m15);
}

void CountWaves(const SwingPoint &swings[], WaveState &wave) {
   wave.valid = false;
   int n = ArraySize(swings);
   if(n < 4) return;

   int lookback = MathMin(6, n - 1);
   int start = n - lookback;
   double best_score = 0;
   int best_idx = start;

   for(int i = start + 2; i < n; i++) {
      double prev_sz = MathAbs(swings[i-1].price - swings[i-2].price);
      double curr_sz = MathAbs(swings[i].price - swings[i-1].price);
      if(prev_sz == 0) continue;
      double ratio = curr_sz / prev_sz;
      if(ratio > 1.5 || ratio < 0.67) {
         double s = MathAbs(MathLog(ratio));
         if(s > best_score) { best_score = s; best_idx = i - 1; }
      }
   }

   if(best_score > 0.3) {
      wave.wave_0_price = swings[best_idx].price;
      int scenario_len = n - best_idx;
      wave.wave_number = scenario_len - 1;
      wave.wave_0_size = (scenario_len >= 2) ?
         MathAbs(swings[best_idx+1].price - swings[best_idx].price) :
         MathAbs(swings[n-1].price - swings[n-2].price);
      wave.direction = (swings[best_idx].type == "low") ? "up" : "down";
      wave.is_trending = (wave.wave_number % 2 == 1);
      ArrayResize(wave.targets, 7);
      for(int k = 0; k < 7; k++)
         wave.targets[k] = (wave.direction == "up") ?
            wave.wave_0_price + wave.wave_0_size * (k + 2) :
            wave.wave_0_price - wave.wave_0_size * (k + 2);
      wave.valid = true;
   }
}

//+------------------------------------------------------------------+
//| BOX MANAGEMENT                                                    |
//+------------------------------------------------------------------+
void RemoveBox(BoxState &boxes[], int &count, int idx) {
   for(int i = idx; i < count - 1; i++)
      boxes[i] = boxes[i + 1];
   count--;
}

void ProcessScale(BoxState &boxes[], int &num_boxes,
                  const MqlRates &m5[], int m5_count,
                  string scale, int max_boxes) {
   int total_open = CountAllPositions();
   if(total_open >= MAX_TOTAL_OPEN) return;

   double vib_q = (scale == "H1") ? (double)V_QUANTUM : (double)V_QUANTUM_M15;
   double lost_m = (scale == "H1") ? LOST_MOTION_H1 : LOST_MOTION_M15;
   int wave_mult = (scale == "H1") ? InpWaveMultH1 : InpWaveMultM15;
   double max_gap = vib_q * 6.0;
   int quant_window = (scale == "H1") ? 50 : 30;

   // Process existing boxes (reverse iteration for removal)
   for(int i = num_boxes - 1; i >= 0; i--) {
      // Expired?
      if(boxes[i].state == 0) {  // QUANT_FORMING
         if(g_m5_count - boxes[i].convergence_bar > quant_window) {
            RemoveBox(boxes, num_boxes, i);
            continue;
         }
      }
      else if(boxes[i].state == 1) {  // BOX_ACTIVE
         if(boxes[i].has_box && g_m5_count > boxes[i].box.end_bar) {
            RemoveBox(boxes, num_boxes, i);
            continue;
         }
      }
      else {  // DONE
         RemoveBox(boxes, num_boxes, i);
         continue;
      }

      // Process QUANT_FORMING
      if(boxes[i].state == 0) {
         int bars_since = g_m5_count - boxes[i].convergence_bar;
         GannBox new_box;
         if(MeasureQuant(m5, bars_since, m5_count, vib_q, quant_window, new_box)) {
            boxes[i].box = new_box;
            boxes[i].has_box = true;
            boxes[i].state = 1;
            Print(scale, " Box: $", DoubleToString(new_box.bottom,2), "-$",
                  DoubleToString(new_box.top,2), " w=", new_box.width);
         }
      }
      // Process BOX_ACTIVE
      else if(boxes[i].state == 1 && boxes[i].has_box) {
         total_open = CountAllPositions();  // refresh
         if(total_open >= MAX_TOTAL_OPEN) continue;
         if(g_dailyTrades >= InpMaxDaily) continue;
         if(g_m5_count < boxes[i].box.green_start) continue;

         // M15 requires H1 direction clear
         if(scale == "M15" && g_h1_wave_direction == "flat") continue;

         double current_price = m5[1].close;
         double entry_price, sl_price, tp_price;
         string trade_dir;

         if(FindGreenZoneEntry(boxes[i].box, current_price, lost_m,
                               wave_mult, max_gap,
                               entry_price, sl_price, tp_price, trade_dir)) {
            double sl_dist = MathAbs(entry_price - sl_price);
            ENUM_ORDER_TYPE type = (trade_dir == "long") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;

            if(OpenTrade(type, sl_price, tp_price, scale, entry_price, sl_dist)) {
               g_dailyTrades++;
               boxes[i].state = 2;  // DONE
               Print(scale, " Trade #", g_dailyTrades, " today");
            }
         }
      }
   }

   // Scan for new convergence
   if(num_boxes >= max_boxes) return;
   if(g_dailyTrades >= InpMaxDaily) return;

   double current_price = m5[1].close;
   SwingPoint &swings[] = (scale == "H1") ? g_swings_h1 : g_swings_m15;
   int n_swings = ArraySize(swings);
   if(n_swings < 4) return;

   // M15 needs H1 direction
   if(scale == "M15" && g_h1_wave_direction == "flat") return;

   GannBox dummy_box;
   int score = ScoreConvergence(current_price, g_m5_count,
                                swings, n_swings,
                                g_swings_h4, ArraySize(g_swings_h4),
                                vib_q, lost_m,
                                false, dummy_box, false);

   if(score >= InpMinConvScan) {
      // Check spacing
      bool is_new = true;
      for(int j = 0; j < num_boxes; j++) {
         double center = boxes[j].has_box ?
            (boxes[j].box.top + boxes[j].box.bottom) / 2.0 :
            boxes[j].convergence_price;
         if(MathAbs(current_price - center) < vib_q) {
            is_new = false; break;
         }
      }
      if(is_new && num_boxes < max_boxes) {
         boxes[num_boxes].state = 0;
         boxes[num_boxes].convergence_bar = g_m5_count;
         boxes[num_boxes].convergence_price = current_price;
         boxes[num_boxes].convergence_score = score;
         boxes[num_boxes].has_box = false;
         num_boxes++;
         Print(scale, " Convergence: score=", score,
               " @$", DoubleToString(current_price,2));
      }
   }
}

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit() {
   if(StringFind(_Symbol, "XAU") < 0 && StringFind(_Symbol, "GOLD") < 0)
      Print("WARNING: EA designed for XAUUSD, running on ", _Symbol);

   Print("=== GannScalper v9.2 Multi-Scale + Auto-Scaling ===");
   Print("H1: conv=", InpMinConvScan, " wave_mult=", InpWaveMultH1,
         " spread=$", InpMaxSpreadH1);
   Print("M15: enabled=", InpEnableM15, " wave_mult=", InpWaveMultM15,
         " spread=$", InpMaxSpreadM15);
   Print("R:R min=", InpMinRR, " Trail@", InpTrailAtR, "R");

   // Force load MTF data
   iClose(_Symbol, PERIOD_H1, 0);
   iClose(_Symbol, PERIOD_H4, 0);
   iClose(_Symbol, PERIOD_D1, 0);
   if(InpEnableM15) iClose(_Symbol, PERIOD_M15, 0);

   g_numH1Boxes = 0;
   g_numM15Boxes = 0;
   g_wave_h1.valid = false;
   g_wave_m15.valid = false;
   g_peakBalance = AccountInfoDouble(ACCOUNT_BALANCE);

   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   Print("GannScalper v9.2 stopped. Reason=", reason,
         " DailyTrades=", g_dailyTrades,
         " H1Boxes=", g_numH1Boxes, " M15Boxes=", g_numM15Boxes);
}

//+------------------------------------------------------------------+
//| OnTick — MAIN LOOP                                                |
//+------------------------------------------------------------------+
void OnTick() {
   if(!IsNewBar_M5()) return;
   g_m5_count++;

   // Daily reset
   datetime today = iTime(_Symbol, PERIOD_D1, 0);
   if(today != g_lastTradeDay) {
      g_lastTradeDay = today;
      g_dailyTrades = 0;
   }

   // Load M5 data
   MqlRates m5[];
   ArraySetAsSeries(m5, true);
   int m5_count = CopyRates(_Symbol, PERIOD_M5, 0, 500, m5);
   if(m5_count < 100) return;

   // Update swings periodically
   if(g_m5_count % 12 == 0)
      UpdateSwings();

   // Manage positions
   ManagePositions();

   // Spread check per scale
   double spread = SymbolInfoDouble(_Symbol, SYMBOL_ASK) -
                   SymbolInfoDouble(_Symbol, SYMBOL_BID);
   bool h1_spread_ok  = spread <= InpMaxSpreadH1;
   bool m15_spread_ok = spread <= InpMaxSpreadM15;

   // Process H1 boxes
   if(h1_spread_ok)
      ProcessScale(g_h1Boxes, g_numH1Boxes, m5, m5_count, "H1", MAX_H1_BOXES);

   // Process M15 boxes (only if enabled and H1 direction clear)
   if(InpEnableM15 && m15_spread_ok && g_h1_wave_direction != "flat")
      ProcessScale(g_m15Boxes, g_numM15Boxes, m5, m5_count, "M15", MAX_M15_BOXES);

   // Clean up stale trail tracking
   for(int i = ArraySize(g_trails) - 1; i >= 0; i--) {
      bool found = false;
      for(int p = 0; p < PositionsTotal(); p++) {
         if(PositionGetSymbol(p) == _Symbol &&
            PositionGetInteger(POSITION_TICKET) == (long)g_trails[i].ticket) {
            found = true; break;
         }
      }
      if(!found) {
         for(int j = i; j < ArraySize(g_trails) - 1; j++)
            g_trails[j] = g_trails[j + 1];
         ArrayResize(g_trails, ArraySize(g_trails) - 1);
      }
   }
}
