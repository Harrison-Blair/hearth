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

from tui import discovery


@dataclass(frozen=True)
class Field:
    key: tuple[str, ...]
    label: str
    kind: str  # "select" | "multiselect" | "text" | "number" | "toggle"
    # None for free text/number; for selects, a provider with signature
    # (host=..., **_) -> list[str] | Awaitable[list[str]] (see discovery).
    options: Callable | None = None
    # Stepper bounds for "number" fields (ignored for other kinds).
    lo: float = 0.0
    hi: float = 1.0
    step: float = 1.0

    @property
    def env(self) -> str:
        return env_name(self.key)


def coerce(field: Field, raw: object) -> object:
    """Parse a widget's value into the type config.yaml expects."""
    if field.kind == "multiselect":
        return list(raw)  # a SelectionList's selected paths, stored as a YAML list
    if field.kind == "number":
        try:
            return int(str(raw))
        except ValueError:
            return float(str(raw))
    if field.kind == "toggle":
        # raw is a stringified bool ("True"/"False") — parse it, since bool("False")
        # is truthy. Stored as a real YAML bool.
        return str(raw).strip().lower() in ("true", "1", "yes", "on")
    return raw


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
    Field(("wake", "model_paths"), "Wake models", "multiselect", discovery.wake_model_choices),
    Field(("wake", "threshold"), "Wake threshold", "number", lo=0.0, hi=1.0, step=0.05),
    # LLM identity (provider-aware): each pick persists to config.yaml + restarts,
    # dropping any ASSISTANT_LLM__* env override that would shadow the new default.
    Field(("llm", "provider"), "LLM provider", "select", discovery.llm_provider_options),
    Field(("llm", "model"), "LLM model", "select", discovery.llm_model_options),
    Field(("llm", "fallback"), "Fallback provider", "select", discovery.llm_fallback_options),
    Field(("llm", "fallback_model"), "Fallback model", "select", discovery.llm_fallback_model_options),
    Field(("logging", "level"), "Log level", "select", discovery.log_levels),
    Field(("stt", "model"), "STT model", "select", discovery.stt_model_options),
    Field(("tts", "model_path"), "Voice", "select", discovery.voice_options),
    Field(("tts", "length_scale"), "Speaking rate", "number", lo=0.5, hi=2.0, step=0.1),
    Field(("tts", "ack_phrases"), "Ack sounds", "multiselect", discovery.ack_choices),
    Field(("audio", "output_volume"), "Output volume", "number", lo=0.0, hi=1.0, step=0.05),
    Field(("recorder", "silence_ms"), "Silence (ms)", "number", lo=100, hi=3000, step=100),
    Field(("recorder", "aggressiveness"), "VAD aggressiveness", "number", lo=0, hi=3, step=1),
    Field(("recorder", "max_ms"), "Max utterance (ms)", "number", lo=5000, hi=60000, step=1000),
    Field(("agent", "turn_timeout_s"), "Turn budget (s)", "number", lo=10, hi=120, step=5),
    Field(("tts", "ack_delay_s"), "Ack delay (s)", "number", lo=0.0, hi=1.0, step=0.05),
    Field(("conversation", "decision_enabled"), "Follow-up chime", "toggle"),
    # Verify loop (the five surfaced knobs; pre/post/max_tool_rounds/max_retries
    # stay config.yaml-only — they're advanced/debugging).
    Field(("verify", "enabled"), "Verify master", "toggle"),
    Field(("verify", "spoken_feedback"), "Verify feedback", "toggle"),
    Field(("verify", "max_verify_rounds"), "Verify rounds", "number", lo=0, hi=4, step=1),
]
