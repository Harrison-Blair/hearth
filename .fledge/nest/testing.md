---
generated: 2026-07-08T00:34:07Z
commit: 0a67e65dc3d33b2e9c911f1296eef515124fa678
agent: fledge-forager
fledge_version: unknown
---

# Testing

87 files under `tests/` (~1300+ test functions). pytest with `asyncio_mode = auto` (`pyproject.toml`) — `async def test_...` runs without a marker. The suite is hermetic: no real Ollama, Piper, faster-whisper, livekit, microphone, GPU, or network. `pip install -e ".[dev]"` is enough. Lint: `ruff check assistant tests` (line-length 100).

## Running
```
pytest                                            # all
pytest tests/test_pipeline.py                     # one file
pytest tests/test_openai_compatible_provider.py   # LLM gateway
pytest tests/test_config.py -k env                # one pattern
ASSISTANT_EVAL=1 pytest tests/eval/               # opt-in eval (needs live Ollama)
```

## How isolation is achieved
- **HTTP:** `httpx.MockTransport(handler)` + `monkeypatch` of the `AsyncClient` factory intercepts every provider request (Ollama, OpenAI-compatible gateways, Tavily, Exa, Wikipedia, Open-Meteo, Google Calendar). Handlers assert on `json.loads(request.content)` and return `httpx.Response`.
- **Native libs:** `sys.modules["speexdsp"] = None` (forces AEC passthrough), monkeypatched `PiperVoice.load`, injected `FakeWakeWordModel`, stubbed `sounddevice`. Model paths are passed but never loaded.
- **Storage:** `:memory:` SQLite for logic tests; `tmp_path` for persistence/reopen/migration tests.
- **Time & clocks:** constructor `now=lambda: dt` for Clock/Reminder/Timer/StandDown/scheduler/watcher; `FakeClock` for StandDown; monotonic-based timeout tests use small budgets.
- **LLM:** scripted/fake providers implementing the full `LLMProvider` interface — `ScriptedLLM`, `FakeLLM`, `StubLLM`, `TaggingRevoicer`, and the production `ReplayProvider` (`tests/eval/replay.py`).
- **Config:** `monkeypatch.setenv("ASSISTANT_*", ...)`; TUI tests use an autouse hermetic-config fixture seeding `Config` from model defaults so they don't read the developer's `config.yaml`.

## Coverage map (by area)

### Config & LLM path (tests-core — first-class for the LLM/secrets feature)
- `test_config.py` — `*Config` defaults, `ASSISTANT_*` env override, `config.yaml` composition, `WakeConfig.model_refs()` precedence, JSON/bool env parsing.
- `test_llm_dispatch.py` — `_build_one_llm` resolves provider name → concrete type via `GATEWAYS`; blank `base_url` uses table default, explicit overrides; unknown provider → `OllamaProvider`.
- `test_app_llm_diagnostics.py` — `_gateway_base_url` lookup + override; `_llm_unhealthy_warning` for openrouter/opencode-zen/ollama (no network).
- `test_openai_compatible_provider.py` — chat/complete/chat_tools OpenAI contract; blank `api_key` omits `Authorization`; `response_format` on `json=True`; tool-call parsing (string vs dict args); null content → "".
- `test_openai_compatible_provider_guards.py` — `LLMResponseError` on empty choices / missing message / non-JSON / non-dict body; retry policy (429/5xx/transport/malformed-200 retried; 400/401/403 not); `max_retries=2` = 3 attempts; payload stable across retries.
- `test_openrouter_compat.py` — `openrouter/free` model id reaches the wire verbatim; tools + `response_format` declared with no special-casing.
- `test_fallback_provider.py` — primary used when healthy; fallback only on exception; empty primary response does NOT fall back; `health()` is logical OR; label passthrough.
- `test_ollama_provider.py` — Ollama HTTP contract, `think`/`num_ctx` threading, tracing, `health()` via `/api/tags`.
- `test_replay_provider.py` — content-hash replay keying, strict vs empty on-miss, FIFO for repeated calls.

### Orchestration, verify, persona, speech (tests-core)
- `test_orchestrator.py` — tool dispatch → `Intent.slots`; native vs JSON fallback; `_TOOL_REPEAT_CAP=2`; turn timeout → fallback; unknown tool → general; persona-free tool-decision; turn record fields.
- `test_orchestrator_verify.py` — pre/post stages, filler via `on_say` (voiced, bypasses revoicer), verdict JSON, per-stage `max_verify_rounds`, `verify.enabled=False` byte-identical.
- `test_persona.py` — suffix composition, per-skill injection points, `canned()` determinism under a seeded RNG, canned keys (error_generic, cant_help, llm_offline, no_answer, unexpected_reply, update_signoff).
- `test_verify.py` — verdict JSON parsing, stage-specific fields, fail-open on malformed.
- `test_revoice.py` — timeout/error/empty/digit-mutation → plain; circuit-breaker + cooldown; seeded-unhealthy immediate passthrough.
- `test_speech_invariants.py` — exhaustive "nothing unflavored reaches TTS": deterministic skill revoiced; `voiced=True` bypasses; verify filler bypasses; `canned()` bypasses; `_speak()` defaults `voiced=False`.

