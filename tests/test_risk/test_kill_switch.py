"""Tests for kill switch per RISK-05, D-09, D-10.

Validates activate, reset, is_killed, and no-auto-reset behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from fxsoqqabot.core.state import BreakerState, StateManager
from fxsoqqabot.risk.kill_switch import KillSwitch


@pytest.fixture
async def state_mgr(tmp_path):
    """Create a StateManager with a temporary database."""
    db_path = tmp_path / "ks_test.db"
    mgr = StateManager(db_path=db_path)
    await mgr.initialize()
    yield mgr
    await mgr.close()


@pytest.fixture
def mock_order_manager():
    """Create a mock OrderManager."""
    om = AsyncMock()
    om.close_all_positions = AsyncMock(return_value=[])
    return om


@pytest.fixture
async def kill_switch(state_mgr, mock_order_manager):
    """Create a KillSwitch for testing."""
    return KillSwitch(state_mgr, mock_order_manager)


class TestActivate:
    """Test kill switch activation."""

    async def test_activate_sets_killed_state(self, kill_switch, state_mgr):
        """activate() sets kill_switch to KILLED and persists state."""
        await kill_switch.activate()

        loaded = await state_mgr.load_breaker_state()
        assert loaded.kill_switch == BreakerState.KILLED

    async def test_activate_closes_all_positions(
        self, kill_switch, mock_order_manager
    ):
        """activate() calls close_all_positions on OrderManager."""
        await kill_switch.activate()

        mock_order_manager.close_all_positions.assert_awaited_once()

    async def test_activate_returns_summary(self, kill_switch):
        """activate() returns summary dict."""
        result = await kill_switch.activate()
        assert "positions_closed" in result
        assert "fills" in result


class TestIsKilled:
    """Test kill switch state check."""

    async def test_is_killed_false_initially(self, kill_switch):
        """is_killed() returns False when kill_switch is ACTIVE."""
        result = await kill_switch.is_killed()
        assert result is False

    async def test_is_killed_true_after_activate(self, kill_switch):
        """is_killed() returns True after activation."""
        await kill_switch.activate()
        result = await kill_switch.is_killed()
        assert result is True


class TestReset:
    """Test kill switch reset."""

    async def test_reset_changes_killed_to_active(self, kill_switch, state_mgr):
        """reset() changes kill_switch from KILLED to ACTIVE."""
        await kill_switch.activate()
        assert await kill_switch.is_killed() is True

        await kill_switch.reset()
        assert await kill_switch.is_killed() is False

        loaded = await state_mgr.load_breaker_state()
        assert loaded.kill_switch == BreakerState.ACTIVE

    async def test_reset_noop_if_not_killed(self, kill_switch, state_mgr):
        """reset() does nothing if not currently KILLED."""
        await kill_switch.reset()
        loaded = await state_mgr.load_breaker_state()
        assert loaded.kill_switch == BreakerState.ACTIVE


class TestNoAutoReset:
    """Test that kill switch is NOT auto-reset per D-10."""

    async def test_kill_switch_survives_state_reload(self, state_mgr):
        """Kill switch state persists across StateManager reloads (no auto-reset)."""
        # Activate kill switch
        ks = KillSwitch(state_mgr)
        await ks.activate()

        # Verify it persists in SQLite
        loaded = await state_mgr.load_breaker_state()
        assert loaded.kill_switch == BreakerState.KILLED

        # A new KillSwitch reading the same state should still see KILLED
        ks2 = KillSwitch(state_mgr)
        assert await ks2.is_killed() is True
