---
generated: 2026-07-07T02:45:41Z
commit: 8d180f04862c48fdddc61804b81dafcd0f620344
agent: fledge-forager
fledge_version: unknown
---

# Testing

How the suite is structured, run, and stubbed, and what it covers. 74 test files under `tests/`. Framework is pytest with `asyncio_mode = auto`, so `async def test_...` needs no marker. Everything native (models, devices, network) is stubbed — `pip install -e ".[dev]"` alone runs the whole suite.

## Running

```bash
pytest                                            # all
pytest tests/test_pipeline.py                     # one file
pytest tests/test_pipeline.py -k followup         # filter
ruff check assistant tests                        # lint (line length 100)
```

## Stubbing philosophy

Tests never touch a model, device, or network. Every capability has a fake that mirrors its ABC and records calls for assertion. Common patterns (`tests-core`, `tests-capabilities` scouts):

- **Interface-matching fakes**: `ScriptedLLM` (queued tool/complete responses, for orchestrator), `FakeLLM` (fixed text, for pipeline/skills), `FakeDetector` (fires after N frames), `FakeRecorder`/`FakeSTT`/`FakeTTS`/`FakeOut`, `FakeVad`, `FakeWakeWordModel`, `FakeSupervisor` (TUI, avoids spawning a real daemon).
- **Injected clocks**: `StandDown(clock=FakeClock())`, `scheduler(now=lambda: 100.0)` — deterministic time.
- **HTTP mocking**: `httpx.MockTransport` handlers for Ollama/Wikipedia/Open-Meteo; `monkeypatch.setattr` to substitute `DDGS`, `sounddevice`, `PiperVoice.load`, `sys.modules["speexdsp"]`.
- **In-memory / tmp storage**: `ReminderStore(":memory:")` for logic, `tmp_path` for persistence/reopen tests.
- **Recording doubles**: `RecordingEmitter.states`, `FakeSpeaker.spoken`, `LLM.calls` — assert on captured state.
- **Error injectors**: `RaisingSkill`, `BoomOut`, `SlowLLM`, `FlakyTTS` exercise degradation paths.

## Coverage map

### Core (feature-relevant)

- **`tests/test_pipeline.py`** (1466 lines) — the deepest file. Covers the wake loop, VAD-skip on low RMS, empty-capture retry, conversation/follow-up, `max_history_turns` cap, stand-down suppression, barge-in gating, the continuation decision (`listen`/`confirm`/`end` with JSON-parse fallback to listen), confirm/decline/end phrases, hallucination filtering, earcon bracketing, arbiter-busy wake suppression, and — key for self-update — **`test_expects_reply_routes_followup_to_handle_reply`, `test_reply_is_one_round_only`, `test_expects_reply_skips_decision`, `test_silence_during_pending_reply_cancels`** (the confirm-then-act seam).
- **`tests/test_orchestrator.py`** (327 lines) — tool-call dispatch (args → slots), direct-answer path, delegation to general skill, native→JSON fallback, `max_tool_rounds` cap, repeat-tool cap, turn-timeout degradation, and route-trace logging.
- **`tests/test_control.py`** — every control verb (`TEXT`/`LISTEN`/`CANCEL`/`STOP`/`SAY`/`SET`/`RESUME`), including SAY waiting on the `AudioArbiter` and rate-prefix parsing.
- **`tests/test_persona.py`** — persona suffix scoping (reply prompts yes; tool-decision/JSON no), delegation re-voicing drafts, disabled = byte-identical.
- **`tests/test_standdown.py`** — timed expiry, indefinite, resume, re-engage, clock injection.
- **`tests/test_conversation.py`**, **`tests/test_state.py`**, **`tests/test_config.py`** (env override precedence, defaults), **`tests/test_logging.py`** (JSONL formatter, per-run dirs, prune), **`tests/test_scheduler.py`** (due firing, boot catch-up coalescing, arbiter hold, standdown skip, transient-retry/permanent-drop, recurring re-arm), **`tests/test_reminder_store.py`** (queries, migration, kind filtering).
- **Skill tests**: `test_general_skill`, `test_reminder_skill` (incl. bulk-cancel confirm via `expects_reply`), `test_clock_skill`, `test_timer_skill`, `test_stand_down_skill` (sign-off wording, indefinite fallback), `test_calendar_skill` (535 lines), `test_weather_skill`, `test_web_search_skill`.

