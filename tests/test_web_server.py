"""Tests for web dashboard FastAPI server.

Tests REST endpoints, WebSocket authentication, kill/pause controls,
and trade query filtering using httpx AsyncClient with ASGITransport.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import duckdb
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from fxsoqqabot.config.models import WebConfig
from fxsoqqabot.core.state_snapshot import TradingEngineState
from fxsoqqabot.dashboard.web.server import DashboardServer
from fxsoqqabot.learning.trade_logger import TradeContextLogger


@pytest.fixture
def web_config() -> WebConfig:
    """WebConfig with known test API key."""
    return WebConfig(host="127.0.0.1", port=8080, api_key="testkey", enabled=True)


@pytest.fixture
def state() -> TradingEngineState:
    """Pre-populated TradingEngineState for testing."""
    s = TradingEngineState()
    s.equity = 42.50
    s.daily_pnl = 2.10
    s.spread = 0.32
    s.daily_win_rate = 0.67
    s.daily_trade_count = 3
    s.equity_history = [20.0, 21.0, 22.5, 42.5]
    return s


@pytest.fixture
def trade_logger() -> TradeContextLogger:
    """In-memory DuckDB trade logger with sample trades."""
    db = duckdb.connect(":memory:")
    logger = TradeContextLogger(db)
    # Insert sample trades
    db.execute("""
        INSERT INTO trade_log (
            trade_id, ticket, timestamp, action, entry_price, exit_price,
            lot_size, sl_distance, tp_distance, regime, regime_confidence,
            chaos_direction, chaos_confidence, flow_direction, flow_confidence,
            timing_direction, timing_confidence, composite_score, fused_confidence,
            confidence_threshold, weight_chaos, weight_flow, weight_timing,
            atr, spread_at_entry, slippage, equity_at_trade, pnl,
            hold_duration_seconds, exit_regime, is_paper, variant_id
        ) VALUES
        (1, 1001, '2026-03-27 14:32:00', 'BUY', 2345.0, 2348.0, 0.01, 5.0, 15.0,
         'trending_up', 0.82, 0.7, 0.74, 0.6, 0.68, -0.3, 0.42, 0.65, 0.72,
         0.5, 0.4, 0.35, 0.25, 3.5, 0.32, 0.05, 20.0, 0.80, 120.0,
         'trending_up', false, 'live'),
        (2, 1002, '2026-03-27 14:15:00', 'SELL', 2350.0, 2351.0, 0.01, 4.0, 12.0,
         'ranging', 0.55, -0.5, 0.52, -0.4, 0.48, 0.2, 0.38, 0.45, 0.52,
         0.6, 0.4, 0.35, 0.25, 3.2, 0.28, 0.03, 20.80, -0.20, 90.0,
         'ranging', false, 'live'),
        (3, 1003, '2026-03-27 13:50:00', 'BUY', 2340.0, 2344.0, 0.01, 6.0, 18.0,
         'trending_up', 0.78, 0.8, 0.80, 0.7, 0.72, 0.5, 0.65, 0.70, 0.78,
         0.5, 0.4, 0.35, 0.25, 4.0, 0.30, 0.04, 20.0, 1.50, 180.0,
         'trending_up', false, 'live')
    """)
    return logger


@pytest.fixture
def server(web_config: WebConfig, state: TradingEngineState, trade_logger: TradeContextLogger) -> DashboardServer:
    """DashboardServer instance with test config."""
    return DashboardServer(
        config=web_config,
        state=state,
        trade_logger=trade_logger,
        kill_callback=None,
        pause_callback=None,
    )


@pytest_asyncio.fixture
async def client(server: DashboardServer) -> AsyncClient:
    """httpx AsyncClient with ASGI transport."""
    transport = ASGITransport(app=server.get_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# --- Test 1: GET / returns 200 with HTML content ---

@pytest.mark.asyncio
async def test_get_root_returns_html(client: AsyncClient) -> None:
    """GET / should return 200 with HTML content."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# --- Test 2: GET /api/trades returns list of trades ---

