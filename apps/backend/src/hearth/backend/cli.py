"""Command line entry point for the hearth backend."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from collections.abc import Sequence

from .config import (
    DEFAULT_DEVICES_PATH,
    BackendConfig,
    ConfigError,
    load_config,
)
from .devices import DeviceError, DeviceStore
from .llm import build_llm
from .server import Backend


def _serve(config: BackendConfig) -> int:
    devices = DeviceStore(DEFAULT_DEVICES_PATH)
    llm = build_llm(config, "fast")
    backend = Backend(config, devices, llm)

    async def run() -> None:
        try:
            async with backend.serve():
                print(
                    f"hearth-backend listening on ws://{config.server.host}:{config.server.port}",
                    flush=True,
                )
                await asyncio.Event().wait()
        finally:
            await llm.aclose()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())
    return 0


def _add_device(device_id: str) -> int:
    token = DeviceStore(DEFAULT_DEVICES_PATH).add(device_id)
    print(token)
    return 0


def _remove_device(device_id: str) -> int:
    DeviceStore(DEFAULT_DEVICES_PATH).remove(device_id)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hearth-backend")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the WebSocket server")
    add = commands.add_parser("add-device", help="register a device and print its token once")
    add.add_argument("device_id", metavar="id")
    remove = commands.add_parser("remove-device", help="remove a registered device")
    remove.add_argument("device_id", metavar="id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            return _serve(load_config())
        if args.command == "add-device":
            return _add_device(args.device_id)
        return _remove_device(args.device_id)
    except (ConfigError, DeviceError, OSError) as exc:
        print(f"hearth-backend: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
