"""FXSoqqaBot web dashboard -- FastAPI server with WebSocket live feed.

Serves a single-page dashboard accessible from any device on the local
network. Provides REST endpoints for trade history, equity data, regime
timeline, and module weights. WebSocket streams live state every second.
"""

from fxsoqqabot.dashboard.web.server import DashboardServer

__all__ = ["DashboardServer"]
