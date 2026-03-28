"""Optuna search space and trial-to-settings conversion.

Defines the 11 continuous FusionConfig parameters that Optuna tunes in Phase A.
The 3 weight seeds (chaos/flow/timing) are excluded -- those are evolved by
DEAP in Phase B.

Threshold ordering is enforced: aggressive < selective < conservative.
"""

from __future__ import annotations

from typing import Any

import optuna

from fxsoqqabot.config.models import BotSettings, FusionConfig

# ---------------------------------------------------------------------------
# Search space: 11 continuous FusionConfig parameters for Optuna TPE.
# Bounds sourced from PARAM_BOUNDS in learning/evolution.py plus additional
# fusion params not in the GA space.
# ---------------------------------------------------------------------------
OPTUNA_SEARCH_SPACE: dict[str, tuple[float, float]] = {
    "aggressive_confidence_threshold": (0.3, 0.7),
    "selective_confidence_threshold": (0.4, 0.8),
    "conservative_confidence_threshold": (0.5, 0.9),
    "sl_atr_base_multiplier": (1.0, 4.0),
    "trending_rr_ratio": (1.5, 5.0),
    "ranging_rr_ratio": (1.0, 3.0),
    "high_chaos_size_reduction": (0.2, 0.8),
    "high_chaos_rr_ratio": (1.0, 4.0),
    "sl_chaos_widen_factor": (1.0, 2.5),
    "high_chaos_confidence_boost": (0.05, 0.3),
    "ema_alpha": (0.01, 0.3),
}


def sample_trial(trial: optuna.Trial) -> dict[str, float]:
    """Sample all 11 parameters from an Optuna trial.

    Enforces threshold ordering: aggressive < selective < conservative
    by using the previous threshold as the lower bound for the next.
    If Optuna clamps cause equal values, that is acceptable.

    Args:
        trial: Optuna Trial object.

    Returns:
        Dict mapping parameter names to sampled values.
    """
    params: dict[str, float] = {}

    # Confidence thresholds with ordering constraint
    aggressive = trial.suggest_float(
        "aggressive_confidence_threshold", 0.3, 0.7,
    )
    params["aggressive_confidence_threshold"] = aggressive

    selective = trial.suggest_float(
        "selective_confidence_threshold", max(0.4, aggressive), 0.8,
    )
    params["selective_confidence_threshold"] = selective

    conservative = trial.suggest_float(
        "conservative_confidence_threshold", max(0.5, selective), 0.9,
    )
    params["conservative_confidence_threshold"] = conservative

    # Remaining parameters (independent, no ordering constraint)
    for name, (low, high) in OPTUNA_SEARCH_SPACE.items():
        if name in params:
            continue  # Already sampled above
        params[name] = trial.suggest_float(name, low, high)

    return params


def apply_params_to_settings(
    settings: BotSettings,
    params: dict[str, float],
) -> BotSettings:
    """Apply parameter overrides to BotSettings via Pydantic model_copy chain.

    Produces a NEW BotSettings without mutating the original. Only overrides
    fields that exist on FusionConfig.

    Args:
        settings: Base BotSettings to override.
        params: Dict of parameter name -> value overrides.

    Returns:
        New BotSettings with overridden fusion parameters.
    """
    fusion_overrides: dict[str, Any] = {
        k: v for k, v in params.items() if k in FusionConfig.model_fields
    }

    if not fusion_overrides:
        return settings

    new_fusion = settings.signals.fusion.model_copy(update=fusion_overrides)
    new_signals = settings.signals.model_copy(update={"fusion": new_fusion})
    return settings.model_copy(update={"signals": new_signals})
