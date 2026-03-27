# Phase 2: Signal Pipeline and Decision Fusion - Research

**Researched:** 2026-03-27
**Domain:** Nonlinear dynamics, order flow microstructure, signal fusion, market regime detection
**Confidence:** MEDIUM-HIGH (algorithms well-established; Feigenbaum and quantum timing are novel applications without reference implementations)

## Summary

Phase 2 builds four analysis modules (chaos/regime, order flow, institutional footprint, quantum timing) and a decision fusion core on top of the Phase 1 trading infrastructure. The core scientific computing stack (NumPy 2.4.3, SciPy 1.17.1, Numba 0.64.0) is already specified in CLAUDE.md. The nolds library (0.6.3) provides reference implementations for Hurst exponent, Lyapunov exponents (Rosenstein and Eckmann algorithms), correlation dimension, DFA, and sample entropy -- these serve as the starting point, with Numba-JIT reimplementations for production-speed hot paths.

The architecture integrates into the existing TradingEngine via a new `_signal_loop()` added to `asyncio.gather()`. Each signal module implements a common `SignalModule` Protocol producing a `SignalOutput` frozen dataclass with score, confidence, and metadata. The fusion core combines these using the confidence-weighted blend described in D-01 through D-05, with EMA-based adaptive weights tracking module accuracy over a rolling window. Numba-heavy chaos computations run via `asyncio.to_thread()` following the established pattern for blocking work.

Two areas carry elevated risk: Feigenbaum bifurcation detection in financial time series has no reference implementations (STATE.md blocker), and the "quantum timing" concept is a novel abstraction that must be grounded in concrete mathematics (Ornstein-Uhlenbeck mean-reversion timing, volatility energy representations, phase-transition probability modeling). Both start simplified and can deepen in later phases.

**Primary recommendation:** Build four signal modules behind a common Protocol interface, integrate via a new signal analysis loop in TradingEngine, and implement the confidence-weighted fusion core. Use nolds for reference algorithms, Numba for hot paths, and keep Feigenbaum/quantum timing deliberately simple in v1.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Confidence-weighted blend for signal fusion. Each module outputs a score + confidence. Fusion multiplies score x confidence x adaptive weight. Highest composite wins direction. Transparent and debuggable.
- **D-02:** Adaptive weights use exponential moving average (EMA) of module accuracy over a rolling window (e.g., last 50 trades). Weights decay smoothly when a module is wrong, recover gradually when right. No sudden weight flips.
- **D-03:** Configurable minimum fused confidence threshold below which no trade fires, even if signals align. Prevents low-conviction trades.
- **D-04:** Confidence threshold varies by capital phase: aggressive ($20-$100) uses lower threshold (e.g., 0.5) for more trade frequency; conservative ($300+) uses higher threshold (e.g., 0.7) to protect capital. Aligns with three-phase risk model from Phase 1.
- **D-05:** Fusion weights adapt purely from accuracy (EMA), NOT from regime state. No hardcoded regime-to-weight mappings. If chaos is accurate during trends, its weight naturally rises. Regime is context for behavior, not for weight overrides.
- **D-06:** In high-chaos or pre-bifurcation regimes: reduce activity, don't stop. Raise the confidence threshold, widen SL distances, reduce position size. The bot still trades on very high-conviction signals.
- **D-07:** In ranging regimes: let fusion decide. No hardcoded ranging behavior (no forced mean-reversion or sitting out). If order flow and quantum timing produce high-confidence signals in a range, trade them. Regime is context, not a veto.
- **D-08:** On adverse regime transition with open position: tighten stops to lock in profit or reduce loss. Don't force-close -- let the tightened SL do its job.
- **D-09:** Dynamic risk-reward ratio based on regime: trending = 3:1 RR, ranging = 1.5:1 RR, high-chaos = 2:1 RR. SL distance from ATR x chaos-aware multiplier, TP = SL x RR ratio.
- **D-10:** Regime-aware trailing stops. In trending regime: activate trailing stop after price moves 1x SL distance in profit (trail at 0.5x ATR). In ranging: no trailing, use fixed TP. In high-chaos: aggressive trail (0.3x ATR) to lock in quickly.
- **D-11:** One position at a time. Simpler risk management, clearer P&L attribution, easier to debug. At $20 starting capital, multiple positions would over-leverage.
- **D-12:** Quantum timing has no veto or delay power over entry. Timing contributes to the confidence-weighted blend like any other module. Low timing confidence reduces overall score but doesn't delay or block entries.
- **D-13:** Tick-first, DOM as enhancement. Build order flow primarily on tick data (volume delta, bid-ask aggression, tick velocity). DOM analysis is an optional layer that activates when available and passes quality checks. ~80% tick / ~20% DOM effort split.
- **D-14:** Institutional footprint detection uses both statistical anomaly detection AND volume profile clustering from tick data. Statistical signatures: large volume without price movement (absorption), repeated volume at same price level (iceberg reload), volume spikes with spread widening (HFT). Volume-at-price profiles identify institutional levels as high-volume nodes.
- **D-15:** DOM quality auto-detection on startup. Sample DOM snapshots for ~60 seconds. If depth >= 5 levels on both sides and updates >= 1/sec, enable DOM analysis. Re-check periodically. Auto-disable if quality degrades, with logging.

