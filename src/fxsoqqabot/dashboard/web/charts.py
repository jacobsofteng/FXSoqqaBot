"""Plotly chart generation helpers for the web dashboard.

Generates JSON chart specifications for equity curves with drawdown
overlay, regime timelines, and module performance line charts. All
functions return Plotly JSON strings for client-side rendering.
"""

from __future__ import annotations

import plotly.graph_objects as go


# Chart color constants per UI-SPEC
_BG_COLOR = "#0f1117"
_PLOT_BG_COLOR = "#1a1d27"
_FONT_COLOR = "#e1e4eb"
_POSITIVE_COLOR = "#22c55e"
_NEGATIVE_COLOR = "#ef4444"
_WARNING_COLOR = "#eab308"
_ACCENT_COLOR = "#3b82f6"

# Regime -> color mapping
_REGIME_COLORS: dict[str, str] = {
    "trending_up": _POSITIVE_COLOR,
    "trending_down": _POSITIVE_COLOR,
    "ranging": _WARNING_COLOR,
    "high_chaos": _NEGATIVE_COLOR,
    "pre_bifurcation": _NEGATIVE_COLOR,
}


def _base_layout(**overrides: object) -> dict:
    """Return base Plotly layout matching UI-SPEC dark theme."""
    layout = {
        "paper_bgcolor": _BG_COLOR,
        "plot_bgcolor": _PLOT_BG_COLOR,
        "font": {"color": _FONT_COLOR},
        "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
    }
    layout.update(overrides)
    return layout


def generate_equity_chart(equity_data: list[dict]) -> str:
    """Generate Plotly JSON for equity curve with drawdown overlay.

    Args:
        equity_data: List of {"timestamp": str, "equity": float, "drawdown": float}.

    Returns:
        Plotly figure as JSON string for client-side rendering.
    """
    timestamps = [d.get("timestamp", str(i)) for i, d in enumerate(equity_data)]
    equities = [d.get("equity", 0.0) for d in equity_data]
    drawdowns = [d.get("drawdown", 0.0) for d in equity_data]

    fig = go.Figure()

    # Equity line
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=equities,
        mode="lines",
        name="Equity",
        line={"color": _POSITIVE_COLOR, "width": 2},
    ))

    # Drawdown area overlay
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=drawdowns,
        mode="lines",
        name="Drawdown",
        fill="tozeroy",
        line={"color": _NEGATIVE_COLOR, "width": 1},
        fillcolor="rgba(239, 68, 68, 0.3)",
        yaxis="y2",
    ))

    fig.update_layout(
        **_base_layout(),
        title="Equity Curve",
        yaxis={"title": "Equity ($)", "gridcolor": "#252836"},
        yaxis2={
            "title": "Drawdown (%)",
            "overlaying": "y",
            "side": "right",
            "gridcolor": "#252836",
        },
        legend={"x": 0, "y": 1.1, "orientation": "h"},
    )

    return fig.to_json()


def generate_regime_timeline(regime_data: list[dict]) -> str:
    """Generate Plotly JSON for horizontal regime timeline bar chart.

    Args:
        regime_data: List of {"timestamp": str, "regime": str}.

    Returns:
        Plotly figure as JSON string.
    """
    fig = go.Figure()

    if regime_data:
        timestamps = [d.get("timestamp", "") for d in regime_data]
        regimes = [d.get("regime", "unknown") for d in regime_data]
        colors = [_REGIME_COLORS.get(r, "#8b8fa3") for r in regimes]

        fig.add_trace(go.Bar(
            x=timestamps,
            y=[1] * len(timestamps),
            marker_color=colors,
            text=regimes,
            textposition="inside",
            hovertemplate="%{x}<br>%{text}<extra></extra>",
            showlegend=False,
        ))

    fig.update_layout(
        **_base_layout(),
        title="Regime Timeline",
        yaxis={"visible": False},
        xaxis={"title": "Time", "gridcolor": "#252836"},
        bargap=0,
    )

    return fig.to_json()


def generate_module_performance(weight_data: list[dict]) -> str:
    """Generate Plotly JSON for module weight performance over time.

    Args:
        weight_data: List of {"timestamp": str, "chaos": float,
                     "flow": float, "timing": float}.

    Returns:
        Plotly figure as JSON string.
    """
    fig = go.Figure()

    if weight_data:
        timestamps = [d.get("timestamp", str(i)) for i, d in enumerate(weight_data)]

        for module_name, color in [
            ("chaos", _NEGATIVE_COLOR),
            ("flow", _ACCENT_COLOR),
            ("timing", _POSITIVE_COLOR),
        ]:
            values = [d.get(module_name, 0.0) for d in weight_data]
            fig.add_trace(go.Scatter(
                x=timestamps,
                y=values,
                mode="lines",
                name=module_name.capitalize(),
                line={"color": color, "width": 2},
            ))

    fig.update_layout(
        **_base_layout(),
        title="Module Performance",
        yaxis={"title": "Weight", "gridcolor": "#252836"},
        xaxis={"title": "Time", "gridcolor": "#252836"},
        legend={"x": 0, "y": 1.1, "orientation": "h"},
    )

    return fig.to_json()
