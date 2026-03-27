"""Entry point for python -m fxsoqqabot.

Dispatches to CLI commands: run, kill, status, reset.
"""

from fxsoqqabot.cli import main

if __name__ == "__main__":
    main()
