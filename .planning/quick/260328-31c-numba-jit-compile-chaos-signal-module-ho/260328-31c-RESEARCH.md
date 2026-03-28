# Quick Task: Numba JIT-Compile Chaos Signal Module Hot Loops - Research

**Researched:** 2026-03-28
**Domain:** Numba JIT compilation for nonlinear dynamics computations
**Confidence:** HIGH

## Summary

The backtest bottleneck is confirmed: the five chaos signal functions (hurst, lyapunov, fractal, feigenbaum, entropy) are called on every M1 bar during walk-forward replay. With 1440-point close_prices arrays (full M1 buffer), the three nolds-backed functions take ~93ms per bar. At 3.8M bars that's ~98 hours of pure chaos computation -- the dominant cost.

**Profiled per-bar cost at 1440 points:**
| Function | Time | % of Total | Bottleneck |
|----------|------|------------|------------|
| `nolds.corr_dim` (fractal.py) | 40ms | 43% | O(n^2) distance matrix |
| `nolds.lyap_r` (lyapunov.py) | 25ms | 27% | O(n^2) distance matrix + FFT for lag |
| `nolds.hurst_rs` (hurst.py) | 27ms | 29% | Loop over 15 subseries lengths |
| feigenbaum (scipy.argrelextrema) | <0.1ms | ~0% | Already fast (vectorized numpy) |
| entropy (scipy.stats.entropy) | <0.5ms | ~0% | Already fast (vectorized numpy) |

**Primary recommendation:** Rewrite the inner loops of hurst_rs, lyap_r, and corr_dim as standalone `@njit(cache=True)` functions. Leave feigenbaum and entropy alone -- they are already fast. The backtest engine loop itself is NOT jittable (uses async, classes, dicts, structlog) but benefits indirectly from faster signal functions.

## Project Constraints (from CLAUDE.md)

- Numba 0.64.0 already in stack (verified installed)
- NumPy 2.4.3 compatible with Numba 0.64 (verified in CLAUDE.md Version Compatibility table)
- nolds 0.6.3 used as reference implementation; CLAUDE.md says "re-implement hot paths with Numba for production speed"
- Python 3.12.x runtime
- `cache=True` on all jitted functions for persistent compilation cache

## Architecture: What to JIT and What Not To

### The Three Functions That Matter

**1. `corr_dim` (fractal.py) -- 43% of time**
- Inner loop: builds an n x n distance matrix via `rowwise_euclidean` called n times
- Then counts pairs within radius thresholds
- Both loops are pure numeric, fully Numba-compatible
- Replace with single `@njit` function doing delay_embedding + pairwise distances + correlation sums

**2. `lyap_r` (lyapunov.py) -- 27% of time**
- Inner loop: builds n x n distance matrix (same pattern as corr_dim)
- Then masks temporal neighbors, finds nearest neighbors, follows divergence trajectories
- FFT for auto-lag detection is NOT Numba-compatible (`np.fft.rfft` unsupported in nopython)
- Strategy: precompute lag/min_tsep outside @njit, pass them into the jitted core

**3. `hurst_rs` (hurst.py) -- 29% of time**
- Inner loop: `rs()` function called 15 times for different subseries lengths
- `rs()` itself is mostly vectorized numpy (reshape, cumsum, std, max, min)
- The loop over 15 nvals + the `rs` inner computation are jittable
- `poly_fit` with RANSAC is NOT jittable (uses sklearn) -- do line fit outside @njit

### Functions to Leave Alone

- **feigenbaum.py**: Uses `scipy.signal.argrelextrema` + numpy vectorized ops. Already <0.1ms. Not worth touching.
- **entropy.py**: Uses `np.histogram` + `scipy.stats.entropy`. Already <0.5ms. `np.histogram` IS supported in Numba but there's no meaningful gain.
- **regime.py**: Pure Python comparisons, no loops. Negligible cost.
- **module.py**: Async orchestrator, not jittable.

### BacktestEngine.run() Loop

The bar-by-bar loop in `engine.py` is NOT a candidate for Numba JIT:
- Uses `async/await`, class instances, Python dicts, structlog, Pydantic models
- The loop overhead itself is minimal; the cost is in the signal functions it calls
- Once chaos functions are 10-30x faster, the loop becomes IO/overhead bound, not compute bound

## Numba Compatibility: Verified Operations

