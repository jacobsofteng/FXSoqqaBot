"""Shared test fixtures for FXSoqqaBot."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with TOML config files for testing."""
    default_toml = tmp_path / "default.toml"
    default_toml.write_text(
        textwrap.dedent("""\
        [execution]
        mode = "paper"
        symbol = "XAUUSD"

        [risk]
        aggressive_risk_pct = 0.10
        selective_risk_pct = 0.05
        conservative_risk_pct = 0.02

        [session]
        timezone = "UTC"

        [[session.windows]]
        start = "13:00"
        end = "17:00"
    """)
    )

    paper_toml = tmp_path / "paper.toml"
    paper_toml.write_text("[execution]\nmode = \"paper\"\n")

    live_toml = tmp_path / "live.toml"
    live_toml.write_text("[execution]\nmode = \"live\"\n")

    return tmp_path


@pytest.fixture
def default_settings():
    """Return BotSettings with all defaults (no TOML files loaded)."""
    from fxsoqqabot.config.models import BotSettings

    return BotSettings()
