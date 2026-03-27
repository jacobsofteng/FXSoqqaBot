"""Custom panel formatting functions for the TUI dashboard.

Pure functions that take TradingEngineState fields and return Rich markup
strings. Testable without Textual -- no widget imports required.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fxsoqqabot.signals.base import RegimeState


# ── Regime colors per D-02 / UI-SPEC traffic-light mapping ──────────────

_REGIME_COLORS: dict[RegimeState, str] = {
    RegimeState.TRENDING_UP: "green",
    RegimeState.TRENDING_DOWN: "green",
    RegimeState.RANGING: "yellow",
    RegimeState.HIGH_CHAOS: "red",
    RegimeState.PRE_BIFURCATION: "red",
}


def format_regime_panel(
    regime: RegimeState,
    confidence: float,
    *,
    is_connected: bool = True,
) -> str:
    """Format the regime panel with traffic-light color coding.

    Args:
        regime: Current market regime state.
        confidence: Regime confidence from 0.0 to 1.0.
        is_connected: Whether MT5 is connected.

    Returns:
        Rich markup string for the regime panel.
    """
    if not is_connected:
        return "[bold red]MT5 DISCONNECTED[/] -- Reconnecting..."

    color = _REGIME_COLORS.get(regime, "white")
    return f"[bold {color}]REGIME: {regime.value.upper()}[/] ({confidence:.0%})"


def format_signals_panel(
    confidences: dict[str, float],
    directions: dict[str, float],
) -> str:
    """Format per-module signal confidence with direction arrows.

    Args:
        confidences: Module name -> confidence (0.0 to 1.0).
        directions: Module name -> direction (-1.0 to +1.0).

    Returns:
        Rich markup string with one line per module.
    """
    lines: list[str] = []
    for name in sorted(confidences.keys()):
        conf = confidences.get(name, 0.0)
        direction = directions.get(name, 0.0)

        # Direction arrow
        if direction > 0:
            arrow = "^"
        elif direction < 0:
            arrow = "v"
        else:
            arrow = "-"

        # Color by confidence tier
        if conf >= 0.70:
            color = "green"
        elif conf >= 0.40:
            color = "yellow"
        else:
            color = "red"

        lines.append(f"[{color}]{name.title():8s}: {arrow} {conf:.0%}[/]")

    return "\n".join(lines) if lines else "[dim]No signals[/]"


def format_position_panel(position: dict | None) -> str:
    """Format the open position panel.

    Args:
        position: Position dict with keys action, lots, price, pnl, sl,
            or None if no position is open.

    Returns:
        Rich markup string for the position panel.
    """
    if position is None:
        return "No open position"

    action = position.get("action", "?").upper()
    lots = position.get("lots", 0.0)
    price = position.get("price", 0.0)
    pnl = position.get("pnl", 0.0)
    sl = position.get("sl", 0.0)

    pnl_color = "green" if pnl >= 0 else "red"
    pnl_str = f"[{pnl_color}]${pnl:+.2f}[/{pnl_color}]"

    return (
        f"{action} {lots:.2f} @ {price:.2f} "
        f"| P&L: {pnl_str} "
        f"| SL: {sl:.2f}"
    )


def format_risk_panel(
    breaker_status: dict[str, str],
    is_killed: bool,
) -> str:
    """Format the risk/circuit breaker status panel.

    Args:
        breaker_status: Dict with breaker names -> status strings.
        is_killed: Whether the kill switch is active.

    Returns:
        Rich markup string for the risk panel.
    """
    if is_killed:
        return "[bold red on white]KILLED[/]"

    # Check for any tripped breaker
    tripped = [
        name for name, status in breaker_status.items()
        if status.upper() == "TRIPPED"
    ]
    if tripped:
        reason = ", ".join(tripped)
        return f"[bold red]HALTED ({reason})[/]"

    dd = breaker_status.get("daily_drawdown", "0%")
    # Summarize breaker statuses (skip daily_drawdown -- it's a value, not a status)
    breaker_statuses = {
        k: v for k, v in breaker_status.items() if k != "daily_drawdown"
    }
    all_ok = all(
        s.upper() in ("OK", "ACTIVE", "NORMAL")
        for s in breaker_statuses.values()
    ) if breaker_statuses else True
    status_str = "[green]OK[/]" if all_ok else "ACTIVE"
    return f"Daily DD: {dd} | Breakers: {status_str}"


def format_order_flow(
    volume_delta: float,
    bid_pressure: float,
    ask_pressure: float,
) -> str:
    """Format order flow volume delta and pressure.

    Args:
        volume_delta: Net volume delta (positive = buy pressure).
        bid_pressure: Bid-side pressure ratio 0.0 to 1.0.
        ask_pressure: Ask-side pressure ratio 0.0 to 1.0.

    Returns:
        Rich markup string for order flow panel.
    """
    return (
        f"Delta: {volume_delta:+.0f} "
        f"| Bid: {bid_pressure:.0%} Ask: {ask_pressure:.0%}"
    )


def format_stats_panel(
    trade_count: int,
    win_rate: float,
    daily_pnl: float,
    equity: float,
) -> str:
    """Format the daily statistics panel.

    Args:
        trade_count: Number of trades today.
        win_rate: Win rate from 0.0 to 1.0.
        daily_pnl: Daily profit/loss in dollars.
        equity: Current account equity.

    Returns:
        Rich markup string for the stats panel.
    """
    pnl_color = "green" if daily_pnl >= 0 else "red"
    pnl_str = f"[{pnl_color}]${daily_pnl:+.2f}[/{pnl_color}]"

    return (
        f"Trades: {trade_count} | Win: {win_rate:.0%} "
        f"| P&L: {pnl_str} | Equity: ${equity:.2f}"
    )


def format_trade_row(trade: dict) -> list[str]:
    """Format a single trade as a DataTable row.

    Args:
        trade: Trade dict with keys timestamp, action, lots, entry, exit,
            pnl, regime.

    Returns:
        List of string values for DataTable columns:
        [time, action, lots, entry, exit, pnl, regime].
    """
    ts = trade.get("timestamp")
    if isinstance(ts, (int, float)):
        time_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M")
    elif isinstance(ts, str):
        time_str = ts[:5] if len(ts) >= 5 else ts
    elif isinstance(ts, datetime):
        time_str = ts.strftime("%H:%M")
    else:
        time_str = "--:--"

    pnl = trade.get("pnl", 0.0)
    pnl_str = f"${pnl:+.2f}"

    return [
        time_str,
        trade.get("action", "?").upper(),
        f"{trade.get('lots', 0.0):.2f}",
        f"{trade.get('entry', 0.0):.2f}",
        f"{trade.get('exit', 0.0):.2f}",
        pnl_str,
        trade.get("regime", "?"),
    ]


def is_mutation_event(trade: dict) -> bool:
    """Check if a trade dict represents a mutation event.

    Args:
        trade: Trade dict, possibly containing a "mutation" key.

    Returns:
        True if the trade has mutation=True.
    """
    return bool(trade.get("mutation", False))


def format_mutation_row(mutation: dict) -> str:
    """Format a mutation event row with magenta highlighting per D-03.

    Args:
        mutation: Dict with keys param, old, new, reason.

    Returns:
        Rich markup string with bold magenta highlighting.
    """
    param = mutation.get("param", "?")
    old = mutation.get("old", "?")
    new = mutation.get("new", "?")
    reason = mutation.get("reason", "?")
    return (
        f"[bold magenta][MUTATED] {param}: {old} -> {new} ({reason})[/]"
    )
