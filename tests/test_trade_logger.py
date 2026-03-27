"""Tests for TradeContextLogger with DuckDB trade_log table.

Covers: table creation, log_trade_open, log_trade_close,
query_trades (by regime, outcome, date range), get_recent_trades.
Uses in-memory DuckDB connection for test isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from fxsoqqabot.core.events import FillEvent
from fxsoqqabot.signals.base import RegimeState, SignalOutput
from fxsoqqabot.signals.fusion.core import FusionResult
from fxsoqqabot.signals.fusion.trade_manager import TradeDecision


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    """In-memory DuckDB connection for test isolation."""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def make_decision():
    """Factory for TradeDecision instances."""
    def _make(
        action: str = "buy",
        sl_distance: float = 2.0,
        tp_distance: float = 6.0,
        lot_size: float = 0.01,
        confidence: float = 0.75,
        regime: RegimeState = RegimeState.TRENDING_UP,
        reason: str = "Fusion threshold exceeded",
    ) -> TradeDecision:
        return TradeDecision(
            action=action,
            sl_distance=sl_distance,
            tp_distance=tp_distance,
            lot_size=lot_size,
            confidence=confidence,
            regime=regime,
            reason=reason,
        )
    return _make


@pytest.fixture
def make_fill():
    """Factory for FillEvent instances."""
    def _make(
        ticket: int = 12345,
        fill_price: float = 2050.50,
        slippage: float = 0.10,
        is_paper: bool = False,
        action: str = "buy",
        timestamp: datetime | None = None,
    ) -> FillEvent:
        return FillEvent(
            ticket=ticket,
            symbol="XAUUSD",
            action=action,
            volume=0.01,
            fill_price=fill_price,
            requested_price=fill_price - slippage,
            slippage=slippage,
            sl=2048.50,
            tp=2056.50,
            magic=20260327,
            is_paper=is_paper,
            timestamp=timestamp or datetime.now(UTC),
        )
    return _make


@pytest.fixture
def make_signals():
    """Factory for a list of SignalOutput instances."""
    def _make(
        chaos_dir: float = 0.8,
        chaos_conf: float = 0.7,
        flow_dir: float = 0.6,
        flow_conf: float = 0.8,
        timing_dir: float = 0.5,
        timing_conf: float = 0.6,
        regime: RegimeState = RegimeState.TRENDING_UP,
    ) -> list[SignalOutput]:
        return [
            SignalOutput(
                module_name="chaos",
                direction=chaos_dir,
                confidence=chaos_conf,
                regime=regime,
            ),
            SignalOutput(
                module_name="flow",
                direction=flow_dir,
                confidence=flow_conf,
            ),
            SignalOutput(
                module_name="timing",
                direction=timing_dir,
                confidence=timing_conf,
            ),
        ]
    return _make


@pytest.fixture
def make_fusion_result():
    """Factory for FusionResult instances."""
    def _make(
        direction: float = 1.0,
        composite_score: float = 0.7,
        fused_confidence: float = 0.72,
        should_trade: bool = True,
        regime: RegimeState = RegimeState.TRENDING_UP,
    ) -> FusionResult:
        return FusionResult(
            direction=direction,
            composite_score=composite_score,
            fused_confidence=fused_confidence,
            should_trade=should_trade,
            regime=regime,
            module_scores={"chaos": 0.56, "flow": 0.48, "timing": 0.30},
            confidence_threshold=0.5,
        )
    return _make


@pytest.fixture
def weights():
    """Default module weights."""
    return {"chaos": 0.4, "flow": 0.35, "timing": 0.25}


# ---------------------------------------------------------------------------
# Test: table creation
# ---------------------------------------------------------------------------


class TestTradeLogTable:
    """Tests for trade_log table creation."""

    def test_init_creates_table(self, db):
        """_init_trade_log_table() creates the trade_log table."""
        from fxsoqqabot.learning.trade_logger import TradeContextLogger

        logger = TradeContextLogger(db)
        # Table should exist -- query it
        result = db.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'trade_log'"
        ).fetchone()
        assert result[0] == 1

    def test_table_has_expected_columns(self, db):
        """trade_log table has all ~25+ columns from D-11."""
        from fxsoqqabot.learning.trade_logger import TradeContextLogger

        logger = TradeContextLogger(db)
        cols = db.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'trade_log' ORDER BY ordinal_position"
        ).fetchall()
        col_names = [c[0] for c in cols]

        expected = [
            "trade_id", "ticket", "timestamp", "action", "entry_price",
            "exit_price", "lot_size", "sl_distance", "tp_distance",
            "regime", "regime_confidence", "chaos_direction", "chaos_confidence",
            "flow_direction", "flow_confidence", "timing_direction",
            "timing_confidence", "composite_score", "fused_confidence",
            "confidence_threshold", "weight_chaos", "weight_flow",
            "weight_timing", "atr", "spread_at_entry", "slippage",
            "equity_at_trade", "pnl", "hold_duration_seconds",
            "exit_regime", "is_paper", "variant_id",
        ]
        for col in expected:
            assert col in col_names, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# Test: log_trade_open
# ---------------------------------------------------------------------------


class TestLogTradeOpen:
    """Tests for log_trade_open()."""

    def test_inserts_record(
        self, db, make_decision, make_fill, make_signals, make_fusion_result, weights
    ):
        """log_trade_open() inserts a record with all fields populated."""
        from fxsoqqabot.learning.trade_logger import TradeContextLogger

        logger = TradeContextLogger(db)
        decision = make_decision()
        fill = make_fill()
        signals = make_signals()
        fusion = make_fusion_result()

        logger.log_trade_open(
            decision=decision,
            fill=fill,
            signals=signals,
            fusion_result=fusion,
            weights=weights,
            equity=20.0,
            atr=3.5,
        )

        rows = db.execute("SELECT * FROM trade_log").fetchall()
        assert len(rows) == 1

    def test_exit_fields_null_on_open(
        self, db, make_decision, make_fill, make_signals, make_fusion_result, weights
    ):
        """exit_price, pnl, hold_duration_seconds are NULL on open."""
        from fxsoqqabot.learning.trade_logger import TradeContextLogger

        logger = TradeContextLogger(db)
        logger.log_trade_open(
            decision=make_decision(),
            fill=make_fill(),
            signals=make_signals(),
            fusion_result=make_fusion_result(),
            weights=weights,
            equity=20.0,
            atr=3.5,
        )

        row = db.execute(
            "SELECT exit_price, pnl, hold_duration_seconds FROM trade_log"
        ).fetchone()
        assert row[0] is None  # exit_price
        assert row[1] is None  # pnl
        assert row[2] is None  # hold_duration_seconds

    def test_signal_fields_populated(
        self, db, make_decision, make_fill, make_signals, make_fusion_result, weights
    ):
        """Per-module direction and confidence are extracted from signals list."""
        from fxsoqqabot.learning.trade_logger import TradeContextLogger

        logger = TradeContextLogger(db)
        signals = make_signals(
            chaos_dir=0.8, chaos_conf=0.7,
            flow_dir=0.6, flow_conf=0.8,
            timing_dir=0.5, timing_conf=0.6,
        )
        logger.log_trade_open(
            decision=make_decision(),
            fill=make_fill(),
            signals=signals,
            fusion_result=make_fusion_result(),
            weights=weights,
            equity=20.0,
            atr=3.5,
        )

        row = db.execute(
            "SELECT chaos_direction, chaos_confidence, flow_direction, "
            "flow_confidence, timing_direction, timing_confidence FROM trade_log"
        ).fetchone()
        assert row[0] == pytest.approx(0.8)  # chaos_direction
        assert row[1] == pytest.approx(0.7)  # chaos_confidence
        assert row[2] == pytest.approx(0.6)  # flow_direction
        assert row[3] == pytest.approx(0.8)  # flow_confidence
        assert row[4] == pytest.approx(0.5)  # timing_direction
        assert row[5] == pytest.approx(0.6)  # timing_confidence


# ---------------------------------------------------------------------------
# Test: log_trade_close
# ---------------------------------------------------------------------------


class TestLogTradeClose:
    """Tests for log_trade_close()."""

    def test_updates_exit_fields(
        self, db, make_decision, make_fill, make_signals, make_fusion_result, weights
    ):
        """log_trade_close() updates exit_price, pnl, hold_duration_seconds, exit_regime."""
        from fxsoqqabot.learning.trade_logger import TradeContextLogger

        logger = TradeContextLogger(db)
        logger.log_trade_open(
            decision=make_decision(),
            fill=make_fill(ticket=100),
            signals=make_signals(),
            fusion_result=make_fusion_result(),
            weights=weights,
            equity=20.0,
            atr=3.5,
        )

        logger.log_trade_close(
            ticket=100,
            exit_price=2053.50,
            pnl=3.0,
            hold_duration_seconds=45.0,
            exit_regime="ranging",
        )

        row = db.execute(
            "SELECT exit_price, pnl, hold_duration_seconds, exit_regime "
            "FROM trade_log WHERE ticket = 100"
        ).fetchone()
        assert row[0] == pytest.approx(2053.50)
        assert row[1] == pytest.approx(3.0)
        assert row[2] == pytest.approx(45.0)
        assert row[3] == "ranging"


# ---------------------------------------------------------------------------
# Test: query_trades
# ---------------------------------------------------------------------------


class TestQueryTrades:
    """Tests for query_trades() with filtering."""

    def _insert_trades(self, db, make_decision, make_fill, make_signals, make_fusion_result, weights):
        """Helper to insert multiple trades for query tests."""
        from fxsoqqabot.learning.trade_logger import TradeContextLogger

        logger = TradeContextLogger(db)

        # Trade 1: trending_up, win
        logger.log_trade_open(
            decision=make_decision(regime=RegimeState.TRENDING_UP),
            fill=make_fill(ticket=1, timestamp=datetime(2026, 3, 20, 10, 0, tzinfo=UTC)),
            signals=make_signals(regime=RegimeState.TRENDING_UP),
            fusion_result=make_fusion_result(regime=RegimeState.TRENDING_UP),
            weights=weights,
            equity=20.0,
            atr=3.5,
        )
        logger.log_trade_close(ticket=1, exit_price=2053.0, pnl=2.5, hold_duration_seconds=30.0, exit_regime="trending_up")

        # Trade 2: ranging, loss
        logger.log_trade_open(
            decision=make_decision(regime=RegimeState.RANGING),
            fill=make_fill(ticket=2, timestamp=datetime(2026, 3, 21, 14, 0, tzinfo=UTC)),
            signals=make_signals(regime=RegimeState.RANGING),
            fusion_result=make_fusion_result(regime=RegimeState.RANGING),
            weights=weights,
            equity=22.5,
            atr=3.0,
        )
        logger.log_trade_close(ticket=2, exit_price=2048.0, pnl=-2.0, hold_duration_seconds=60.0, exit_regime="ranging")

        # Trade 3: trending_up, win
        logger.log_trade_open(
            decision=make_decision(regime=RegimeState.TRENDING_UP),
            fill=make_fill(ticket=3, timestamp=datetime(2026, 3, 25, 9, 0, tzinfo=UTC)),
            signals=make_signals(regime=RegimeState.TRENDING_UP),
            fusion_result=make_fusion_result(regime=RegimeState.TRENDING_UP),
            weights=weights,
            equity=20.5,
            atr=4.0,
        )
        logger.log_trade_close(ticket=3, exit_price=2055.0, pnl=4.5, hold_duration_seconds=120.0, exit_regime="trending_up")

        return logger

    def test_filter_by_regime(
        self, db, make_decision, make_fill, make_signals, make_fusion_result, weights
    ):
        """query_trades(regime='trending_up') returns only trending_up trades."""
        logger = self._insert_trades(
            db, make_decision, make_fill, make_signals, make_fusion_result, weights
        )
        results = logger.query_trades(regime="trending_up")
        assert len(results) == 2
        for r in results:
            assert r["regime"] == "trending_up"

    def test_filter_by_outcome_win(
        self, db, make_decision, make_fill, make_signals, make_fusion_result, weights
    ):
        """query_trades(outcome='win') returns trades with pnl > 0."""
        logger = self._insert_trades(
            db, make_decision, make_fill, make_signals, make_fusion_result, weights
        )
        results = logger.query_trades(outcome="win")
        assert len(results) == 2
        for r in results:
            assert r["pnl"] > 0

    def test_filter_by_outcome_loss(
        self, db, make_decision, make_fill, make_signals, make_fusion_result, weights
    ):
        """query_trades(outcome='loss') returns trades with pnl < 0."""
        logger = self._insert_trades(
            db, make_decision, make_fill, make_signals, make_fusion_result, weights
        )
        results = logger.query_trades(outcome="loss")
        assert len(results) == 1
        assert results[0]["pnl"] < 0

    def test_filter_by_date_range(
        self, db, make_decision, make_fill, make_signals, make_fusion_result, weights
    ):
        """query_trades(start_date, end_date) returns trades within range."""
        logger = self._insert_trades(
            db, make_decision, make_fill, make_signals, make_fusion_result, weights
        )
        results = logger.query_trades(
            start_date=datetime(2026, 3, 21, tzinfo=UTC),
            end_date=datetime(2026, 3, 22, tzinfo=UTC),
        )
        assert len(results) == 1
        assert results[0]["ticket"] == 2


# ---------------------------------------------------------------------------
# Test: get_recent_trades
# ---------------------------------------------------------------------------


class TestGetRecentTrades:
    """Tests for get_recent_trades()."""

    def test_limit_respected(
        self, db, make_decision, make_fill, make_signals, make_fusion_result, weights
    ):
        """get_recent_trades(limit=2) returns at most 2 rows ordered by timestamp DESC."""
        from fxsoqqabot.learning.trade_logger import TradeContextLogger

        logger = TradeContextLogger(db)

        for i in range(5):
            logger.log_trade_open(
                decision=make_decision(),
                fill=make_fill(
                    ticket=100 + i,
                    timestamp=datetime(2026, 3, 20 + i, 10, 0, tzinfo=UTC),
                ),
                signals=make_signals(),
                fusion_result=make_fusion_result(),
                weights=weights,
                equity=20.0,
                atr=3.5,
            )

        results = logger.get_recent_trades(limit=2)
        assert len(results) == 2
        # Most recent first
        assert results[0]["ticket"] == 104
        assert results[1]["ticket"] == 103


# ---------------------------------------------------------------------------
# Test: get_trade_count
# ---------------------------------------------------------------------------


class TestGetTradeCount:
    """Tests for get_trade_count()."""

    def test_count_zero_initially(self, db):
        """Trade count starts at 0."""
        from fxsoqqabot.learning.trade_logger import TradeContextLogger

        logger = TradeContextLogger(db)
        assert logger.get_trade_count() == 0

    def test_count_after_inserts(
        self, db, make_decision, make_fill, make_signals, make_fusion_result, weights
    ):
        """Trade count increments with each log_trade_open()."""
        from fxsoqqabot.learning.trade_logger import TradeContextLogger

        logger = TradeContextLogger(db)
        for i in range(3):
            logger.log_trade_open(
                decision=make_decision(),
                fill=make_fill(ticket=i),
                signals=make_signals(),
                fusion_result=make_fusion_result(),
                weights=weights,
                equity=20.0,
                atr=3.5,
            )
        assert logger.get_trade_count() == 3
