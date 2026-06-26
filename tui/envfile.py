"""Read/write and reconcile the daemon's ``.env`` file (edited in the TUI).

The supervisor merges ``.env`` into the child's environment at (re)start, so
editing it here changes the daemon's ``ASSISTANT_*`` settings without touching
config.yaml. ``env.example`` is the canonical key set the two sync helpers
reconcile against. Pure functions only — no Textual, dependency-free parsing.
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


def write(path: str, text: str) -> None:
    if text and not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def add_missing(current_text: str, example_text: str) -> str:
    """Append example keys absent from the current text, with their example values."""
    current = parse(current_text)
    additions = [f"{k}={v}" for k, v in parse(example_text).items() if k not in current]
    if not additions:
        return current_text
    base = current_text.rstrip("\n")
    lines = ([base] if base else []) + additions
    return "\n".join(lines) + "\n"


def remove_extra(current_text: str, example_text: str) -> str:
    """Drop KEY=VALUE lines whose key isn't in env.example (comments/blanks kept)."""
    allowed = set(parse(example_text))
    kept: list[str] = []
    for line in current_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            kept.append(line)
            continue
        if stripped.partition("=")[0].strip() in allowed:
            kept.append(line)
    text = "\n".join(kept)
    return text + "\n" if text.strip() else ""
