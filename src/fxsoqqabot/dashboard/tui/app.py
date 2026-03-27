"""FXSoqqaBot TUI application.

Rich terminal dashboard using Textual 8.1.1 for real-time monitoring of
the trading engine. Three-column layout per UI-SPEC D-01 with auto-refresh
every 1 second (D-05). Reads from TradingEngineState snapshot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import structlog
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Footer, Header, Sparkline, Static

from fxsoqqabot.core.state_snapshot import TradingEngineState
from fxsoqqabot.dashboard.tui.widgets import (
    format_mutation_row,
    format_order_flow,
    format_position_panel,
    format_regime_panel,
    format_risk_panel,
    format_signals_panel,
    format_stats_panel,
    format_trade_row,
    is_mutation_event,
)

logger = structlog.get_logger().bind(component="tui")


class FXSoqqaBotTUI(App):
    """Real-time terminal dashboard for FXSoqqaBot.

    Displays regime state, signal confidences, open positions, risk status,
    recent trades (with mutation highlights), order flow, daily stats,
    equity sparkline, and a kill switch button in a three-column layout.

    Args:
        state: Shared TradingEngineState snapshot (engine writes, TUI reads).
        kill_callback: Optional callable invoked when kill switch is activated.
        pause_callback: Optional callable invoked when pause is toggled.
    """

    TITLE = "FXSoqqaBot - XAUUSD Scalper"
    CSS_PATH = Path(__file__).parent / "styles.tcss"

    BINDINGS = [
        Binding("q", "quit_app", "Quit"),
        Binding("k", "kill_all", "Kill"),
        Binding("p", "toggle_pause", "Pause"),
    ]

    def __init__(
        self,
        state: TradingEngineState,
        kill_callback: Callable[[], None] | None = None,
        pause_callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._state = state
        self._kill_callback = kill_callback
        self._pause_callback = pause_callback

    def compose(self) -> ComposeResult:
        """Build the three-column layout per UI-SPEC D-01."""
        yield Header()
        with Horizontal():
            with Vertical(id="left-panel"):
                yield Static("", id="regime-panel", classes="panel")
                yield Static("", id="signals-panel", classes="panel")
                yield Static("", id="order-flow-panel", classes="panel")
            with Vertical(id="center-panel"):
                yield Static("", id="position-panel", classes="panel")
                yield Static("", id="risk-panel", classes="panel")
                yield DataTable(id="trades-table", classes="panel")
            with Vertical(id="right-panel"):
                yield Static("", id="stats-panel", classes="panel")
                yield Sparkline([], id="equity-spark", classes="panel")
                yield Button(
                    "KILL ALL POSITIONS", id="kill-btn", variant="error",
                )
        yield Footer()

    def on_mount(self) -> None:
        """Initialize DataTable columns and start 1-second refresh timer."""
        table = self.query_one("#trades-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Time", "Action", "Lots", "Entry", "Exit", "P&L", "Regime")

        # Start 1-second auto-refresh per D-05
        self.set_interval(1.0, self._refresh_all)

        # Initial refresh
        self._refresh_all()

    def _refresh_all(self) -> None:
        """Refresh all panels from the shared TradingEngineState."""
        state = self._state

        # ── Left column ──
        self.query_one("#regime-panel", Static).update(
            format_regime_panel(
                state.regime,
                state.regime_confidence,
                is_connected=state.is_connected,
            ),
        )
        self.query_one("#signals-panel", Static).update(
            format_signals_panel(
                state.signal_confidences,
                state.signal_directions,
            ),
        )
        self.query_one("#order-flow-panel", Static).update(
            format_order_flow(
                state.volume_delta,
                state.bid_pressure,
                state.ask_pressure,
            ),
        )

        # ── Center column ──
        self.query_one("#position-panel", Static).update(
            format_position_panel(state.open_position),
        )
        self.query_one("#risk-panel", Static).update(
            format_risk_panel(state.breaker_status, state.is_killed),
        )

        # Trades table: clear and repopulate with last 20 trades
        table = self.query_one("#trades-table", DataTable)
        table.clear()

        for trade in state.recent_trades[-20:]:
            if is_mutation_event(trade):
                # Mutation events get highlighted but still show as trade rows
                row = format_trade_row(trade)
                table.add_row(*row)
            else:
                row = format_trade_row(trade)
                table.add_row(*row)

        # Render mutation events inline below trades
        for mutation in state.recent_mutations[-5:]:
            mutation_text = format_mutation_row(mutation)
            table.add_row(mutation_text, "", "", "", "", "", "")

        # ── Right column ──
        self.query_one("#stats-panel", Static).update(
            format_stats_panel(
                state.daily_trade_count,
                state.daily_win_rate,
                state.daily_pnl,
                state.equity,
            ),
        )

        # Update equity sparkline with last 50 data points
        sparkline = self.query_one("#equity-spark", Sparkline)
        sparkline.data = state.equity_history[-50:]

    def action_quit_app(self) -> None:
        """Quit the TUI only -- trading engine continues running."""
        logger.info("TUI exiting, engine continues")
        self.exit()

    def action_kill_all(self) -> None:
        """Activate the kill switch via callback."""
        if self._kill_callback is not None:
            self._kill_callback()
        logger.warning("Kill switch activated from TUI")

    def action_toggle_pause(self) -> None:
        """Toggle trading pause via callback."""
        if self._pause_callback is not None:
            self._pause_callback()

        if self._state.is_paused:
            self.sub_title = ""
            logger.info("Trading resumed from TUI")
        else:
            self.sub_title = "[PAUSED]"
            logger.info("Trading paused from TUI")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle kill button press."""
        if event.button.id == "kill-btn":
            self.action_kill_all()
