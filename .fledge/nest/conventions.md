---
generated: 2026-07-08T00:34:07Z
commit: 0a67e65dc3d33b2e9c911f1296eef515124fa678
agent: fledge-forager
fledge_version: unknown
---

# Conventions

Patterns to follow when adding or changing code, reconciled across all modules. Sourced from `CLAUDE.md`, `AGENTS.md`, and observed practice in the source.

## Layering & dependency rules
- **Interface-per-capability.** Every capability has a `base.py` ABC + concrete implementation(s) beside it. The pipeline and skills import only the ABC; concrete types are constructed exclusively in `assistant/app.py`. When swapping an implementation, code against the ABC — never let the pipeline reach for a concrete provider.
- **Composition root is app.py.** All wiring, construction-time choices (which skills, the default skill, which LLM provider), and provider health-checks live there.
- **Acyclic graph via core/.** Shared records (`core/events.py`) and config (`core/config.py`) live in `core/` so capability packages never import each other. Add new cross-stage records to `core/events.py`.
- **TUI dependency is one-directional.** `tui/` imports only `assistant.core.config.Config` and `assistant.wake.registry`; nothing under `assistant/` may import `tui`.
- **No cross-skill imports.** Each skill imports only its base, `core/events`, and its own provider/parser deps.

## Async
- All pipeline-facing capability methods are `async def`. Blocking model/native calls are wrapped in `asyncio.to_thread()` (STT, TTS, ddgs, google-auth token refresh). The wake `process()` is intentionally synchronous (called from the mic tap).
- Concurrency is `asyncio.gather` of the pipeline + scheduler + control (+ optional calendar watcher).

## Configuration
- **Config is the single source of truth.** Every device id, model path, threshold, endpoint, and tunable is a typed field on a `*Config` model — never hard-code a path, threshold, or vendor value in a component. Add a new tunable as a typed field mirrored in **both** `config.yaml` and `default-config.yaml`.
- **Components take primitives, not `Config`.** Constructors receive paths/thresholds/keys, not the whole `Config` object — keeps them unit-testable in isolation.
- **Env override & precedence.** `ASSISTANT_<SECTION>__<FIELD>` with `__` nesting; precedence is init args > env > `config.yaml` (`Config.settings_customise_sources`). Booleans are lowercase `true`/`false`; list/JSON values are `json.loads`-parsed (e.g. `ASSISTANT_WAKE__MODEL_PATHS='["a.onnx","b.onnx"]'`).

## Secrets
- **Secrets are never committed.** API keys (LLM bearer token, Tavily/Exa) and calendar credentials arrive via environment, not YAML. `config.yaml` ships blank key fields (`api_key: ''`, `tavily_api_key: ''`, `exa_api_key: ''`).
- **Per-provider secret precedent.** `WebSearchConfig.tavily_api_key`/`exa_api_key` (constructor params `TavilySearch(api_key=...)`, `ExaSearch(api_key=...)`) are the existing model for storing a per-provider secret on a config model and threading it into the provider. `LlmConfig.api_key` follows the same shape for the LLM gateway.
- **`.env` is TUI-mediated.** The daemon's pydantic-settings does not read `.env`; the monitor TUI (`tui/envfile.py` + `tui/supervisor.py`) merges `.env` into the daemon child's environment on (re)start. Env-override precedence into the child: process env < `.env` < the TUI's in-session config overrides.
- **Mask on output.** `app.py:_config_dump` masks `llm.api_key` and calendar ids to `***` in the boot trace; discovery omits the bearer header when the key is blank.

## Offline-first & degradation
- **Local is the guaranteed path; remote is an accelerator behind an interface with a local fallback.** `sync/` and `connectivity/` are deliberate seams reserving that boundary — do not delete them, or the stub base classes.
- **Health-check at boot, degrade with a warning.** Providers implement `health()`; a failed check logs a clear warning and the daemon continues rather than crashing (`app.py` LLM boot check, `MultiSearch.health()` = any-healthy).
- **Fail-forward in the speech path.** The verify loop fails open (`None` → approve). The revoicer returns plain text on timeout/error/digit-mutation and opens a circuit-breaker. Skills touching remote resources wrap in try/except and return `SkillResult(success=False)` with an apology rather than crashing.
- **Bare `except Exception` in the pipeline is intentional** (device disconnect, synth failure, skill crash) — logged, never fatal to the wake loop. Documented in `CLAUDE.md`/`AGENTS.md`.

## LLM provider conventions
- **Vendor-neutral gateway table.** New OpenAI-compatible gateways are added as a `GATEWAYS` entry (name → base_url + extra_headers), not new per-vendor code. Diagnostics (`_llm_unhealthy_warning`, boot endpoint log) are driven by `GATEWAYS[provider]`, not hard-coded vendor checks.
- **Pooled httpx client per provider instance** (a voice turn makes 2+ calls); omit the `Authorization` header entirely when the key is blank (httpx rejects a bare `Bearer `).
- **Retry classification.** Retry 429/5xx/transport/malformed-200 with exponential backoff + up to 25% jitter (0.5s → 2.0s cap); never retry 400/401/403 (config bugs).
- **Fallback is exception-based.** `FallbackLLMProvider` delegates to fallback only on exception; a valid-but-empty response is not a fallback trigger (the orchestrator handles empty).

## Persona & speech
- Persona applies only to spoken output. Never inject persona into tool-decision, verify-decision, or routing prompts (invariant enforced by `tests/test_speech_invariants.py`). `SkillResult.voiced=True` marks already-flavored replies to skip the revoicer; deterministic skill replies default `voiced=False` and are revoiced. Digit preservation is guarded in the revoicer.

## Storage
- SQLite with `WAL` + `synchronous=NORMAL`; synchronous single-statement methods on the event loop (sub-millisecond, no thread pool). UTC epoch-second timestamps. Schema migrations add columns to pre-existing tables on open (`ReminderStore._migrate`).

## Logging
- Console format `HH:MM:SS LEVEL-7 name: message` (the TUI log parser is keyed to this). Per-run directories `assistant-YYYYMMDD-HHMMSS/` with plain + JSONL handlers; turn/LLM events logged with `extra={"data": {...}}` for JSONL extraction; old runs pruned per family at boot.

## Packaging & extras
- Heavy/native deps are split into per-capability extras (`tts`, `wake`, `stt`, `vad`, `llm`, `nlu`, `scheduling`, `search`, `gcal`, `aec`; `tui` deliberately separate and not in `all`). `[vad]` pins `setuptools<81` (webrtcvad needs `pkg_resources`). Tests run on `.[dev]` alone.

## Formatting & tests
- Ruff line-length 100 (`pyproject.toml`). pytest `asyncio_mode = auto` — `async def test_...` needs no marker. Native deps are stubbed in tests; no real Ollama/TTS/mic/GPU needed.

## The Pi-5 TUI grid
- Every TUI screen is designed for ~40×30 cells, portrait, touch-only: one focused screen per job, full-width height-3 controls, steppers/pickers instead of text inputs, no horizontal overflow at 40 columns (`tests/test_tui_screens.py` enforces `region.right <= 40` and `max_scroll_x == 0`).
