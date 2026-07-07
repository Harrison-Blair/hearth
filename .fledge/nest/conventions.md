---
generated: 2026-07-07T07:06:00Z
commit: 02f839d7a116780b02510c2d5b339c23c64a51f5
agent: fledge-forager
fledge_version: unknown
---

# Conventions

Coding and design conventions observed across the repository, reconciled from every module's report. These are the rules a change should follow to match the existing codebase.

## Async everywhere pipeline-facing
Every capability method that the pipeline or a skill calls is `async def` — STT, TTS, LLM, search, calendar, weather, skill `handle()`. CPU-bound or blocking work is wrapped in `asyncio.to_thread()` (Whisper, Piper, Ollama HTTP, the synchronous `ddgs` client) so the event loop is never blocked (`assistant/stt/faster_whisper_stt.py`, `assistant/search/ddgs_provider.py`). Tests match: `pytest` runs with `asyncio_mode = auto`, so `async def test_...` needs no marker.

## Interface-per-capability, ABC in `base.py`
Each capability package holds an ABC in `base.py` and concrete implementation(s) beside it. The pipeline and skills type against the ABC and never import a concrete provider. When adding a capability or swapping an implementation, code against `base.py`. New search backends implement `assistant/search/base.py:SearchProvider` (`async search(query, *, count)`, `async health()`, `async aclose()`) — do not let a caller reach for `DdgsSearch`/`WikipediaSearch` directly.

## `app.py` is the sole composition root
All concrete construction and dependency injection happens in `assistant/app.py`. Components never build their collaborators; they receive them. Construction-time choices (which skills, default skill, provider fallback order, `MultiSearch` provider list) live in `app.py`, isolated in `_build_*` factories. Nothing else instantiates a provider.

## Components take primitives, not the whole `Config`
Constructors accept scalar config values (paths, thresholds, host URLs, timeouts, counts), never the global `Config` object. This keeps every component unit-testable in isolation (`assistant/core/config.py` conventions; confirmed by all provider tests instantiating with bare kwargs).

## Config is the single source of truth
Every device id, model path, and threshold is a typed field on a `*Config` model in `assistant/core/config.py`, mirrored in both `config.yaml` and `default-config.yaml`. Values are overridable by `ASSISTANT_*` env vars using `__` for nesting; precedence is init args > env > `config.yaml`. Never hard-code a path/threshold/device in a component — add a tunable to the relevant `*Config` and mirror it in both YAML files.

## Shared cross-stage records live in `core/events.py`
`WakeEvent`, `Command`, `Intent`, `SkillResult`, `Turn`, `ToolCall` live in `assistant/core/events.py` so capability packages exchange them without importing each other, keeping the dependency graph acyclic. Provider-local types (e.g. `SearchResult` in `search/base.py`, `Forecast` in `weather/base.py`) stay in their own package — they are not cross-stage pipeline records.

## Graceful degradation over crashing
Offline-first means never crashing the loop. Patterns seen throughout:
- Providers expose `health() -> bool`, checked at boot in `app.py`, which logs a warning and continues rather than aborting.
- Skills wrap provider/LLM calls in `try/except` and return `SkillResult(..., success=False)` with an apologetic spoken line instead of raising.
- LLM/JSON/timeout failures in the orchestrator degrade to the `default=True` `GeneralSkill`.
- `MultiSearch` logs and skips a failing provider; it only raises if all fail.
- `verify()` fails open — a malformed verdict is treated as approve.
- Pipeline uses intentional bare `except Exception` to survive transient device/synth/skill errors (documented in `AGENTS.md` — do not "fix" these).

## Remote behind an interface with a local fallback
Cloud services (OpenCode Zen LLM, Google Calendar, DuckDuckGo) are optional accelerators behind an ABC with a guaranteed-local path (`OllamaProvider`, `WikipediaSearch`, no-calendar). `FallbackLLMProvider` retries on the fallback only on an exception from the primary — a valid-but-empty primary response does not fall back. Transient HTTP failures (429/5xx, truncated 200) retry with exponential backoff + jitter; auth/4xx never retry (`OpenCodeZenProvider`).

## Skills are plug-ins; routing never names them
A skill is a `Skill` subclass declaring `name` + `intents` + static `tool_specs`, registered via `SkillRegistry.register(...)`. The tool name IS the intent type — the orchestrator dispatches by name with no mapping layer. Slots come from tool arguments, with `intent.slots.get("x") or cmd.text` as the fallback. Skills that should answer directly (e.g. `GeneralSkill`) override `tools()` to return `[]`.

## Prompt-injection defense for untrusted web content
Any web content fed to the LLM is fenced and neutralized. `WebSearchSkill._neutralize()` strips internal fence markers, regex-filters injection patterns ("ignore previous instructions", role prefixes, "new instructions:", exfil URLs) to `[filtered]`, wraps each result in `<<<…>>>`, and the assess system prompt forbids following instructions inside fences. Model-emitted `new_query`/`remark` are length-capped so injected text can't ride out at scale. A new search provider's snippets flow through the same path.

## Persona is scoped to spoken outputs only
The Calcifer persona suffix (`core/persona.py:with_persona`) is appended only to terminal spoken replies (`chat`/`complete`), never to tool-decision (`chat_tools`) or verification-routing fields. In the verify loop, persona rides only `feedback`/`rewritten_speech`; `decision`/`rewritten_tool`/`rewritten_arguments` stay persona-free.

## Logging and diagnostics
Console logs use a fixed `HH:MM:SS LEVEL logger: message` format the TUI parses. Structured diagnostics go to JSONL via `JsonlFormatter` with a reserved `extra={"data": {...}}` dict; LLM providers log full payloads + `latency_ms`. Pipeline state is emitted to stdout as `@@STATE {json}\n` markers for the TUI. Console lines are clipped (200–2000 chars); JSONL keeps full payloads.

## TUI conventions (40×30 portrait, touch-first)
- Dependency is one-directional: `tui` imports only `assistant.core.config.Config` and `assistant.wake.registry`; nothing in `assistant/` imports `tui`.
- Thin screens, thick app: all state lives on `AssistantTUI`; screens are views that call back via `self.app._method()`.
- One screen per job; full-width height-3 tappable controls; steppers/pickers/switches instead of text inputs (no free-text fields); no horizontal overflow at 40 columns (enforced by `tests/test_tui_screens.py:test_no_screen_overflows_40_columns`).
- Config editing is declarative via `config_schema.py:FIELDS`; Save writes `config.yaml`, Apply sets env overrides + restarts, Reset re-seeds from `default-config.yaml`.

## Formatting and tooling
- Python ≥3.11 (repo pins 3.12.13); `ruff` with line-length 100 (`ruff check assistant tests`).
- Native/heavy deps are split into per-capability optional extras; tests run on `[dev]` alone with everything native stubbed.
- Injectable clocks: skills/schedulers take an optional `now: Callable[[], datetime]` (default `local_now()`/`datetime.now`) for deterministic tests.
- Timestamps: UTC epoch seconds in SQLite; tz-aware `datetime` elsewhere.
