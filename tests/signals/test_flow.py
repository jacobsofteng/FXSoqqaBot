"""Tests for order flow and institutional detection signal module.

Covers volume delta (FLOW-01), aggression imbalance (FLOW-02), HFT signatures
(FLOW-05), institutional footprints (FLOW-04), DOM analysis (FLOW-03), DOM
quality checker (D-15), and OrderFlowModule integration (FLOW-06/D-13).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import numpy as np
import pytest

from fxsoqqabot.config.models import FlowConfig
from fxsoqqabot.core.events import DOMEntry, DOMSnapshot


# ─── Volume Delta Tests (FLOW-01) ──────────────────────────────────


class TestVolumeDelta:
    """Tests for compute_volume_delta function."""

    def test_all_ticks_at_ask_positive_delta(self) -> None:
        """All ticks at ask price: cum_delta > 0, buy_vol > 0, sell_vol == 0."""
        from fxsoqqabot.signals.flow.volume_delta import compute_volume_delta

        bid = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
        ask = np.array([101.0, 101.0, 101.0, 101.0, 101.0])
        last = np.array([101.0, 101.0, 101.0, 101.0, 101.0])  # at ask
        volume_real = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

        cum_delta, buy_vol, sell_vol, ambiguous_pct = compute_volume_delta(
            bid, ask, last, volume_real, window=10
        )
        assert cum_delta > 0
        assert buy_vol > 0
        assert sell_vol == 0.0
        assert ambiguous_pct == 0.0

    def test_all_ticks_at_bid_negative_delta(self) -> None:
        """All ticks at bid price: cum_delta < 0, sell_vol > 0, buy_vol == 0."""
        from fxsoqqabot.signals.flow.volume_delta import compute_volume_delta

        bid = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
        ask = np.array([101.0, 101.0, 101.0, 101.0, 101.0])
        last = np.array([100.0, 100.0, 100.0, 100.0, 100.0])  # at bid
        volume_real = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

        cum_delta, buy_vol, sell_vol, ambiguous_pct = compute_volume_delta(
            bid, ask, last, volume_real, window=10
        )
        assert cum_delta < 0
        assert sell_vol > 0
        assert buy_vol == 0.0
        assert ambiguous_pct == 0.0

    def test_empty_arrays_return_neutral(self) -> None:
        """Empty arrays return (0.0, 0.0, 0.0, 1.0)."""
        from fxsoqqabot.signals.flow.volume_delta import compute_volume_delta

        empty = np.array([], dtype=np.float64)
        cum_delta, buy_vol, sell_vol, ambiguous_pct = compute_volume_delta(
            empty, empty, empty, empty
        )
        assert cum_delta == 0.0
        assert buy_vol == 0.0
        assert sell_vol == 0.0
        assert ambiguous_pct == 1.0

    def test_ambiguous_ticks_between_bid_ask(self) -> None:
        """Ticks between bid and ask are counted as ambiguous."""
        from fxsoqqabot.signals.flow.volume_delta import compute_volume_delta

        bid = np.array([100.0, 100.0, 100.0])
        ask = np.array([102.0, 102.0, 102.0])
        last = np.array([101.0, 101.0, 101.0])  # between bid and ask
        volume_real = np.array([1.0, 1.0, 1.0])

        cum_delta, buy_vol, sell_vol, ambiguous_pct = compute_volume_delta(
            bid, ask, last, volume_real, window=10
        )
        assert cum_delta == 0.0
        assert buy_vol == 0.0
        assert sell_vol == 0.0
        assert ambiguous_pct == 1.0

    def test_window_slicing(self) -> None:
        """Only the last `window` ticks are used."""
        from fxsoqqabot.signals.flow.volume_delta import compute_volume_delta

        # 10 ticks at bid, then 5 at ask. Window=5 should see only buy ticks.
        bid = np.concatenate([np.full(10, 100.0), np.full(5, 100.0)])
        ask = np.concatenate([np.full(10, 101.0), np.full(5, 101.0)])
        last = np.concatenate([np.full(10, 100.0), np.full(5, 101.0)])
        volume_real = np.ones(15)

        cum_delta, buy_vol, sell_vol, _ = compute_volume_delta(
            bid, ask, last, volume_real, window=5
        )
        assert cum_delta > 0
        assert buy_vol == 5.0
        assert sell_vol == 0.0


# ─── Aggression Imbalance Tests (FLOW-02) ─────────────────────────


class TestAggressionImbalance:
    """Tests for compute_aggression_imbalance function."""

    def test_all_buy_aggression(self) -> None:
        """All ticks at ask -> imbalance_ratio = +1.0."""
        from fxsoqqabot.signals.flow.aggression import compute_aggression_imbalance

        bid = np.full(50, 100.0)
        ask = np.full(50, 101.0)
        last = np.full(50, 101.0)  # all at ask
        volume_real = np.ones(50)

        imbalance, zscore, confidence = compute_aggression_imbalance(
            bid, ask, last, volume_real, window=50
        )
        assert imbalance == pytest.approx(1.0)

    def test_all_sell_aggression(self) -> None:
        """All ticks at bid -> imbalance_ratio = -1.0."""
        from fxsoqqabot.signals.flow.aggression import compute_aggression_imbalance

        bid = np.full(50, 100.0)
        ask = np.full(50, 101.0)
        last = np.full(50, 100.0)  # all at bid
        volume_real = np.ones(50)

        imbalance, zscore, confidence = compute_aggression_imbalance(
            bid, ask, last, volume_real, window=50
        )
        assert imbalance == pytest.approx(-1.0)

    def test_empty_arrays_return_neutral(self) -> None:
        """Empty arrays return (0.0, 0.0, 0.0)."""
        from fxsoqqabot.signals.flow.aggression import compute_aggression_imbalance

        empty = np.array([], dtype=np.float64)
        imbalance, zscore, confidence = compute_aggression_imbalance(
            empty, empty, empty, empty
        )
        assert imbalance == 0.0
        assert zscore == 0.0
        assert confidence == 0.0

    def test_confidence_scales_with_zscore(self) -> None:
        """Confidence = min(1.0, abs(zscore) / 3.0)."""
        from fxsoqqabot.signals.flow.aggression import compute_aggression_imbalance

        # Strong unidirectional volume should produce high z-score -> high confidence
        bid = np.full(200, 100.0)
        ask = np.full(200, 101.0)
        last = np.full(200, 101.0)  # all buy
        volume_real = np.ones(200)

        _, zscore, confidence = compute_aggression_imbalance(
            bid, ask, last, volume_real, window=200
        )
        # With all buy ticks, z-score should be large, confidence should be high
        assert confidence > 0.0
        assert confidence <= 1.0


# ─── HFT Signature Detection Tests (FLOW-05) ──────────────────────


class TestHFTSignatures:
    """Tests for detect_hft_signatures function."""

    def test_normal_tick_rate_no_hft(self) -> None:
        """Normal tick rate should not trigger HFT detection."""
        from fxsoqqabot.signals.flow.aggression import detect_hft_signatures

        # Ticks at regular 100ms intervals -> 10 ticks/sec, uniform
        time_msc = np.arange(0, 10000, 100, dtype=np.int64)  # 100 ticks
        spread = np.full(len(time_msc), 1.0)
        volume_real = np.ones(len(time_msc))

        is_hft, confidence = detect_hft_signatures(time_msc, spread, volume_real)
        assert is_hft is False
        assert confidence == 0.0

    def test_hft_burst_detected(self) -> None:
        """Sudden burst of rapid ticks with spread widening -> HFT detected."""
        from fxsoqqabot.signals.flow.aggression import detect_hft_signatures

        # Normal ticks for 50 intervals, then burst of rapid ticks with wide spread
        normal_times = np.arange(0, 5000, 100, dtype=np.int64)  # 50 ticks
        burst_times = np.arange(5000, 5100, 2, dtype=np.int64)  # 50 ticks in 100ms
        time_msc = np.concatenate([normal_times, burst_times])

        normal_spread = np.full(50, 1.0)
        burst_spread = np.full(50, 5.0)  # wide spread
        spread = np.concatenate([normal_spread, burst_spread])

        volume_real = np.ones(len(time_msc))

        is_hft, confidence = detect_hft_signatures(time_msc, spread, volume_real)
        assert is_hft is True
        assert confidence > 0.0

    def test_empty_arrays_no_hft(self) -> None:
        """Empty arrays return (False, 0.0)."""
        from fxsoqqabot.signals.flow.aggression import detect_hft_signatures

        empty_int = np.array([], dtype=np.int64)
        empty_float = np.array([], dtype=np.float64)
        is_hft, confidence = detect_hft_signatures(
            empty_int, empty_float, empty_float
        )
        assert is_hft is False
        assert confidence == 0.0

    def test_too_few_ticks_no_hft(self) -> None:
        """Single tick returns no HFT."""
        from fxsoqqabot.signals.flow.aggression import detect_hft_signatures

        time_msc = np.array([1000], dtype=np.int64)
        spread = np.array([1.0])
        volume_real = np.array([1.0])
        is_hft, confidence = detect_hft_signatures(time_msc, spread, volume_real)
        assert is_hft is False
        assert confidence == 0.0


# ─── Institutional Footprint Tests (FLOW-04) ──────────────────────


class TestInstitutionalFootprints:
    """Tests for detect_institutional_footprints function."""

    def test_absorption_detected(self) -> None:
        """Large volume without price movement triggers absorption score."""
        from fxsoqqabot.signals.flow.institutional import (
            detect_institutional_footprints,
        )

        n = 100
        bid = np.full(n, 2000.0)
        ask = np.full(n, 2000.5)
        last = np.full(n, 2000.25)  # flat price
        spread = np.full(n, 0.5)
        time_msc = np.arange(0, n * 100, 100, dtype=np.int64)

        # Most volume normal, a few ticks with massive volume (absorption)
        volume_real = np.ones(n)
        volume_real[40:45] = 50.0  # huge volume spike, no price move

        score, confidence, signals = detect_institutional_footprints(
            bid, ask, last, volume_real, spread, time_msc
        )
        assert "absorption" in signals
        assert signals["absorption"]["count"] > 0

    def test_iceberg_detected(self) -> None:
        """Repeated large volume at same price -> iceberg detection."""
        from fxsoqqabot.signals.flow.institutional import (
            detect_institutional_footprints,
        )

        n = 100
        # Price moves a bit but keeps returning to 2000.0
        bid = np.full(n, 2000.0)
        ask = np.full(n, 2000.5)
        last = np.linspace(2000.0, 2001.0, n)
        spread = np.full(n, 0.5)
        time_msc = np.arange(0, n * 100, 100, dtype=np.int64)

        volume_real = np.ones(n)
        # Multiple large volume hits at the same price level
        for i in [10, 30, 50, 70]:
            last[i] = 2000.0
            volume_real[i] = 20.0

        score, confidence, signals = detect_institutional_footprints(
            bid, ask, last, volume_real, spread, time_msc,
            price_tolerance=0.5, min_repeats=3,
        )
        assert "iceberg" in signals

    def test_empty_arrays_return_neutral(self) -> None:
        """Empty arrays return (0.0, 0.0, {})."""
        from fxsoqqabot.signals.flow.institutional import (
            detect_institutional_footprints,
        )

        empty_f = np.array([], dtype=np.float64)
        empty_i = np.array([], dtype=np.int64)
        score, confidence, signals = detect_institutional_footprints(
            empty_f, empty_f, empty_f, empty_f, empty_f, empty_i
        )
        assert score == 0.0
        assert confidence == 0.0
        assert signals == {}

    def test_score_direction_positive_for_buying(self) -> None:
        """Score is positive when institutional buying detected."""
        from fxsoqqabot.signals.flow.institutional import (
            detect_institutional_footprints,
        )

        n = 100
        bid = np.full(n, 2000.0)
        ask = np.full(n, 2000.5)
        # All ticks at ask = buying
        last = np.full(n, 2000.5)
        spread = np.full(n, 0.5)
        time_msc = np.arange(0, n * 100, 100, dtype=np.int64)

        volume_real = np.ones(n)
        # Large buy absorption
        volume_real[20:25] = 50.0

        score, confidence, signals = detect_institutional_footprints(
            bid, ask, last, volume_real, spread, time_msc
        )
        assert score >= 0.0  # buying detected -> positive score

    def test_score_bounded_minus_one_to_plus_one(self) -> None:
        """Score is always in [-1, +1] range."""
        from fxsoqqabot.signals.flow.institutional import (
            detect_institutional_footprints,
        )

        n = 200
        bid = np.full(n, 2000.0)
        ask = np.full(n, 2000.5)
        last = np.full(n, 2000.5)
        spread = np.full(n, 0.5)
        time_msc = np.arange(0, n * 100, 100, dtype=np.int64)
        volume_real = np.ones(n)
        volume_real[50:80] = 100.0

        score, confidence, _ = detect_institutional_footprints(
            bid, ask, last, volume_real, spread, time_msc
        )
        assert -1.0 <= score <= 1.0
        assert 0.0 <= confidence <= 1.0


# ─── DOM Analysis Tests (FLOW-03) ─────────────────────────────────


class TestDOMAnalysis:
    """Tests for analyze_dom function."""

    def test_none_dom_returns_zero(self) -> None:
        """None DOM snapshot returns (0.0, 0.0)."""
        from fxsoqqabot.signals.flow.dom_analyzer import analyze_dom

        imbalance, confidence = analyze_dom(None)
        assert imbalance == 0.0
        assert confidence == 0.0

    def test_empty_dom_returns_zero(self) -> None:
        """DOM with no entries returns (0.0, 0.0)."""
        from fxsoqqabot.signals.flow.dom_analyzer import analyze_dom

        dom = DOMSnapshot(symbol="XAUUSD", time_msc=0, entries=())
        imbalance, confidence = analyze_dom(dom)
        assert imbalance == 0.0
        assert confidence == 0.0

    def test_bid_heavy_dom_positive_imbalance(self) -> None:
        """More volume on bid side -> positive imbalance."""
        from fxsoqqabot.signals.flow.dom_analyzer import analyze_dom

        entries = (
            # type=2 = buy (bid side)
            DOMEntry(type=2, price=2000.0, volume=100, volume_dbl=100.0),
            DOMEntry(type=2, price=1999.5, volume=80, volume_dbl=80.0),
            DOMEntry(type=2, price=1999.0, volume=60, volume_dbl=60.0),
            # type=1 = sell (ask side)
            DOMEntry(type=1, price=2000.5, volume=20, volume_dbl=20.0),
            DOMEntry(type=1, price=2001.0, volume=10, volume_dbl=10.0),
            DOMEntry(type=1, price=2001.5, volume=10, volume_dbl=10.0),
        )
        dom = DOMSnapshot(symbol="XAUUSD", time_msc=1000, entries=entries)
        imbalance, confidence = analyze_dom(dom)
        assert imbalance > 0  # bid-heavy -> positive
        assert confidence > 0

    def test_ask_heavy_dom_negative_imbalance(self) -> None:
        """More volume on ask side -> negative imbalance."""
        from fxsoqqabot.signals.flow.dom_analyzer import analyze_dom

        entries = (
            DOMEntry(type=2, price=2000.0, volume=10, volume_dbl=10.0),
            DOMEntry(type=2, price=1999.5, volume=10, volume_dbl=10.0),
            DOMEntry(type=1, price=2000.5, volume=100, volume_dbl=100.0),
            DOMEntry(type=1, price=2001.0, volume=80, volume_dbl=80.0),
            DOMEntry(type=1, price=2001.5, volume=60, volume_dbl=60.0),
        )
        dom = DOMSnapshot(symbol="XAUUSD", time_msc=1000, entries=entries)
        imbalance, confidence = analyze_dom(dom)
        assert imbalance < 0  # ask-heavy -> negative


# ─── DOM Quality Checker Tests (D-15) ─────────────────────────────


class TestDOMQualityChecker:
    """Tests for DOMQualityChecker class."""

    def test_initially_disabled(self) -> None:
        """DOM is disabled before any samples are recorded."""
        from fxsoqqabot.signals.flow.dom_quality import DOMQualityChecker

        checker = DOMQualityChecker(FlowConfig())
        assert checker.is_dom_enabled is False

    def test_enabled_after_sufficient_quality_snapshots(self) -> None:
        """DOM is enabled after sampling period with sufficient quality."""
        from fxsoqqabot.signals.flow.dom_quality import DOMQualityChecker

        config = FlowConfig(
            dom_quality_check_duration_seconds=1,  # short for testing
            dom_min_depth=2,
            dom_min_update_rate=1.0,
        )
        checker = DOMQualityChecker(config)

        # Simulate rapid DOM snapshots with good depth
        entries = (
            DOMEntry(type=2, price=2000.0, volume=10, volume_dbl=10.0),
            DOMEntry(type=2, price=1999.5, volume=10, volume_dbl=10.0),
            DOMEntry(type=1, price=2000.5, volume=10, volume_dbl=10.0),
            DOMEntry(type=1, price=2001.0, volume=10, volume_dbl=10.0),
        )
        # Record multiple snapshots spread over the check duration
        base_time = 1000000
        for i in range(20):
            dom = DOMSnapshot(
                symbol="XAUUSD",
                time_msc=base_time + i * 100,  # every 100ms = 10/sec
                entries=entries,
            )
            checker.record_snapshot(dom)

        assert checker.is_dom_enabled is True

    def test_disabled_with_insufficient_depth(self) -> None:
        """DOM stays disabled if depth is insufficient."""
        from fxsoqqabot.signals.flow.dom_quality import DOMQualityChecker

        config = FlowConfig(
            dom_quality_check_duration_seconds=1,
            dom_min_depth=5,  # requires 5 levels each side
            dom_min_update_rate=1.0,
        )
        checker = DOMQualityChecker(config)

        # Only 1 entry per side
        entries = (
            DOMEntry(type=2, price=2000.0, volume=10, volume_dbl=10.0),
            DOMEntry(type=1, price=2000.5, volume=10, volume_dbl=10.0),
        )
        base_time = 1000000
        for i in range(20):
            dom = DOMSnapshot(
                symbol="XAUUSD",
                time_msc=base_time + i * 100,
                entries=entries,
            )
            checker.record_snapshot(dom)

        assert checker.is_dom_enabled is False


# ─── OrderFlowModule Integration Tests (FLOW-06/D-13) ─────────────


class TestOrderFlowModule:
    """Tests for OrderFlowModule implementing SignalModule Protocol."""

    def test_name_is_flow(self) -> None:
        """Module name returns 'flow'."""
        from fxsoqqabot.signals.flow.module import OrderFlowModule

        module = OrderFlowModule(FlowConfig())
        assert module.name == "flow"

    def test_isinstance_signal_module(self) -> None:
        """OrderFlowModule passes SignalModule isinstance check."""
        from fxsoqqabot.signals.base import SignalModule
        from fxsoqqabot.signals.flow.module import OrderFlowModule

        module = OrderFlowModule(FlowConfig())
        assert isinstance(module, SignalModule)

    @pytest.mark.asyncio
    async def test_update_with_empty_tick_data(self) -> None:
        """Empty tick arrays -> confidence=0.0, direction=0.0."""
        from fxsoqqabot.signals.flow.module import OrderFlowModule

        module = OrderFlowModule(FlowConfig())
        await module.initialize()

        empty_arrays = {
            k: np.array([], dtype=np.float64)
            for k in ("time_msc", "bid", "ask", "last", "spread", "volume_real")
        }

        output = await module.update(empty_arrays, {}, None)
        assert output.module_name == "flow"
        assert output.confidence == 0.0
        assert output.direction == 0.0

    @pytest.mark.asyncio
    async def test_update_with_tick_data_no_dom(self) -> None:
        """Tick-only data produces valid signal (graceful degradation)."""
        from fxsoqqabot.signals.flow.module import OrderFlowModule

        module = OrderFlowModule(FlowConfig())
        await module.initialize()

        n = 200
        tick_arrays = {
            "time_msc": np.arange(0, n * 100, 100, dtype=np.int64),
            "bid": np.full(n, 2000.0),
            "ask": np.full(n, 2000.5),
            "last": np.full(n, 2000.5),  # all at ask = buying
            "spread": np.full(n, 0.5),
            "volume_real": np.ones(n),
        }

        output = await module.update(tick_arrays, {}, None)
        assert output.module_name == "flow"
        assert -1.0 <= output.direction <= 1.0
        assert 0.0 <= output.confidence <= 1.0
        # Should be positive direction since all ticks are at ask (buying)
        assert output.direction > 0

    @pytest.mark.asyncio
    async def test_update_with_dom_data(self) -> None:
        """Update with DOM data incorporates DOM analysis when quality passes."""
        from fxsoqqabot.signals.flow.module import OrderFlowModule

        config = FlowConfig(
            dom_quality_check_duration_seconds=0,  # instant quality check
            dom_min_depth=1,
            dom_min_update_rate=0.0,  # no minimum rate
        )
        module = OrderFlowModule(config)
        await module.initialize()

        n = 200
        tick_arrays = {
            "time_msc": np.arange(0, n * 100, 100, dtype=np.int64),
            "bid": np.full(n, 2000.0),
            "ask": np.full(n, 2000.5),
            "last": np.full(n, 2000.5),
            "spread": np.full(n, 0.5),
            "volume_real": np.ones(n),
        }

        dom_entries = (
            DOMEntry(type=2, price=2000.0, volume=100, volume_dbl=100.0),
            DOMEntry(type=2, price=1999.5, volume=80, volume_dbl=80.0),
            DOMEntry(type=1, price=2000.5, volume=20, volume_dbl=20.0),
            DOMEntry(type=1, price=2001.0, volume=10, volume_dbl=10.0),
        )
        dom = DOMSnapshot(symbol="XAUUSD", time_msc=5000, entries=dom_entries)

        # First call to get quality checker warmed up
        output1 = await module.update(tick_arrays, {}, dom)
        # Call again with DOM to get DOM-enhanced output
        output2 = await module.update(tick_arrays, {}, dom)

        assert output2.module_name == "flow"
        assert -1.0 <= output2.direction <= 1.0

    @pytest.mark.asyncio
    async def test_metadata_populated(self) -> None:
        """Update populates metadata with component details."""
        from fxsoqqabot.signals.flow.module import OrderFlowModule

        module = OrderFlowModule(FlowConfig())
        await module.initialize()

        n = 200
        tick_arrays = {
            "time_msc": np.arange(0, n * 100, 100, dtype=np.int64),
            "bid": np.full(n, 2000.0),
            "ask": np.full(n, 2000.5),
            "last": np.full(n, 2000.25),
            "spread": np.full(n, 0.5),
            "volume_real": np.ones(n),
        }

        output = await module.update(tick_arrays, {}, None)
        assert "volume_delta" in output.metadata
        assert "aggression_imbalance" in output.metadata
