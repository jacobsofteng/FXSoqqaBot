"""Ornstein-Uhlenbeck mean-reversion timing model.

Estimates OU process parameters (kappa, theta, sigma) from price series
via OLS regression on discrete observations. Provides entry and exit
timing windows based on displacement from the long-term mean, half-life
of mean reversion, and probability-weighted confidence.

Implements QTIM-01 (price-time coupled state modeling) and QTIM-03
(probability-weighted entry/exit windows with confidence intervals).

Reference:
    dX = kappa * (theta - X) * dt + sigma * dW
    where kappa = mean-reversion speed, theta = long-term mean,
    sigma = volatility of the process.
"""

from __future__ import annotations

import numpy as np


def estimate_ou_parameters(
    prices: np.ndarray, dt: float = 1.0
) -> tuple[float, float, float, float]:
    """Estimate Ornstein-Uhlenbeck parameters from price series.

    Uses OLS regression on the discrete SDE:
        X_{t+1} - X_t = kappa * (theta - X_t) * dt + noise
    Rearranged as linear regression:
        dx = a + b * x + noise
    where a = kappa * theta * dt, b = -kappa * dt.

    Args:
        prices: 1-D array of price observations.
        dt: Time step between observations (default 1.0 = 1 bar).

    Returns:
        (kappa, theta, sigma, confidence) where:
        - kappa: mean-reversion speed (>0 for mean-reverting).
        - theta: long-term mean level.
        - sigma: volatility of the OU process.
        - confidence: R-squared of the OLS fit, clamped to [0, 1].

        Returns (0.0, mean(prices), 0.0, 0.0) if len < 30 or
        denominator is near zero (constant prices).
    """
    if len(prices) < 30:
        return 0.0, float(np.mean(prices)), 0.0, 0.0

    # OLS estimation on discrete observations
    x = prices[:-1]
    dx = np.diff(prices)

    # Linear regression: dx = a + b * x + noise
    n = len(x)
    sx = np.sum(x)
    sx2 = np.sum(x**2)
    sdx = np.sum(dx)
    sxdx = np.sum(x * dx)

    denom = n * sx2 - sx**2
    if abs(denom) < 1e-10:
        return 0.0, float(np.mean(prices)), 0.0, 0.0

    b = (n * sxdx - sx * sdx) / denom
    a = (sdx - b * sx) / n

    kappa = float(-b / dt)
    theta = float(a / (kappa * dt)) if kappa > 0 else float(np.mean(prices))

    residuals = dx - (a + b * x)
    sigma = float(np.std(residuals)) / np.sqrt(dt)

    # Confidence: R-squared of the regression
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((dx - np.mean(dx)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    confidence = max(0.0, min(1.0, r_squared))

    return float(kappa), float(theta), float(sigma), confidence


def compute_entry_window(
    kappa: float,
    theta: float,
    sigma: float,
    current_price: float,
    confidence: float,
) -> tuple[float, float, float]:
    """Compute entry timing window from OU parameters.

    Determines direction (buy/sell), urgency (how far from mean in
    sigma units), and window confidence (quality of the timing signal).

    Args:
        kappa: Mean-reversion speed from estimate_ou_parameters.
        theta: Long-term mean level.
        sigma: OU process volatility.
        current_price: Current price observation.
        confidence: Quality of OU parameter fit (R-squared).

    Returns:
        (direction, urgency, window_confidence) where:
        - direction: +1.0 (price below mean, expect rise) or
                     -1.0 (price above mean, expect fall), or
                     0.0 if no mean reversion detected.
        - urgency: 0.0 to 1.0, how strongly the timing signal fires.
        - window_confidence: combined fit quality and urgency.
    """
    if kappa <= 0 or confidence < 0.1:
        return 0.0, 0.0, 0.0

    displacement = theta - current_price
    direction = 1.0 if displacement > 0 else -1.0

    # Half-life: time to revert halfway to mean
    half_life = np.log(2) / kappa if kappa > 0 else float("inf")

    # Urgency: how far from mean in sigma units
    urgency = min(1.0, abs(displacement) / (2 * sigma + 1e-10))

    # If half_life < 5 bars: timing is imminent, boost urgency
    if half_life < 5.0:
        urgency = min(1.0, urgency * 1.5)

    # Window confidence: fit quality only (urgency applied once in module.py line 136)
    window_confidence = confidence

    return direction, float(urgency), float(window_confidence)


def compute_exit_window(
    kappa: float,
    theta: float,
    current_price: float,
    entry_price: float,
) -> tuple[float, float]:
    """Compute exit timing window based on OU mean reversion.

    Estimates whether the trade should be held or exited based on
    the relationship between current price, theta, and entry price.

    Args:
        kappa: Mean-reversion speed.
        theta: Long-term mean level.
        current_price: Current price.
        entry_price: Price at which position was entered.

    Returns:
        (exit_urgency, confidence) where:
        - exit_urgency: 0.0 (hold) to 1.0 (exit now).
        - confidence: reliability of the exit signal.
    """
    if kappa <= 0:
        # No mean reversion detected -- exit now
        return 1.0, 1.0

    half_life = np.log(2) / kappa

    # Determine if we are long or short based on entry vs theta
    is_long = entry_price < theta  # bought expecting rise toward theta

    if is_long:
        # Moving away from theta = price dropping below entry
        if current_price < entry_price:
            return 1.0, 1.0  # Exit now: moving wrong direction
        # Approaching theta: compute progress
        total_distance = abs(theta - entry_price)
        progress = abs(current_price - entry_price) / (total_distance + 1e-10)
        if progress > 0.8:
            # Near target
            return 0.7, 0.9
        elif half_life < 5.0:
            # Fast reversion expected, hold
            return 0.3, 0.8
        else:
            return 0.5, 0.7
    else:
        # Short: expecting fall toward theta
        if current_price > entry_price:
            return 1.0, 1.0  # Exit now: moving wrong direction
        total_distance = abs(entry_price - theta)
        progress = abs(entry_price - current_price) / (total_distance + 1e-10)
        if progress > 0.8:
            return 0.7, 0.9
        elif half_life < 5.0:
            return 0.3, 0.8
        else:
            return 0.5, 0.7
