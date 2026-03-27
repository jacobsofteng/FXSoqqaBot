"""Configuration loader for FXSoqqaBot.

Provides load_settings() to load and validate configuration from
TOML files with environment variable overrides.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fxsoqqabot.config.models import BotSettings

logger = logging.getLogger(__name__)


def load_settings(
    config_files: list[str] | None = None,
) -> BotSettings:
    """Load and validate bot configuration.

    Args:
        config_files: Optional list of TOML file paths to load.
            If None, uses the default config/default.toml.

    Returns:
        Validated BotSettings instance.

    Note:
        Missing config files are handled gracefully with a warning.
        Defaults are used for any values not specified in config files.
    """
    if config_files is not None:
        # Check for missing files and warn
        for f in config_files:
            if not Path(f).exists():
                logger.warning("Config file not found: %s (using defaults)", f)
        return BotSettings.from_toml(config_files)

    return BotSettings()
