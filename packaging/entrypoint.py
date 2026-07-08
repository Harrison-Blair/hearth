"""PyInstaller entry script for the frozen `assistant` binary.

In a frozen onefile build, PyInstaller extracts the bundle to ``sys._MEIPASS``.
The app resolves ``config.yaml`` and the relative ``models/wake|piper/...`` paths
against the current working directory (see ``assistant/core/config.py``), so we
``chdir`` into the bundle to reproduce the dev invariant (cwd == repo root). Only
the *writable* sinks (the SQLite DB and the HuggingFace cache) are redirected to a
persistent XDG dir via the ``ASSISTANT_*`` / ``HF_HOME`` overrides the config
already honors — the bundle itself is read-only and recreated on every launch.

Running from source (not frozen) leaves cwd and env untouched.
"""

from __future__ import annotations

import os
import sys


def _prepare_frozen_env() -> None:
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return  # running from source: behave exactly like `python -m assistant.app`

    # Mirror the dev invariant (cwd == repo root): the bundled config.yaml and its
    # relative model paths now resolve under the extracted bundle.
    os.chdir(meipass)

    data_home = os.environ.get("ASSISTANT_HOME") or os.path.join(
        os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
        "assistant",
    )
    os.makedirs(data_home, exist_ok=True)

    # Absolute writable paths beat the cwd-relative defaults from config.yaml.
    os.environ.setdefault(
        "ASSISTANT_STORAGE__DB_PATH", os.path.join(data_home, "assistant.db")
    )
    os.environ.setdefault("HF_HOME", os.path.join(data_home, "hf-cache"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def main() -> int:
    _prepare_frozen_env()
    argv = sys.argv[1:]

    if argv and argv[0] in ("--version", "-V"):
        import assistant

        print(f"assistant {assistant.__version__}")
        return 0

    if argv and argv[0] in ("doctor", "bootstrap", "--bootstrap"):
        from assistant.bootstrap import run as bootstrap_run

        return bootstrap_run(argv[1:])

    if argv and argv[0] == "tui":
        from tui.app import main as tui_main

        tui_main()
        return 0

    # Default — and any TUI-supervisor argv like ["-m", "assistant.app"] — runs
    # the daemon. The daemon ignores argv, so unrecognized flags are harmless.
    from assistant.app import main as daemon_main

    daemon_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
