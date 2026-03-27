"""FastAPI web dashboard server with WebSocket and REST endpoints.

Provides real-time monitoring via WebSocket (/ws/live) and historical
data via REST endpoints (/api/trades, /api/equity, /api/regime-timeline,
/api/module-weights). Kill switch and pause/resume require API key auth.

Serves static files (HTML, CSS, JS) for the single-page dashboard.
Accessible from any device on the local network via 0.0.0.0 binding.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import structlog

from fxsoqqabot.config.models import WebConfig
from fxsoqqabot.core.state_snapshot import TradingEngineState

logger = structlog.get_logger().bind(component="web_dashboard")

_STATIC_DIR = Path(__file__).parent / "static"


class DashboardServer:
    """FastAPI web dashboard for FXSoqqaBot real-time monitoring.

    Wraps a FastAPI app with WebSocket live feed, REST endpoints for
    trade history and analytics, and kill/pause controls with API key auth.

    Args:
        config: WebConfig with host, port, api_key settings.
        state: Shared TradingEngineState updated by the trading engine.
        trade_logger: Optional TradeContextLogger for trade queries.
        kill_callback: Optional async/sync callable invoked on kill.
        pause_callback: Optional async/sync callable invoked on pause/resume.
    """

    def __init__(
        self,
        config: WebConfig,
        state: TradingEngineState,
        trade_logger: Any | None = None,
        kill_callback: Callable[[], Any] | None = None,
        pause_callback: Callable[[], Any] | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._trade_logger = trade_logger
        self._kill_callback = kill_callback
        self._pause_callback = pause_callback
        self._server: Any | None = None

        self._app = FastAPI(title="FXSoqqaBot Dashboard")

        # Mount static files
        if _STATIC_DIR.exists():
            self._app.mount(
                "/static",
                StaticFiles(directory=str(_STATIC_DIR)),
                name="static",
            )

        self._register_routes()

    def _register_routes(self) -> None:
        """Register all REST and WebSocket routes."""
        app = self._app

        @app.get("/", response_class=HTMLResponse)
        async def get_index() -> FileResponse:
            """Serve the dashboard HTML page."""
            index_path = _STATIC_DIR / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path), media_type="text/html")
            return HTMLResponse(
                content="<html><body><h1>FXSoqqaBot Dashboard</h1>"
                "<p>Static files not found. Place index.html in static/.</p>"
                "</body></html>",
                status_code=200,
            )

        @app.get("/api/trades")
        async def get_trades(
            regime: str | None = Query(None),
            outcome: str | None = Query(None),
            start_date: str | None = Query(None),
            end_date: str | None = Query(None),
            min_confidence: float | None = Query(None),
            variant_id: str | None = Query(None),
            limit: int = Query(100),
        ) -> list[dict[str, Any]]:
            """Query trades with optional filters.

            Delegates to TradeContextLogger.query_trades() if available.
            Returns empty list if no trade_logger is configured.
            """
            if self._trade_logger is None:
                return []

            trades = self._trade_logger.query_trades(
                regime=regime,
                outcome=outcome,
                start_date=start_date,
                end_date=end_date,
                min_confidence=min_confidence,
                variant_id=variant_id,
                limit=limit,
            )
            # Convert any non-serializable types (timestamps, etc.)
            return _sanitize_trades(trades)

        @app.get("/api/equity")
        async def get_equity() -> dict[str, Any]:
            """Return equity history data for Plotly chart."""
            history = self._state.equity_history
            data = [
                {"index": i, "equity": val}
                for i, val in enumerate(history)
            ]
            return {"data": data}

        @app.get("/api/regime-timeline")
        async def get_regime_timeline() -> dict[str, Any]:
            """Return regime state history from trade log."""
            if self._trade_logger is None:
                return {"data": []}

            trades = self._trade_logger.query_trades(limit=200)
            data = []
            for trade in trades:
                ts = trade.get("timestamp")
                regime = trade.get("regime")
                if ts is not None and regime is not None:
                    data.append({
                        "timestamp": str(ts),
                        "regime": regime,
                    })
            return {"data": data}

        @app.get("/api/module-weights")
        async def get_module_weights() -> dict[str, Any]:
            """Return module weight history (placeholder until learning loop wired)."""
            # Placeholder -- will be populated when learning loop tracks weight history
            return {"data": []}

        @app.post("/api/kill")
        async def kill_positions(
            api_key: str | None = Query(None),
        ) -> dict[str, str]:
            """Emergency kill: close all positions and halt trading.

            Requires valid API key matching WebConfig.api_key.
            """
            if api_key is None or api_key != self._config.api_key:
                raise HTTPException(status_code=403, detail="Invalid API key")

            self._state.is_killed = True

            if self._kill_callback is not None:
                result = self._kill_callback()
                if asyncio.iscoroutine(result):
                    await result

            logger.warning("kill_switch_activated", source="web_dashboard")
            return {"status": "killed"}

        @app.post("/api/pause")
        async def pause_trading(
            api_key: str | None = Query(None),
        ) -> dict[str, str]:
            """Toggle pause/resume trading state.

            Requires valid API key matching WebConfig.api_key.
            """
            if api_key is None or api_key != self._config.api_key:
                raise HTTPException(status_code=403, detail="Invalid API key")

            self._state.is_paused = not self._state.is_paused
            status = "paused" if self._state.is_paused else "resumed"

            if self._pause_callback is not None:
                result = self._pause_callback()
                if asyncio.iscoroutine(result):
                    await result

            logger.info("trading_state_changed", status=status, source="web_dashboard")
            return {"status": status}

        @app.websocket("/ws/live")
        async def websocket_live(ws: WebSocket) -> None:
            """Stream live TradingEngineState every 1 second."""
            await ws.accept()
            logger.info("websocket_connected", client=str(ws.client))

            try:
                while True:
                    state_dict = self._state.to_dict()
                    await ws.send_json(state_dict)
                    await asyncio.sleep(1.0)
            except WebSocketDisconnect:
                logger.info("websocket_disconnected", client=str(ws.client))
            except Exception:
                logger.exception("websocket_error")

    def get_app(self) -> FastAPI:
        """Return the FastAPI app instance for uvicorn or testing."""
        return self._app

    async def start(self) -> None:
        """Start uvicorn server programmatically."""
        import uvicorn

        config = uvicorn.Config(
            self._app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        await self._server.serve()

    async def stop(self) -> None:
        """Trigger server shutdown if running."""
        if self._server is not None:
            self._server.should_exit = True


def _sanitize_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert non-JSON-serializable types in trade records.

    DuckDB/pandas may return Timestamp objects, numpy types, etc.
    Convert everything to JSON-safe primitives.
    """
    sanitized = []
    for trade in trades:
        clean: dict[str, Any] = {}
        for k, v in trade.items():
            if hasattr(v, "isoformat"):
                clean[k] = v.isoformat()
            elif hasattr(v, "item"):
                # numpy scalar -> Python scalar
                clean[k] = v.item()
            else:
                clean[k] = v
        sanitized.append(clean)
    return sanitized