### Claude's Discretion
- Signal module abstract interface design (ABC/Protocol patterns)
- New package structure under `src/fxsoqqabot/signals/`
- Chaos analysis algorithm selection (Rosenstein vs Eckmann for Lyapunov, etc.)
- Quantum timing simplified implementation approach
- Pydantic config model structure for signal modules
- SQLite schema extensions for signal state persistence
- Integration pattern into TradingEngine (new loop vs inline processing)
- ATR computation approach and lookback periods
- Feigenbaum bifurcation detection algorithm design
- Crowd entropy statistical mechanics implementation

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CHAOS-01 | Rolling Hurst Exponent for trend/mean-reversion/random walk classification | nolds.hurst_rs and nolds.dfa provide reference; Numba reimplementation for speed |
| CHAOS-02 | Lyapunov Exponent for dynamical stability measurement | nolds.lyap_r (Rosenstein algorithm) recommended over lyap_e for robustness |
| CHAOS-03 | Fractal Dimension for complexity measurement | nolds.corr_dim (Grassberger-Procaccia) with embedding dimension selection |
| CHAOS-04 | Feigenbaum bifurcation proximity via period-doubling ratios | Novel implementation: detect period-doubling in price oscillation peaks/troughs, measure ratio convergence toward delta=4.669 |
| CHAOS-05 | Crowd entropy through statistical mechanics | Shannon entropy on return distribution + sample entropy on price series; entropy spikes signal crowd panic/euphoria |
| CHAOS-06 | Discrete regime classification with confidence levels | Combine CHAOS-01 through CHAOS-05 outputs via threshold-based classifier into 5 regimes |
| FLOW-01 | Cumulative volume delta from tick data | Classify each tick as buy/sell from bid/ask comparison, accumulate delta over rolling window |
| FLOW-02 | Bid-ask aggression imbalance detection | Ratio of volume hitting ask vs bid over sliding window; z-score for significance |
| FLOW-03 | DOM depth analysis when available | Parse DOMSnapshot entries for weight distribution, large orders, liquidity absorption |
| FLOW-04 | Institutional footprint detection | Statistical anomaly (absorption, iceberg reload) + volume profile clustering per D-14 |
| FLOW-05 | HFT acceleration signatures | Tick velocity spikes, spread widening + volume spikes, distinguish from retail noise |
| FLOW-06 | Graceful degradation tick-only vs DOM | DOM quality check per D-15; disable DOM signals when unavailable, full functionality on tick data |
| QTIM-01 | Price-time coupled state modeling with probability-weighted windows | OU process for mean-reversion timing; volatility-adjusted probability windows |
| QTIM-02 | Timing estimation for move begin/end | Phase transition detection from volatility compression/expansion; energy representation |
| QTIM-03 | Probability weights and confidence intervals on timing windows | Bootstrap confidence intervals on OU parameter estimates; output probability distributions |
| FUSE-01 | Confidence-weighted fusion of all upstream modules | score x confidence x adaptive_weight per D-01; composite score determines direction |
| FUSE-02 | Adaptive module weights via rolling accuracy EMA | EMA(alpha) on binary accuracy over last N trades per D-02; normalize weights |
| FUSE-03 | Phase-aware position sizing integration | Connect to existing PositionSizer; vary confidence threshold by phase per D-04 |
| FUSE-04 | Smooth capital phase transitions | Sigmoid or linear interpolation between phase behaviors at equity boundaries per D-04 |
| FUSE-05 | Trade firing with entry/SL/TP and position management | Use OrderManager.place_market_order(); regime-aware SL/TP per D-09/D-10; trailing stops |
</phase_requirements>

## Standard Stack

### Core (already in CLAUDE.md -- use these exact versions)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| NumPy | 2.4.3 | Array operations, FFT, linear algebra | Already installed. Foundation for all signal computation. |
| SciPy | 1.17.1 | Signal processing, ODE solvers, statistics | Welch PSD, entropy functions, OU parameter estimation. Must add to pyproject.toml. |
| Numba | 0.64.0 | JIT compilation for hot loops | Lyapunov, Hurst, fractal dimension inner loops need 10-30x speedup. Must add to pyproject.toml. |
| nolds | 0.6.3 | Reference implementations for nonlinear dynamics | Hurst (hurst_rs), Lyapunov (lyap_r, lyap_e), correlation dimension (corr_dim), DFA, sample entropy. Use as reference, then Numba-ify hot paths. Must add to pyproject.toml. |
| scikit-learn | 1.8.0 | Regime classification | Not needed in Phase 2 v1 -- threshold-based regime classifier is sufficient. Add when LEARN-03 requires it in Phase 4. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| aiosqlite | 0.22.1 | Async SQLite for signal state persistence | Already installed. Extend StateManager with signal state tables. |
| structlog | 25.5.0 | Structured logging with context binding | Already installed. Bind regime state, signal scores to log context. |
| Pydantic | 2.12.5 | Config validation for signal modules | Already installed. New config models for chaos, flow, timing, fusion parameters. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| nolds for reference | EntropyHub or NeuroKit2 | Heavier dependencies; nolds is numpy-only, fits our stack. Use nolds. |
| Threshold-based regime classifier | scikit-learn RandomForest | Overkill for 5 discrete regimes with clear thresholds. Defer ML classification to Phase 4. |
| Custom Numba Lyapunov | nolds.lyap_r directly | nolds is pure Python loops -- too slow for real-time on 10000+ tick buffers. Use nolds for validation, Numba for production. |
| SciPy for OU estimation | statsmodels | statsmodels adds heavy dependency; OU parameter estimation is simple OLS on log prices with scipy.optimize. |

