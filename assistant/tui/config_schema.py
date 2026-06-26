"""Declarative schema of editable config fields — the extensibility seam.

Adding a new editable setting = appending one ``Field`` to ``FIELDS``; the Config
tab builds itself by iterating this list, so there is no UI to touch.

Each field maps a dotted config key (e.g. ``("llm", "model")``) to its
``ASSISTANT_*`` env override (``ASSISTANT_LLM__MODEL``), a label, a widget kind,
and — for selects — an options provider from ``discovery``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from assistant.tui import discovery


@dataclass(frozen=True)
class Field:
    key: tuple[str, ...]
    label: str
    kind: str  # "select" | "text" | "number"
    # None for free text/number; for selects, a provider with signature
    # (host=..., **_) -> list[str] | Awaitable[list[str]] (see discovery).
    options: Callable | None = None

    @property
    def env(self) -> str:
        return env_name(self.key)


def env_name(key: tuple[str, ...]) -> str:
    """Dotted config key -> ASSISTANT_* env var: ("llm","model") -> ASSISTANT_LLM__MODEL."""
    return "ASSISTANT_" + "__".join(part.upper() for part in key)


def overrides_for(changes: dict[tuple[str, ...], str]) -> dict[str, str]:
    """Map a {key: value} dict of changed fields to {ENV_VAR: value}."""
    return {env_name(key): value for key, value in changes.items()}


def changed_fields(
    form: dict[tuple[str, ...], str], current: dict[tuple[str, ...], str]
) -> dict[tuple[str, ...], str]:
    """Keep only the form values that differ from the current effective value."""
    return {
        key: value
        for key, value in form.items()
        if str(value) != str(current.get(key, ""))
    }


FIELDS: list[Field] = [
    Field(("wake", "model_path"), "Wake model", "select", discovery.wake_models),
    Field(("wake", "phrase"), "Wake phrase", "text"),
    Field(("wake", "threshold"), "Wake threshold", "number"),
    Field(("llm", "model"), "LLM model", "select", discovery.ollama_model_options),
    Field(("logging", "level"), "Log level", "select", discovery.log_levels),
    Field(("stt", "model"), "STT model", "text"),
    Field(("audio", "output_volume"), "Output volume", "number"),
    Field(("recorder", "silence_ms"), "Silence (ms)", "number"),
    Field(("recorder", "aggressiveness"), "VAD aggressiveness", "number"),
]
