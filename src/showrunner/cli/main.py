"""Argument parsing and dispatch for `showrunner-cli`."""

import argparse
from collections.abc import Sequence

from showrunner import __version__
from showrunner.app.profiles import registered  # noqa: F401  # registers every stage's options


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="showrunner-cli", description="Showrunner command line.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