### Installation

New dependencies to add to `pyproject.toml`:
```toml
[project]
dependencies = [
    # ... existing ...
    "scipy>=1.17",
    "numba>=0.64",
    "nolds>=0.6.3",
]
```

```bash
uv sync
```

**Version verification:** NumPy 2.4.3 confirmed installed. SciPy 1.17.1, Numba 0.64.0, nolds 0.6.3 confirmed available on PyPI per CLAUDE.md. Numba 0.64 explicitly supports NumPy 2.x per CLAUDE.md compatibility table.

## Architecture Patterns

### Recommended Project Structure
```
src/fxsoqqabot/
├── signals/                    # NEW: Signal pipeline package
│   ├── __init__.py
│   ├── base.py                 # SignalModule Protocol + SignalOutput dataclass
│   ├── chaos/                  # Chaos & regime detection module
│   │   ├── __init__.py
│   │   ├── module.py           # ChaosRegimeModule (implements SignalModule)
│   │   ├── hurst.py            # Rolling Hurst exponent computation
│   │   ├── lyapunov.py         # Lyapunov exponent (Rosenstein)
│   │   ├── fractal.py          # Fractal dimension (correlation dimension)
│   │   ├── feigenbaum.py       # Bifurcation proximity detection
│   │   ├── entropy.py          # Crowd entropy (Shannon + sample entropy)
│   │   └── regime.py           # Regime classifier combining all chaos metrics
│   ├── flow/                   # Order flow & institutional detection
│   │   ├── __init__.py
│   │   ├── module.py           # OrderFlowModule (implements SignalModule)
│   │   ├── volume_delta.py     # Cumulative volume delta
│   │   ├── aggression.py       # Bid-ask aggression imbalance
│   │   ├── dom_analyzer.py     # DOM depth analysis (optional layer)
│   │   ├── institutional.py    # Institutional footprint detection
│   │   └── dom_quality.py      # DOM quality auto-detection per D-15
│   ├── timing/                 # Quantum timing engine
│   │   ├── __init__.py
│   │   ├── module.py           # QuantumTimingModule (implements SignalModule)
│   │   ├── ou_model.py         # Ornstein-Uhlenbeck mean-reversion timing
│   │   └── phase_transition.py # Volatility compression/expansion detection
│   └── fusion/                 # Decision fusion core
│       ├── __init__.py
│       ├── core.py             # FusionCore: combines all signals per D-01
│       ├── weights.py          # Adaptive EMA weight tracker per D-02
│       ├── trade_manager.py    # Trade execution: entry/SL/TP/trailing per D-09/D-10
│       └── phase_behavior.py   # Capital phase behavior transitions per D-04/D-06
├── config/
│   └── models.py               # Extended with ChaosConfig, FlowConfig, TimingConfig, FusionConfig
└── core/
    ├── engine.py               # Extended with _signal_loop()
    └── state.py                # Extended with signal state tables
```

### Pattern 1: SignalModule Protocol

**What:** Structural typing Protocol defining the contract for all signal modules. Each module takes market data, returns a SignalOutput with score and confidence.

**When to use:** Every signal module (chaos, flow, timing) implements this Protocol.

**Example:**
```python
# src/fxsoqqabot/signals/base.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

@dataclass(frozen=True, slots=True)
class SignalOutput:
    """Output from any signal module."""
    module_name: str           # "chaos", "flow", "timing"
    direction: float           # -1.0 (sell) to +1.0 (buy), 0.0 = neutral
    confidence: float          # 0.0 to 1.0
    regime: str | None = None  # Current regime classification (chaos module only)
    metadata: dict = field(default_factory=dict)  # Module-specific debug info
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

@runtime_checkable
class SignalModule(Protocol):
    """Protocol for all signal analysis modules."""
    @property
    def name(self) -> str: ...

    async def update(
        self,
        tick_arrays: dict[str, np.ndarray],
        bar_arrays: dict[str, dict[str, np.ndarray]],
        dom: DOMSnapshot | None,
    ) -> SignalOutput: ...

    async def initialize(self) -> None: ...
```

**Why Protocol over ABC:** The existing codebase uses structural typing patterns (TYPE_CHECKING imports, duck typing). Protocol avoids import coupling and forced inheritance hierarchies. Use `@runtime_checkable` for optional isinstance checks.

### Pattern 2: asyncio.to_thread for Numba-JIT Computation

**What:** Wrap blocking Numba-compiled chaos computations in asyncio.to_thread() to avoid blocking the event loop.

**When to use:** Any computation that takes >1ms (Lyapunov, Hurst, fractal dimension on 1000+ point series).

