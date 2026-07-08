---
generated: 2026-07-08T00:34:07Z
commit: 0a67e65dc3d33b2e9c911f1296eef515124fa678
agent: fledge-forager
fledge_version: unknown
---

# Entry Points & Public Interfaces

How execution enters the system, how to run/build it, and the public seams other code depends on. The daemon and TUI are the two runnable processes; `app.py` is the daemon's composition root.

## Running & building

- **Daemon:** `python -m assistant.app` (`assistant/app.py:main`) — greets, then runs the wake→record→transcribe→route→skill→speak loop; Ctrl-C to stop. Installed console script `assistant` → `assistant.app:main` (`pyproject.toml`).
- **Provisioning:** `assistant doctor` (`assistant/bootstrap.py:run`) — idempotent; ensures Ollama installed/serving, models pulled, STT model pre-downloaded; exit 0 success / 1 warnings.
- **Monitor TUI:** `python -m tui` (`tui/__main__.py` → `tui.app.main` → `AssistantTUI().run()`). Convenience wrapper `./start.sh` activates the venv, reaps an orphaned daemon, execs the TUI.
- **Setup:** `./install.sh [options]` — platform detection (pacman/apt), PortAudio, venv, `pip install -e ".[extras]"`, wake/Piper downloads, optional systemd unit. Flags: `--minimal`, `--systemd`, `--prewarm-stt`, `--extras`, `--ollama-model`, `--piper-voice`, `--python`, `--no-*`.
- **Dev:** `source .venv/bin/activate`; `pip install -e ".[dev]"`; `pytest`; `ruff check assistant tests` (line-length 100).
- **Release:** `make release` → `bash packaging/build.sh` builds `dist/assistant-<arch>` via PyInstaller (native per-arch; no cross-compile). `.github/workflows/release.yml` builds x86_64 + aarch64 on `v*` tag push.
- **Smoke tests:** `python verify_calendar.py` (Google Calendar CRUD round-trip), `python verify_wikipedia.py` (Wikipedia search).
- **Frozen binary subcommands** (`packaging/entrypoint.py`): `--version`, `doctor`, `bootstrap`, `tui`, or default daemon.

## Config entry

`assistant/core/config.py:Config` (pydantic `BaseSettings`). `SettingsConfigDict(yaml_file="config.yaml", env_prefix="ASSISTANT_", env_nested_delimiter="__", extra="ignore")`. `settings_customise_sources` fixes precedence to **init args > env vars > `config.yaml`** (returns `(init_settings, env_settings, YamlConfigSettingsSource)` — dotenv is not wired into the daemon). Every value is overridable via `ASSISTANT_<SECTION>__<FIELD>` (e.g. `ASSISTANT_LLM__MODEL`, `ASSISTANT_LLM__API_KEY`).

## LLM building (app.py — post-PLM-004)

`assistant/app.py` resolves `LlmConfig` into a provider graph:

- `_build_llm(cfg)` — builds the primary via `_build_one_llm(cfg, cfg.provider, cfg.model)`; if `cfg.fallback` is set and differs, wraps `FallbackLLMProvider(primary, fallback)` where the fallback model is `cfg.fallback_model or cfg.model`.
- `_build_one_llm(cfg, provider, model)` — if `provider in GATEWAYS`: warns when `cfg.api_key` is empty, then constructs `OpenAICompatibleProvider(model, api_key=cfg.api_key, base_url=_gateway_base_url(cfg, provider), timeout, health_timeout, max_retries, extra_headers=GATEWAYS[provider]["extra_headers"])`. Otherwise constructs `OllamaProvider(model, cfg.host, cfg.timeout, cfg.health_timeout, cfg.num_ctx, cfg.think)`; an unknown provider name logs a warning and defaults to Ollama.
- `_gateway_base_url(cfg, provider=None)` — returns `None` for non-gateway providers (Ollama); else `cfg.base_url or GATEWAYS[provider]["base_url"]` (explicit `base_url` overrides the table default).
- `_llm_unhealthy_warning(cfg)` — vendor-neutral boot warning; for a gateway provider it names the provider, resolved `base_url`, model, and points at `ASSISTANT_LLM__API_KEY`; for Ollama it points at `ollama serve`/`ollama pull`.
- Boot: `llm = _build_llm(config.llm)`; `if not await llm.health(): log.warning(_llm_unhealthy_warning(config.llm))` — the daemon continues (graceful degradation). `_config_dump` masks `llm.api_key` and calendar ids to `***` in the boot trace.

## LLMProvider interface (`assistant/llm/base.py`)

Contract implemented by `OllamaProvider`, `OpenAICompatibleProvider`, `FallbackLLMProvider`, and the test `ReplayProvider`:

- `async complete(prompt, *, system=None, json=False, label="") -> str`
- `async chat(messages, *, system=None, label="") -> str`
- `async chat_tools(messages, *, system=None, tools=None, label="") -> ChatResponse` (`ChatResponse.content`, `ChatResponse.tool_calls: list[ToolCall]`)
- `async health() -> bool` (Ollama: model present in `/api/tags`; gateway: `GET {base_url}/models` succeeds)
- `async aclose() -> None`

`OpenAICompatibleProvider` omits the `Authorization` header when `api_key` is blank (httpx rejects a bare `Bearer `), merges `extra_headers`, and retries transient failures (429/5xx/transport/malformed-200) with jittered backoff while never retrying 400/401/403.

## Orchestrator (`assistant/core/orchestrator.py`)

`async Orchestrator.handle(text, history, *, spoken, on_say=None) -> (SkillResult | None, Skill | None)` — the routing entry. Exposes `SkillRegistry.tool_schemas()` to the LLM, dispatches one tool call (populating `Intent.slots`) or takes the direct-answer path, applies the optional verify loop, and degrades to `GeneralSkill` on failure/timeout/unknown-tool. (The eval harness scores `Orchestrator._decide` directly.)

## Skill interface (`assistant/skills/base.py`)

- `Skill`: `name`, `intents`, `tool_specs`, `tools()` (OpenAI function schemas; `GeneralSkill` returns `[]`), `async handle(cmd, intent) -> SkillResult`, optional `async handle_reply(cmd) -> SkillResult` (for `expects_reply=True`).
- `SkillRegistry`: `register(skill, *, default=False)`, `get(intent_type) -> Skill | None`, `tool_schemas()` (all non-default skills), `intents` property.

## Capability provider interfaces

- `SearchProvider.search(query, *, count) -> list[SearchResult]`, `health()`, `aclose()` (`assistant/search/base.py`); `MultiSearch(providers, *, max_results)` fan-out.
- `WeatherProvider.geocode(place) -> Place | None`, `forecast(lat, lon, *, name) -> Forecast` (`assistant/weather/base.py`).
- `CalendarProvider.list_events/create_event/update_event/delete_event/health/aclose` (`assistant/calendar/base.py`).
- `WakeDetector.process(frame) -> WakeEvent | None`, `reset()`; `SpeechToText.transcribe(audio) -> str`; `TextToSpeech.synthesize(text, length_scale=None) -> bytes`; `AudioIn.stream()`/`AudioOut.play(bytes)`.

## TUI control channel (`assistant/core/control.py`)

`ControlChannel.dispatch(line)` parses one stdin command from the TUI: `TEXT <utterance>` → `pipeline.submit_text`, `LISTEN` → `request_listen`, `CANCEL`/`STOP`, `SAY [<rate>|]<text>`, `RESUME`, `SET audio.output_volume <float>` → `out.set_volume`. The daemon emits `@@STATE {json}` lines on stdout (`assistant/core/state.py:StateEmitter`) that the TUI parses for the Now screen.
