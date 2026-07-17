"""hearth CLI entry point."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from hearth import __version__

logger = logging.getLogger(__name__)


def _build_llm_clients(settings):
    """One httpx client per LLM backend, each carrying the configured
    `llm.timeout`. Without an explicit timeout httpx defaults to 5s, so any
    generation over 5s trips a read timeout and surfaces as "backend
    unreachable" -- keep this wired to `settings.llm.timeout`."""
    import httpx

    return {
        name: httpx.AsyncClient(base_url=backend.base_url, timeout=settings.llm.timeout)
        for name, backend in settings.llm.backends.items()
    }


async def _run_daemon() -> int:
    import httpx
    from dotenv import load_dotenv

    from hearth.brain.router import Router
    from hearth.config import Settings
    from hearth.logging_setup import setup_logging
    from hearth.loop import Loop
    from hearth.memory.log import EventLog
    from hearth.tools.consult import BrainConsult
    from hearth.tools.registry import ToolRegistry
    from hearth.transcript import Transcript
    from hearth.gateway.server import Gateway

    # Load .env into os.environ so backends' resolve_api_key() (a plain
    # os.environ lookup by api_key_env name) can see the secrets. Per FTHR-015,
    # API keys live only in .env; pydantic-settings reads .env into the Settings
    # model but does not export it to the process environment.
    load_dotenv()

    settings = Settings()
    setup_logging(settings.logging)
    logger.info("hearth daemon starting", extra={"category": "server"})
    transcript = (
        Transcript(settings.logging.transcript_dir)
        if settings.logging.transcript_enabled
        else None
    )
    # One client per LLM backend: each backend has its own base_url, so a
    # single shared client would send every request to whichever backend
    # built it, regardless of which tier the router selects.
    clients = _build_llm_clients(settings)
    # Separate client for tool calls (e.g. Wikipedia): the LLM clients'
    # base_urls point at chat backends, not a tool's own endpoint.
    tool_client = httpx.AsyncClient()
    try:
        router = Router(settings.llm, clients=clients)
        log = EventLog(settings.storage.db_path)
        # Wikipedia now lives brain-side only: the top-level orchestrator
        # never holds this registry directly, it reaches it exclusively
        # through consult_brain's nested ReAct loop.
        wiki_registry = ToolRegistry(tool_config=settings.tool, client=tool_client)
        consult = BrainConsult(router, wiki_registry, log, settings, transcript=transcript)
        loop = Loop(router, log, settings, consult=consult, transcript=transcript)
        gateway = Gateway(loop, log, settings)
        logger.info(
            "gateway serving host=%s port=%s",
            settings.gateway.host,
            settings.gateway.port,
            extra={"category": "server"},
        )
        await gateway.serve(settings.gateway.host, settings.gateway.port)
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