**Example:**
```python
# In chaos module.py
async def update(self, tick_arrays, bar_arrays, dom):
    close_prices = bar_arrays["M1"]["close"]
    # Run Numba-JIT computation off the event loop
    hurst_val = await asyncio.to_thread(compute_hurst_numba, close_prices)
    lyap_val = await asyncio.to_thread(compute_lyap_r_numba, close_prices)
    # ... combine into SignalOutput
```

### Pattern 3: Frozen Dataclass Events for Signals

**What:** Follow the Phase 1 pattern of frozen dataclasses with `__slots__` for all new event/data types.

**When to use:** SignalOutput, RegimeState, FusionResult, TradeDecision.

### Pattern 4: New Signal Loop in TradingEngine

**What:** Add `_signal_loop()` to the engine's asyncio.gather() alongside tick/bar/health loops. This loop runs signal analysis after each bar refresh cycle.

**When to use:** Regime detection operates on bar data (M1/M5 timeframes). Order flow operates on tick data. Timing integrates both.

**Example:**
```python
# In engine.py start()
await asyncio.gather(
    self._tick_loop(),
    self._bar_loop(),
    self._health_loop(),
    self._signal_loop(),  # NEW
)
```

The signal loop orchestrates: (1) update all signal modules, (2) fuse signals, (3) check if trade decision exceeds threshold, (4) execute trade if conditions met.

### Anti-Patterns to Avoid
- **Module vetoing:** No module has veto power (per D-07, D-12). Every module contributes to the blend.
- **Regime-to-weight hardcoding:** Regime does NOT override fusion weights (per D-05). Regime only adjusts behavior parameters (confidence threshold, SL width, RR ratio).
- **Blocking the event loop:** Never run nolds/Numba functions directly in async context. Always `asyncio.to_thread()`.
- **Over-engineering Feigenbaum:** No reference implementation exists. Start with the simplest period-doubling detection possible. The research confirms universality of the 4.669 constant but no financial market implementations exist.
- **Indicator soup:** Do NOT add RSI, MACD, Bollinger Bands (per CLAUDE.md "What NOT to Use" -- indicator soup with correlated price-derived indicators).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Hurst exponent | Custom rescaled range analysis | nolds.hurst_rs (reference) + Numba reimplementation (production) | Anis-Lloyd-Peters correction and RANSAC fitting are non-trivial to get right |
| Lyapunov exponent | Custom phase space reconstruction | nolds.lyap_r (Rosenstein algorithm) + Numba reimplementation | Embedding dimension selection, temporal separation, trajectory following are complex |
| Fractal dimension | Custom Grassberger-Procaccia | nolds.corr_dim (reference) + Numba reimplementation | Distance threshold selection and scaling region identification need robust fitting |
| Sample entropy | Custom template matching | nolds.sampen (reference) | Tolerance auto-scaling (0.2 * std) is standard but easy to get wrong |
| ATR (Average True Range) | Custom ATR from scratch | Simple vectorized NumPy computation | It's 5 lines of NumPy, but use the standard Wilder smoothing formula exactly |
| Shannon entropy on returns | Custom entropy | scipy.stats.entropy | Handles edge cases (zero probabilities, normalization) correctly |
| OU parameter estimation | Custom MLE | scipy.optimize.minimize with OLS initial estimates | Closed-form OLS works for discrete observations; MLE refines |

**Key insight:** nolds provides battle-tested reference implementations for all chaos metrics. Use them for correctness validation. Build Numba-JIT versions for the hot paths that must run in real-time (<10ms per update cycle). Keep the nolds versions as unit test oracles.

## Common Pitfalls

### Pitfall 1: Numba Compilation Latency on First Call
**What goes wrong:** First call to a @njit function triggers compilation, taking 1-10 seconds. In a trading loop, this causes the first signal update to be drastically slow.
**Why it happens:** Numba JIT compiles on first invocation with concrete types.
**How to avoid:** Call all Numba functions with representative data during `initialize()` to trigger compilation before the trading loop starts. Use `@njit(cache=True)` to persist compiled code across restarts.
**Warning signs:** First signal update taking >1 second in logs.

### Pitfall 2: Insufficient Data for Chaos Metrics
**What goes wrong:** Hurst exponent, Lyapunov exponent, and fractal dimension need minimum data lengths (typically 100-500 points) to produce meaningful results. On bot startup, buffers are empty.
**Why it happens:** nolds functions return garbage or raise on short series.
**How to avoid:** Each chaos metric must have a `min_data_length` check. Return `SignalOutput(confidence=0.0)` until sufficient data accumulates. Use `nolds.lyap_r_len()` and `nolds.lyap_e_len()` helper functions to compute minimum required lengths for given parameters.
**Warning signs:** Wild oscillations in regime classification during the first minutes of operation.

### Pitfall 3: Volume Delta Sign Convention in Forex
**What goes wrong:** Forex tick data from MT5 does not have a clear "trade at bid" vs "trade at ask" distinction like futures. Volume delta classification is approximate.
**Why it happens:** Forex is OTC -- RoboForex ECN provides aggregated volume, not exchange-level last-sale data. The `flags` field in ticks and the relationship between `last` price and bid/ask must be used heuristically.
**How to avoid:** Classify ticks as buy-initiated if last >= ask (lifting the offer) and sell-initiated if last <= bid (hitting the bid). Ticks between bid and ask are ambiguous -- split 50/50 or ignore. Document the heuristic clearly.
**Warning signs:** Volume delta always positive or always negative (sign convention error).

