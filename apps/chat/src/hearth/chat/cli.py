"""Console line REPL for the hearth chat client."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import threading

from websockets.exceptions import ConnectionClosed, InvalidURI

from .client import ChatClient, TurnResult
from .config import ChatConfig, ChatConfigError, load_config


def _print_delta(text: str) -> None:
    print(text, end="", flush=True)


def _deliver_line(
    loop: asyncio.AbstractEventLoop,
    lines: asyncio.Queue[str | None],
    line: str | None,
) -> None:
    with contextlib.suppress(RuntimeError):
        loop.call_soon_threadsafe(lines.put_nowait, line)


def _start_stdin_reader(loop: asyncio.AbstractEventLoop) -> asyncio.Queue[str | None]:
    """Read stdin on a daemon thread so Ctrl-C never waits for a blocked read."""
    lines: asyncio.Queue[str | None] = asyncio.Queue()

    def read_lines() -> None:
        while True:
            try:
                line = sys.stdin.readline()
            except OSError, ValueError:
                line = ""
            if line == "":
                _deliver_line(loop, lines, None)
                return
            _deliver_line(loop, lines, line.removesuffix("\n"))

    threading.Thread(target=read_lines, name="hearth-chat-stdin", daemon=True).start()
    return lines


async def _repl(config: ChatConfig) -> None:
    async with ChatClient(config.backend_url, config.device_id, config.token) as client:
        lines = _start_stdin_reader(asyncio.get_running_loop())
        while True:
            print("> ", end="", flush=True)
            line = await lines.get()
            if line is None:
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