**Tested working in Numba 0.64 nopython mode:**
| Operation | Status | Notes |
|-----------|--------|-------|
| `np.mean`, `np.std`, `np.sum` | OK | Core stats |
| `np.cumsum`, `np.diff`, `np.clip` | OK | Array ops |
| `np.max`, `np.min`, `np.abs`, `np.sqrt`, `np.log` | OK | Math |
| `np.sign`, `np.isfinite` | OK | Helpers |
| `np.reshape`, `np.arange`, `np.empty`, `np.zeros` | OK | Array creation |
| `np.argsort`, `np.argmin(axis=N)` | OK | Sorting |
| `np.where` | OK | Conditional indexing |
| `np.histogram` | OK | Binning |
| `np.linalg.lstsq` | OK | Linear regression |
| `np.conj` | OK | Complex numbers |

**NOT supported in nopython mode:**
| Operation | Workaround |
|-----------|------------|
| `np.fft.rfft` / `np.fft.irfft` | Compute outside @njit, pass result in |
| `np.polyfit` | Use manual OLS formula or `np.linalg.lstsq` |
| `np.polyval` | Manual polynomial evaluation |
| `scipy.*` anything | Compute outside @njit |
| `sklearn.*` anything | Compute outside @njit (RANSAC) |
| `float("inf")` | Use `np.inf` instead |
| String operations | Not in nopython mode |

## Implementation Pattern

### Pattern: Extract-JIT-Wrap

The correct pattern for each function:

```python
# In e.g. chaos/_numba_core.py
from numba import njit

@njit(cache=True)
def _hurst_rs_core(data: np.ndarray, nvals: np.ndarray, unbiased: bool) -> np.ndarray:
    """JIT-compiled inner loop for R/S computation across all nvals."""
    # Pure numeric loop here
    ...

# In hurst.py (wrapper keeps same API)
def compute_hurst(close_prices, min_length=100):
    # ... guards, nvals computation ...
    rsvals = _hurst_rs_core(data, nvals, True)
    # ... RANSAC/poly fit (not jittable) ...
    # ... confidence calculation ...
    return (hurst_val, confidence)
```

Key principles:
1. **JIT the inner computation, not the whole function** -- keep Python-level guards, logging, exception handling outside
2. **One `_numba_core.py` file** for all jitted functions -- clean separation
3. **`cache=True`** on every `@njit` decorator -- persists compiled code to `__pycache__`
4. **Warm-up in `ChaosRegimeModule.initialize()`** -- call each jitted function once with small dummy data to trigger compilation before the backtest loop

### Pattern: Manual OLS for Line Fitting Inside @njit

```python
@njit(cache=True)
def _ols_slope(x, y):
    """Simple OLS slope computation -- replaces np.polyfit(x, y, 1)[0]."""
    n = len(x)
    sx = sy = sxx = sxy = 0.0
    for i in range(n):
        sx += x[i]
        sy += y[i]
        sxx += x[i] * x[i]
        sxy += x[i] * y[i]
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-30:
        return 0.0
    return (n * sxy - sx * sy) / denom
```

Note: This replaces RANSAC with simple OLS inside the jitted path. For the Hurst exponent final fit, keep RANSAC outside -- only the inner `rs()` loop gets jitted.

### Pattern: Delay Embedding

```python
@njit(cache=True)
def _delay_embedding(data, emb_dim, lag):
    """Time-delay embedding -- Numba version."""
    n = len(data) - (emb_dim - 1) * lag
    result = np.empty((n, emb_dim))
    for i in range(n):
        for d in range(emb_dim):
            result[i, d] = data[i + d * lag]
    return result
```

### Pattern: Pairwise Distance Matrix (the real hot loop)

```python
@njit(cache=True)
def _pairwise_euclidean(orbit):
    """O(n^2) pairwise Euclidean distances -- Numba version."""
    n = orbit.shape[0]
    dim = orbit.shape[1]
    dists = np.empty((n, n))
    for i in range(n):
        dists[i, i] = 0.0
        for j in range(i + 1, n):
            s = 0.0
            for d in range(dim):
                diff = orbit[i, d] - orbit[j, d]
                s += diff * diff
            dist = np.sqrt(s)
            dists[i, j] = dist
            dists[j, i] = dist
    return dists
```

This is where the biggest speedup comes from -- the nolds version uses a Python loop calling numpy vectorized `rowwise_euclidean` n times. Numba fuses this into a single compiled nested loop.

## Common Pitfalls

### Pitfall 1: First-Call Compilation Overhead
**What goes wrong:** First call to a jitted function takes 1-5 seconds to compile, causing backtest start delay.
**How to avoid:** Use `cache=True` (persists to `__pycache__/`) AND warm up in `ChaosRegimeModule.initialize()` with small dummy arrays. After first run, cached bytecode loads in <50ms.