### Pitfall 4: Numba Type Restrictions
**What goes wrong:** Numba @njit does not support all Python types -- no dicts, no strings, no Pydantic models, no dataclasses inside JIT functions.
**Why it happens:** Numba compiles a subset of Python to LLVM IR. Only NumPy arrays and primitive types are supported.
**How to avoid:** Structure code so that Numba functions take only numpy arrays and scalar arguments. All type conversion happens outside the @njit boundary. Return tuples or numpy arrays from Numba functions, convert to dataclasses/dicts in the calling code.
**Warning signs:** Numba compilation errors mentioning "Unsupported type."

### Pitfall 5: Overfitting Chaos Parameters to XAUUSD
**What goes wrong:** Tuning embedding dimension, lag, trajectory length specifically for gold price dynamics creates parameters that only work in current market conditions.
**Why it happens:** Chaos metrics are sensitive to parameter choice. Optimizing for recent data overfits.
**How to avoid:** Use default nolds parameters as starting point. Make all parameters configurable via TOML. Log parameter sensitivity in development. The self-learning loop (Phase 4) will adapt these -- Phase 2 uses sensible defaults.
**Warning signs:** Regime classification accuracy degrades over days/weeks without parameter changes.

### Pitfall 6: EMA Weight Initialization Cold Start
**What goes wrong:** Adaptive weights (D-02) need trade outcome history to compute accuracy. On fresh start, all weights are equal but uninformed.
**Why it happens:** EMA of accuracy requires a rolling window of past trade results.
**How to avoid:** Initialize all module weights equally (1/N). Persist weight state to SQLite via StateManager so weights survive restarts. Use a warm-up period of ~10 trades before weights meaningfully diverge.
**Warning signs:** Sudden strategy changes after restarting the bot (weight state lost).

### Pitfall 7: Blocking Signal Computation Starving Tick Loop
**What goes wrong:** If signal computation takes too long, the tick loop is starved (both run in the same event loop).
**Why it happens:** asyncio.gather runs coroutines cooperatively. A long-running computation blocks other tasks.
**How to avoid:** Signal computation runs in a thread via asyncio.to_thread(). Add timing instrumentation to signal updates. Set a hard time budget (e.g., 50ms per module) -- if exceeded, log warning and skip the update cycle.
**Warning signs:** Tick data gaps or increasing buffer staleness during active signal computation.

## Code Examples

### Hurst Exponent (Reference with nolds)
```python
# Source: nolds docs https://cschoel.github.io/nolds/nolds.html
import nolds
import numpy as np

def compute_hurst(close_prices: np.ndarray) -> tuple[float, float]:
    """Compute Hurst exponent with confidence indicator.

    Returns (hurst_value, confidence) where confidence is based on
    data length relative to minimum required.
    """
    min_len = 100  # Practical minimum for rescaled range
    if len(close_prices) < min_len:
        return 0.5, 0.0  # Random walk assumption, zero confidence

    h = nolds.hurst_rs(close_prices, corrected=True, unbiased=True)

    # Confidence scales with data length up to 1.0 at 500+ points
    confidence = min(1.0, len(close_prices) / 500.0)
    return h, confidence
```

### Lyapunov Exponent (Rosenstein -- recommended over Eckmann)
```python
# Source: nolds docs - lyap_r is more robust to parameter choices
import nolds

def compute_lyapunov(close_prices: np.ndarray, emb_dim: int = 10) -> tuple[float, float]:
    """Compute largest Lyapunov exponent via Rosenstein algorithm.

    Positive = chaotic/unstable, Negative = stable/convergent, ~0 = neutral.
    """
    min_len = nolds.lyap_r_len(emb_dim=emb_dim, trajectory_len=20)
    if len(close_prices) < min_len:
        return 0.0, 0.0

    lyap = nolds.lyap_r(close_prices, emb_dim=emb_dim, fit="RANSAC")
    confidence = min(1.0, len(close_prices) / (min_len * 3))
    return lyap, confidence
```

### Volume Delta from Tick Data
```python
# Source: Order flow analysis literature + MT5 tick flag analysis
import numpy as np

def compute_volume_delta(
    bid: np.ndarray, ask: np.ndarray, last: np.ndarray,
    volume_real: np.ndarray
) -> tuple[float, float, float]:
    """Compute cumulative volume delta from tick arrays.

    Classifies ticks as buy-initiated (last >= ask) or sell-initiated (last <= bid).
    Returns (cumulative_delta, buy_volume, sell_volume).
    """
    buy_mask = last >= ask  # Lifting the offer
    sell_mask = last <= bid  # Hitting the bid
    # Ticks between bid and ask are ambiguous -- ignore

    buy_volume = float(np.sum(volume_real[buy_mask]))
    sell_volume = float(np.sum(volume_real[sell_mask]))
    cumulative_delta = buy_volume - sell_volume

    return cumulative_delta, buy_volume, sell_volume
```