@pytest.mark.asyncio
async def test_get_trades_returns_list(client: AsyncClient) -> None:
    """GET /api/trades should return a list of trade records."""
    resp = await client.get("/api/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 3


# --- Test 3: GET /api/trades?regime=trending_up filters correctly ---

@pytest.mark.asyncio
async def test_get_trades_filter_regime(client: AsyncClient) -> None:
    """GET /api/trades?regime=trending_up should filter by regime."""
    resp = await client.get("/api/trades", params={"regime": "trending_up"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    for trade in data:
        assert trade["regime"] == "trending_up"


# --- Test 4: GET /api/trades?outcome=win filters pnl > 0 ---

@pytest.mark.asyncio
async def test_get_trades_filter_outcome_win(client: AsyncClient) -> None:
    """GET /api/trades?outcome=win should return only winning trades."""
    resp = await client.get("/api/trades", params={"outcome": "win"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    for trade in data:
        assert trade["pnl"] > 0


# --- Test 5: POST /api/kill without api_key returns 403 ---

@pytest.mark.asyncio
async def test_kill_without_key_returns_403(client: AsyncClient) -> None:
    """POST /api/kill without api_key should return 403."""
    resp = await client.post("/api/kill")
    assert resp.status_code == 403


# --- Test 6: POST /api/kill with correct key returns 200 ---

@pytest.mark.asyncio
async def test_kill_with_correct_key_returns_200(client: AsyncClient) -> None:
    """POST /api/kill?api_key=testkey should return 200 with killed status."""
    resp = await client.post("/api/kill", params={"api_key": "testkey"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "killed"


# --- Test 7: POST /api/pause with correct key returns 200 ---

@pytest.mark.asyncio
async def test_pause_with_correct_key_returns_200(client: AsyncClient) -> None:
    """POST /api/pause?api_key=testkey should return 200."""
    resp = await client.post("/api/pause", params={"api_key": "testkey"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("paused", "resumed")


# --- Test 8: GET /api/equity returns equity history ---

@pytest.mark.asyncio
async def test_get_equity_returns_data(client: AsyncClient) -> None:
    """GET /api/equity should return equity history data."""
    resp = await client.get("/api/equity")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert isinstance(data["data"], list)


# --- Test 9: GET /api/regime-timeline returns regime state history ---

@pytest.mark.asyncio
async def test_get_regime_timeline(client: AsyncClient) -> None:
    """GET /api/regime-timeline should return regime state history."""
    resp = await client.get("/api/regime-timeline")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert isinstance(data["data"], list)


# --- Additional tests ---

@pytest.mark.asyncio
async def test_kill_with_wrong_key_returns_403(client: AsyncClient) -> None:
    """POST /api/kill with wrong api_key should return 403."""
    resp = await client.post("/api/kill", params={"api_key": "wrongkey"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_pause_without_key_returns_403(client: AsyncClient) -> None:
    """POST /api/pause without api_key should return 403."""
    resp = await client.post("/api/pause")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_pause_toggles_state(
    client: AsyncClient, state: TradingEngineState
) -> None:
    """POST /api/pause should toggle is_paused state."""
    assert state.is_paused is False
    resp = await client.post("/api/pause", params={"api_key": "testkey"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"
    assert state.is_paused is True

    resp = await client.post("/api/pause", params={"api_key": "testkey"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "resumed"
    assert state.is_paused is False


@pytest.mark.asyncio
async def test_get_module_weights(client: AsyncClient) -> None:
    """GET /api/module-weights should return data list."""
    resp = await client.get("/api/module-weights")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_server_without_trade_logger() -> None:
    """Server should work without trade_logger (returns empty lists)."""
    config = WebConfig(api_key="testkey")
    state = TradingEngineState()
    srv = DashboardServer(config=config, state=state)
    transport = ASGITransport(app=srv.get_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        resp = await ac.get("/api/trades")
        assert resp.status_code == 200
        assert resp.json() == []
