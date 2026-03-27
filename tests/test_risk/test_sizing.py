"""Tests for the position sizing engine with three-phase capital model.

Tests verify per D-03 / D-04 / RISK-02:
- Lot size calculation from equity, risk percentage, and SL distance
- Lot size rounded down to volume_step (0.01) and clamped to volume_min/volume_max
- Trade skipped when minimum lot (0.01) risk exceeds phase limit per D-04
- Three capital phases return correct risk percentages: 10%, 5%, 2%
- Spread consideration adjusts effective SL distance
"""

from __future__ import annotations

import pytest

from fxsoqqabot.config.models import RiskConfig
from fxsoqqabot.risk.sizing import PositionSizer, SizingResult, SymbolSpecs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def risk_config() -> RiskConfig:
    """Default RiskConfig with standard three-phase values."""
    return RiskConfig()


@pytest.fixture
def sizer(risk_config: RiskConfig) -> PositionSizer:
    """PositionSizer with default config."""
    return PositionSizer(risk_config)


@pytest.fixture
def default_specs() -> SymbolSpecs:
    """Default XAUUSD symbol specs."""
    return SymbolSpecs()


# ---------------------------------------------------------------------------
# Test: Capital phase detection per D-03
# ---------------------------------------------------------------------------


class TestCapitalPhase:
    """Tests for get_capital_phase method."""

    def test_aggressive_phase_at_20(self, sizer: PositionSizer) -> None:
        """$20 equity is in the aggressive phase (<$100)."""
        assert sizer.get_capital_phase(20.0) == "aggressive"

    def test_aggressive_phase_at_99(self, sizer: PositionSizer) -> None:
        """$99 equity is still aggressive (< $100 boundary)."""
        assert sizer.get_capital_phase(99.0) == "aggressive"

    def test_selective_phase_at_100(self, sizer: PositionSizer) -> None:
        """$100 equity crosses into selective phase."""
        assert sizer.get_capital_phase(100.0) == "selective"

    def test_selective_phase_at_150(self, sizer: PositionSizer) -> None:
        """$150 equity is in selective phase."""
        assert sizer.get_capital_phase(150.0) == "selective"

    def test_selective_phase_at_299(self, sizer: PositionSizer) -> None:
        """$299 equity is still selective (< $300 boundary)."""
        assert sizer.get_capital_phase(299.0) == "selective"

    def test_conservative_phase_at_300(self, sizer: PositionSizer) -> None:
        """$300 equity crosses into conservative phase."""
        assert sizer.get_capital_phase(300.0) == "conservative"

    def test_conservative_phase_at_500(self, sizer: PositionSizer) -> None:
        """$500 equity is in conservative phase."""
        assert sizer.get_capital_phase(500.0) == "conservative"


# ---------------------------------------------------------------------------
# Test: Lot size calculation (core formula)
# ---------------------------------------------------------------------------


class TestLotSizeCalculation:
    """Tests for calculate_lot_size with various equity/SL combinations."""

    def test_20_equity_2_sl_returns_min_lot(self, sizer: PositionSizer) -> None:
        """$20 equity, $2 SL -> risk=$2, lot=0.01 (min), actual risk=$2=10%, can trade.

        Calculation: risk_amount = $20 * 0.10 = $2.00
                     lot = $2.00 / ($2.00 * 100) = 0.01 -> exactly min lot
                     actual risk = 0.01 * $2.00 * 100 = $2.00 = 10%, equals limit
        """
        result = sizer.calculate_lot_size(equity=20.0, sl_distance=2.0)
        assert isinstance(result, SizingResult)
        assert result.lot_size == 0.01
        assert result.can_trade is True
        assert result.capital_phase == "aggressive"
        assert result.skip_reason is None

    def test_20_equity_3_sl_skips_trade(self, sizer: PositionSizer) -> None:
        """$20 equity, $3 SL -> min lot 0.01 risks $3 = 15% > 10% limit, skip per D-04.

        Calculation: risk_amount = $20 * 0.10 = $2.00
                     lot = $2.00 / ($3.00 * 100) = 0.0067 -> rounds to 0.00 -> clamps to 0.01
                     actual risk = 0.01 * $3.00 * 100 = $3.00 = 15% > 10%
        """
        result = sizer.calculate_lot_size(equity=20.0, sl_distance=3.0)
        assert result.can_trade is False
        assert result.skip_reason is not None
        assert "exceeds" in result.skip_reason.lower()

    def test_20_equity_1_5_sl_returns_min_lot(self, sizer: PositionSizer) -> None:
        """$20 equity, $1.5 SL -> lot=0.0133 rounds to 0.01, risk=7.5% < 10%, OK.

        Calculation: risk_amount = $20 * 0.10 = $2.00
                     lot = $2.00 / ($1.50 * 100) = 0.01333 -> rounds to 0.01
                     actual risk = 0.01 * $1.50 * 100 = $1.50 = 7.5%
        """
        result = sizer.calculate_lot_size(equity=20.0, sl_distance=1.5)
        assert result.lot_size == 0.01
        assert result.can_trade is True
        assert result.risk_pct == pytest.approx(0.075, abs=0.001)

    def test_200_equity_3_sl_selective_phase(self, sizer: PositionSizer) -> None:
        """$200 equity (selective), $3 SL -> lot=0.03.

        Calculation: risk_amount = $200 * 0.05 = $10.00
                     lot = $10.00 / ($3.00 * 100) = 0.0333 -> rounds to 0.03
        """
        result = sizer.calculate_lot_size(equity=200.0, sl_distance=3.0)
        assert result.lot_size == 0.03
        assert result.can_trade is True
        assert result.capital_phase == "selective"

    def test_500_equity_3_sl_conservative_phase(self, sizer: PositionSizer) -> None:
        """$500 equity (conservative), $3 SL -> lot=0.03.

        Calculation: risk_amount = $500 * 0.02 = $10.00
                     lot = $10.00 / ($3.00 * 100) = 0.0333 -> rounds to 0.03
        """
        result = sizer.calculate_lot_size(equity=500.0, sl_distance=3.0)
        assert result.lot_size == 0.03
        assert result.can_trade is True
        assert result.capital_phase == "conservative"


