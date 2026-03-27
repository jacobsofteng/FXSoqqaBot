"""Lyapunov exponent computation for dynamical stability measurement.

CHAOS-02: Largest Lyapunov exponent via Rosenstein algorithm. Positive
values indicate chaotic/unstable dynamics, negative values indicate
stable dynamics, ~0 is neutral.

Inner distance matrix and neighbor search JIT-compiled via _numba_core.
FFT for auto-lag and final RANSAC line fit stay in Python.
"""

from __future__ import annotations

import numpy as np
from nolds.measures import poly_fit as _nolds_poly_fit

from fxsoqqabot.signals.chaos._numba_core import _delay_embedding, _lyap_r_core


def compute_lyapunov(
    close_prices: np.ndarray,
    emb_dim: int = 10,
    min_length: int = 300,
) -> tuple[float, float]:
    """Compute the largest Lyapunov exponent from close prices.

    Args:
        close_prices: 1D array of close prices.
        emb_dim: Embedding dimension for phase-space reconstruction.
        min_length: Minimum data points required. Below this,
            returns (0.0, 0.0) -- neutral assumption with zero confidence.

    Returns:
        (lyapunov_value, confidence) where confidence scales linearly
        from 0.0 to 1.0 at 3x min_length data points.
    """
    if len(close_prices) < min_length:
        return (0.0, 0.0)

    try:
        data = np.ascontiguousarray(close_prices, dtype=np.float64)
        n = len(data)
        trajectory_len = 20
        tau = 1

        # FFT for auto-lag and min_tsep (not jittable, stays in Python)
        f = np.fft.rfft(data, n * 2 - 1)
        freqs = np.fft.rfftfreq(n * 2 - 1)
        psd = np.abs(f) ** 2
        psd_sum = np.sum(psd[1:])
        if psd_sum > 0:
            mf = float(np.sum(freqs[1:] * psd[1:]) / psd_sum)
        else:
            mf = 1.0 / n
        if mf > 0:
            min_tsep = int(np.ceil(1.0 / mf))
        else:
            min_tsep = 1
        min_tsep = min(min_tsep, int(0.25 * n))

        # Autocorrelation for lag
        acorr = np.fft.irfft(f * np.conj(f))
        acorr = np.roll(acorr, n - 1)
        eps = acorr[n - 1] * (1 - 1.0 / np.e)
        lag = 1
        for k in range(1, n):
            if acorr[n - 1 + k] < eps:
                lag = k
                break

        # JIT-compiled delay embedding
        orbit = _delay_embedding(data, emb_dim, lag)

        # JIT-compiled core: distance matrix, neighbor search, divergence
        div_traj = _lyap_r_core(orbit, min_tsep, trajectory_len)

        # Filter -inf from div_traj and fit line (RANSAC)
        ks = np.arange(len(div_traj), dtype=np.float64)
        finite_mask = np.isfinite(div_traj)
        if np.sum(finite_mask) < 2:
            return (0.0, 0.0)

        poly = _nolds_poly_fit(
            ks[finite_mask], div_traj[finite_mask], 1, fit="RANSAC"
        )
        lyap_val = float(poly[0]) / tau
    except Exception:
        return (0.0, 0.0)

    if not np.isfinite(lyap_val):
        return (0.0, 0.0)

    # Confidence scales linearly with data length
    confidence = float(min(1.0, len(close_prices) / (min_length * 3)))

    return (float(lyap_val), confidence)
