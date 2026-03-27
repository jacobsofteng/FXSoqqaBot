"""CLI entry points for FXSoqqaBot per D-09.

Supports commands:
- run: Start the trading bot (with optional --no-tui, --no-web, --no-learning)
- dashboard: Run web dashboard only
- learning: Show learning loop status
- optimize: Run Optuna + DEAP parameter optimization
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
    """Create argument parser with run, dashboard, learning, kill, status, reset subcommands."""
    parser = argparse.ArgumentParser(
        prog="fxsoqqabot",
        description="FXSoqqaBot: Self-learning XAUUSD scalping bot",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run command with Phase 4 flags
    run_parser = subparsers.add_parser("run", help="Start the trading bot")
    run_parser.add_argument(
        "--config",
        nargs="*",
        default=None,
        help="TOML config file(s) to load (e.g., config/paper.toml)",
    )
    run_parser.add_argument(
        "--no-tui",
        action="store_true",
        default=False,
        help="Disable terminal UI dashboard",
    )
    run_parser.add_argument(
        "--no-web",
        action="store_true",
        default=False,
        help="Disable web dashboard server",
    )
    run_parser.add_argument(
        "--no-learning",
        action="store_true",
        default=False,
        help="Disable self-learning loop",
    )

    # dashboard command
    dashboard_parser = subparsers.add_parser(
        "dashboard", help="Run dashboard (web-only or TUI)"
    )
    dashboard_parser.add_argument(
        "--web-only",
        action="store_true",
        default=False,
        help="Run only the web dashboard without TUI",
    )
    dashboard_parser.add_argument(
        "--config",
        nargs="*",
        default=None,
        help="TOML config file(s) to load",
    )

    # learning command
    learning_parser = subparsers.add_parser(
        "learning", help="Learning loop control and status"
    )
    learning_parser.add_argument(
        "--status",
        action="store_true",
        default=False,
        help="Show learning loop status",
    )
    learning_parser.add_argument(
        "--config",
        nargs="*",
        default=None,
        help="TOML config file(s) to load",
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

    # backtest command
    backtest_parser = subparsers.add_parser(
        "backtest", help="Run full backtesting pipeline"
    )
    backtest_parser.add_argument(
        "--config",
        nargs="*",
        default=None,
        help="TOML config file(s) to load",
    )
    backtest_parser.add_argument(
        "--skip-ingestion",
        action="store_true",
        default=False,
        help="Skip CSV-to-Parquet ingestion (use existing Parquet data)",
    )

    # optimize command
    optimize_parser = subparsers.add_parser(
        "optimize", help="Optimize strategy parameters via Optuna + DEAP"
    )
    optimize_parser.add_argument(
        "--config",
        nargs="*",
        default=None,
        help="TOML config file(s) to load (e.g., config/paper.toml)",
    )
    optimize_parser.add_argument(
        "--n-trials",
        type=int,
        default=50,
        help="Number of Optuna trials (default: 50)",
    )
    optimize_parser.add_argument(
        "--n-generations",
        type=int,
        default=10,
        help="Number of DEAP GA generations for weight evolution (default: 10)",
    )
    optimize_parser.add_argument(
        "--output",
        type=str,
        default="config/optimized.toml",
        help="Path to write optimized config (default: config/optimized.toml)",
    )
    optimize_parser.add_argument(
        "--skip-ingestion",
        action="store_true",
        default=False,
        help="Skip CSV-to-Parquet ingestion (use existing Parquet data)",
    )

    return parser


async def cmd_run(args: argparse.Namespace) -> None:
    """Start the trading bot with the given configuration.

    Handles SIGINT/SIGTERM for graceful shutdown. Supports --no-tui,
    --no-web, and --no-learning flags to disable Phase 4 features.
    """
    from fxsoqqabot.core.engine import TradingEngine

    settings = load_settings(args.config)

    # Apply CLI overrides for Phase 4 features
    if getattr(args, "no_tui", False):
        settings.tui.enabled = False
    if getattr(args, "no_web", False):
        settings.web.enabled = False
    if getattr(args, "no_learning", False):
        settings.learning.enabled = False

    _setup_logging(settings)

    logger = structlog.get_logger()
    logger.info(
        "bot_starting",
        mode=settings.execution.mode,
        symbol=settings.execution.symbol,
        tui=settings.tui.enabled,
        web=settings.web.enabled,
        learning=settings.learning.enabled,
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

    # If TUI enabled, start engine in background and TUI as main loop
    if settings.tui.enabled and not getattr(args, "no_tui", False):
        try:
            from fxsoqqabot.dashboard.tui.app import FXSoqqaBotTUI

            tui = FXSoqqaBotTUI(
                state=engine.engine_state,
                kill_callback=engine._handle_kill,
                pause_callback=engine._handle_pause,
            )
            engine_task = asyncio.create_task(engine.start())
            await tui.run_async()
            engine_task.cancel()
        except KeyboardInterrupt:
            logger.info("keyboard_interrupt")
            await engine.stop()
    else:
        try:
            await engine.start()
        except KeyboardInterrupt:
            logger.info("keyboard_interrupt")
            await engine.stop()


async def cmd_dashboard(args: argparse.Namespace) -> None:
    """Run dashboard standalone (web-only or TUI).

    Useful for connecting to a running bot's state or for development.
    """
    from fxsoqqabot.core.state_snapshot import TradingEngineState

    settings = load_settings(getattr(args, "config", None))
    _setup_logging(settings)

    state = TradingEngineState()

    if getattr(args, "web_only", False):
        from fxsoqqabot.dashboard.web.server import DashboardServer

        server = DashboardServer(
            config=settings.web,
            state=state,
        )
        print(f"Starting web dashboard on http://{settings.web.host}:{settings.web.port}")
        await server.start()
    else:
        from fxsoqqabot.dashboard.tui.app import FXSoqqaBotTUI

        tui = FXSoqqaBotTUI(state=state)
        await tui.run_async()


async def cmd_learning(args: argparse.Namespace) -> None:
    """Show learning loop status.

    Reads trade context from DuckDB and displays learning metrics.
    """
    settings = load_settings(getattr(args, "config", None))

    print("FXSoqqaBot Learning Status")
    print("=" * 40)
    print(f"Learning enabled:       {settings.learning.enabled}")
    print(f"Evolve every N trades:  {settings.learning.evolve_every_n_trades}")
    print(f"Shadow variants:        {settings.learning.n_shadow_variants}")
    print(f"Promotion alpha:        {settings.learning.promotion_alpha}")
    print(f"Retirement threshold:   {settings.learning.retirement_threshold}")
    print(f"GA population:          {settings.learning.ga_population_size}")
    print(f"GA crossover prob:      {settings.learning.ga_crossover_prob}")
    print(f"GA mutation prob:       {settings.learning.ga_mutation_prob}")


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


async def cmd_backtest(args: argparse.Namespace) -> None:
    """Run the full backtesting pipeline.

    Ingests histdata.com CSVs, runs walk-forward validation, OOS evaluation,
    and Monte Carlo simulation with formatted results.
    """
    from fxsoqqabot.backtest.config import BacktestConfig
    from fxsoqqabot.backtest.runner import run_full_backtest

    settings = load_settings(args.config)
    _setup_logging(settings)

    bt_config = BacktestConfig()
    await run_full_backtest(settings, bt_config, skip_ingestion=args.skip_ingestion)


def cmd_optimize(args: argparse.Namespace) -> None:
    """Run parameter optimization. Synchronous -- Optuna drives the event loop.

    Each Optuna objective call uses its own asyncio.run() to bridge to
    async BacktestEngine. This function must NOT be wrapped in asyncio.run()
    by the CLI dispatcher (Pitfall 2).
    """
    from fxsoqqabot.backtest.config import BacktestConfig
    from fxsoqqabot.optimization.optimizer import run_optimization

    settings = load_settings(args.config)
    _setup_logging(settings)

    bt_config = BacktestConfig()
    run_optimization(
        settings=settings,
        bt_config=bt_config,
        n_trials=args.n_trials,
        n_generations=args.n_generations,
        output_path=args.output,
        skip_ingestion=args.skip_ingestion,
    )


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
        "dashboard": lambda: cmd_dashboard(args),
        "learning": lambda: cmd_learning(args),
        "kill": cmd_kill,
        "status": cmd_status,
        "reset": cmd_reset,
        "backtest": lambda: cmd_backtest(args),
        "optimize": lambda: cmd_optimize(args),
    }

    result = commands[args.command]()
    if asyncio.iscoroutine(result):
        asyncio.run(result)
    # If result is None (sync command like optimize), nothing to do


if __name__ == "__main__":
    main()
