"""hearth CLI entry point."""
from __future__ import annotations

import argparse
import asyncio
import sys

from hearth import __version__


async def _run_daemon() -> int:
    import httpx
    from dotenv import load_dotenv

    from hearth.brain.router import Router
    from hearth.config import Settings
    from hearth.loop import Loop
    from hearth.memory.log import EventLog
    from hearth.tools.registry import ToolRegistry
    from hearth.veneer.server import Veneer

    # Load .env into os.environ so backends' resolve_api_key() (a plain
    # os.environ lookup by api_key_env name) can see the secrets. Per FTHR-015,
    # API keys live only in .env; pydantic-settings reads .env into the Settings
    # model but does not export it to the process environment.
    load_dotenv()

    settings = Settings()
    # One client per LLM backend: each backend has its own base_url, so a
    # single shared client would send every request to whichever backend
    # built it, regardless of which tier the router selects.
    clients = {
        name: httpx.AsyncClient(base_url=backend.base_url)
        for name, backend in settings.llm.backends.items()
    }
    # Separate client for tool calls (e.g. Wikipedia): the LLM clients'
    # base_urls point at chat backends, not a tool's own endpoint.
    tool_client = httpx.AsyncClient()
    try:
        router = Router(settings.llm, clients=clients)
        log = EventLog(settings.storage.db_path)
        registry = ToolRegistry(tool_config=settings.tool, client=tool_client)
        loop = Loop(router, log, settings, registry=registry)
        veneer = Veneer(loop, log, settings)
        await veneer.serve(settings.veneer.host, settings.veneer.port)
    finally:
        for client in clients.values():
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
