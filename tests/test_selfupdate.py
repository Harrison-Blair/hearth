"""restart_in_place(): re-execs the source-mode target via os.execv."""

import sys

from assistant.core import selfupdate


async def test_restart_in_place_reexecs_source_target(monkeypatch):
    calls = []
    monkeypatch.setattr(selfupdate.os, "execv", lambda *a: calls.append(a))

    selfupdate.restart_in_place()

    assert calls == [(sys.executable, [sys.executable, "-m", "assistant.app"])]
