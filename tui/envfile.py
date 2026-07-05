"""Read and parse the daemon's ``.env`` file.

The supervisor merges ``.env`` into the child's environment at (re)start, so
its ``ASSISTANT_*`` settings apply without touching config.yaml. Pure functions
only — no Textual, dependency-free parsing.
"""

from __future__ import annotations


def parse(text: str) -> dict[str, str]:
    """Ordered {KEY: VALUE} from .env text; ignores blank lines and ``#`` comments."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value.strip()
    return out


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""
