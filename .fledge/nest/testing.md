---
generated: 2026-07-07T22:56:23Z
commit: 58fb2ba9bbeefc5db7d530261bcb3450573048fa
agent: fledge-forager
fledge_version: unknown
---

# Testing

The suite is ~84 files under `tests/` (~26k LOC across the two core batches plus TUI and eval), run with **pytest + pytest-asyncio in `asyncio_mode = "auto"`** (from `pyproject.toml`) — so `async def test_...` needs no marker. Everything native (LLM, HTTP, audio devices, ONNX models, `os.execv`) is stubbed, so `pip install -e ".[dev]"` alone runs the whole suite offline.

## Running

```bash
pytest                                            # all
pytest tests/test_pipeline.py                     # one file
pytest tests/test_router.py -k route_falls_back   # one test
ruff check assistant tests                        # lint
ASSISTANT_EVAL=1 pytest tests/eval/test_tool_eval.py   # opt-in live LLM eval
```

## Test-doubling patterns

- **HTTP wire mocking** — `httpx.MockTransport` via a shared `_patch_transport(monkeypatch, handler)` helper that routes an `AsyncClient` through a handler `(httpx.Request) -> httpx.Response`. Handlers inspect URL/headers/JSON body (often capturing into a dict) and return crafted responses or raise `ConnectError`. Used for every LLM and web-search provider, weather, Google Calendar, and TUI discovery.
- **Monkeypatch import stubbing** — `monkeypatch.setattr(module, "NativeClass", Fake)` replaces speexdsp, sounddevice, `piper.PiperVoice`, livekit wake model, `ddgs.DDGS` at import time.
- **Fakes/spies** — inline classes prefixed `Fake*` or descriptive: `FakeLLM`/`ScriptedLLM` (scripted response queues that record `.calls`/`.prompts`/`.messages`; `IndexError` when exhausted fails the test), `FakeTTS`/spy-TTS (accumulates `.spoke`), `TaggingRevoicer` (marks revoiced output with `<<REVOICED>>`), `FakeClock` (`.now` + `advance(dt)`), `FakeProvider`/`FakeWeather`/`FakeSearch`/`FakeStore`, `FakeVad`/`FakeWakeWordModel`, `FakeSupervisor`/`FakePipeline`/`FakeOut` (TUI). Test skills: `EchoSkill`, `DataOnlySkill`, `FallbackSkill`, `OtherSkill`.
- **Databases** — real SQLite against `:memory:` or `tmp_path`; reopened with a new instance to prove persistence/migration.

## LLM provider coverage (the next feature's safety net)

- **`tests/test_zen_provider.py`** — `OpenCodeZenProvider` wire tests over `httpx.MockTransport` on `/chat/completions`: `complete`/`chat`/`chat_tools` shapes, `Bearer {key}` auth header (omitted when key is empty), `json=True` adds `response_format`, system message prepended to messages, null content→`""`, whitespace stripped, tool_calls rebuilt.
- **`tests/test_zen_provider_guards.py`** — retry/guard policy: `LLMResponseError(retryable=…)` on empty choices / missing message / non-JSON / non-dict body; 429 and 503 and transport `ConnectError` retry (respecting `max_retries`); 401 does **not** retry (fails immediately); `retry_backoff_s=0.0` keeps tests fast.
- **`tests/test_ollama_provider.py`** — `/api/generate` fields (model/prompt/system/think/num_ctx/format); `think=False` when `json=True`; labeled INFO trace logging with `latency_ms` in `record.data`.
- **`tests/test_fallback_provider.py`** — primary→fallback delegation on raise; an empty `chat_tools` response does **not** fall back; `health()` ORs both providers.
- **`tests/eval/`** — orchestrator routing accuracy. `run_eval.py` (live, opt-in `ASSISTANT_EVAL=1`, skips if Ollama down) scores each of 23 `dataset.py` cases on tool-name + required-arg correctness against a ≥0.90 gate. `run_replay.py` re-runs captured real turns through `Orchestrator._decide()` with `ReplayProvider` (responses keyed by SHA-256 of `(kind, label, payload)`, so any prompt/tool change misses and forces re-capture) asserting exact reproducibility (score == 1.0). `test_replay_eval.py` skips when `captures/` has no turn records; workflow is capture (`extract.py`) → curate → replay.

## Core coverage by area

