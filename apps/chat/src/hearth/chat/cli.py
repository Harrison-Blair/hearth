"""Console line REPL for the hearth chat client."""

from __future__ import annotations

import asyncio
import sys

from websockets.exceptions import ConnectionClosed, InvalidURI

from .client import ChatClient, TurnResult
from .config import ChatConfig, ChatConfigError, load_config


def _print_delta(text: str) -> None:
    print(text, end="", flush=True)


async def _repl(config: ChatConfig) -> None:
    async with ChatClient(config.backend_url, config.device_id, config.token) as client:
        while True:
            try:
                line = await asyncio.to_thread(input, "> ")
            except EOFError:
                break
            if not line.strip():
                continue
            try:
                result = await client.ask(line, on_delta=_print_delta)
            except ConnectionClosed as exc:
                received = exc.rcvd
                code = "unknown" if received is None else received.code
                print(f"\nhearth-chat: connection closed ({code})", file=sys.stderr)
                break
            print()
            _report(result)


def _report(result: TurnResult) -> None:
    if result.error_code is not None:
        print(f"error [{result.error_code}]: {result.error_message}", file=sys.stderr)


def main() -> int:
    try:
        config = load_config()
    except ChatConfigError as exc:
        print(f"hearth-chat: {exc}", file=sys.stderr)
        return 1

    try:
        asyncio.run(_repl(config))
    except KeyboardInterrupt:
        pass
    except (OSError, ConnectionClosed, InvalidURI) as exc:
        print(f"hearth-chat: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
