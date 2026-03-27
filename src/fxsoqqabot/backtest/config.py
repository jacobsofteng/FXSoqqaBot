"""BacktestConfig: Pydantic configuration models for backtesting.

Defines validated configuration for walk-forward windows (D-05), Monte Carlo
simulation (D-07), out-of-sample holdout (D-12), session-aware spread
modeling (D-09), stochastic slippage (D-10), and commission modeling (D-11).

All parameters have sensible defaults for XAUUSD backtesting with $20 starting
capital on RoboForex ECN.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, field_validator


class SpreadModel(BaseModel):
    """Session-aware spread model per D-09.

    Models XAUUSD spread as a function of trading session (time of day)
    with stochastic sampling within session-specific ranges.

    Session boundaries (UTC):
    - 13-17: London-NY overlap (tightest)
    - 8-12: London session
    - 0-7: Asian session
    - 18-23: Low liquidity (widest)
    """

    london_ny_overlap_pips: tuple[float, float] = (2.0, 3.0)
    london_session_pips: tuple[float, float] = (3.0, 5.0)
    asian_session_pips: tuple[float, float] = (4.0, 6.0)
    low_liquidity_pips: tuple[float, float] = (6.0, 10.0)
    pip_to_price: float = 0.01  # For XAUUSD, 1 pip = $0.01

    def sample_spread(
        self,
        hour_utc: int,
        rng: np.random.Generator,
        volatility_factor: float = 1.0,
    ) -> float:
        """Sample a spread value for the given hour and volatility.

        Returns spread in price units (pips * pip_to_price).

        Args:
            hour_utc: Hour of day in UTC (0-23).
            rng: NumPy random generator for reproducibility.
            volatility_factor: Multiplier for spread (1.0 = normal, >1 = wider).
        """
        if 13 <= hour_utc <= 17:
            low, high = self.london_ny_overlap_pips
        elif 8 <= hour_utc <= 12:
            low, high = self.london_session_pips
        elif 0 <= hour_utc <= 7:
            low, high = self.asian_session_pips
        else:
            low, high = self.low_liquidity_pips

        pips = rng.uniform(low, high) * volatility_factor
        return pips * self.pip_to_price


class SlippageModel(BaseModel):
    """Stochastic slippage model per D-10.

    Models order execution slippage as a discrete probability distribution.
    Slippage is always adverse (positive value added to cost).

    Default distribution based on ECN execution quality:
    - 80% no slippage
    - 15% 1-pip slippage
    - 4% 2-pip slippage
    - 1% 3+ pip slippage
    """

    no_slip_pct: float = 0.80
    slip_1pip_pct: float = 0.15
    slip_2pip_pct: float = 0.04
    slip_3plus_pct: float = 0.01
    pip_to_price: float = 0.01

    def sample_slippage(
        self,
        rng: np.random.Generator,
        volatility_factor: float = 1.0,
    ) -> float:
        """Sample a slippage value in price units.

        Always adverse (non-negative). Higher volatility_factor increases
        slippage magnitude for non-zero outcomes.

        Args:
            rng: NumPy random generator for reproducibility.
            volatility_factor: Multiplier for slippage magnitude.

        Returns:
            Slippage in price units (always >= 0.0).
        """
        roll = rng.random()
        if roll < self.no_slip_pct:
            return 0.0
        elif roll < self.no_slip_pct + self.slip_1pip_pct:
            pips = 1.0
        elif roll < self.no_slip_pct + self.slip_1pip_pct + self.slip_2pip_pct:
            pips = 2.0
        else:
            pips = 3.0 + rng.exponential(1.0)  # 3+ with exponential tail

        return pips * self.pip_to_price * volatility_factor


class BacktestConfig(BaseModel):
    """Top-level backtest configuration with Pydantic validation.

    Centralizes all backtesting parameters referenced by D-05 through D-13:
    - Walk-forward validation windows (D-05, D-06)
    - Monte Carlo simulation settings (D-07)
    - Out-of-sample holdout (D-12, D-13)
    - Spread and slippage modeling (D-09, D-10)
    - Commission (D-11)
    """

    # Data source
    histdata_dir: str = "data/histdata"
    parquet_dir: str = "data/historical"
    symbol: str = "XAUUSD"

    # Walk-forward per D-05
    wf_train_months: int = 6
    wf_validation_months: int = 2
    wf_step_months: int = 2

    # Walk-forward thresholds per D-06
    wf_min_profitable_pct: float = 0.70
    wf_min_profit_factor: float = 1.5

    # Monte Carlo per D-07
    n_monte_carlo: int = 10000
    mc_seed: int = 42
    mc_max_drawdown_pct: float = 0.40

    # OOS holdout per D-12
    holdout_months: int = 6

    # OOS divergence per D-13
    oos_min_pf_ratio: float = 0.50
    oos_max_dd_ratio: float = 2.0

    # Spread/slippage per D-09/D-10
    spread_model: SpreadModel = SpreadModel()
    slippage_model: SlippageModel = SlippageModel()

    # Commission per D-11
    commission_per_lot_round_trip: float = 6.0

    # Starting equity for backtest
    starting_equity: float = 20.0

    @field_validator("n_monte_carlo")
    @classmethod
    def validate_n_monte_carlo(cls, v: int) -> int:
        """Monte Carlo runs must be >= 1000 for statistical significance."""
        if v < 1000:
            raise ValueError(
                f"n_monte_carlo must be >= 1000, got {v}"
            )
        return v

    @field_validator("holdout_months")
    @classmethod
    def validate_holdout_months(cls, v: int) -> int:
        """Holdout period must be at least 1 month."""
        if v < 1:
            raise ValueError(f"holdout_months must be >= 1, got {v}")
        return v

    @field_validator("wf_train_months")
    @classmethod
    def validate_wf_train_months(cls, v: int) -> int:
        """Walk-forward training window must be at least 1 month."""
        if v < 1:
            raise ValueError(f"wf_train_months must be >= 1, got {v}")
        return v

    @field_validator("commission_per_lot_round_trip")
    @classmethod
    def validate_commission(cls, v: float) -> float:
        """Commission must be non-negative."""
        if v < 0:
            raise ValueError(
                f"commission_per_lot_round_trip must be >= 0, got {v}"
            )
        return v
