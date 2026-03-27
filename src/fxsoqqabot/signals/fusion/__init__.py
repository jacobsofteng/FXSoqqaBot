"""Decision fusion layer combining all signal module outputs.

Exports:
    FusionCore: Confidence-weighted signal combination per D-01.
    FusionResult: Frozen dataclass result of signal fusion.
    AdaptiveWeightTracker: EMA accuracy-based weight tracking per D-02.
    PhaseBehavior: Phase-aware behavior with smooth transitions per D-04/FUSE-04.
    TradeManager: Trade execution with regime-aware SL/TP per FUSE-05.
    TradeDecision: Frozen dataclass result of trade evaluation.
"""

from fxsoqqabot.signals.fusion.core import FusionCore, FusionResult
from fxsoqqabot.signals.fusion.phase_behavior import PhaseBehavior
from fxsoqqabot.signals.fusion.trade_manager import TradeDecision, TradeManager
from fxsoqqabot.signals.fusion.weights import AdaptiveWeightTracker

__all__ = [
    "AdaptiveWeightTracker",
    "FusionCore",
    "FusionResult",
    "PhaseBehavior",
    "TradeDecision",
    "TradeManager",
]
