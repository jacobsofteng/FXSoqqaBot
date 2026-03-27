"""Order flow and institutional footprint detection signal module.

Exports OrderFlowModule as the primary interface for order flow
analysis implementing the SignalModule Protocol.
"""

from fxsoqqabot.signals.flow.module import OrderFlowModule

__all__ = ["OrderFlowModule"]