### ATR Computation (Wilder smoothing)
```python
import numpy as np

def compute_atr(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14
) -> np.ndarray:
    """Compute Average True Range with Wilder smoothing.

    Uses the standard Wilder (exponential) smoothing method.
    """
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]

    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
    )

    # Wilder smoothing: ATR = prev_ATR * (period-1)/period + TR/period
    atr = np.empty_like(tr)
    atr[:period] = np.mean(tr[:period])  # Simple average for initial
    for i in range(period, len(tr)):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period

    return atr
```

### Confidence-Weighted Fusion (per D-01)
```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class FusionResult:
    direction: float       # -1.0 to +1.0
    composite_score: float # Fused confidence-weighted score
    should_trade: bool     # Exceeds threshold for current capital phase
    sl_distance: float     # ATR-based, regime-adjusted
    tp_distance: float     # SL x RR ratio per regime
    regime: str            # Current regime classification
    module_scores: dict    # Individual module contributions

def fuse_signals(
    signals: list[SignalOutput],
    weights: dict[str, float],  # Module name -> adaptive weight
    confidence_threshold: float,
) -> FusionResult:
    """Fuse signals per D-01: score x confidence x adaptive_weight."""
    weighted_scores = []
    total_weight = 0.0

    for sig in signals:
        w = weights.get(sig.module_name, 1.0)
        weighted_score = sig.direction * sig.confidence * w
        weighted_scores.append(weighted_score)
        total_weight += sig.confidence * w

    if total_weight == 0:
        composite = 0.0
    else:
        composite = sum(weighted_scores) / total_weight

    fused_confidence = total_weight / len(signals) if signals else 0.0
    should_trade = abs(composite) > 0 and fused_confidence >= confidence_threshold

    direction = 1.0 if composite > 0 else (-1.0 if composite < 0 else 0.0)
    return FusionResult(
        direction=direction,
        composite_score=composite,
        should_trade=should_trade,
        # sl_distance, tp_distance, regime filled by caller
        sl_distance=0.0, tp_distance=0.0, regime="",
        module_scores={s.module_name: s.direction * s.confidence for s in signals},
    )
```

### Adaptive EMA Weight Tracker (per D-02)
```python
class AdaptiveWeightTracker:
    """Track module accuracy with EMA and compute adaptive weights per D-02."""

    def __init__(self, module_names: list[str], alpha: float = 0.1, window: int = 50):
        self._alpha = alpha  # EMA decay factor
        self._accuracies = {name: 0.5 for name in module_names}  # Start at 50%
        self._trade_count = 0

    def record_outcome(self, module_signals: dict[str, float], actual_direction: float):
        """Update accuracy EMA after trade outcome.

        actual_direction: +1.0 if trade was profitable, -1.0 if loss.
        """
        self._trade_count += 1
        for name, predicted in module_signals.items():
            correct = 1.0 if (predicted * actual_direction > 0) else 0.0
            old = self._accuracies[name]
            self._accuracies[name] = self._alpha * correct + (1 - self._alpha) * old

    def get_weights(self) -> dict[str, float]:
        """Return normalized weights proportional to accuracy."""
        total = sum(self._accuracies.values())
        if total == 0:
            n = len(self._accuracies)
            return {name: 1.0 / n for name in self._accuracies}
        return {name: acc / total for name, acc in self._accuracies.items()}
```

### Simplified Feigenbaum Bifurcation Proximity
```python
import numpy as np
from scipy.signal import argrelextrema

FEIGENBAUM_DELTA = 4.669201609  # Universal constant

def detect_bifurcation_proximity(
    close_prices: np.ndarray, order: int = 5
) -> tuple[float, float]:
    """Detect period-doubling bifurcation proximity.

    Measures ratio of successive peak/trough intervals.
    If ratio approaches Feigenbaum delta (4.669), regime transition is imminent.

    Returns (proximity_score, confidence) where proximity_score 0.0-1.0
    indicates how close to bifurcation.
    """
    if len(close_prices) < 50:
        return 0.0, 0.0

    # Find local maxima (peaks)
    maxima_idx = argrelextrema(close_prices, np.greater, order=order)[0]
    if len(maxima_idx) < 4:
        return 0.0, 0.0

    # Compute intervals between successive peaks
    intervals = np.diff(maxima_idx).astype(float)
    if len(intervals) < 3:
        return 0.0, 0.0

    # Compute ratios of successive interval differences
    # Period doubling: intervals should show ratio approaching delta
    ratios = []
    for i in range(len(intervals) - 2):
        diff1 = abs(intervals[i] - intervals[i+1])
        diff2 = abs(intervals[i+1] - intervals[i+2])
        if diff2 > 0:
            ratios.append(diff1 / diff2)

    if not ratios:
        return 0.0, 0.0

    # How close is the average ratio to Feigenbaum delta?
    avg_ratio = np.mean(ratios)
    proximity = 1.0 - min(1.0, abs(avg_ratio - FEIGENBAUM_DELTA) / FEIGENBAUM_DELTA)
    confidence = min(1.0, len(ratios) / 10.0)  # More ratios = more confident

    return float(proximity), float(confidence)
```

