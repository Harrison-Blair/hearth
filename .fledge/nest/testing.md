---
generated: 2026-07-07T07:06:00Z
commit: 02f839d7a116780b02510c2d5b339c23c64a51f5
agent: fledge-forager
fledge_version: unknown
---

# Testing

How the suite is structured, run, and stubbed, with special attention to the seams a new web-search provider must satisfy. Tests live under `tests/` (plus `tests/eval/`).

## Framework and running
- **pytest + pytest-asyncio** with `asyncio_mode = auto` (`pyproject.toml`): `async def test_...` needs no marker.
- Install with `pip install -e ".[dev]"` — **no native extras needed**; anything touching a model, device, or network is stubbed.
- Run: `pytest` (all), `pytest tests/test_pipeline.py` (one file), `pytest tests/test_web_search_skill.py -k happy_path` (one test). Lint: `ruff check assistant tests`.

## Stubbing patterns (used everywhere)
- **`httpx.MockTransport`** — every network provider test routes `httpx.AsyncClient` to a handler `fn(request) -> httpx.Response`. Shared `_patch_transport(monkeypatch, handler)` closure reused across Wikipedia, Open-Meteo, Google Calendar, Ollama, Zen, and voice-download tests.
- **In-line `FakeX` classes** — `FakeLLM` (scripted JSON responses consumed in order, tracks prompts), `FakeProvider`/`FakeSearch` (search stubs), `FakeVoice`/`FakeWakeWordModel`/`FakeVad`/`FakeSd` (native-dep stubs), `FakeTTS`/`FakeOut`, `ScriptedLLM`/`DirectOrchestrator` (core), `FakeSupervisor` (TUI).
- **SQLite** — `:memory:` for isolated tests; `tmp_path/"x.db"` + reopen to simulate a daemon restart / migration.
- **Injection** — `monkeypatch.setattr(module, "Class", FakeClass)`; `monkeypatch.setenv("ASSISTANT_…", …)` for config precedence; injectable `now=lambda: …` clocks.
- **Assertions on side effects** — fakes expose `.calls`/`.spoken`/`.plays`/`.queries`/`.received`; tests assert routing, speech, and persistence rather than internals.

## Test groups

### Core (`tests/test_*` — pipeline/orchestrator/config/verify/infra)
- `test_pipeline.py` (~1466 lines, 50+ tests): full wake→speak flow, earcons, silence/no-speech retry, hallucination gating, conversation follow-ups, decision loop (confirm/listen/end), barge-in, stand-down, `@@STATE` emission. Uses `_pipeline()` factory + `FakeAudioIn`/`ScriptedDetector`/`RecordingEmitter`.
- `test_orchestrator.py` (16) + `test_orchestrator_verify.py` (22): tool dispatch, direct answers, native→JSON fallback, `max_tool_rounds`, timeouts, `_TOOL_REPEAT_CAP`, turn records; verify verdicts (approve/reject/rewrite), filler-only-on-reject, barge abort, best-draft-on-timeout, `max_verify_rounds` sub-cap, fail-open.
- `test_verify.py` (20), `test_persona.py` (11), `test_config.py` (19, incl. `web_search` defaults), `test_control.py` (13), `test_conversation.py`, `test_standdown.py`, `test_state.py`, `test_logging.py`, plus training-adjacent `test_manifest.py`/`test_train_batch.py`.

### Capabilities (`tests/test_*` — providers & skills)
Audio (`test_aec`, `test_audio_processing`, `test_devices`, `test_earcon`, `test_mic_hub`, `test_recorder`), calendar (6 files incl. `test_calendar_skill.py` ~45 tests, `test_calendar_watcher.py` ~15), weather (`test_open_meteo`, `test_weather_skill`), LLM (`test_ollama_provider`, `test_fallback_provider`, `test_zen_provider`, `test_zen_provider_guards` ~17 retry/guard tests, `test_replay_provider`), TTS/wake (`test_piper_tts`, `test_livekit_detector`, `test_wake_registry`, `test_voice_download`), skills (`test_clock`, `test_reminder`, `test_timer`, `test_stand_down`, `test_general`), storage/scheduling (`test_reminder_store`, `test_calendar_state_store`, `test_scheduler`, `test_timespec`).

### Search tests — the seam for a new AI-first provider (focus area)
Four files define what any new backend must satisfy:

