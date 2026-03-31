"""
Position Sizing -- v9.2 Auto-Scaling with Drawdown Protection

Tier-based lot sizing that scales with account balance.
Separate tiers for H1 ($6 SL) and M15 ($3 SL).
Drawdown protection halves lots when balance drops 30% from peak.
"""

import math


TIERS = {
    'H1': [
        (0,    0.01),   # $6 risk
        (150,  0.02),   # $12 risk = 8% at $150
        (300,  0.03),   # $18 risk = 6% at $300
        (500,  0.05),   # $30 risk = 6% at $500
        (800,  0.08),   # $48 risk = 6% at $800
        (1500, 0.15),   # $90 risk = 6% at $1500
        (3000, 0.25),   # $150 risk = 5% at $3000
        (5000, 0.40),   # $240 risk = 4.8% at $5000
    ],
    'M15': [
        (0,    0.01),   # $3 risk
        (100,  0.02),   # $6 risk = 6% at $100
        (200,  0.03),   # $9 risk = 4.5% at $200
        (400,  0.05),   # $15 risk = 3.75% at $400
        (700,  0.08),   # $24 risk = 3.4% at $700
        (1200, 0.12),   # $36 risk = 3% at $1200
        (2500, 0.20),   # $60 risk = 2.4% at $2500
        (4000, 0.35),   # $105 risk = 2.6% at $4000
    ],
}


def get_lot_size(balance: float, scale: str = 'H1') -> float:
    """
    Get lot size based on current balance and scale.

    Uses tier-based sizing — NOT risk-percentage.
    Each tier is calibrated for appropriate risk at that balance level.
    """
    tiers = TIERS.get(scale, TIERS['H1'])
    lot = tiers[0][1]  # minimum
    for min_bal, lot_size in tiers:
        if balance >= min_bal:
            lot = lot_size
    return lot


class DrawdownProtection:
    """
    Halves position size during drawdowns.

    Activates when balance drops 30% from peak.
    Deactivates when balance recovers to 90% of peak.
    """

    def __init__(self):
        self.peak = 0.0
        self.active = False
        self.activations = 0

    def update(self, balance: float):
        if balance > self.peak:
            self.peak = balance
            self.active = False

        if not self.active and balance < self.peak * 0.70:
            self.active = True
            self.activations += 1

        if self.active and balance > self.peak * 0.90:
            self.active = False

    def adjust(self, lots: float) -> float:
        if self.active:
            return max(0.01, round(lots / 2, 2))
        return lots
