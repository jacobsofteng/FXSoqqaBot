"""Pareto front selection with trade count target proximity per D-03.

Selects the Pareto-optimal trial closest to the 10-20 trades/day target,
then maximizes profit factor within that band. PF >= 1.0 is a soft floor.
"""

from __future__ import annotations

import optuna


def select_from_pareto(
    trials: list[optuna.trial.FrozenTrial],
    target_min_tpd: float = 10.0,
    target_max_tpd: float = 20.0,
    min_pf: float = 1.0,
) -> optuna.trial.FrozenTrial:
    """Select Pareto-optimal trial closest to trade count target with PF floor.

    Per D-03: trade count priority -- select the Pareto-optimal config closest
    to 10-20 trades/day, then maximize profit factor within that band.
    Per D-04: PF >= 1.0 is a soft floor -- prefer trials meeting it, but fall
    back to best available if none qualify.

    Args:
        trials: Pareto front trials from study.best_trials.
                trials[i].values = (profit_factor, trades_per_day).
        target_min_tpd: Minimum target trades per day.
        target_max_tpd: Maximum target trades per day.
        min_pf: Minimum profit factor floor (soft constraint).

    Returns:
        Best trial by trade count proximity + PF.

    Raises:
        ValueError: If trials list is empty.
    """
    if not trials:
        raise ValueError("No Pareto front trials to select from")

    # Prefer trials meeting PF floor, but fall back to all if none qualify
    viable = [t for t in trials if t.values[0] >= min_pf]
    if not viable:
        viable = trials  # Soft floor: best available

    def _score(trial: optuna.trial.FrozenTrial) -> tuple[float, float]:
        """Score by (distance_to_target_band, -profit_factor).

        Lower is better. Trials within the target band score 0 distance
        and are then sorted by highest PF (negated for min sort).
        """
        tpd = trial.values[1]
        if target_min_tpd <= tpd <= target_max_tpd:
            return (0.0, -trial.values[0])
        dist = min(abs(tpd - target_min_tpd), abs(tpd - target_max_tpd))
        return (dist, -trial.values[0])

    return min(viable, key=_score)
