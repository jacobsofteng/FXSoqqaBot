"""Logging module for FXSoqqaBot."""

import structlog

from fxsoqqabot.logging.setup import setup_logging

# Convenience alias for getting a bound logger
get_logger = structlog.get_logger

__all__ = ["setup_logging", "get_logger"]
