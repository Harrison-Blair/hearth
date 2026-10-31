"""Keep every test independent of the developer's environment and config."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith("HEARTH_"):
            monkeypatch.delenv(key)