### Capabilities

Audio (AEC, recorder VAD, earcons, devices, mic hub, processing), search (ddgs/wikipedia/multi with dedup + fallback), weather (Open-Meteo), LLM (`test_ollama_provider.py` — complete/chat/chat_tools/health/num_ctx/tracing), TTS (Piper length_scale), wake (`test_livekit_detector.py` windowing/threshold/streak; `test_wake_registry.py` phrase derivation), voice download, calendar (blocklist/extraction/state store/watcher), timespec, and training helpers (`test_train_batch.py`, `test_manifest.py`).

### TUI

- **`tests/test_tui_supervisor.py`** — `DaemonSupervisor` lifecycle: start streams lines + merges env, stop terminates, **restart changes PID**, send is a no-op when not running, `.env` merge, session-override precedence.
- **`tests/test_tui_screens.py`** (609 lines) — **`test_no_screen_overflows_40_columns`** enforces the 40-col portrait constraint for every screen (`_assert_fits_40_cols` at `size=(40,30)`); plus volume/mute, chat modal → TEXT, config steppers → env overrides → restart, model/voice pickers, `@@STATE` → Now screen, context-button verb-per-state.
- **`tests/test_tui_control.py`**, `test_tui_ollama.py` (server autostart/restart/adopt-external), `test_tui_discovery.py`, `test_tui_config_schema.py` (no free-text fields; stepper bounds), plus log parse/color/collapse/reflow/runlog/selection/widgets.
- Uses Textual's `app.run_test(size=...)` pilot harness with `FakeSupervisor` (no real daemon spawn).

### Eval / replay harness — `tests/eval/`

Two tracks (`tests-eval` scout):
- **Live eval** (`run_eval.py`, `test_tool_eval.py`) — runs 23 dataset cases (`dataset.py`) through a real orchestrator + Ollama, scoring tool-name + required-arg correctness; gate ≥ 90%. Opt-in via `ASSISTANT_EVAL=1`; **skips if Ollama unreachable** so offline CI stays green.
- **Replay eval** (`replay.py`, `run_replay.py`, `test_replay_eval.py`) — a regression gate that re-runs captured real sessions through the orchestrator with a `ReplayProvider` serving LLM responses keyed by SHA256 of canonical JSON; gate = 100% exact tool/arg match. **Skips if `tests/eval/captures/` is empty** (empty at checkout). `extract.py` builds captures from daemon JSONL logs.
- Unit tests: `test_eval_extract.py`, `test_replay_provider.py` (key stability, FIFO replay, strict/empty miss modes).

## Test-first guidance for a self-update feature

A new self-update skill/verb should be tested by: (1) a skill unit test asserting the confirmation prompt carries `expects_reply=True` and that `handle_reply` acts only on an affirmative (mirror `test_reminder_skill` bulk-cancel); (2) a pipeline integration test that the sign-off is spoken before the restart callback fires (extend `test_pipeline.py`); (3) if a control verb is added, a `test_control.py` case; (4) if the TUI observes the restart, a `test_tui_supervisor.py` case for how the supervisor handles a same-PID re-exec vs. a normal exit. Per repo convention (`CLAUDE.md`), verify each new test fails against the unfixed code before it passes.

## Open Questions

- The self-update / re-exec feature is untested; whether the supervisor distinguishes an `os.execv` re-exec (same PID, preserved pipes) from a normal exit is unverified (`tests-tui`, `tui` scouts).
- No conditional-skip on missing native deps was observed beyond the eval opt-ins; whether any capability tests are gated in CI is unconfirmed (`tests-capabilities` scout).