### Simplified Quantum Timing (OU-based)
```python
import numpy as np
from scipy.optimize import minimize_scalar

def estimate_ou_parameters(
    prices: np.ndarray, dt: float = 1.0
) -> tuple[float, float, float, float]:
    """Estimate Ornstein-Uhlenbeck parameters from price series.

    dX = kappa * (theta - X) * dt + sigma * dW

    Returns (kappa, theta, sigma, confidence) where:
    - kappa: mean-reversion speed (higher = faster reversion)
    - theta: long-term mean level
    - sigma: volatility
    - confidence: quality of fit
    """
    if len(prices) < 30:
        return 0.0, float(np.mean(prices)), 0.0, 0.0

    # OLS estimation on discrete observations
    # X_{t+1} - X_t = kappa * (theta - X_t) * dt + noise
    x = prices[:-1]
    dx = np.diff(prices)

    # Linear regression: dx = a + b * x + noise
    # where a = kappa * theta * dt, b = -kappa * dt
    n = len(x)
    sx = np.sum(x)
    sx2 = np.sum(x ** 2)
    sdx = np.sum(dx)
    sxdx = np.sum(x * dx)

    denom = n * sx2 - sx ** 2
    if abs(denom) < 1e-10:
        return 0.0, float(np.mean(prices)), 0.0, 0.0

    b = (n * sxdx - sx * sdx) / denom
    a = (sdx - b * sx) / n

    kappa = -b / dt
    theta = a / (kappa * dt) if kappa > 0 else float(np.mean(prices))

    residuals = dx - (a + b * x)
    sigma = float(np.std(residuals)) / np.sqrt(dt)

    # Confidence: R-squared of the regression
    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((dx - np.mean(dx)) ** 2)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    confidence = max(0.0, min(1.0, r_squared))

    return float(kappa), float(theta), float(sigma), confidence
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pure technical indicators (RSI, MACD) | Nonlinear dynamics + order flow fusion | 2020s research trend | Orthogonal signals reduce false positives |
| Fixed fusion weights | Adaptive weights via rolling accuracy | Established in ML ensembles | Self-correcting when a module underperforms |
| Binary regime (trend/range) | Multi-state regime with confidence | Modern regime-switching literature | Captures pre-bifurcation and high-chaos states |
| nolds pure Python loops | Numba JIT for real-time computation | Numba matured ~2022-2024 | 10-30x speedup makes real-time chaos analysis feasible |
| ABC inheritance for interfaces | typing.Protocol structural subtyping | PEP 544 (Python 3.8+), mainstream by 3.12 | Looser coupling, no forced inheritance |

**Deprecated/outdated:**
- **Backtrader** for backtesting -- abandoned, breaks on modern Python. Use vectorbt (Phase 3).
- **TA-Lib** for indicators -- we explicitly avoid indicator soup per CLAUDE.md constraints.

## Open Questions

1. **Feigenbaum in financial data -- does it produce actionable signals?**
   - What we know: Feigenbaum's delta (4.669) is universal for period-doubling cascades in nonlinear systems. Academic papers confirm period-doubling exists in some financial models.
   - What's unclear: Whether real XAUUSD tick/bar data exhibits measurable period-doubling with enough regularity to generate signals. No reference implementations exist for financial markets.
   - Recommendation: Implement the simplest possible detector (peak interval ratios). Keep confidence low initially. Validate against historical data in Phase 3 backtesting. If it produces noise, it contributes near-zero weight via the adaptive EMA mechanism.

2. **Quantum timing -- what concrete math underpins "price-time coupled state variables"?**
   - What we know: The concept maps to Ornstein-Uhlenbeck mean-reversion timing (when will price return to mean?), volatility compression as "stored energy" (breakout timing), and phase-transition modeling from statistical mechanics.
   - What's unclear: The optimal formulation for XAUUSD scalping. This is a novel framing without established implementations.
   - Recommendation: Start with OU parameter estimation for mean-reversion timing plus volatility regime energy (ATR compression/expansion). Output probability windows based on OU expected hitting times. The "quantum" label is aspirational -- the math is classical stochastic processes dressed in physics language.

3. **Volume delta accuracy on forex ECN data**
   - What we know: MT5 TickEvent has bid, ask, last, volume, flags. Forex volume is not exchange-aggregated like futures.
   - What's unclear: How reliably RoboForex ECN reports last-trade prices relative to bid/ask for delta classification.
   - Recommendation: Build the delta computation. Log classification statistics (% buy vs sell vs ambiguous). If ambiguous fraction is >30%, reduce volume delta confidence score proportionally.

4. **Numba + nolds interaction**
   - What we know: nolds is pure Python/NumPy. Numba @njit requires NumPy-only code.
   - What's unclear: Whether we can simply wrap nolds algorithms with @njit or need full reimplementation.
   - Recommendation: Likely need full reimplementation for hot paths. nolds code structure (simple loops over numpy arrays) is Numba-friendly but uses Python features (dicts, debug flags) that @njit cannot handle. Plan for separate Numba implementations that produce identical outputs to nolds for given inputs (unit test oracle pattern).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All code | Yes (venv) | 3.12.13 | -- |
| NumPy | Chaos/flow/timing | Yes | 2.4.3 | -- |
| SciPy | Chaos (FFT, entropy), Timing (OU estimation) | No (not installed) | -- | Must add to pyproject.toml |
| Numba | Real-time chaos computation | No (not installed) | -- | Must add to pyproject.toml; fallback to pure Python (slow) |
| nolds | Reference chaos implementations | No (not installed) | -- | Must add to pyproject.toml |
| pandas | Data manipulation | Yes | 2.3.3 | -- |
| structlog | Logging | Yes | 25.5.0 | -- |
| Pydantic | Config validation | Yes | 2.12.5 | -- |
| aiosqlite | State persistence | Yes | 0.22.1 | -- |

**Missing dependencies with no fallback:**
- SciPy, Numba, nolds must be installed. These are `uv add` operations -- straightforward.

**Missing dependencies with fallback:**
- None. If Numba fails to install (rare on Windows), chaos computations can run via pure Python/nolds at reduced speed. This is acceptable for paper trading but not for live scalping.

## Project Constraints (from CLAUDE.md)

### Must Follow
- **Python 3.12.x** -- venv already set up correctly at 3.12.13
- **NumPy 2.4.3, SciPy 1.17.1, Numba 0.64.0** -- exact versions from CLAUDE.md stack
- **nolds 0.6.3** -- for reference chaos/fractal implementations
- **No TensorFlow, No PyTorch** for v1 -- scikit-learn if ML needed, but threshold-based classifier sufficient for Phase 2
- **No TA-Lib, no indicator soup** -- orthogonal signals only (chaos, flow, timing)
- **Frozen dataclasses with __slots__** for all events
- **asyncio.to_thread()** for all blocking operations (Numba JIT calls)
- **structlog** with context binding for all modules
- **Pydantic BaseModel** for config; extend existing hierarchy
- **SQLite WAL mode** for state persistence (extend StateManager)
- **pytest with pytest-asyncio** for testing
- **ruff** for linting, **mypy** for type checking
- **uv** for package management

### Forbidden
- Backtrader, TA-Lib, TensorFlow, PyTorch, Streamlit, MongoDB, Redis, Celery, ccxt
- Grid/martingale position management
- Indicator soup (RSI + MACD + Stochastic + Bollinger)
- Multiple positions at same time (per D-11)

## Sources

### Primary (HIGH confidence)
- [nolds documentation](https://cschoel.github.io/nolds/nolds.html) -- Full API reference for lyap_r, lyap_e, hurst_rs, corr_dim, dfa, sampen; parameter documentation and algorithm descriptions
- [nolds PyPI](https://pypi.org/project/nolds/) -- Version 0.6.3, numpy-only dependency, Python 2/3 compatible
- [nolds GitHub](https://github.com/CSchoel/nolds) -- Source code for algorithm verification
- [Numba performance docs](https://numba.readthedocs.io/en/stable/user/performance-tips.html) -- @njit, parallel=True, cache=True patterns
- [SciPy signal docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html) -- Welch PSD for spectral analysis
- Phase 1 source code -- Direct examination of engine.py, events.py, buffers.py, models.py, orders.py, sizing.py, state.py, circuit_breakers.py

### Secondary (MEDIUM confidence)
- [Rosenstein et al. 1993](https://physionet.org/files/lyapunov/1.0.0/RosensteinM93.pdf) -- Original paper on practical Lyapunov exponent estimation
- [Feigenbaum constants (Wikipedia)](https://en.wikipedia.org/wiki/Feigenbaum_constants) -- Universal delta=4.669 for period-doubling
- [Thermodynamic analysis of order books](https://pmc.ncbi.nlm.nih.gov/articles/PMC10813935/) -- Market entropy from order flow
- [Shannon entropy for market efficiency](https://www.sciencedirect.com/science/article/abs/pii/S0960077922006130) -- High-frequency entropy regime detection
- [OU process for trading (QuantStart)](https://www.quantstart.com/articles/ornstein-uhlenbeck-simulation-with-python/) -- Python OU implementation and parameter estimation
- [Confidence-weighted fusion strategy](https://www.emergentmind.com/topics/confidence-weighted-fusion-strategy) -- Literature review on adaptive signal fusion
- [Order flow Python package](https://github.com/AndreaFerrante/Orderflow) -- Reference for tick-level order flow reshaping

### Tertiary (LOW confidence)
- Feigenbaum bifurcation detection in financial markets -- theoretical basis confirmed, but no validated implementations found. Novel territory.
- Quantum timing as described in project -- novel framing mapped to classical stochastic processes (OU, phase transitions). No direct reference implementations.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries well-established and pinned in CLAUDE.md
- Architecture: HIGH -- follows established Phase 1 patterns (Protocol, frozen dataclass, asyncio.to_thread, structlog, Pydantic config)
- Chaos/fractal algorithms: HIGH -- nolds provides validated implementations; Numba JIT is established practice
- Order flow: MEDIUM -- volume delta heuristic for forex ECN is approximate; DOM availability unknown
- Feigenbaum detection: LOW -- no financial market reference implementations; novel territory
- Quantum timing: MEDIUM-LOW -- mapped to OU processes and volatility energy, which are established, but the specific framing is novel
- Fusion/adaptive weights: HIGH -- standard ensemble learning pattern; EMA accuracy tracking well-understood
- Pitfalls: HIGH -- derived from actual library documentation and Phase 1 development experience

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable domain -- chaos theory and order flow fundamentals don't change; library versions are pinned)
