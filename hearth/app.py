"""hearth CLI entry point."""
from __future__ import annotations

import argparse
import asyncio
import sys

from hearth import __version__


async def _run_daemon() -> int:
    import httpx

    from hearth.brain.router import Router
    from hearth.config import Settings
    from hearth.loop import Loop
    from hearth.memory.log import EventLog
    from hearth.tools.registry import ToolRegistry
    from hearth.veneer.server import Veneer

    settings = Settings()
    default_backend = settings.llm.resolve_tier("default")
    client = httpx.AsyncClient(base_url=default_backend.base_url)
    # Separate client for tool calls (e.g. Wikipedia): the LLM client's
    # base_url points at the chat backend, not a tool's own endpoint.
    tool_client = httpx.AsyncClient()
    try:
        router = Router(settings.llm, client=client)
        log = EventLog(settings.storage.db_path)
        registry = ToolRegistry(tool_config=settings.tool, client=tool_client)
        loop = Loop(router, log, settings, registry=registry)
        veneer = Veneer(loop, log, settings)
        await veneer.serve(settings.veneer.host, settings.veneer.port)
    finally:
        await client.aclose()
        await tool_client.aclose()
    return 0


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
        return asyncio.run(_run_daemon())

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
