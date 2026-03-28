"""Unified Optuna search space (~20 parameters) and trial-to-settings mapper.

Defines parameters across 5 categories for NSGA-II multi-objective optimization:
1. FusionConfig: 11 continuous params (confidence thresholds, SL/TP ratios)
2. Signal weights: 3 continuous params (folded from DEAP per D-08)
3. RiskConfig: 2 continuous params (risk_pct, drawdown limit)
4. ChaosConfig: 5 continuous + 1 categorical (regime thresholds, direction mode)
5. TimingConfig: 3 continuous params (compression/expansion thresholds, urgency_floor)

Session windows are FIXED per D-07 -- not in search space.
"""

from __future__ import annotations

from typing import Any

import optuna

from fxsoqqabot.config.models import (
    BotSettings,
    ChaosConfig,
    FusionConfig,
    RiskConfig,
    TimingConfig,
)

# --- Category 1: FusionConfig (11 continuous) ---
FUSION_PARAMS: dict[str, tuple[float, float]] = {
    "aggressive_confidence_threshold": (0.20, 0.50),
    "selective_confidence_threshold": (0.30, 0.60),
    "conservative_confidence_threshold": (0.40, 0.75),
    "sl_atr_base_multiplier": (0.5, 3.0),
    "trending_rr_ratio": (1.5, 5.0),
    "ranging_rr_ratio": (1.0, 3.0),
    "high_chaos_size_reduction": (0.2, 0.8),
    "high_chaos_rr_ratio": (1.0, 4.0),
    "sl_chaos_widen_factor": (1.0, 2.5),
    "high_chaos_confidence_boost": (0.05, 0.3),
    "ema_alpha": (0.01, 0.3),
}

# --- Category 2: Signal weights (3 continuous, folded from DEAP per D-08) ---
WEIGHT_PARAMS: dict[str, tuple[float, float]] = {
    "weight_chaos_seed": (0.1, 0.9),
    "weight_flow_seed": (0.1, 0.9),
    "weight_timing_seed": (0.1, 0.9),
}

# --- Category 3: RiskConfig (2 continuous) ---
RISK_PARAMS: dict[str, tuple[float, float]] = {
    "aggressive_risk_pct": (0.05, 0.20),
    "daily_drawdown_pct": (0.03, 0.15),
}

# --- Category 4: ChaosConfig (5 continuous + 1 categorical) ---
CHAOS_FLOAT_PARAMS: dict[str, tuple[float, float]] = {
    "hurst_trending_threshold": (0.50, 0.75),
    "hurst_ranging_threshold": (0.30, 0.50),
    "lyapunov_chaos_threshold": (0.3, 0.8),
    "entropy_chaos_threshold": (0.5, 0.9),
    "bifurcation_threshold": (0.5, 0.9),
}
CHAOS_CATEGORICAL: dict[str, list[str]] = {
    "direction_mode": ["zero", "drift", "flow_follow"],
}

# --- Category 5: TimingConfig (3 continuous) ---
TIMING_PARAMS: dict[str, tuple[float, float]] = {
    "phase_transition_compression_threshold": (0.3, 0.8),
    "phase_transition_expansion_threshold": (1.5, 3.0),
    "urgency_floor": (0.0, 0.3),
}

# Combined float params for convenience
ALL_FLOAT_PARAMS: dict[str, tuple[float, float]] = {
    **FUSION_PARAMS,
    **WEIGHT_PARAMS,
    **RISK_PARAMS,
    **CHAOS_FLOAT_PARAMS,
    **TIMING_PARAMS,
}

# Backward compat: old code references this name
OPTUNA_SEARCH_SPACE = FUSION_PARAMS


def get_all_param_names() -> set[str]:
    """Return all parameter names in the search space."""
    names = set(ALL_FLOAT_PARAMS.keys())
    names.update(CHAOS_CATEGORICAL.keys())
    return names


def sample_trial(trial: optuna.Trial) -> dict[str, Any]:
    """Sample all ~25 parameters from an Optuna trial.

    Enforces threshold ordering: aggressive < selective < conservative.
    Handles categorical direction_mode via suggest_categorical (per D-06).

    Returns:
        Dict mapping parameter names to sampled values (floats and strings).
    """
    params: dict[str, Any] = {}

    # Confidence thresholds with ordering constraint
    aggressive = trial.suggest_float(
        "aggressive_confidence_threshold", 0.20, 0.50,
    )
    params["aggressive_confidence_threshold"] = aggressive

    selective = trial.suggest_float(
        "selective_confidence_threshold", max(0.30, aggressive + 0.01), 0.60,
    )
    params["selective_confidence_threshold"] = selective

    conservative = trial.suggest_float(
        "conservative_confidence_threshold", max(0.40, selective + 0.01), 0.75,
    )
    params["conservative_confidence_threshold"] = conservative

    # All other float params (independent, no ordering constraint)
    for name, (low, high) in ALL_FLOAT_PARAMS.items():
        if name in params:
            continue  # Already sampled above
        params[name] = trial.suggest_float(name, low, high)

    # Categorical params (per D-06)
    for name, choices in CHAOS_CATEGORICAL.items():
        params[name] = trial.suggest_categorical(name, choices)

    return params


def apply_params_to_settings(
    settings: BotSettings,
    params: dict[str, Any],
) -> BotSettings:
    """Apply parameter overrides to BotSettings across all config models.

    Checks each param key against FusionConfig, RiskConfig, ChaosConfig,
    and TimingConfig model_fields. Produces a NEW BotSettings without
    mutating the original.

    Args:
        settings: Base BotSettings to override.
        params: Dict of parameter name -> value overrides.

    Returns:
        New BotSettings with overridden parameters across all config models.
    """
    fusion_overrides: dict[str, Any] = {
        k: v for k, v in params.items() if k in FusionConfig.model_fields
    }
    risk_overrides: dict[str, Any] = {
        k: v for k, v in params.items() if k in RiskConfig.model_fields
    }
    chaos_overrides: dict[str, Any] = {
        k: v for k, v in params.items() if k in ChaosConfig.model_fields
    }
    timing_overrides: dict[str, Any] = {
        k: v for k, v in params.items() if k in TimingConfig.model_fields
    }

    new_settings = settings

    if fusion_overrides:
        new_fusion = settings.signals.fusion.model_copy(update=fusion_overrides)
        new_signals = new_settings.signals.model_copy(update={"fusion": new_fusion})
        new_settings = new_settings.model_copy(update={"signals": new_signals})

    if risk_overrides:
        new_risk = settings.risk.model_copy(update=risk_overrides)
        new_settings = new_settings.model_copy(update={"risk": new_risk})

    if chaos_overrides:
        new_chaos = new_settings.signals.chaos.model_copy(update=chaos_overrides)
        new_signals = new_settings.signals.model_copy(update={"chaos": new_chaos})
        new_settings = new_settings.model_copy(update={"signals": new_signals})

    if timing_overrides:
        new_timing = new_settings.signals.timing.model_copy(update=timing_overrides)
        new_signals = new_settings.signals.model_copy(update={"timing": new_timing})
        new_settings = new_settings.model_copy(update={"signals": new_signals})

    return new_settings
