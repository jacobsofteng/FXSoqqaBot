"""Tests for Pydantic configuration models.

Covers: BotSettings, RiskConfig (three capital phases per D-03),
ExecutionConfig (mode defaults to paper per D-01), SessionConfig,
DataConfig, LoggingConfig, TOML loading, env var overrides.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# RiskConfig — capital phase risk percentages (D-03)
# ---------------------------------------------------------------------------


class TestRiskConfig:
    """Tests for the three-phase risk model per D-03."""

    def test_aggressive_phase_risk(self):
        """$50 equity falls within aggressive phase (<$100), risk should be 10%."""
        from fxsoqqabot.config.models import RiskConfig

        cfg = RiskConfig()
        assert cfg.get_risk_pct(equity=50.0) == 0.10

    def test_selective_phase_risk(self):
        """$150 equity falls within selective phase ($100-$300), risk should be 5%."""
        from fxsoqqabot.config.models import RiskConfig

        cfg = RiskConfig()
        assert cfg.get_risk_pct(equity=150.0) == 0.05

    def test_conservative_phase_risk(self):
        """$500 equity falls within conservative phase (>$300), risk should be 2%."""
        from fxsoqqabot.config.models import RiskConfig

        cfg = RiskConfig()
        assert cfg.get_risk_pct(equity=500.0) == 0.02

    def test_boundary_aggressive_to_selective(self):
        """$100 equity is at the boundary -- should transition to selective."""
        from fxsoqqabot.config.models import RiskConfig

        cfg = RiskConfig()
        assert cfg.get_risk_pct(equity=100.0) == 0.05

    def test_boundary_selective_to_conservative(self):
        """$300 equity is at the boundary -- should transition to conservative."""
        from fxsoqqabot.config.models import RiskConfig

        cfg = RiskConfig()
        assert cfg.get_risk_pct(equity=300.0) == 0.02

    def test_invalid_negative_risk_pct(self):
        """Negative risk percentage must be rejected."""
        from fxsoqqabot.config.models import RiskConfig

        with pytest.raises(ValidationError):
            RiskConfig(aggressive_risk_pct=-0.01)

    def test_invalid_risk_pct_over_one(self):
        """Risk percentage > 1.0 must be rejected."""
        from fxsoqqabot.config.models import RiskConfig

        with pytest.raises(ValidationError):
            RiskConfig(aggressive_risk_pct=1.5)

    def test_invalid_zero_risk_pct(self):
        """Zero risk percentage must be rejected (must be > 0)."""
        from fxsoqqabot.config.models import RiskConfig

        with pytest.raises(ValidationError):
            RiskConfig(selective_risk_pct=0.0)

    def test_default_values(self):
        """All RiskConfig defaults should match the spec."""
        from fxsoqqabot.config.models import RiskConfig

        cfg = RiskConfig()
        assert cfg.aggressive_max == 100.0
        assert cfg.selective_max == 300.0
        assert cfg.aggressive_risk_pct == 0.10
        assert cfg.selective_risk_pct == 0.05
        assert cfg.conservative_risk_pct == 0.02
        assert cfg.daily_drawdown_pct == 0.05
        assert cfg.weekly_drawdown_pct == 0.10
        assert cfg.max_total_drawdown_pct == 0.25
        assert cfg.max_consecutive_losses == 5
        assert cfg.max_daily_trades == 20
        assert cfg.rapid_equity_drop_pct == 0.05
        assert cfg.rapid_equity_drop_window_minutes == 15
        assert cfg.spread_threshold_multiplier == 2.0
        assert cfg.spread_spike_multiplier == 5.0
        assert cfg.spread_spike_duration_seconds == 30


# ---------------------------------------------------------------------------
# ExecutionConfig — paper mode default (D-01/D-02)
# ---------------------------------------------------------------------------


class TestExecutionConfig:
    """Tests for execution configuration."""

    def test_mode_defaults_to_paper(self):
        """Per D-01: default mode must be 'paper'."""
        from fxsoqqabot.config.models import ExecutionConfig

        cfg = ExecutionConfig()
        assert cfg.mode == "paper"

    def test_symbol_defaults_to_xauusd(self):
        from fxsoqqabot.config.models import ExecutionConfig

        cfg = ExecutionConfig()
        assert cfg.symbol == "XAUUSD"

    def test_invalid_mode_rejected(self):
        """Mode must be 'paper' or 'live'."""
        from fxsoqqabot.config.models import ExecutionConfig

        with pytest.raises(ValidationError):
            ExecutionConfig(mode="backtest")


# ---------------------------------------------------------------------------
# SessionConfig
# ---------------------------------------------------------------------------


class TestSessionConfig:
    """Tests for session configuration."""

    def test_default_windows(self):
        """Default session window should be 13:00-17:00 UTC."""
        from fxsoqqabot.config.models import SessionConfig

        cfg = SessionConfig()
        assert len(cfg.windows) == 1
        assert cfg.windows[0]["start"] == "13:00"
        assert cfg.windows[0]["end"] == "17:00"

    def test_custom_windows(self):
        """Should accept custom session windows."""
        from fxsoqqabot.config.models import SessionConfig

        cfg = SessionConfig(
            windows=[
                {"start": "08:00", "end": "12:00"},
                {"start": "13:00", "end": "17:00"},
            ]
        )
        assert len(cfg.windows) == 2


# ---------------------------------------------------------------------------
# DataConfig
# ---------------------------------------------------------------------------


class TestDataConfig:
    def test_default_tick_buffer_size(self):
        from fxsoqqabot.config.models import DataConfig

        cfg = DataConfig()
        assert cfg.tick_buffer_size == 10000

    def test_default_bar_buffer_sizes(self):
        from fxsoqqabot.config.models import DataConfig

        cfg = DataConfig()
        assert cfg.bar_buffer_sizes["M1"] == 1440
        assert cfg.bar_buffer_sizes["M5"] == 288
        assert cfg.bar_buffer_sizes["M15"] == 96
        assert cfg.bar_buffer_sizes["H1"] == 24
        assert cfg.bar_buffer_sizes["H4"] == 6


# ---------------------------------------------------------------------------
# LoggingConfig
# ---------------------------------------------------------------------------


class TestLoggingConfig:
    def test_default_json_mode_false(self):
        from fxsoqqabot.config.models import LoggingConfig

        cfg = LoggingConfig()
        assert cfg.json_mode is False

    def test_default_level_info(self):
        from fxsoqqabot.config.models import LoggingConfig

        cfg = LoggingConfig()
        assert cfg.level == "INFO"


# ---------------------------------------------------------------------------
# BotSettings — full settings loading from TOML
# ---------------------------------------------------------------------------


class TestBotSettings:
    """Tests for the top-level BotSettings loaded from TOML."""

    def test_loads_with_defaults(self):
        """BotSettings should load with all defaults populated."""
        from fxsoqqabot.config.models import BotSettings

        settings = BotSettings()
        assert settings.execution.mode == "paper"
        assert settings.risk.aggressive_risk_pct == 0.10
        assert settings.session.timezone == "UTC"
        assert settings.data.tick_buffer_size == 10000
        assert settings.logging.json_mode is False

    def test_loads_from_default_toml(self, tmp_path: Path):
        """BotSettings should load values from a TOML file."""
        from fxsoqqabot.config.models import BotSettings

        toml_content = textwrap.dedent("""\
            [execution]
            mode = "paper"
            symbol = "XAUUSD"

            [risk]
            aggressive_risk_pct = 0.08

            [session]
            timezone = "UTC"
        """)
        toml_file = tmp_path / "test_config.toml"
        toml_file.write_text(toml_content)

        settings = BotSettings.from_toml(str(toml_file))
        # The TOML-loaded value should override the default
        assert settings.risk.aggressive_risk_pct == 0.08

    def test_env_var_overrides_toml(self, monkeypatch):
        """Environment variable FXBOT_EXECUTION__MODE should override TOML value."""
        from fxsoqqabot.config.models import BotSettings

        monkeypatch.setenv("FXBOT_EXECUTION__MODE", "live")
        settings = BotSettings()
        assert settings.execution.mode == "live"
        monkeypatch.delenv("FXBOT_EXECUTION__MODE", raising=False)


# ---------------------------------------------------------------------------
# TOML files — paper.toml and live.toml overrides
# ---------------------------------------------------------------------------


class TestTomlOverrides:
    """Tests for config override files."""

    def test_paper_toml_sets_paper_mode(self, tmp_path: Path):
        """Paper.toml should set mode to 'paper'."""
        from fxsoqqabot.config.models import BotSettings

        toml_content = textwrap.dedent("""\
            [execution]
            mode = "paper"
        """)
        toml_file = tmp_path / "paper.toml"
        toml_file.write_text(toml_content)

        settings = BotSettings.from_toml(str(toml_file))
        assert settings.execution.mode == "paper"

    def test_live_toml_sets_live_mode(self, tmp_path: Path):
        """Live.toml should set mode to 'live'."""
        from fxsoqqabot.config.models import BotSettings

        toml_content = textwrap.dedent("""\
            [execution]
            mode = "live"
        """)
        toml_file = tmp_path / "live.toml"
        toml_file.write_text(toml_content)

        settings = BotSettings.from_toml(str(toml_file))
        assert settings.execution.mode == "live"


# ---------------------------------------------------------------------------
# Loader — load_settings()
# ---------------------------------------------------------------------------


class TestLoadSettings:
    """Tests for the load_settings() convenience function."""

    def test_load_settings_returns_bot_settings(self):
        """load_settings() should return a validated BotSettings instance."""
        from fxsoqqabot.config.loader import load_settings
        from fxsoqqabot.config.models import BotSettings

        settings = load_settings()
        assert isinstance(settings, BotSettings)
        assert settings.execution.mode == "paper"

    def test_load_settings_with_custom_files(self, tmp_path: Path):
        """load_settings() should accept custom config file paths."""
        from fxsoqqabot.config.loader import load_settings

        toml_content = textwrap.dedent("""\
            [execution]
            mode = "live"
        """)
        toml_file = tmp_path / "custom.toml"
        toml_file.write_text(toml_content)

        settings = load_settings(config_files=[str(toml_file)])
        assert settings.execution.mode == "live"
