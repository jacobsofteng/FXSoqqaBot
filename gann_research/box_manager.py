"""
Box Manager -- v9.2 Parallel Box Tracking

Replaces the single-state machine with multi-box management.
Supports both single-scale (H1 only) and multi-scale (H1 + M15).

Rules:
  1. Maximum 3 active boxes per scale
  2. Maximum 2 open trades simultaneously (single-scale) or 3 (multi-scale)
  3. All boxes must agree on D1 direction
  4. New box must be >= 1 vibration quantum away from existing box centers
  5. New box cannot start within Green Zone time window of existing box
  6. When a trade opens from a box, that box -> DONE
  7. Expired boxes are removed silently
"""

from .scale_constants import get_scale


class ActiveBox:
    """Single active box with its own lifecycle."""

    def __init__(self, convergence_bar: int, convergence_price: float,
                 convergence_score: int, scale: str = 'H1'):
        self.state = 'QUANT_FORMING'  # QUANT_FORMING -> BOX_ACTIVE -> DONE
        self.convergence_bar = convergence_bar
        self.convergence_price = convergence_price
        self.convergence_score = convergence_score
        self.scale = scale
        self.quant = None
        self.box = None

        sc = get_scale(scale)
        self._quant_timeout = sc['quant_window']
        self._vibration_quantum = sc['vibration_quantum']

    def is_expired(self, current_bar: int) -> bool:
        if self.state == 'QUANT_FORMING':
            return (current_bar - self.convergence_bar) > self._quant_timeout
        if self.state == 'BOX_ACTIVE' and self.box:
            return current_bar > self.box['box']['end']
        return self.state == 'DONE'

    def price_zone_center(self) -> float:
        if self.box:
            return (self.box['box']['bottom'] + self.box['box']['top']) / 2
        return self.convergence_price

    def green_zone_range(self) -> tuple[int, int] | None:
        """Return (green_start, green_end) bar indices, or None."""
        if self.box and 'zones' in self.box:
            return self.box['zones']['green']
        return None


class BoxManager:
    """Manages parallel boxes for a single scale (H1)."""

    def __init__(self, max_parallel: int = 3, max_open_trades: int = 2):
        self.active_boxes: list[ActiveBox] = []
        self.max_parallel = max_parallel
        self.max_open = max_open_trades
        self.open_trades: list[dict] = []

    def can_add_box(self, price: float, bar: int,
                    vibration_quantum: float) -> bool:
        """Check if a new box can be added (spacing + capacity rules)."""
        if len(self.active_boxes) >= self.max_parallel:
            return False

        for b in self.active_boxes:
            # Price spacing: at least 1 vibration quantum apart
            if abs(price - b.price_zone_center()) < vibration_quantum:
                return False
            # Time spacing: not inside existing Green Zone
            gz = b.green_zone_range()
            if gz and gz[0] <= bar <= gz[1]:
                return False

        return True

    def cleanup(self, current_bar: int):
        """Remove expired and DONE boxes."""
        self.active_boxes = [
            b for b in self.active_boxes
            if not b.is_expired(current_bar) and b.state != 'DONE'
        ]


class MultiScaleBoxManager:
    """Manages parallel boxes across H1 and M15 scales."""

    def __init__(self):
        self.h1_boxes: list[ActiveBox] = []
        self.m15_boxes: list[ActiveBox] = []
        self.open_trades: list[dict] = []
        self.max_total_open = 3   # 3 trades max across both scales
        self.max_h1_boxes = 3
        self.max_m15_boxes = 3

    def total_open(self) -> int:
        return len(self.open_trades)

    def can_add_box(self, price: float, bar: int,
                    scale: str) -> bool:
        """Check if a new box can be added at given scale."""
        sc = get_scale(scale)
        vq = sc['vibration_quantum']

        boxes = self.h1_boxes if scale == 'H1' else self.m15_boxes
        max_boxes = self.max_h1_boxes if scale == 'H1' else self.max_m15_boxes

        if len(boxes) >= max_boxes:
            return False

        for b in boxes:
            if abs(price - b.price_zone_center()) < vq:
                return False
            gz = b.green_zone_range()
            if gz and gz[0] <= bar <= gz[1]:
                return False

        return True

    def cleanup(self, current_bar: int):
        """Remove expired and DONE boxes from both scales."""
        self.h1_boxes = [
            b for b in self.h1_boxes
            if not b.is_expired(current_bar) and b.state != 'DONE'
        ]
        self.m15_boxes = [
            b for b in self.m15_boxes
            if not b.is_expired(current_bar) and b.state != 'DONE'
        ]
