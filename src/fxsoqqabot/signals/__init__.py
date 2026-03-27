"""Signal pipeline package for FXSoqqaBot.

Exports the base types used by all signal modules:
  - SignalModule: Protocol defining the contract for signal modules.
  - SignalOutput: Frozen dataclass carrying signal data.
  - RegimeState: Enum for market regime classification.
"""

from fxsoqqabot.signals.base import RegimeState, SignalModule, SignalOutput

__all__ = ["RegimeState", "SignalModule", "SignalOutput"]