# ---------------------------------------------------------------------------
# Test: Risk budget validation per D-04
# ---------------------------------------------------------------------------


class TestRiskBudgetValidation:
    """Tests for trade skip logic when min lot exceeds risk limit."""

    def test_skip_when_min_lot_exceeds_risk_budget(
        self, sizer: PositionSizer
    ) -> None:
        """When even minimum lot (0.01) risk exceeds phase limit, skip trade."""
        # $10 equity, $2 SL: min lot risk = $2 = 20% > 10%
        result = sizer.calculate_lot_size(equity=10.0, sl_distance=2.0)
        assert result.can_trade is False
        assert result.skip_reason is not None

    def test_negative_sl_not_allowed(self, sizer: PositionSizer) -> None:
        """SL distance must be positive."""
        result = sizer.calculate_lot_size(equity=100.0, sl_distance=-1.0)
        assert result.can_trade is False
        assert "positive" in result.skip_reason.lower()

    def test_zero_sl_not_allowed(self, sizer: PositionSizer) -> None:
        """SL distance of zero is invalid."""
        result = sizer.calculate_lot_size(equity=100.0, sl_distance=0.0)
        assert result.can_trade is False


# ---------------------------------------------------------------------------
# Test: Volume constraints (broker limits)
# ---------------------------------------------------------------------------


class TestVolumeConstraints:
    """Tests for volume_min, volume_max, and volume_step clamping."""

    def test_lot_rounded_down_to_volume_step(self, sizer: PositionSizer) -> None:
        """Lot size rounds DOWN to nearest volume_step, not up."""
        # $1000 equity conservative, $1 SL: lot = $20 / ($1*100) = 0.20
        # With custom step of 0.05: 0.20 -> 0.20 (exact)
        specs = SymbolSpecs(volume_step=0.05)
        result = sizer.calculate_lot_size(equity=1000.0, sl_distance=1.0, specs=specs)
        # risk = $20, lot = 0.20, step = 0.05, 0.20 is already on step
        assert result.lot_size == 0.20

    def test_lot_clamped_to_volume_max(self, sizer: PositionSizer) -> None:
        """Very large equity should have lot capped at volume_max."""
        specs = SymbolSpecs(volume_max=0.05)
        # $5000 equity, $1 SL: lot = $100 / 100 = 1.0, capped to 0.05
        result = sizer.calculate_lot_size(equity=5000.0, sl_distance=1.0, specs=specs)
        assert result.lot_size == 0.05

    def test_lot_at_least_volume_min(self, sizer: PositionSizer) -> None:
        """Calculated lot always at least volume_min (after risk check)."""
        # Small calculation should clamp up to 0.01
        result = sizer.calculate_lot_size(equity=20.0, sl_distance=2.0)
        assert result.lot_size >= 0.01


# ---------------------------------------------------------------------------
# Test: Spread consideration
# ---------------------------------------------------------------------------


class TestSpreadConsideration:
    """Tests for spread-adjusted SL distance."""

    def test_spread_increases_effective_sl(self, sizer: PositionSizer) -> None:
        """Adding spread to SL distance reduces effective lot size.

        With spread=0.50 and SL=2.0, effective SL = 2.5
        $20 equity: risk=$2, lot=$2/(2.5*100) = 0.008 -> 0.00 -> clamp 0.01
        actual risk = 0.01 * 2.5 * 100 = $2.50 = 12.5% > 10% -> skip
        """
        result = sizer.calculate_lot_size(
            equity=20.0, sl_distance=2.5
        )
        # SL=2.5 with $20: risk=$2, lot=0.008 -> 0.01 min, actual=2.5*100*0.01=$2.5=12.5%>10%
        assert result.can_trade is False


# ---------------------------------------------------------------------------
# Test: SizingResult dataclass
# ---------------------------------------------------------------------------


class TestSizingResult:
    """Tests for the SizingResult data structure."""

    def test_sizing_result_is_frozen(self) -> None:
        """SizingResult should be immutable (frozen dataclass)."""
        result = SizingResult(
            lot_size=0.01,
            risk_amount=2.0,
            risk_pct=0.10,
            capital_phase="aggressive",
            sl_distance=2.0,
            can_trade=True,
            skip_reason=None,
        )
        with pytest.raises(AttributeError):
            result.lot_size = 0.02  # type: ignore[misc]

    def test_sizing_result_fields(self) -> None:
        """SizingResult exposes all required fields."""
        result = SizingResult(
            lot_size=0.03,
            risk_amount=9.0,
            risk_pct=0.045,
            capital_phase="selective",
            sl_distance=3.0,
            can_trade=True,
            skip_reason=None,
        )
        assert result.lot_size == 0.03
        assert result.risk_amount == 9.0
        assert result.risk_pct == 0.045
        assert result.capital_phase == "selective"
        assert result.sl_distance == 3.0
        assert result.can_trade is True
        assert result.skip_reason is None
