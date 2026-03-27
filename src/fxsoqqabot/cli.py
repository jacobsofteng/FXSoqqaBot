"""CLI entry points for FXSoqqaBot per D-09.

Supports four commands:
- run: Start the trading bot
- kill: Activate kill switch (close all positions, halt trading)
- status: Show circuit breaker states and counters
- reset: Reset kill switch (explicit manual action per D-10)

Kill switch is invocable via `python -m fxsoqqabot kill` independently
of TUI per D-09.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog

from fxsoqqabot.config.loader import load_settings
from fxsoqqabot.config.models import BotSettings
from fxsoqqabot.core.state import StateManager


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser with run, kill, status, reset subcommands."""
    parser = argparse.ArgumentParser(
        prog="fxsoqqabot",
        description="FXSoqqaBot: Self-learning XAUUSD scalping bot",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run command
    run_parser = subparsers.add_parser("run", help="Start the trading bot")
    run_parser.add_argument(
        "--config",
        nargs="*",
        default=None,
        help="TOML config file(s) to load (e.g., config/paper.toml)",
    )

    # kill command (no args) per D-09
    subparsers.add_parser(
        "kill", help="Activate kill switch: close all positions, halt trading"
    )

    # status command (no args)
    subparsers.add_parser(
        "status", help="Show circuit breaker states and counters"
    )

    # reset command (no args) per D-10
    subparsers.add_parser(
        "reset", help="Reset kill switch (requires explicit action)"
    )

    return parser


async def cmd_run(args: argparse.Namespace) -> None:
    """Start the trading bot with the given configuration.

    Handles SIGINT/SIGTERM for graceful shutdown.
    """
    from fxsoqqabot.core.engine import TradingEngine

    settings = load_settings(args.config)
    _setup_logging(settings)

    logger = structlog.get_logger()
    logger.info(
        "bot_starting",
        mode=settings.execution.mode,
        symbol=settings.execution.symbol,
    )

    engine = TradingEngine(settings)

    # Setup signal handling for graceful shutdown
    try:
        import signal

        loop = asyncio.get_running_loop()

        def _shutdown_signal() -> None:
            logger.info("shutdown_signal_received")
            asyncio.ensure_future(engine.stop())

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _shutdown_signal)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler for all signals
                pass
    except Exception:
        pass

    try:
        await engine.start()
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
        await engine.stop()


async def cmd_kill() -> None:
    """Activate kill switch per D-09.

    Loads settings, initializes StateManager and MT5Bridge.
    Creates KillSwitch with OrderManager (if MT5 connected) or without.
    """
    from fxsoqqabot.execution.mt5_bridge import MT5Bridge
    from fxsoqqabot.execution.orders import OrderManager
    from fxsoqqabot.risk.kill_switch import KillSwitch

    settings = load_settings()
    state = StateManager(settings.data.storage_path + "/state.db")
    await state.initialize()

    bridge = MT5Bridge(settings.execution)
    order_manager: OrderManager | None = None

    # Try to connect to close positions
    if await bridge.connect():
        order_manager = OrderManager(bridge, settings.execution)

    kill_switch = KillSwitch(state, order_manager)
    result = await kill_switch.activate()

    print(f"Kill switch activated. Positions closed: {result['positions_closed']}")

    if order_manager is not None:
        await bridge.shutdown()
    await state.close()


async def cmd_status() -> None:
    """Show circuit breaker states and counters.

    Reads breaker state from SQLite and prints all statuses.
    """
    settings = load_settings()
    state = StateManager(settings.data.storage_path + "/state.db")
    await state.initialize()

    snapshot = await state.load_breaker_state()

    print("FXSoqqaBot Status")
    print("=" * 40)
    print(f"Mode:           {settings.execution.mode}")
    print(f"Symbol:         {settings.execution.symbol}")
    print(f"Session date:   {snapshot.session_date or 'N/A'}")
    print()
    print("Circuit Breakers:")
    print(f"  Kill switch:       {snapshot.kill_switch.value}")
    print(f"  Daily drawdown:    {snapshot.daily_drawdown.value}")
    print(f"  Loss streak:       {snapshot.loss_streak.value}")
    print(f"  Rapid equity drop: {snapshot.rapid_equity_drop.value}")
    print(f"  Max trades:        {snapshot.max_trades.value}")
    print(f"  Spread spike:      {snapshot.spread_spike.value}")
    print()
    print("Counters:")
    print(f"  Daily P&L:           ${snapshot.daily_pnl:.2f}")
    print(f"  Weekly P&L:          ${snapshot.weekly_pnl:.2f}")
    print(f"  Consecutive losses:  {snapshot.consecutive_losses}")
    print(f"  Daily trades:        {snapshot.daily_trade_count}")
    print(f"  Equity HWM:          ${snapshot.equity_high_water_mark:.2f}")
    print(f"  Starting equity:     ${snapshot.daily_starting_equity:.2f}")

    await state.close()


async def cmd_reset() -> None:
    """Reset kill switch per D-10.

    Only resets if kill switch is currently in KILLED state.
    """
    from fxsoqqabot.risk.kill_switch import KillSwitch

    settings = load_settings()
    state = StateManager(settings.data.storage_path + "/state.db")
    await state.initialize()

    kill_switch = KillSwitch(state)

    if await kill_switch.is_killed():
        await kill_switch.reset()
        print("Kill switch has been reset. Trading can resume.")
    else:
        print("Kill switch is not active. Nothing to reset.")

    await state.close()


def _setup_logging(settings: BotSettings) -> None:
    """Configure structlog based on settings."""
    import logging

    log_level = getattr(logging, settings.logging.level.upper(), logging.INFO)

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
    )


def main() -> None:
    """Main entry point: parse args, dispatch to async command."""
    parser = create_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        "run": lambda: cmd_run(args),
        "kill": cmd_kill,
        "status": cmd_status,
        "reset": cmd_reset,
    }

    coro = commands[args.command]()
    asyncio.run(coro)


if __name__ == "__main__":
    main()
