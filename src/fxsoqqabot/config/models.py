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
