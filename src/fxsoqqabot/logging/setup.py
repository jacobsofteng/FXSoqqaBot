"""Structured logging configuration for FXSoqqaBot.

Configures structlog with dual renderer modes:
  - Development (json_mode=False): Rich-powered console output
  - Production (json_mode=True): JSON output for machine parsing / DuckDB analysis

Uses contextvars for cross-module context propagation (trade_id, regime_state, etc.).
"""

from __future__ import annotations

import logging

import structlog

from fxsoqqabot.config.models import LoggingConfig


def setup_logging(config: LoggingConfig) -> None:
    """Configure structlog for the trading bot.

    Args:
        config: LoggingConfig instance controlling output format and level.
    """
    # Map string level to logging constant
    log_level = getattr(logging, config.level.upper(), logging.INFO)

    # Shared processors for both modes
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if config.json_mode:
        # Production: JSON output for machine parsing and DuckDB analysis
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        # Development: colorful console output via Rich
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            renderer,
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )
