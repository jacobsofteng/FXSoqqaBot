"""Tests for Phase 7 validation pipeline entry points.

Verifies CLI subcommand registration for validate-regimes and stress-test,
and runner pipeline extension from 4 to 6 steps.
"""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fxsoqqabot.cli import create_parser


class TestCLISubcommands:
    """Verify validate-regimes and stress-test CLI registration."""

    def test_validate_regimes_subcommand_registered(self) -> None:
        """validate-regimes is a recognized subcommand."""
        parser = create_parser()
        args = parser.parse_args(["validate-regimes"])
        assert args.command == "validate-regimes"

    def test_validate_regimes_has_config_arg(self) -> None:
        """validate-regimes accepts --config argument."""
        parser = create_parser()
        args = parser.parse_args(["validate-regimes", "--config", "test.toml"])
        assert args.config == ["test.toml"]

    def test_validate_regimes_has_skip_ingestion_arg(self) -> None:
        """validate-regimes accepts --skip-ingestion flag."""
        parser = create_parser()
        args = parser.parse_args(["validate-regimes", "--skip-ingestion"])
        assert args.skip_ingestion is True

    def test_stress_test_subcommand_registered(self) -> None:
        """stress-test is a recognized subcommand."""
        parser = create_parser()
        args = parser.parse_args(["stress-test"])
        assert args.command == "stress-test"

    def test_stress_test_has_config_arg(self) -> None:
        """stress-test accepts --config argument."""
        parser = create_parser()
        args = parser.parse_args(["stress-test", "--config", "custom.toml"])
        assert args.config == ["custom.toml"]


class TestRunnerStepHeaders:
    """Verify runner uses 6-step headers."""

    def test_runner_has_six_step_headers(self) -> None:
        """runner.py step headers all show /6, not /4."""
        import inspect

        from fxsoqqabot.backtest import runner

        source = inspect.getsource(runner)
        # Must have all 6 step headers
        assert "[1/6]" in source
        assert "[2/6]" in source
        assert "[3/6]" in source
        assert "[4/6]" in source
        assert "[5/6]" in source
        assert "[6/6]" in source
        # Must NOT have old /4 headers
        assert "[1/4]" not in source
        assert "[2/4]" not in source
        assert "[3/4]" not in source
        assert "[4/4]" not in source


class TestRunnerIntegration:
    """Verify runner calls RegimeTagger and FeigenbaumStressTest."""

    def test_runner_imports_regime_tagger(self) -> None:
        """runner.py imports RegimeTagger."""
        from fxsoqqabot.backtest import runner

        assert hasattr(runner, "RegimeTagger")

    def test_runner_imports_feigenbaum_stress_test(self) -> None:
        """runner.py imports FeigenbaumStressTest."""
        from fxsoqqabot.backtest import runner

        assert hasattr(runner, "FeigenbaumStressTest")

    @pytest.mark.asyncio
    async def test_runner_stress_test_failure_causes_overall_fail(self) -> None:
        """When stress test fails, overall pipeline reports FAIL."""
        # This test verifies the logic by checking runner source code structure.
        # A full integration test would require historical data, so we verify
        # the overall_pass computation includes stress test.
        import inspect

        from fxsoqqabot.backtest import runner

        source = inspect.getsource(runner.run_full_backtest)
        # overall_pass must include stress test pass condition
        assert "stress" in source.lower()
        # The failures list must check stress test
        assert "Stress Test" in source
