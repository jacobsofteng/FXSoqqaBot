"""Optuna search space and trial-to-settings conversion.

Defines continuous FusionConfig parameters that Optuna tunes in Phase A.
The 3 weight seeds (chaos/flow/timing) are excluded -- those are evolved by
DEAP in Phase B.

Search space tuned for SCALPING frequency (50-100 trades/day target):
- Low confidence thresholds so trades trigger often
- Tight SL/TP for fast turnover
- Multiple concurrent positions allowed
- max_concurrent_positions included in search space

Threshold ordering is enforced: aggressive < selective < conservative.
"""

from __future__ import annotations

from typing import Any

import optuna

from fxsoqqabot.config.models import BotSettings, FusionConfig

# ---------------------------------------------------------------------------
# Search space tuned for scalping frequency.
# Key changes from conservative defaults:
# - Confidence thresholds start at 0.10 (was 0.30) to generate more trades
# - SL multiplier down to 0.5 (was 1.0) for tighter stops = faster exits
# - RR ratios include sub-1.0 for quick scalp targets
# - max_concurrent_positions up to 5 (was fixed at 1)
# - high_chaos_confidence_boost lowered to not kill trade frequency in volatile markets
# ---------------------------------------------------------------------------
OPTUNA_SEARCH_SPACE: dict[str, tuple[float, float]] = {
    "aggressive_confidence_threshold": (0.10, 0.40),
    "selective_confidence_threshold": (0.15, 0.50),
    "conservative_confidence_threshold": (0.20, 0.60),
    "sl_atr_base_multiplier": (0.5, 2.5),
    "trending_rr_ratio": (0.8, 3.0),
    "ranging_rr_ratio": (0.5, 2.0),
    "high_chaos_size_reduction": (0.3, 0.8),
    "high_chaos_rr_ratio": (0.5, 2.5),
    "sl_chaos_widen_factor": (1.0, 2.0),
    "high_chaos_confidence_boost": (0.0, 0.15),
    "ema_alpha": (0.05, 0.3),
    "max_concurrent_positions": (1.0, 5.0),  # Sampled as float, cast to int
}


def sample_trial(trial: optuna.Trial) -> dict[str, float]:
    """Sample all parameters from an Optuna trial.

    Enforces threshold ordering: aggressive < selective < conservative.
    max_concurrent_positions sampled as int.

    Args:
        trial: Optuna Trial object.

    Returns:
        Dict mapping parameter names to sampled values.
    """
    params: dict[str, float] = {}

    # Confidence thresholds with ordering constraint
    aggressive = trial.suggest_float(
        "aggressive_confidence_threshold", 0.10, 0.40,
    )
    params["aggressive_confidence_threshold"] = aggressive

    selective = trial.suggest_float(
        "selective_confidence_threshold", max(0.15, aggressive + 0.02), 0.50,
    )
    params["selective_confidence_threshold"] = selective

    conservative = trial.suggest_float(
        "conservative_confidence_threshold", max(0.20, selective + 0.02), 0.60,
    )
    params["conservative_confidence_threshold"] = conservative

    # Max concurrent positions as integer
    max_pos = trial.suggest_int("max_concurrent_positions", 1, 5)
    params["max_concurrent_positions"] = float(max_pos)

    # Remaining parameters (independent, no ordering constraint)
    for name, (low, high) in OPTUNA_SEARCH_SPACE.items():
        if name in params:
            continue
        params[name] = trial.suggest_float(name, low, high)

    return params


def apply_params_to_settings(
    settings: BotSettings,
    params: dict[str, float],
) -> BotSettings:
    """Apply parameter overrides to BotSettings via Pydantic model_copy chain.

    Produces a NEW BotSettings without mutating the original. Only overrides
    fields that exist on FusionConfig. Handles int casting for
    max_concurrent_positions.

    Args:
        settings: Base BotSettings to override.
        params: Dict of parameter name -> value overrides.

    Returns:
        New BotSettings with overridden fusion parameters.
    """
    fusion_overrides: dict[str, Any] = {}
    for k, v in params.items():
        if k not in FusionConfig.model_fields:
            continue
        # Cast int fields
        if k == "max_concurrent_positions":
            fusion_overrides[k] = int(v)
        else:
            fusion_overrides[k] = v

    if not fusion_overrides:
        return settings

    new_fusion = settings.signals.fusion.model_copy(update=fusion_overrides)
    new_signals = settings.signals.model_copy(update={"fusion": new_fusion})
    return settings.model_copy(update={"signals": new_signals})
