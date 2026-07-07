---
generated: 2026-07-07T02:45:41Z
commit: 8d180f04862c48fdddc61804b81dafcd0f620344
agent: fledge-forager
fledge_version: unknown
---

# Entry Points & Public Interfaces

Where execution enters the system, the public interfaces components expose, how to run and build the project, and — with detail relevant to a self-update feature — the confirm-then-act reply seam, the sign-off/persona layer, the control channel, and the daemon supervision lifecycle.

## How to run

```bash
source .venv/bin/activate
pip install -e ".[dev]"          # core + pytest/pytest-asyncio/ruff (enough to run tests)
python -m assistant.app          # boot the daemon (Ctrl-C to stop)
python -m tui                    # boot the monitor TUI (supervises the daemon)
./start.sh                       # activate venv, reap stray daemon, exec `python -m tui`
assistant doctor                 # provisioning: ensure Ollama + STT models ready
```

Build/lint/test:

```bash
pytest                                   # all tests (asyncio_mode=auto)
pytest tests/test_pipeline.py            # one file
ruff check assistant tests               # lint, line length 100
make release                             # → packaging/build.sh → dist/assistant-$(uname -m) (PyInstaller)
```

Frozen binary (`packaging/entrypoint.py`) subcommands: `assistant` (daemon), `assistant tui`, `assistant doctor`/`bootstrap`, `assistant --version`.

## Daemon entry — `assistant/app.py`

- `main()` — sync CLI wrapper; calls `asyncio.run(_run(config, devices))`; catches `KeyboardInterrupt`. **This is the only shutdown hook today — no signal handlers, no re-exec.**
- `_run(config, devices)` — the composition root: constructs all providers/skills, builds the shared `StandDown` and `AudioArbiter`, registers skills (`GeneralSkill` as `default=True`), and runs `pipeline.run()`, `scheduler.run()`, `control.run()`, and optional `calendar_watcher.run()` under one `asyncio.gather(...)`, cleaning up stores/providers in `finally`.

## Pipeline — `assistant/core/pipeline.py:VoicePipeline`

- `run()` (async) — the main event loop; entry point for the daemon.
- `request_listen()` — tap-to-listen (bypass wake word); called by the control channel.
- `cancel()` — tap-to-cancel; stops the audio device and current capture.
- `submit_text(text)` (async) — inject a typed command from the TUI; runs the same route → skill → speak path as a spoken turn.

### The confirm-then-act reply seam (self-update relevance)

When a skill returns `SkillResult(expects_reply=True)`, the pipeline stores that skill as the pending reply handler and dispatches the **next** utterance directly to `skill.handle_reply(cmd)` — no re-orchestration, exactly one round, and the decision LLM is skipped (`assistant/core/pipeline.py`; tests `test_expects_reply_routes_followup_to_handle_reply`, `test_reply_is_one_round_only`, `test_expects_reply_skips_decision`). A silent/empty follow-up is passed to `handle_reply` as a cancel. This is the mechanism a self-update skill should use to ask "Are you sure?" and act on the confirmation. `ReminderSkill.manage_reminders` is the existing example (bulk-delete confirmation).

## Orchestrator — `assistant/core/orchestrator.py:Orchestrator`

- `handle(text, history)` (async) → `(SkillResult, Skill)` — routes one transcript. Builds the tool list from `SkillRegistry.tool_schemas()`, calls the LLM; the model either calls a tool (arguments → `Intent.slots`) or answers directly. Bounded by `max_tool_rounds` and `turn_timeout_s`; native tool-calling falls back to JSON completion (`tool_mode="auto"`); any failure/timeout/repeat degrades to the default `GeneralSkill`. Emits a structured JSON turn-trace log per handle (used by the eval harness).

## Skill contract — `assistant/skills/base.py`

- **`Skill`** ABC: class attrs `name: str`, `intents: set[str]`, `tool_specs: dict[str,dict] = {}`; methods `async handle(cmd, intent) -> SkillResult` (abstract), `tools() -> list[dict]` (OpenAI schemas, one per intent), `async handle_reply(cmd) -> SkillResult` (default returns generic failure — override for confirm-then-act).
- **`SkillRegistry`**: `register(skill, *, default=False)`, `get(intent_type) -> Skill | None` (falls back to default), `intents` property, `tool_schemas() -> list[dict]` (aggregated; the default skill contributes none).

**To add a skill (e.g. a self-update skill)**: subclass `Skill`, declare `name` + `intents` + `tool_specs`, implement `handle` (and `handle_reply` for confirmation), construct it in `assistant/app.py:_run()`, and `registry.register(...)`. It must be injected with any dependencies (a restart callback, `StandDown`, etc.) at construction time — components never read `Config` directly.

### Sign-off / persona layer (self-update relevance)