- **Config** (`test_config.py`, `test_configfile.py`) — pydantic defaults, env-override precedence (var > yaml > default), type coercion (bool/float/list-JSON), every config block; TUI persistence via `write_fields`.
- **Pipeline/orchestrator** (`test_pipeline.py`, `test_orchestrator.py`, `test_orchestrator_verify.py`) — wake→record→STT→route→TTS with fake stages; followup windows; multi-round tool loops with data-only skills; fallback on LLM failure; verify pre/post approve/reject/rewrite; filler-on-reject only when persona + `spoken_feedback`; TimeoutError → best draft; per-stage `max_verify_rounds` subcap; disabled = byte-identical.
- **Persona/revoice invariants** (`test_persona.py`, `test_revoice.py`, `test_speech_invariants.py`) — suffix/strength composition; revoice timeout/circuit/digit-preservation; **spy-TTS + `TaggingRevoicer` prove every string reaching TTS is either revoiced, `voiced=True`, or from `canned()`** — four path classes (deterministic→revoiced, persona-marked bypass, verify filler bypass, canned error bypass) plus the `_speak` default-`voiced=False` pin. This is the PLM-003/FTHR-009 hardening guarantee; each invariant test is demonstrated failing under a deliberate seam break.
- **Skills** — per-skill tests with fakes: clock (ordinals/12h), reminder/timer (relative/recurring parse, LLM slot extraction, `kind`), weather (geocode+summary), calendar (CRUD + blocklist), web_search (refine→assess→retry, injection content passed unchanged), general (history order, error fallback), stand_down (duration/indefinite), update (confirm→restart + canned signoff).
- **Search providers (PLM-002)** — `test_tavily_provider.py`/`test_exa_provider.py`/`test_wikipedia_provider.py` (httpx mock: result mapping, snippet truncation, api-key headers, answer-block synthesis, injection content unchanged, health), `test_ddgs_provider.py` (FakeDDGS context manager), `test_multi_search.py` (round-robin interleave, URL dedup, cap, skip-failed, all-fail reraise, any-healthy).
- **Audio** (`test_aec`, `test_audio_processing`, `test_devices`, `test_earcon`, `test_mic_hub`, `test_piper_tts`, `test_recorder`) — subframe AEC pairing + missing-dep passthrough, normalization edges, device resolution, earcon distinctness, TTS length_scale plumbing, VAD end/timeout/cancel/min-speech/max-cap, MicHub tap/drain/overflow-drop.
- **Wake** (`test_livekit_detector.py`) — window fill, ordered samples, threshold firing, `reset`, `score_interval` skip, `trigger_frames` consecutive-hit debounce, streak reset.
- **Scheduling/storage/control/state** — scheduler (fire/delete/retry/defer, boot catch-up coalesce, arbiter, standdown, revoice), watcher (announce/dedupe-across-restart/reschedule/all-day-skip/blocklist/imminent/standdown/fallback-revoicer), reminder+calendar stores (migration, dedupe key, purge, reopen), control channel verbs, `StateEmitter` JSONL, conversation trim, standdown engage/resume/expiry, logging JSONL + `prune_runs`, selfupdate `os.execv` target.

## TUI coverage (`tests/test_tui_*.py`, 16 files)

Textual's `app.run_test(size=SIZE)` async harness with a pilot for clicks/keys. **`SIZE = (40, 30)` and `test_tui_screens.py:_assert_fits_40_cols()` are the deployment gate**: every non-hidden widget must satisfy `region.right <= 40` and `max_scroll_x == 0` across all screens (portrait 320×480). Also: supervisor env-merge + pdeathsig survival across `os.execv` re-exec (multi-stage subprocess scripts), control TEXT/SET dispatch, LLM tier badges (up/degraded/down), Ollama/Zen discovery over httpx mock (health, model options, registry scrape + 72h cache, pull progress, delete), log parse/color/collapse/reflow, run-log rotation, config-schema field metadata + coercion, Stepper bounds, NavBar dots. Hermetic autouse fixture patches `discovery.current_config()` to typed defaults (never reads yaml).

## Test-first discipline (PLM feathers)

Every feather (FTHR-001..009) wrote its tests failing first against unchanged code, then confirmed passing; hardening tests (FTHR-009) verify invariants by deliberate seam breaks. No test invokes real network, native ML deps, or `os.execv`. Full green suite is an acceptance criterion on every feather. This matches the repo/user convention: a test only counts if it fails when the behavior breaks.

## Open Questions

- No cross-domain integration tests (e.g. calendar extraction → TTS → arbiter) or latency/performance gates were observed beyond unit coverage and the opt-in eval.
- Whether any pre-recorded `tests/eval/captures/*.jsonl` are checked in, or must be recorded fresh per developer, is unresolved.