- **`test_ddgs_provider.py`** (6): `FakeDDGS` intercepts the `DDGS` constructor + context manager + `.text()`, records init/query kwargs. Asserts row→`SearchResult` mapping (title/body/href → title/snippet/url, `domain()` source), snippet truncation to `max_snippet_chars`, region/timeout/count pass-through, backend error propagation, and `health()` both paths. Fixture is `autouse` monkeypatching `ddgs_provider.DDGS`.
- **`test_multi_search.py`** (8): `FakeProvider(results, exc, healthy)` with async `search`/`health`/`aclose`. Asserts round-robin interleave, URL dedup (trailing-slash normalized), `max_results` cap, a failing provider skipped, all-fail re-raises the first, all-empty → `[]`, `health()` true if any child healthy, `aclose()` fans out. Helper `_r(url, source)` builds `SearchResult`.
- **`test_wikipedia_provider.py`** (8): `httpx.MockTransport` handler returns the Action-API JSON. Asserts extract→snippet mapping + `"wikipedia"` source + URL from title, ordering by `index`, snippet truncation, empty/malformed → `[]`, `health()` true/false, custom `language` (de.wikipedia.org), `gsrlimit == count`.
- **`test_web_search_skill.py`** (14): `FakeSearch` + `FakeLLM` + `FakeSpeaker`. Asserts the full agentic loop — happy path (refine JSON → assess `sufficient:true` → answer, one search, spoken "Searching for…"), insufficient→retry with `new_query`+`remark`, rounds-exhausted unsuccessful, assess-bad-JSON → plain-summary fallback, empty results / search error degrade gracefully, refine-parse-failure → stripped-transcript query, and the **prompt-injection defenses**: untrusted snippets fenced in `<<<…>>>`, imperative injection neutralized to `[filtered]` before fencing, stray fence markers can't break the boundary, benign text passes through, overlong `new_query`/`remark` rejected, `speaker=None` silent-and-works, pending progress speech awaited before return, refine call is JSON-only (no system prompt).

**Net seam contract for a new provider:** implement `async search(query, *, count) -> list[SearchResult]` and `async health() -> bool` (+ `aclose()`); return `SearchResult` with a domain-ish `source` and dedup-able `url`; honor `count`, `timeout`, and `max_snippet_chars`; raise on backend error (let `MultiSearch` skip it). A test should mock the provider's HTTP via `httpx.MockTransport` in the same style, and — if wired into `WebSearchSkill` — nothing in the skill changes (it depends only on the ABC). Add a `test_<provider>_provider.py` mirroring `test_wikipedia_provider.py` and extend `test_multi_search.py` only if merge behavior changes.

### TUI (`tests/test_tui_*`)
16 files driven by Textual's pilot at fixed `SIZE=(40,30)`. **The gate:** `test_tui_screens.py:test_no_screen_overflows_40_columns` asserts `widget.region.right <= 40` and `max_scroll_x == 0` for every non-hidden widget on every screen — this is the hard constraint for the Pi 5 portrait display. Other files cover `AssistantTUI` health tiering, `DaemonSupervisor` start/stop/restart + env-override precedence, control channel (TEXT/SET), discovery (Ollama/Zen/registry/pull/cache-TTL, `test_tui_discovery.py` ~483 lines), config schema/file/env, log parse/color/collapse/reflow/runlog, widgets (Stepper/NavBar), and mouse selection.

### Eval harness (`tests/eval/`)
Two offline gates that keep a fresh checkout green:
- `test_tool_eval.py:test_tool_call_formatting` — **live** eval; skips unless `ASSISTANT_EVAL=1` and Ollama reachable. Runs ~20 `CASES` through the real orchestrator, asserts tool-name + required-arg score ≥ `PASS_THRESHOLD = 0.90`.
- `test_replay_eval.py:test_replay_matches_baseline` — **replay** eval; skips when `tests/eval/captures/` has no scoreable turns (only `.gitkeep` on a fresh checkout). Replays captured turns through the orchestrator with `ReplayProvider` (content-hash keyed), asserts exact-match score == 1.0.
- `build_orchestrator()` wires the real skill registry (Clock/Reminder/Timer/WebSearch/Weather/General) minus audio/TTS, using `:memory:` `ReminderStore`. Supporting unit tests: `test_eval_extract.py`, `test_replay_provider.py`.

## Test-verification discipline
Per repo/user convention: a new test must be shown to fail against the unfixed/stubbed behavior before it counts. The eval replay gate exists precisely as a regression gate — refactors to routing must reproduce identical decisions from identical model output.

## Open Questions
- `tests/eval/captures/` ships empty (`.gitkeep`), so the replay gate is inert on a fresh checkout by design; a real baseline must be captured+curated to activate it.
- `test_web_search_skill.py` checks a remark length ≤150 while the skill's `_MAX_REMARK_CHARS` is 140 — the exact cap/where it's enforced is worth confirming before relying on it in new provider tests.
- No end-to-end test exercises real Ollama/Piper/Whisper models; native extras are integration-only.