### Pipeline & lifecycle (tests-core)
- `test_pipeline.py` (largest) — full wake→TTS loop, confident-threshold greeting, multi-sentence split, revoice vs bypass, conversation/followup, decision prompt, barge-in, expects-reply/`handle_reply`, error/can't-help canned paths.
- `test_control.py` — control verbs (TEXT/LISTEN/CANCEL/STOP/SAY/SET) dispatch; case-insensitive.
- `test_conversation.py` — add/trim/history copy isolation. `test_standdown.py` — engage/resume/remaining with fake clock. `test_state.py` — `@@STATE` JSONL emitter + null emitter. `test_selfupdate.py` — `restart_in_place` os.execv target. `test_logging.py` — JsonlFormatter, run_id, prune. `test_manifest.py`/`test_train_batch.py`/`test_voice_download.py` — training/registry/discovery logic.

### Skills & capabilities (tests-features, 34 files)
- Skills: `test_{clock,general,reminder,timer,stand_down,update,weather,web_search,calendar}_skill.py`, `test_skill_base.py` — handle/handle_reply, slot usage, LLM integration, persona fallback, error recovery.
- Search providers: `test_{ddgs,tavily,exa,wikipedia}_provider.py`, `test_multi_search.py` — result mapping, **API-key auth (constructor `api_key`, x-api-key/body param)**, snippet truncation, injection passthrough, round-robin merge/dedup, skip-failing-provider.
- Calendar/scheduling: `test_calendar_{skill,blocklist,extraction,state_store,watcher}.py`, `test_google_calendar.py`, `test_reminder_store.py` (incl. legacy-schema migration), `test_scheduler.py`.
- Audio/wake: `test_{aec,audio_processing,earcon,mic_hub,piper_tts,recorder,devices,livekit_detector,wake_registry}.py`. Utilities: `test_timespec.py`, `test_eval_extract.py`.

### TUI (tests-tui, 16 files)
- `test_tui_screens.py` — the deployment-size gate: renders every screen at `SIZE=(40,30)` and asserts `_assert_fits_40_cols` (`region.right <= 40`, `max_scroll_x == 0`).
- `test_tui_app.py` / `test_tui_ollama.py` — LLM health tier (up/degraded/down), status-line ≤38 chars, provider routing, Ollama autostart.
- `test_tui_config_schema.py` / `test_tui_configfile.py` / `test_tui_envfile.py` — config-form field kinds, env-name generation, nested YAML writes, `.env` parsing (config/secrets editing surface).
- `test_tui_discovery.py` — Ollama endpoints, **Zen auth header omitted when key blank**, wake globbing, 72h registry cache. `test_tui_supervisor.py` — subprocess lifecycle + `PR_SET_PDEATHSIG` survives `os.execv`. Plus logparse/logcolor/collapse/reflow/runlog/widgets/control/selection.

### Eval harness (tests-eval, `tests/eval/`)
Two opt-in gates scoring `Orchestrator._decide` (skills never execute):
- **Live eval** (`run_eval.py`, `test_tool_eval.py`) — 24-case dataset (`dataset.py:Case`) against the configured Ollama model through a production-mirroring orchestrator (`build_orchestrator`); asserts `score ≥ 0.90`. Skips unless `ASSISTANT_EVAL=1` and Ollama reachable.
- **Replay eval** (`run_replay.py`, `test_replay_eval.py`) — offline re-run of captured turns with `ReplayProvider` serving recorded LLM responses keyed by SHA256 of `(kind, label, payload)` (tool names sorted for stable hashing); asserts `score == 1.0`. Skips when no captures exist, so a fresh checkout stays green. Workflow: run daemon → `python -m tests.eval.extract <jsonl> -o captures/<name>.jsonl` → curate → replay.

## Test-first discipline
Feathers (`pluma/feathers/`) mandate: write the test, confirm it fails against unchanged code for the stated reason, then implement to green. Provider-rename work (FTHR-010) repointed `test_zen_provider.py` → `test_openai_compatible_provider.py` to prove behavior-preserving backward compatibility.

## Open Questions
- No `VERSION` file exists in the repo root, so scouts and these docs record `fledge_version: unknown`; confirm whether a version source is expected.
- Live/replay eval scores are model-dependent; the replay gate only enforces once a baseline capture is committed (none may be present in a fresh checkout).
