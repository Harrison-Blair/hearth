"""Supervise the assistant daemon as a child process.

The TUI never imports the daemon's native deps (sounddevice/whisper/livekit-wakeword/
piper); only the child does. Config is applied as ``ASSISTANT_*`` env overrides on
the child's environment, so config.yaml is never rewritten. Commands (typed
utterances, live volume) are written to the child's stdin (see core/control.py).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import sys
from collections.abc import AsyncIterator
from urllib.parse import urlparse

from tui import envfile

log = logging.getLogger(__name__)

# Frozen: sys.executable is the onefile binary (which defaults to the daemon).
# From source: spawn the daemon module under the interpreter.
DAEMON_ARGV = (
    [sys.executable]
    if getattr(sys, "frozen", False)
    else [sys.executable, "-m", "assistant.app"]
)
ENV_FILE = ".env"
_PID_RE = re.compile(r"pid=(\d+)")


async def _ollama_pid(port: int) -> int | None:
    """PID of the ``ollama`` process listening on localhost:{port}, or None.

    Uses iproute2's ``ss``; if it's missing or matches nothing, returns None.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ss", "-ltnpH", f"sport = :{port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except FileNotFoundError:
        return None
    for line in out.decode(errors="replace").splitlines():
        if '"ollama"' in line:
            m = _PID_RE.search(line)
            if m:
                return int(m.group(1))
    return None


async def free_ollama_port(host: str, timeout: float = 5.0) -> int | None:
    """Terminate an externally-started ``ollama serve`` holding {host}'s port.

    The supervisor can only SIGTERM a child it spawned; a server started elsewhere
    (a bare ``ollama serve`` in another shell) must be stopped by pid so a fresh
    child can bind. SIGTERM first, then SIGKILL if it lingers. Returns the pid we
    stopped, or None if nothing ours was listening (no port owner, or not killable).
    """
    port = urlparse(host).port or 11434
    pid = await _ollama_pid(port)
    if pid is None:
        return None
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return None  # already gone, or owned by another user (e.g. root/systemd)
    deadline = int(timeout * 10)
    for _ in range(deadline):
        if await _ollama_pid(port) is None:
            return pid
        await asyncio.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return pid


class DaemonSupervisor:
    def __init__(self, argv: list[str] | None = None, env_file: str = ENV_FILE) -> None:
        self._argv = argv or DAEMON_ARGV
        self._env_file = env_file
        self._proc: asyncio.subprocess.Process | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def returncode(self) -> int | None:
        return self._proc.returncode if self._proc is not None else None

    async def start(self, overrides: dict[str, str] | None = None) -> None:
        if self.running:
            return
        # Precedence for the child: process env < .env file < session UI overrides.
        env = os.environ.copy()
        env.update(envfile.parse(envfile.read(self._env_file)))
        env.update(overrides or {})
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        log.debug("daemon started pid=%s", self._proc.pid)

    async def stop(self, timeout: float = 5.0) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()  # SIGTERM
        try:
            await asyncio.wait_for(proc.wait(), timeout)
        except asyncio.TimeoutError:
            log.warning("daemon ignored SIGTERM; killing")
            proc.kill()  # SIGKILL
            await proc.wait()

    async def restart(self, overrides: dict[str, str] | None = None) -> None:
        await self.stop()
        await self.start(overrides)

    async def send(self, line: str) -> None:
        """Write one command line to the child's stdin (no-op if not running)."""
        proc = self._proc
        if proc is None or proc.stdin is None or proc.returncode is not None:
            return
        proc.stdin.write((line + "\n").encode())
        await proc.stdin.drain()

    async def lines(self) -> AsyncIterator[str]:
        """Yield decoded stdout lines for the current child until it exits."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        while True:
            raw = await proc.stdout.readline()
            if not raw:  # EOF: child exited
                break
            yield raw.decode(errors="replace").rstrip("\n")
