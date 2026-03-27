"""Numba JIT-compiled core functions for chaos signal computations.

All functions decorated with @njit(cache=True) for persistent compilation
cache. Only numpy arrays and scalars -- no Python objects, strings, scipy,
or sklearn allowed inside jitted code.

Provides:
    _ols_slope          - OLS slope via manual accumulation
    _ols_slope_intercept - OLS slope + intercept
    _delay_embedding    - Time-delay embedding
    _pairwise_euclidean - O(n^2) symmetric distance matrix
    _rs_single          - R/S for a single subsequence length
    _rs_values          - R/S loop over nvals array (hurst hot loop)
    _lyap_r_core        - Rosenstein nearest-neighbor divergence (lyapunov hot loop)
    _corr_dim_core      - Grassberger-Procaccia correlation sums (fractal hot loop)
    warmup_jit          - Trigger compilation of all @njit functions
"""

from __future__ import annotations

import numpy as np
from numba import njit


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


@njit(cache=True)
def _ols_slope(x: np.ndarray, y: np.ndarray) -> float:
    """Simple OLS slope via manual accumulation loop.

    Replaces np.polyfit(x, y, 1)[0] inside jitted paths.
    """
    n = len(x)
    sx = 0.0
    sy = 0.0
    sxx = 0.0
    sxy = 0.0
    for i in range(n):
        sx += x[i]
        sy += y[i]
        sxx += x[i] * x[i]
        sxy += x[i] * y[i]
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-30:
        return 0.0
    return (n * sxy - sx * sy) / denom


@njit(cache=True)
def _ols_slope_intercept(
    x: np.ndarray, y: np.ndarray
) -> tuple[float, float]:
    """OLS slope and intercept via manual accumulation.

    Returns (slope, intercept).
    """
    n = len(x)
    sx = 0.0
    sy = 0.0
    sxx = 0.0
    sxy = 0.0
    for i in range(n):
        sx += x[i]
        sy += y[i]
        sxx += x[i] * x[i]
        sxy += x[i] * y[i]
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-30:
        return 0.0, sy / n if n > 0 else 0.0
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


@njit(cache=True)
def _delay_embedding(
    data: np.ndarray, emb_dim: int, lag: int
) -> np.ndarray:
    """Time-delay embedding. Returns 2D array (n - (emb_dim-1)*lag, emb_dim)."""
    n = len(data) - (emb_dim - 1) * lag
    result = np.empty((n, emb_dim))
    for i in range(n):
        for d in range(emb_dim):
            result[i, d] = data[i + d * lag]
    return result


@njit(cache=True)
def _pairwise_euclidean(orbit: np.ndarray) -> np.ndarray:
    """O(n^2) symmetric pairwise Euclidean distance matrix."""
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


# ---------------------------------------------------------------------------
# Hurst R/S core
# ---------------------------------------------------------------------------


@njit(cache=True)
def _rs_single(data_slice: np.ndarray, n: int, unbiased: bool) -> float:
    """Compute R/S for a single subsequence length n.

    Mirrors nolds.rs(): reshapes data into m subsequences of length n,
    computes rescaled range for each, returns mean(R/S).
    """
    total_N = len(data_slice)
    m = total_N // n
    if m == 0:
        return np.nan

    rs_sum = 0.0
    rs_count = 0

    for seg in range(m):
        start = seg * n
        # Compute mean of subsequence
        seg_mean = 0.0
        for i in range(n):
            seg_mean += data_slice[start + i]
        seg_mean /= n

        # Departures from mean and cumulative sum
        cum_max = 0.0
        cum_min = 0.0
        cum = 0.0
        for i in range(n):
            cum += data_slice[start + i] - seg_mean
            if cum > cum_max:
                cum_max = cum
            if cum < cum_min:
                cum_min = cum

        r = cum_max - cum_min

        # Standard deviation (ddof=1 if unbiased)
        ss = 0.0
        for i in range(n):
            diff = data_slice[start + i] - seg_mean
            ss += diff * diff
        if unbiased and n > 1:
            std = np.sqrt(ss / (n - 1))
        else:
            std = np.sqrt(ss / n)

        if std == 0.0:
            continue

        rs_sum += r / std
        rs_count += 1

    if rs_count == 0:
        return np.nan
    return rs_sum / rs_count


@njit(cache=True)
def _rs_values(
    data: np.ndarray, nvals: np.ndarray, unbiased: bool
) -> np.ndarray:
    """Loop over nvals array, call _rs_single for each.

    Returns 1D array of R/S values same length as nvals.
    """
    result = np.empty(len(nvals))
    for idx in range(len(nvals)):
        result[idx] = _rs_single(data, nvals[idx], unbiased)
    return result


# ---------------------------------------------------------------------------
# Lyapunov Rosenstein core
# ---------------------------------------------------------------------------


