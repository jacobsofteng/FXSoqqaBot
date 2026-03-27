"""Trade context logger with DuckDB trade_log table per D-11/D-12/D-13.

Captures full trade context (~25 fields) to DuckDB for post-hoc analysis,
self-learning feedback, and dashboard consumption. Every trade is logged
with signal-level detail: per-module direction/confidence, fusion scores,
regime state, execution metrics, and outcome.

Follows the TickStorage pattern from data/storage.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import duckdb
import structlog

from fxsoqqabot.core.events import FillEvent
from fxsoqqabot.signals.base import SignalOutput
from fxsoqqabot.signals.fusion.core import FusionResult
from fxsoqqabot.signals.fusion.trade_manager import TradeDecision

_logger = structlog.get_logger().bind(component="trade_logger")


class TradeContextLogger:
    """Logs full trade context to DuckDB trade_log table per D-11.

    Constructor takes a duckdb.DuckDBPyConnection (from TickStorage._db
    or a new connection). Creates the trade_log table on init.

    Args:
        db: DuckDB connection (can be in-memory for testing).
    """

    def __init__(self, db: duckdb.DuckDBPyConnection) -> None:
        self._db = db
        self._init_trade_log_table()

    def _init_trade_log_table(self) -> None:
        """Create the trade_log table if it doesn't exist."""
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS trade_log (
                trade_id INTEGER PRIMARY KEY,
                ticket BIGINT,
                timestamp TIMESTAMP,
                action VARCHAR,
                entry_price DOUBLE,
                exit_price DOUBLE,
                lot_size DOUBLE,
                sl_distance DOUBLE,
                tp_distance DOUBLE,
                regime VARCHAR,
                regime_confidence DOUBLE,
                chaos_direction DOUBLE,
                chaos_confidence DOUBLE,
                flow_direction DOUBLE,
                flow_confidence DOUBLE,
                timing_direction DOUBLE,
                timing_confidence DOUBLE,
                composite_score DOUBLE,
                fused_confidence DOUBLE,
                confidence_threshold DOUBLE,
                weight_chaos DOUBLE,
                weight_flow DOUBLE,
                weight_timing DOUBLE,
                atr DOUBLE,
                spread_at_entry DOUBLE,
                slippage DOUBLE,
                equity_at_trade DOUBLE,
                pnl DOUBLE,
                hold_duration_seconds DOUBLE,
                exit_regime VARCHAR,
                is_paper BOOLEAN DEFAULT FALSE,
                variant_id VARCHAR DEFAULT 'live'
            )
        """)

    def _next_trade_id(self) -> int:
        """Generate auto-incrementing trade_id."""
        result = self._db.execute(
            "SELECT COALESCE(MAX(trade_id), 0) + 1 FROM trade_log"
        ).fetchone()
        return result[0]

    def _extract_signal(
        self, signals: list[SignalOutput], module_name: str
    ) -> tuple[float, float]:
        """Extract direction and confidence for a specific module.

        Args:
            signals: List of SignalOutput from upstream modules.
            module_name: Module identifier ("chaos", "flow", "timing").

        Returns:
            Tuple of (direction, confidence). Defaults to (0.0, 0.0)
            if the module is not found.
        """
        for signal in signals:
            if signal.module_name == module_name:
                return signal.direction, signal.confidence
        return 0.0, 0.0

    def log_trade_open(
        self,
        decision: TradeDecision,
        fill: FillEvent,
        signals: list[SignalOutput],
        fusion_result: FusionResult,
        weights: dict[str, float],
        equity: float,
        atr: float,
        variant_id: str = "live",
    ) -> None:
        """Log a trade open with full context per D-11.

        Inserts a record with all signal, regime, fusion, and execution
        fields populated. Exit fields (exit_price, pnl, hold_duration_seconds,
        exit_regime) are NULL until log_trade_close().

        Args:
            decision: TradeDecision from TradeManager.
            fill: FillEvent from execution layer.
            signals: List of SignalOutput from upstream modules.
            fusion_result: FusionResult from FusionCore.
            weights: Module name -> weight mapping.
            equity: Account equity at time of trade.
            atr: ATR value used for SL computation.
            variant_id: Variant identifier ("live" or shadow variant ID).
        """
        trade_id = self._next_trade_id()

        chaos_dir, chaos_conf = self._extract_signal(signals, "chaos")
        flow_dir, flow_conf = self._extract_signal(signals, "flow")
        timing_dir, timing_conf = self._extract_signal(signals, "timing")

        # Compute spread from fill
        spread_at_entry = fill.ask - fill.fill_price if hasattr(fill, "ask") else 0.0
        # Use slippage from fill directly
        slippage = fill.slippage

        self._db.execute(
            """
            INSERT INTO trade_log (
                trade_id, ticket, timestamp, action, entry_price,
                exit_price, lot_size, sl_distance, tp_distance,
                regime, regime_confidence, chaos_direction, chaos_confidence,
                flow_direction, flow_confidence, timing_direction,
                timing_confidence, composite_score, fused_confidence,
                confidence_threshold, weight_chaos, weight_flow,
                weight_timing, atr, spread_at_entry, slippage,
                equity_at_trade, pnl, hold_duration_seconds,
                exit_regime, is_paper, variant_id
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?
            )
            """,
            [
                trade_id,
                fill.ticket,
                fill.timestamp,
                fill.action,
                fill.fill_price,
                None,  # exit_price
                decision.lot_size,
                decision.sl_distance,
                decision.tp_distance,
                decision.regime.value,
                decision.confidence,
                chaos_dir,
                chaos_conf,
                flow_dir,
                flow_conf,
                timing_dir,
                timing_conf,
                fusion_result.composite_score,
                fusion_result.fused_confidence,
                fusion_result.confidence_threshold,
                weights.get("chaos", 0.0),
                weights.get("flow", 0.0),
                weights.get("timing", 0.0),
                atr,
                spread_at_entry,
                slippage,
                equity,
                None,  # pnl
                None,  # hold_duration_seconds
                None,  # exit_regime
                fill.is_paper,
                variant_id,
            ],
        )

        _logger.info(
            "trade_logged_open",
            trade_id=trade_id,
            ticket=fill.ticket,
            action=fill.action,
            regime=decision.regime.value,
            variant_id=variant_id,
        )

    def log_trade_close(
        self,
        ticket: int,
        exit_price: float,
        pnl: float,
        hold_duration_seconds: float,
        exit_regime: str,
    ) -> None:
        """Update a trade_log row with exit information.

        Args:
            ticket: Position ticket to update.
            exit_price: Price at which the position was closed.
            pnl: Realized profit/loss in account currency.
            hold_duration_seconds: Duration the position was held.
            exit_regime: Market regime at time of close.
        """
        self._db.execute(
            """
            UPDATE trade_log
            SET exit_price = ?,
                pnl = ?,
                hold_duration_seconds = ?,
                exit_regime = ?
            WHERE ticket = ?
            """,
            [exit_price, pnl, hold_duration_seconds, exit_regime, ticket],
        )

        _logger.info(
            "trade_logged_close",
            ticket=ticket,
            exit_price=exit_price,
            pnl=pnl,
            hold_duration_seconds=hold_duration_seconds,
            exit_regime=exit_regime,
        )

    def query_trades(
        self,
        regime: str | None = None,
        outcome: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        min_confidence: float | None = None,
        variant_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query trades with optional filtering.

        Args:
            regime: Filter by regime (e.g. "trending_up").
            outcome: Filter by outcome ("win" -> pnl > 0, "loss" -> pnl < 0).
            start_date: Filter trades on or after this datetime.
            end_date: Filter trades on or before this datetime.
            min_confidence: Filter by minimum fused_confidence.
            variant_id: Filter by variant identifier.
            limit: Maximum number of results (default 100).

        Returns:
            List of trade records as dicts.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if regime is not None:
            conditions.append("regime = ?")
            params.append(regime)

        if outcome is not None:
            if outcome == "win":
                conditions.append("pnl > 0")
            elif outcome == "loss":
                conditions.append("pnl < 0")

        if start_date is not None:
            conditions.append("timestamp >= ?")
            params.append(start_date)

        if end_date is not None:
            conditions.append("timestamp <= ?")
            params.append(end_date)

        if min_confidence is not None:
            conditions.append("fused_confidence >= ?")
            params.append(min_confidence)

        if variant_id is not None:
            conditions.append("variant_id = ?")
            params.append(variant_id)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"SELECT * FROM trade_log {where_clause} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        df = self._db.execute(query, params).fetchdf()
        return df.to_dict(orient="records")

    def get_recent_trades(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return last N trades ordered by timestamp DESC.

        Args:
            limit: Maximum number of trades to return.

        Returns:
            List of trade records as dicts.
        """
        df = self._db.execute(
            "SELECT * FROM trade_log ORDER BY timestamp DESC LIMIT ?",
            [limit],
        ).fetchdf()
        return df.to_dict(orient="records")

    def get_trade_count(self) -> int:
        """Return total number of trades.

        Returns:
            Integer count of all rows in trade_log.
        """
        result = self._db.execute("SELECT COUNT(*) FROM trade_log").fetchone()
        return result[0]

    def get_trade_count_since(self, timestamp: datetime) -> int:
        """Return number of trades since a given datetime.

        Args:
            timestamp: Cutoff datetime.

        Returns:
            Integer count of trades with timestamp >= cutoff.
        """
        result = self._db.execute(
            "SELECT COUNT(*) FROM trade_log WHERE timestamp >= ?",
            [timestamp],
        ).fetchone()
        return result[0]
