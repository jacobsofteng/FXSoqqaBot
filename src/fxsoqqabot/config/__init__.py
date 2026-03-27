"""Configuration module for FXSoqqaBot."""

from fxsoqqabot.config.loader import load_settings
from fxsoqqabot.config.models import BotSettings

__all__ = ["BotSettings", "load_settings"]
