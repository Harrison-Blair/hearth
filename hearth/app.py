"""hearth CLI entry point."""
from __future__ import annotations

import argparse
import sys

from hearth import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hearth")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="run the hearth daemon")

    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.command == "run":
        print("hearth run: the daemon lands in FTHR-003", file=sys.stderr)
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
