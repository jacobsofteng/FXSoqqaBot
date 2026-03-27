"""Pydantic configuration models for FXSoqqaBot.

Defines type-safe, validated configuration for risk management,
execution, session windows, data ingestion, and logging. Loads
from TOML files with environment variable overrides.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RiskConfig(BaseModel):
    """Risk management configuration with three-phase capital model (D-03).

    Phase thresholds:
      - Aggressive: equity < aggressive_max ($100)  -> 10% risk/trade
      - Selective:  equity < selective_max ($300)    -> 5% risk/trade
      - Conservative: equity >= selective_max        -> 2% risk/trade
    """

    # Phase thresholds (equity boundaries)
    aggressive_max: float = 100.0
    selective_max: float = 300.0

    # Risk per trade by phase
    aggressive_risk_pct: float = 0.10
    selective_risk_pct: float = 0.05
    conservative_risk_pct: float = 0.02

    # Circuit breakers (D-08)
    daily_drawdown_pct: float = 0.05
    weekly_drawdown_pct: float = 0.10
    max_total_drawdown_pct: float = 0.25
    max_consecutive_losses: int = 5
    max_daily_trades: int = 20
    rapid_equity_drop_pct: float = 0.05
    rapid_equity_drop_window_minutes: int = 15

    # Spread filter (RISK-03, D-08)
    spread_threshold_multiplier: float = 2.0
    spread_spike_multiplier: float = 5.0
    spread_spike_duration_seconds: int = 30

    @field_validator(
        "aggressive_risk_pct",
        "selective_risk_pct",
        "conservative_risk_pct",
        "daily_drawdown_pct",
        "weekly_drawdown_pct",
        "max_total_drawdown_pct",
        "rapid_equity_drop_pct",
    )
    @classmethod
    def validate_pct_range(cls, v: float, info: Any) -> float:
        """All percentage fields must be 0 < x <= 1.0."""
        if v <= 0:
            raise ValueError(f"{info.field_name} must be > 0, got {v}")
        if v > 1.0:
            raise ValueError(f"{info.field_name} must be <= 1.0, got {v}")
        return v

    def get_risk_pct(self, equity: float) -> float:
        """Return risk percentage for current capital phase per D-03.

        Args:
            equity: Current account equity in USD.

        Returns:
            Risk percentage as a decimal (e.g. 0.10 = 10%).
        """
        if equity < self.aggressive_max:
            return self.aggressive_risk_pct
        elif equity < self.selective_max:
            return self.selective_risk_pct
        else:
            return self.conservative_risk_pct


class SessionConfig(BaseModel):
    """Trading session configuration (RISK-06).

    Defines time windows during which the bot is allowed to open
    new positions, the timezone for those windows, and the hour
    at which daily counters reset (D-10).
    """

    windows: list[dict[str, str]] = [{"start": "13:00", "end": "17:00"}]
    timezone: str = "UTC"
    reset_hour: int = 0  # Session boundary for counter reset per D-10


class ExecutionConfig(BaseModel):
    """Order execution configuration (D-01, D-02).

    mode: "paper" (default) or "live" -- manual switch only (D-02).
    """

    symbol: str = "XAUUSD"
    magic_number: int = 20260327
    deviation: int = 20  # Slippage tolerance in points
    mode: str = "paper"  # Per D-01/D-02: "paper" or "live", manual switch only
    sl_atr_multiplier: float = 2.0  # Per RISK-01
    mt5_path: str | None = None
    mt5_login: int | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        """Mode must be 'paper' or 'live'."""
        allowed = ("paper", "live")
        if v not in allowed:
            raise ValueError(f"mode must be one of {allowed}, got '{v}'")
        return v


class DataConfig(BaseModel):
    """Data ingestion configuration."""

    tick_buffer_size: int = 10000
    bar_buffer_sizes: dict[str, int] = {
        "M1": 1440,
        "M5": 288,
        "M15": 96,
        "H1": 24,
        "H4": 6,
    }
    tick_poll_interval_ms: int = 100
    bar_refresh_interval_seconds: int = 5
    storage_path: str = "data/"
    parquet_partition_by: list[str] = ["year", "month"]


class LoggingConfig(BaseModel):
    """Logging configuration.

    json_mode: False = console renderer (dev), True = JSON renderer (production).
    """

    json_mode: bool = False
    level: str = "INFO"


class ChaosConfig(BaseModel):
    """Configuration for chaos/regime detection module.

    Controls parameters for Hurst exponent, Lyapunov exponent,
    fractal dimension, Feigenbaum bifurcation, and Shannon entropy
    computations used in market regime classification.
    """

    hurst_min_length: int = 100  # Minimum data points for Hurst computation
    lyapunov_emb_dim: int = 10  # Embedding dimension for Rosenstein algorithm
    lyapunov_min_length: int = 300  # Minimum points for Lyapunov (from emb_dim)
    fractal_emb_dim: int = 10  # Embedding dimension for correlation dimension
    fractal_min_length: int = 200  # Minimum data points
    feigenbaum_order: int = 5  # Peak detection order for argrelextrema
    entropy_bins: int = 50  # Number of bins for Shannon entropy
    entropy_min_length: int = 100  # Minimum data points for entropy
    update_interval_bars: int = 1  # Recompute every N bar updates
    computation_timeout_ms: int = 50  # Max time per module update in milliseconds
    primary_timeframe: str = "M5"  # Timeframe for primary regime detection
    secondary_timeframe: str = "H1"  # Timeframe for trend confirmation


class FlowConfig(BaseModel):
    """Configuration for order flow and institutional detection.

    Parameters for volume delta, bid-ask aggression, institutional
    footprint detection, HFT signature recognition, and DOM quality
    checks per D-13/D-15.
    """

    volume_delta_window: int = 100  # Ticks for rolling volume delta
    aggression_window: int = 200  # Ticks for bid-ask aggression
    aggression_zscore_threshold: float = 2.0  # Z-score for significant imbalance
    institutional_volume_threshold: float = 3.0  # Std devs above mean for large volume
    institutional_price_tolerance: float = 0.5  # Points for "same price level" iceberg
    institutional_min_repeats: int = 3  # Min repeats at same level for iceberg
    hft_tick_velocity_threshold: float = 5.0  # Ticks/sec above mean for HFT signature
    hft_spread_widen_multiplier: float = 2.0  # Spread widening multiplier for HFT
    dom_quality_check_duration_seconds: int = 60  # D-15: DOM quality sampling window
    dom_min_depth: int = 5  # D-15: Minimum depth levels each side
    dom_min_update_rate: float = 1.0  # D-15: Minimum updates per second
    dom_recheck_interval_minutes: int = 30  # D-15: Periodic DOM quality recheck


class TimingConfig(BaseModel):
    """Configuration for quantum timing engine.

    Parameters for Ornstein-Uhlenbeck mean-reversion estimation
    and phase transition detection via ATR compression/expansion.
    """

    ou_min_length: int = 30  # Minimum data points for OU estimation
    ou_lookback_bars: int = 100  # Bars for OU parameter estimation
    phase_transition_atr_period: int = 14  # ATR period for volatility energy
    phase_transition_compression_threshold: float = 0.5  # ATR ratio for compression
    phase_transition_expansion_threshold: float = 2.0  # ATR ratio for expansion
    primary_timeframe: str = "M5"  # Timeframe for timing analysis


class FusionConfig(BaseModel):
    """Configuration for signal fusion and trade decisions per D-01 through D-12.

    Covers confidence thresholds per capital phase (D-03/D-04), adaptive
    weights (D-02), risk-reward per regime (D-09), ATR-based stop-loss
    (D-09), trailing stops (D-10), high-chaos adjustments (D-06), phase
    transition smoothing (FUSE-04), and position limits (D-11).
    """

    # Confidence thresholds per capital phase (D-03, D-04)
    aggressive_confidence_threshold: float = 0.5  # $20-$100
    selective_confidence_threshold: float = 0.6  # $100-$300
    conservative_confidence_threshold: float = 0.7  # $300+
    # Adaptive weights (D-02)
    ema_alpha: float = 0.1  # EMA decay for accuracy tracking
    weight_warmup_trades: int = 10  # Trades before weights diverge
    # Risk-reward per regime (D-09)
    trending_rr_ratio: float = 3.0  # Trending regime RR
    ranging_rr_ratio: float = 1.5  # Ranging regime RR
    high_chaos_rr_ratio: float = 2.0  # High-chaos regime RR
    # ATR-based SL (D-09)
    sl_atr_period: int = 14  # ATR lookback for SL computation
    sl_atr_base_multiplier: float = 2.0  # Base ATR multiplier for SL
    sl_chaos_widen_factor: float = 1.5  # Extra widen for high-chaos (D-06)
    # Trailing stops per regime (D-10)
    trending_trail_activation_atr: float = 1.0  # Activate after 1x SL distance profit
    trending_trail_distance_atr: float = 0.5  # Trail at 0.5x ATR
    high_chaos_trail_distance_atr: float = 0.3  # Aggressive trail at 0.3x ATR
    # High-chaos behavior adjustments (D-06)
    high_chaos_confidence_boost: float = 0.15  # Extra confidence required in chaos
    high_chaos_size_reduction: float = 0.5  # Reduce position size by 50%
    # Phase transition smoothing (D-04, FUSE-04)
    phase_transition_equity_buffer: float = 10.0  # Sigmoid smoothing window in $
    # Position limit (D-11)
    max_concurrent_positions: int = 1


class SignalsConfig(BaseModel):
    """Container for all signal module configs."""

    chaos: ChaosConfig = ChaosConfig()
    flow: FlowConfig = FlowConfig()
    timing: TimingConfig = TimingConfig()
    fusion: FusionConfig = FusionConfig()


class TUIConfig(BaseModel):
    """TUI dashboard configuration per D-01/D-05."""

    refresh_interval_s: float = 1.0  # D-05: 1-second refresh
    enabled: bool = True


class WebConfig(BaseModel):
    """Web dashboard configuration per D-06/D-09/D-10."""

    host: str = "0.0.0.0"  # D-10: local network access
    port: int = 8080
    api_key: str = "changeme"  # D-09: simple auth for kill/pause
    enabled: bool = True


class LearningConfig(BaseModel):
    """Self-learning loop configuration per D-14/D-15/D-16/D-17/D-18/D-19."""

    evolve_every_n_trades: int = 50  # D-15: GA trigger threshold
    n_shadow_variants: int = 5  # D-17: 3-5 shadow variants
    promotion_alpha: float = 0.05  # D-18: p < 0.05
    min_promotion_trades: int = 50  # D-18: minimum virtual trades
    retirement_threshold: float = 0.3  # D-19: EMA below this retires
    retirement_min_trades: int = 50  # D-19: min trades before retirement
    ga_population_size: int = 20
    ga_crossover_prob: float = 0.5
    ga_mutation_prob: float = 0.2
    ga_tournament_size: int = 3
    enabled: bool = False  # Off by default, enable when ready


class BotSettings(BaseSettings):
    """Top-level settings container loaded from TOML files.

    Priority order (highest wins):
      1. Init kwargs
      2. Environment variables (FXBOT_ prefix, __ nested delimiter)
      3. TOML config files
      4. Field defaults
    """

    model_config = SettingsConfigDict(
        toml_file=["config/default.toml"],
        env_prefix="FXBOT_",
        env_nested_delimiter="__",
    )

    risk: RiskConfig = RiskConfig()
    session: SessionConfig = SessionConfig()
    execution: ExecutionConfig = ExecutionConfig()
    data: DataConfig = DataConfig()
    logging: LoggingConfig = LoggingConfig()
    signals: SignalsConfig = SignalsConfig()
    tui: TUIConfig = TUIConfig()
    web: WebConfig = WebConfig()
    learning: LearningConfig = LearningConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any = None,
        env_settings: Any = None,
        dotenv_settings: Any = None,
        file_secret_settings: Any = None,
        **kwargs: Any,
    ) -> tuple[Any, ...]:
        """Customise settings sources to include TOML file loading."""
        from pydantic_settings import TomlConfigSettingsSource

        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
        )

    @classmethod
    def from_toml(cls, toml_files: str | list[str]) -> "BotSettings":
        """Create a BotSettings instance from specific TOML files.

        Creates a dynamic subclass so the class-level model_config
        is not mutated (safe for concurrent/test use).
        """
        if isinstance(toml_files, str):
            toml_files = [toml_files]

        # Create a temporary subclass with the overridden toml_file
        overridden = type(
            "BotSettingsOverride",
            (cls,),
            {
                "model_config": SettingsConfigDict(
                    toml_file=toml_files,
                    env_prefix="FXBOT_",
                    env_nested_delimiter="__",
                ),
            },
        )
        return overridden()  # type: ignore[return-value]