- **Quirky sign-off precedent**: `StandDownSkill` (`assistant/skills/stand_down.py`) speaks lines like "Okay, standing down for 30 minutes." / "Okay, standing down until you wake me from the screen." — the closest existing pattern to a self-update sign-off.
- **Persona voice**: `assistant/core/persona.py:with_persona()` appends the Calcifer tone (`PersonaConfig.strength` = `terse`|`expansive`) to final-reply prompts only, never to tool-decision or JSON prompts (`tests/test_persona.py`). `GeneralSkill` re-styles drafts through it. A spoken sign-off before restart should follow this scoping.
- **Conversation end/decline phrases**: `ConversationConfig.end_phrases` (substring match, e.g. "goodbye") close a conversation silently; there is **no** separate sign-off/outro system today (`assistant/core/pipeline.py`, `conversation` scout).

## Control channel — `assistant/core/control.py:ControlChannel`

Reads line verbs from stdin (written by the TUI supervisor) and dispatches them. Verbs (case-insensitive): `TEXT <utterance>` (→ `pipeline.submit_text`), `LISTEN` (→ `request_listen`), `CANCEL` (→ `cancel`), `STOP` (→ `out.stop`), `SAY [rate|]text` (→ speaker, waits for `AudioArbiter`), `SET <key> <value>` (e.g. `SET audio.output_volume 0.75`), `RESUME` (→ `standdown.resume`) (`tests/test_control.py`, `tests/test_tui_control.py`). `run()` reads until EOF; `dispatch(line)` is the unit-tested surface. **A self-update could be triggered by a new control verb here, or by a spoken intent routed to a skill.**

## State feed — `assistant/core/state.py:StateEmitter`

Prints `@@STATE {json}` marker lines to stdout (`state`, plus `transcript`/`text`/`banner`/`level` fields). One-directional; the TUI parses it (`tui/logparse.py:parse_state`) to drive the Now screen. `NullStateEmitter` is a silent no-op; the real emitter is suppressed on interactive TTYs.

## Capability provider interfaces

- **`LLMProvider`** (`assistant/llm/base.py`): `complete(prompt, *, system, json, label)`, `chat(messages, *, system, label)`, `chat_tools(messages, *, system, tools, label)` → `ChatResponse`, `health() -> bool`, `aclose()`.
- **`SpeechToText`** (`assistant/stt/base.py`): `transcribe(audio: bytes) -> str`.
- **`TextToSpeech`** (`assistant/tts/base.py`): `synthesize(text, length_scale=None) -> bytes`.
- **`WakeDetector`** (`assistant/wake/base.py`): `process(frame) -> WakeEvent | None`, `reset()`.
- **`AudioIn`/`AudioOut`** (`assistant/audio/base.py`): `stream()`/`play()`/`drain()`/`set_tap()`/`stop()`.
- **`CalendarProvider`**, **`SearchProvider`**, **`WeatherProvider`** — see `data-model.md` and `modules.md`.

## TUI daemon supervision — `tui/supervisor.py:DaemonSupervisor`

- `start(overrides)` — spawn `python -m assistant.app` as an asyncio subprocess with `ASSISTANT_*` env overrides; `prctl(PR_SET_PDEATHSIG)` orphan-proofs the child.
- `stop()` — SIGTERM then SIGKILL on timeout. `restart(overrides)` — stop + start (PID changes).
- `send(line)` — write a control-channel command to the child's stdin.
- `lines()` — async generator yielding the child's stdout lines until EOF.
- `running` (property), `returncode`, `pid`. `free_ollama_port()` kills an external ollama by PID.

The TUI's `AssistantTUI` (`tui/app.py`) pumps `lines()`, splits `@@STATE` from logs, and exposes Start/Stop/Restart/Restart-LLM plus live volume via the control channel. **Self-update relevance**: an `os.execv` re-exec keeps the daemon's PID and inherited stdin/stdout fds, so the supervisor's child handle and control/state channels can survive it — but the supervisor has no explicit re-exec awareness, and this survival needs verification against Python's fd-inheritance behavior (see `architecture.md` Open Questions).

## Config surface — `assistant/core/config.py` (+ `config.yaml`, `default-config.yaml`)

`Config` root composed of nested models; override any field via `ASSISTANT_<SECTION>__<FIELD>`. Sections: `AudioConfig`, `RecorderConfig` (VAD aggressiveness, silence/max/timeout/preroll ms), `WakeConfig` (model_paths, threshold, trigger_frames), `SttConfig`, `LlmConfig` (provider, model, host, timeout, num_ctx, `serve_cmd`), `AgentConfig` (`tool_mode`, `max_tool_rounds`, `turn_timeout_s`), `PersonaConfig`, `TtsConfig` (voice, length_scale, ack_phrases, ack_delay_s), `StorageConfig` (db_path), `SchedulingConfig`, `WebSearchConfig`, `WeatherConfig`, `CalendarConfig`, `ConversationConfig`, `AecConfig`, `BargeinConfig`, `LoggingConfig`. Add new tunables as typed fields mirrored in both YAML files.

## Smoke scripts & systemd

`verify_calendar.py` (calendar CRUD round-trip) and `verify_wikipedia.py` (search) are manual smoke scripts. `install.sh --systemd` writes a user unit (`ExecStart=$VPY -m assistant.app`, `Restart=on-failure`, `RestartSec=5`, `WorkingDirectory` pinned to repo root) — an alternative restart mechanism to a re-exec.