@njit(cache=True)
def _lyap_r_core(
    orbit: np.ndarray, min_tsep: int, trajectory_len: int
) -> np.ndarray:
    """Rosenstein algorithm inner computation.

    Builds O(n^2) distance matrix, masks temporal neighbors, finds nearest
    neighbors, and computes mean-log divergence trajectory.

    Args:
        orbit: delay-embedded orbit array (m, emb_dim).
        min_tsep: minimum temporal separation for neighbor selection.
        trajectory_len: number of steps to follow divergence.

    Returns:
        div_traj: 1D array of length trajectory_len with mean log divergence.
    """
    m = orbit.shape[0]
    dists = _pairwise_euclidean(orbit)

    # Mask temporal neighbors with inf
    for i in range(m):
        lo = i - min_tsep
        if lo < 0:
            lo = 0
        hi = i + min_tsep + 1
        if hi > m:
            hi = m
        for j in range(lo, hi):
            dists[i, j] = np.inf

    ntraj = m - trajectory_len + 1
    if ntraj <= 0:
        return np.full(trajectory_len, -np.inf)

    # Find nearest neighbors for each point in range(ntraj)
    nb_idx = np.empty(ntraj, dtype=np.int64)
    for i in range(ntraj):
        best_dist = np.inf
        best_j = 0
        for j in range(ntraj):
            if dists[i, j] < best_dist:
                best_dist = dists[i, j]
                best_j = j
        nb_idx[i] = best_j

    # Build divergence trajectory
    div_traj = np.empty(trajectory_len)
    for k in range(trajectory_len):
        log_sum = 0.0
        count = 0
        for i in range(ntraj):
            d = dists[i + k, nb_idx[i] + k]
            if d > 0.0 and np.isfinite(d):
                log_sum += np.log(d)
                count += 1
        if count > 0:
            div_traj[k] = log_sum / count
        else:
            div_traj[k] = -np.inf

    return div_traj


# ---------------------------------------------------------------------------
# Correlation dimension core
# ---------------------------------------------------------------------------


@njit(cache=True)
def _corr_dim_core(orbit: np.ndarray, rvals: np.ndarray) -> np.ndarray:
    """Grassberger-Procaccia correlation sums.

    Computes upper-triangle pairwise distances and counts pairs within
    each radius threshold.

    Args:
        orbit: delay-embedded orbit array (n, emb_dim).
        rvals: 1D array of radius thresholds.

    Returns:
        csums: 1D array of correlation sums C(r), same length as rvals.
    """
    n = orbit.shape[0]
    dim = orbit.shape[1]
    n_r = len(rvals)
    counts = np.zeros(n_r)

    # Compute upper triangle distances and count in-place
    for i in range(n):
        for j in range(i + 1, n):
            s = 0.0
            for d in range(dim):
                diff = orbit[i, d] - orbit[j, d]
                s += diff * diff
            dist = np.sqrt(s)
            for ri in range(n_r):
                if dist <= rvals[ri]:
                    counts[ri] += 1.0

    # Total pairs = n * (n - 1) / 2, doubled for symmetry = n * (n - 1)
    total_pairs = n * (n - 1)
    csums = np.empty(n_r)
    for ri in range(n_r):
        # 2 * count_upper / (n * (n - 1)) = count_upper * 2 / total_pairs
        csums[ri] = (2.0 * counts[ri]) / total_pairs if total_pairs > 0 else 0.0

    return csums


# ---------------------------------------------------------------------------
# Warm-up function (not jitted)
# ---------------------------------------------------------------------------


def warmup_jit() -> None:
    """Trigger compilation of all @njit functions with small dummy data.

    Called from ChaosRegimeModule.initialize() to ensure first real call
    uses cached bytecode with no compilation delay.
    """
    dummy = np.random.RandomState(0).randn(50).astype(np.float64)
    dummy_prices = np.cumsum(dummy) + 100.0

    # _ols_slope
    x = np.arange(10, dtype=np.float64)
    y = np.arange(10, dtype=np.float64) * 2.0 + 1.0
    _ols_slope(x, y)

    # _ols_slope_intercept
    _ols_slope_intercept(x, y)

    # _delay_embedding
    orbit = _delay_embedding(dummy_prices, 3, 1)

    # _pairwise_euclidean
    _pairwise_euclidean(orbit[:10])

    # _rs_single and _rs_values
    nvals = np.array([5, 10], dtype=np.int64)
    _rs_values(dummy_prices, nvals, True)

    # _lyap_r_core
    small_orbit = _delay_embedding(dummy_prices, 3, 1)
    _lyap_r_core(small_orbit[:20], 2, 5)

    # _corr_dim_core
    rvals = np.array([0.1, 0.5, 1.0], dtype=np.float64)
    _corr_dim_core(small_orbit[:20], rvals)
