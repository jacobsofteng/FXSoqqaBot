"""Tests for CLI entry points: argument parsing and command dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fxsoqqabot.cli import create_parser, cmd_reset, cmd_status


class TestCreateParser:
    """Test argument parser creation and subcommand parsing."""

    def test_returns_argument_parser(self) -> None:
        """create_parser returns an ArgumentParser instance."""
        import argparse

        parser = create_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_run_subcommand(self) -> None:
        """Parser recognizes 'run' subcommand."""
        parser = create_parser()
        args = parser.parse_args(["run"])
        assert args.command == "run"

    def test_run_with_config(self) -> None:
        """Parser parses 'run --config config/paper.toml' correctly."""
        parser = create_parser()
        args = parser.parse_args(["run", "--config", "config/paper.toml"])
        assert args.command == "run"
        assert args.config == ["config/paper.toml"]

    def test_run_with_multiple_configs(self) -> None:
        """Parser accepts multiple config files."""
        parser = create_parser()
        args = parser.parse_args(
            ["run", "--config", "config/default.toml", "config/paper.toml"]
        )
        assert args.command == "run"
        assert args.config == ["config/default.toml", "config/paper.toml"]

    def test_kill_subcommand(self) -> None:
        """Parser recognizes 'kill' with no extra args."""
        parser = create_parser()
        args = parser.parse_args(["kill"])
        assert args.command == "kill"

    def test_status_subcommand(self) -> None:
        """Parser recognizes 'status' subcommand."""
        parser = create_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_reset_subcommand(self) -> None:
        """Parser recognizes 'reset' subcommand."""
        parser = create_parser()
        args = parser.parse_args(["reset"])
        assert args.command == "reset"

    def test_no_command_returns_none(self) -> None:
        """Parser returns command=None when no subcommand given."""
        parser = create_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_all_four_commands_present(self) -> None:
        """All four commands (run, kill, status, reset) are parseable."""
        parser = create_parser()
        for cmd in ["run", "kill", "status", "reset"]:
            args = parser.parse_args([cmd])
            assert args.command == cmd


class TestCmdStatus:
    """Test cmd_status reads and displays state."""

    @pytest.mark.asyncio
    async def test_status_reads_breaker_state(self) -> None:
        """cmd_status reads state from StateManager."""
        from fxsoqqabot.core.state import BreakerState, CircuitBreakerSnapshot

        mock_snapshot = CircuitBreakerSnapshot(
            daily_pnl=-5.0,
            weekly_pnl=-3.0,
            consecutive_losses=2,
            daily_trade_count=7,
            equity_high_water_mark=25.0,
            daily_starting_equity=20.0,
            session_date="2026-03-27",
            kill_switch=BreakerState.ACTIVE,
        )

        with (
            patch("fxsoqqabot.cli.load_settings") as mock_settings,
            patch("fxsoqqabot.cli.StateManager") as MockState,
        ):
            settings = MagicMock()
            settings.data.storage_path = "/tmp/test"
            settings.execution.mode = "paper"
            settings.execution.symbol = "XAUUSD"
            mock_settings.return_value = settings

            mock_state_inst = MagicMock()
            mock_state_inst.initialize = AsyncMock()
            mock_state_inst.load_breaker_state = AsyncMock(
                return_value=mock_snapshot
            )
            mock_state_inst.close = AsyncMock()
            MockState.return_value = mock_state_inst

            await cmd_status()

            mock_state_inst.load_breaker_state.assert_awaited_once()
            mock_state_inst.close.assert_awaited_once()


class TestCmdReset:
    """Test cmd_reset resets kill switch when killed."""

    @pytest.mark.asyncio
    async def test_reset_when_killed(self) -> None:
        """cmd_reset resets kill switch when in KILLED state."""
        with (
            patch("fxsoqqabot.cli.load_settings") as mock_settings,
            patch("fxsoqqabot.cli.StateManager") as MockState,
            patch(
                "fxsoqqabot.risk.kill_switch.KillSwitch"
            ) as MockKill,
        ):
            settings = MagicMock()
            settings.data.storage_path = "/tmp/test"
            mock_settings.return_value = settings

            mock_state_inst = MagicMock()
            mock_state_inst.initialize = AsyncMock()
            mock_state_inst.close = AsyncMock()
            MockState.return_value = mock_state_inst

            mock_ks = MagicMock()
            mock_ks.is_killed = AsyncMock(return_value=True)
            mock_ks.reset = AsyncMock()
            MockKill.return_value = mock_ks

            await cmd_reset()

            mock_ks.is_killed.assert_awaited_once()
            mock_ks.reset.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reset_when_not_killed(self) -> None:
        """cmd_reset does not reset when kill switch is not active."""
        with (
            patch("fxsoqqabot.cli.load_settings") as mock_settings,
            patch("fxsoqqabot.cli.StateManager") as MockState,
            patch(
                "fxsoqqabot.risk.kill_switch.KillSwitch"
            ) as MockKill,
        ):
            settings = MagicMock()
            settings.data.storage_path = "/tmp/test"
            mock_settings.return_value = settings

            mock_state_inst = MagicMock()
            mock_state_inst.initialize = AsyncMock()
            mock_state_inst.close = AsyncMock()
            MockState.return_value = mock_state_inst

            mock_ks = MagicMock()
            mock_ks.is_killed = AsyncMock(return_value=False)
            mock_ks.reset = AsyncMock()
            MockKill.return_value = mock_ks

            await cmd_reset()

            mock_ks.is_killed.assert_awaited_once()
            mock_ks.reset.assert_not_awaited()
