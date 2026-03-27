"""Two-phase parameter optimization for FXSoqqaBot.

Phase A: Optuna TPE searches fusion/risk parameter space (confidence thresholds,
ATR multipliers, risk-reward ratios, chaos adjustments) using walk-forward
aggregate profit factor as the objective.

Phase B: DEAP GA evolves signal weight seeds (chaos/flow/timing) with the
best Optuna params frozen as baseline. This separates co-dependent weight
optimization from independent continuous parameter search.

Final validation: best merged params pass walk-forward + OOS + Monte Carlo
gates before writing config/optimized.toml.
"""
