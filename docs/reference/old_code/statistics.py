"""
Statistical Framework — Anti-overfitting defenses.

- Monte Carlo permutation tests
- Bonferroni correction
- Effect size requirements
- Control baselines (random, round numbers, Fibonacci)
"""

import numpy as np
from dataclasses import dataclass


N_TOTAL_TESTS = 18  # Total hypotheses being tested
BONFERRONI_ALPHA = 0.05 / N_TOTAL_TESTS  # ~0.0028
MIN_EFFECT_SIZE = 0.10  # Require >10% absolute improvement over control
TOLERANCE_PRICE = 2.0  # Ferro's +/-2 units — FIXED, no shopping
TOLERANCE_DEGREES = 5.0  # Sq9 degree tolerance — FIXED


@dataclass
class TestResult:
    name: str
    dataset: str  # 'train' or 'test'
    n_samples: int
    hit_rate: float
    control_hit_rate: float
    effect_size: float  # hit_rate - control_hit_rate
    p_value: float
    p_value_corrected: float  # Bonferroni
    is_significant: bool
    is_practically_significant: bool
    details: dict

    def summary(self) -> str:
        sig = "***" if self.is_significant and self.is_practically_significant else (
            "**" if self.is_significant else (
                "*" if self.p_value < 0.05 else ""
            )
        )
        return (
            f"{self.name} [{self.dataset}] {sig}\n"
            f"  Hit rate:    {self.hit_rate:.1%} vs control {self.control_hit_rate:.1%}\n"
            f"  Effect:      {self.effect_size:+.1%}\n"
            f"  p-value:     {self.p_value:.6f} (corrected: {self.p_value_corrected:.6f})\n"
            f"  Significant: {self.is_significant} | Practical: {self.is_practically_significant}\n"
            f"  N={self.n_samples}"
        )


def permutation_test(
    observed_hits: int,
    n_samples: int,
    control_hits: int,
    control_n: int,
    n_permutations: int = 10_000,
    rng_seed: int = 42,
) -> float:
    """Monte Carlo permutation test.

    Pool all events (hits + misses from both groups), shuffle,
    split into two groups, compute difference. p-value = fraction
    of permuted differences >= observed difference.
    """
    rng = np.random.default_rng(rng_seed)

    obs_rate = observed_hits / n_samples if n_samples > 0 else 0
    ctrl_rate = control_hits / control_n if control_n > 0 else 0
    observed_diff = obs_rate - ctrl_rate

    # Pool all outcomes
    total_n = n_samples + control_n
    total_hits = observed_hits + control_hits
    pool = np.zeros(total_n, dtype=int)
    pool[:total_hits] = 1

    count_extreme = 0
    for _ in range(n_permutations):
        rng.shuffle(pool)
        perm_rate_a = pool[:n_samples].sum() / n_samples if n_samples > 0 else 0
        perm_rate_b = pool[n_samples:].sum() / control_n if control_n > 0 else 0
        perm_diff = perm_rate_a - perm_rate_b
        if perm_diff >= observed_diff:
            count_extreme += 1

    return count_extreme / n_permutations


def chi_squared_test(observed_hits: int, n_samples: int, expected_rate: float) -> float:
    """Simple chi-squared test for one proportion vs expected rate."""
    if n_samples == 0:
        return 1.0
    expected_hits = n_samples * expected_rate
    expected_misses = n_samples * (1 - expected_rate)
    if expected_hits <= 0 or expected_misses <= 0:
        return 1.0
    observed_misses = n_samples - observed_hits
    chi2 = (
        (observed_hits - expected_hits) ** 2 / expected_hits
        + (observed_misses - expected_misses) ** 2 / expected_misses
    )
    # One-tailed p-value approximation (chi2 with df=1)
    # Using survival function of chi-squared(1)
    from math import exp, sqrt, pi

    # Wilson's approximation for chi2 df=1
    z = sqrt(chi2)
    # Standard normal survival: P(Z > z) ≈ erfc(z/sqrt(2))/2
    # Use fast approximation
    p = 0.5 * _erfc_approx(z / sqrt(2))
    return p


def _erfc_approx(x: float) -> float:
    """Approximation of complementary error function."""
    if x < 0:
        return 2.0 - _erfc_approx(-x)
    # Abramowitz & Stegun 7.1.26 approximation
    t = 1.0 / (1.0 + 0.3275911 * x)
    poly = t * (
        0.254829592
        + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429)))
    )
    from math import exp
    return poly * exp(-x * x)


def build_test_result(
    name: str,
    dataset: str,
    hits: int,
    n_samples: int,
    control_hits: int,
    control_n: int,
    details: dict | None = None,
    n_permutations: int = 10_000,
) -> TestResult:
    """Build a complete TestResult with permutation test and corrections."""
    hit_rate = hits / n_samples if n_samples > 0 else 0
    control_rate = control_hits / control_n if control_n > 0 else 0
    effect = hit_rate - control_rate

    p_val = permutation_test(hits, n_samples, control_hits, control_n, n_permutations)
    p_corrected = min(p_val * N_TOTAL_TESTS, 1.0)  # Bonferroni

    return TestResult(
        name=name,
        dataset=dataset,
        n_samples=n_samples,
        hit_rate=hit_rate,
        control_hit_rate=control_rate,
        effect_size=effect,
        p_value=p_val,
        p_value_corrected=p_corrected,
        is_significant=p_corrected < 0.05,
        is_practically_significant=effect > MIN_EFFECT_SIZE,
        details=details or {},
    )


def reaction_at_level(
    prices: np.ndarray,
    level: float,
    tolerance_pct: float = 0.001,
    window_bars: int = 5,
) -> bool:
    """Check if price reacted (touched then reversed) near a level.

    tolerance_pct: how close price must get (0.1% = 1 dollar at $1000)
    window_bars: bars to check for reversal after touching
    """
    tol = level * tolerance_pct
    # Find bars where price is within tolerance of level
    near = np.where(np.abs(prices - level) <= tol)[0]
    if len(near) == 0:
        return False
    # Check if price reversed within window_bars after touching
    for idx in near:
        if idx + window_bars >= len(prices):
            continue
        touch_price = prices[idx]
        future = prices[idx + 1: idx + 1 + window_bars]
        if len(future) == 0:
            continue
        # Price came from below (support test)
        if touch_price <= level:
            if np.any(future > touch_price + tol):
                return True
        # Price came from above (resistance test)
        else:
            if np.any(future < touch_price - tol):
                return True
    return False


def generate_random_levels(
    price_min: float, price_max: float, n_levels: int, rng_seed: int = 42
) -> np.ndarray:
    """Generate random price levels as control baseline."""
    rng = np.random.default_rng(rng_seed)
    return rng.uniform(price_min, price_max, n_levels)


def generate_round_number_levels(
    price_min: float, price_max: float, step: float = 50.0
) -> np.ndarray:
    """Generate round number levels (e.g., every $50) as control."""
    start = np.ceil(price_min / step) * step
    return np.arange(start, price_max, step)