### Pitfall 2: Unsupported NumPy Functions Inside @njit
**What goes wrong:** `np.fft.rfft`, `np.polyfit`, scipy functions cause `TypingError` at compile time.
**How to avoid:** Keep the jitted boundary tight. Only the inner numeric loops go inside @njit. FFT, RANSAC, scipy stay outside.

### Pitfall 3: Type Inference Failures
**What goes wrong:** Numba can't infer types from Python `float("inf")`, heterogeneous lists, or optional types.
**How to avoid:** Use `np.inf` instead of `float("inf")`. Use typed arrays, not Python lists. Avoid `Optional` -- use sentinel values like `-1.0` instead.

### Pitfall 4: Array Layout Mismatch
**What goes wrong:** Numba defaults to C-contiguous arrays. Mixed Fortran/C layout causes silent copies or errors.
**How to avoid:** Always pass `np.ascontiguousarray()` to jitted functions when input might be a slice or view.

### Pitfall 5: Numerical Differences from RANSAC to OLS
**What goes wrong:** Hurst exponent and Lyapunov exponent values shift slightly when replacing RANSAC with OLS inside jitted loops.
**How to avoid:** For hurst: keep RANSAC for the final slope fit (outside @njit), only jit the `rs()` inner computation. For lyap_r: the final `poly_fit` can also stay outside @njit. Only the distance matrix + neighbor search goes inside.

### Pitfall 6: The Backtest Engine Is NOT the Bottleneck
**What goes wrong:** Spending time trying to jit the BacktestEngine.run() loop, which uses dicts, classes, async.
**How to avoid:** The profiling proves the chaos functions are 95%+ of the cost. Don't touch engine.py.

## Expected Speedup Estimates

| Function | Current | Expected | Speedup | Reason |
|----------|---------|----------|---------|--------|
| hurst `rs()` loop | 27ms | 2-5ms | 5-15x | Vectorized numpy already fast; main gain from avoiding Python overhead in 15-iteration loop |
| lyap_r distance matrix | 25ms | 1-3ms | 8-25x | Python loop -> compiled nested loop |
| corr_dim distance matrix | 40ms | 2-5ms | 8-20x | Same pattern as lyap_r |
| **Total per bar** | **93ms** | **5-13ms** | **7-18x** | Conservative overall estimate |
| **3.8M bar backtest** | **~98h** | **~5-14h** | **7-18x** | Still long but viable for overnight runs |

Note: The outer parts (FFT for lag, RANSAC fitting, data feed synthesis) are NOT jitted and add a fixed ~2-5ms overhead. This limits the theoretical maximum speedup.

## Implementation Order

1. **`_numba_core.py`** -- all @njit functions in one file
   - `_delay_embedding()` (shared by lyap_r and corr_dim)
   - `_pairwise_euclidean()` (shared by lyap_r and corr_dim)
   - `_rs_values()` (hurst inner loop)
   - `_lyap_r_core()` (neighbor search + divergence trajectory)
   - `_corr_dim_core()` (correlation sum computation)
   - `_ols_slope()` (simple linear regression)

2. **Update `hurst.py`** -- call `_rs_values()` instead of nolds.hurst_rs
3. **Update `lyapunov.py`** -- call `_lyap_r_core()` instead of nolds.lyap_r
4. **Update `fractal.py`** -- call `_corr_dim_core()` instead of nolds.corr_dim
5. **Skip feigenbaum.py and entropy.py** -- already fast
6. **Update `module.py` `initialize()`** -- warm up jitted functions with dummy data
7. **Verify correctness** -- run both nolds and jitted versions on same data, assert results within tolerance

## Sources

### Primary (HIGH confidence)
- Direct profiling of nolds 0.6.3 functions on this machine (timings verified 3x)
- Numba 0.64.0 nopython mode compatibility testing (each operation verified in Python REPL)
- nolds source code review (`measures.py` -- hurst_rs, lyap_r, corr_dim implementations)

### Secondary (MEDIUM confidence)
- Numba documentation for supported numpy features (training data, consistent with testing results)
- CLAUDE.md stack specification (Numba 0.64.0, NumPy 2.4.3 compatibility confirmed)

## Metadata

**Confidence breakdown:**
- Profiling data: HIGH -- measured on this exact machine and codebase
- Numba compatibility: HIGH -- tested each operation in nopython mode
- Speedup estimates: MEDIUM -- based on typical Numba benchmarks, actual results depend on CPU cache effects
- Architecture pattern: HIGH -- standard extract-and-jit pattern, widely proven

**Research date:** 2026-03-28
**Valid until:** Indefinite (Numba API is stable)
