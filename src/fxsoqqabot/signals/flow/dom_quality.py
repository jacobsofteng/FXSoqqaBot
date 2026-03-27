"""DOM quality auto-detection (D-15).

Samples DOM snapshots over a configurable window to determine if DOM
data is reliable enough to use. Checks for minimum depth on both sides
and minimum update rate. Auto-disables if quality degrades. Rechecks
periodically.
"""

from __future__ import annotations

import time
from collections import deque

import structlog

from fxsoqqabot.config.models import FlowConfig
from fxsoqqabot.core.events import DOMSnapshot

logger = structlog.get_logger().bind(component="dom_quality")


class DOMQualityChecker:
    """Tracks DOM snapshot quality and decides whether to enable DOM analysis.

    Implements D-15: sample DOM snapshots for a configurable duration,
    check depth >= min_depth on both sides and update_rate >= min_rate,
    enable/disable DOM analysis accordingly with logging.
    """

    def __init__(self, config: FlowConfig) -> None:
        self._config = config
        self._snapshots: deque[tuple[int, int, int]] = deque(
            maxlen=config.dom_quality_check_duration_seconds * 100,
        )
        # Each entry: (time_msc, bid_count, ask_count)
        self._dom_enabled: bool = False
        self._last_check_time: float = 0.0
        self._check_started: bool = False

    @property
    def is_dom_enabled(self) -> bool:
        """Return whether DOM analysis is currently enabled."""
        return self._dom_enabled

    def record_snapshot(self, dom: DOMSnapshot) -> None:
        """Record a DOM snapshot for quality evaluation.

        After accumulating enough samples (duration_seconds worth),
        evaluates quality and enables/disables DOM analysis.
        """
        bid_count = sum(1 for e in dom.entries if e.type == 2)
        ask_count = sum(1 for e in dom.entries if e.type == 1)

        self._snapshots.append((dom.time_msc, bid_count, ask_count))

        if not self._check_started:
            self._check_started = True
            self._last_check_time = time.monotonic()

        # Evaluate quality once we have enough samples
        if len(self._snapshots) >= 2:
            self._evaluate_quality()

    def _evaluate_quality(self) -> None:
        """Evaluate DOM quality from accumulated snapshots.

        Checks:
        1. Depth >= min_depth on both bid and ask sides
        2. Update rate >= min_update_rate per second

        Sets _dom_enabled accordingly and logs state changes.
        """
        if len(self._snapshots) < 2:
            return

        config = self._config

        # Check depth: average depth on each side across recent snapshots
        bid_depths = [s[1] for s in self._snapshots]
        ask_depths = [s[2] for s in self._snapshots]

        avg_bid_depth = sum(bid_depths) / len(bid_depths)
        avg_ask_depth = sum(ask_depths) / len(ask_depths)

        depth_ok = (
            avg_bid_depth >= config.dom_min_depth
            and avg_ask_depth >= config.dom_min_depth
        )

        # Check update rate: snapshots per second
        times_msc = [s[0] for s in self._snapshots]
        time_span_sec = (times_msc[-1] - times_msc[0]) / 1000.0

        if time_span_sec > 0:
            update_rate = len(self._snapshots) / time_span_sec
        else:
            update_rate = 0.0

        # Check if we have sampled long enough
        duration_ok = time_span_sec >= config.dom_quality_check_duration_seconds

        rate_ok = update_rate >= config.dom_min_update_rate

        was_enabled = self._dom_enabled

        if duration_ok or len(self._snapshots) >= self._snapshots.maxlen:
            self._dom_enabled = depth_ok and rate_ok
        elif config.dom_quality_check_duration_seconds == 0:
            # Instant check mode (for testing)
            self._dom_enabled = depth_ok and rate_ok

        if self._dom_enabled != was_enabled:
            if self._dom_enabled:
                logger.info(
                    "dom_quality_enabled",
                    avg_bid_depth=avg_bid_depth,
                    avg_ask_depth=avg_ask_depth,
                    update_rate=update_rate,
                )
            else:
                logger.info(
                    "dom_quality_disabled",
                    avg_bid_depth=avg_bid_depth,
                    avg_ask_depth=avg_ask_depth,
                    update_rate=update_rate,
                )

        self._last_check_time = time.monotonic()

    def needs_recheck(self) -> bool:
        """Return True if dom_recheck_interval_minutes has elapsed."""
        elapsed = time.monotonic() - self._last_check_time
        return elapsed >= self._config.dom_recheck_interval_minutes * 60
