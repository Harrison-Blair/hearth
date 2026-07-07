## AC-1

Six tests written test-first (spec's Tests section), run against unchanged code.

Command:
```
source .venv/bin/activate
pytest tests/test_pipeline.py::test_pipeline_invokes_restart_after_speaking tests/test_pipeline.py::test_decline_or_silence_cancels_no_restart -v
```

Output (pre-implementation):
```
tests/test_pipeline.py::test_pipeline_invokes_restart_after_speaking FAILED [ 50%]
tests/test_pipeline.py::test_decline_or_silence_cancels_no_restart FAILED [100%]

E       TypeError: VoicePipeline.__init__() got an unexpected keyword argument 'restart_in_place'
tests/test_pipeline.py:182: TypeError
========================= 2 failed, 1 warning in 0.15s =========================
```

Command:
```
pytest tests/test_update_skill.py tests/test_selfupdate.py -v
```

Output (pre-implementation):
```
ERROR tests/test_update_skill.py
ImportError while importing test module '.../tests/test_update_skill.py'.
tests/test_update_skill.py:4: in <module>
    from assistant.skills.update import UpdateSkill
E   ModuleNotFoundError: No module named 'assistant.skills.update'

ERROR tests/test_selfupdate.py
ImportError while importing test module '.../tests/test_selfupdate.py'.
tests/test_selfupdate.py:5: in <module>
    from assistant.core import selfupdate
E   ImportError: cannot import name 'selfupdate' from 'assistant.core' (.../assistant/core/__init__.py)
```

Command:
```
pytest tests/test_orchestrator.py::test_typed_update_routes_to_update_self -v
```

Output (pre-implementation):
```
ERROR tests/test_orchestrator.py
ImportError while importing test module '.../tests/test_orchestrator.py'.
tests/test_orchestrator.py:8: in <module>
    from assistant.skills.update import UpdateSkill
E   ModuleNotFoundError: No module named 'assistant.skills.update'
```

All six named tests fail for the expected reason: the new module/kwarg/field
they exercise does not exist yet on unchanged code. See below for the passing
run captured after implementation.

### Post-implementation (all six green)

Command:
```
pytest tests/test_update_skill.py tests/test_selfupdate.py tests/test_orchestrator.py::test_typed_update_routes_to_update_self tests/test_pipeline.py::test_pipeline_invokes_restart_after_speaking tests/test_pipeline.py::test_decline_or_silence_cancels_no_restart -v
```

Output:
```
tests/test_update_skill.py::test_update_command_prompts_confirmation PASSED [ 14%]
tests/test_update_skill.py::test_confirm_returns_signoff_and_restart_flag PASSED [ 28%]
tests/test_update_skill.py::test_decline_or_silence_cancels_no_restart PASSED [ 42%]
tests/test_selfupdate.py::test_restart_in_place_reexecs_source_target PASSED [ 57%]
tests/test_orchestrator.py::test_typed_update_routes_to_update_self PASSED [ 71%]
tests/test_pipeline.py::test_pipeline_invokes_restart_after_speaking PASSED [ 85%]
tests/test_pipeline.py::test_decline_or_silence_cancels_no_restart PASSED [100%]

========================= 7 passed, 1 warning in 0.15s =========================
```

## AC-2

A spoken/typed update command (and paraphrases) route to `update_self` and
produce a confirmation prompt (`expects_reply=True`), never an immediate
restart.

Command:
```
pytest tests/test_update_skill.py::test_update_command_prompts_confirmation tests/test_orchestrator.py::test_typed_update_routes_to_update_self -v
```

Output:
```
tests/test_update_skill.py::test_update_command_prompts_confirmation PASSED [ 50%]
tests/test_orchestrator.py::test_typed_update_routes_to_update_self PASSED [100%]

========================= 2 passed in 0.06s =========================
```

`test_update_command_prompts_confirmation` exercises three paraphrases
("update yourself", "restart to load the latest code", "check for updates")
against `UpdateSkill.handle()`, asserting `expects_reply=True`, `restart=False`,
and a non-empty spoken prompt for each. `test_typed_update_routes_to_update_self`
exercises the typed path (`spoken=False`) through the real `Orchestrator`,
asserting the model's `update_self` tool call dispatches to `UpdateSkill` and
returns a confirmation, not a restart.

## AC-3

An affirmative confirmation yields a non-empty in-character sign-off and causes
the pipeline to invoke the injected restart callable strictly after the
sign-off has been spoken.

Command:
```
pytest tests/test_update_skill.py::test_confirm_returns_signoff_and_restart_flag tests/test_pipeline.py::test_pipeline_invokes_restart_after_speaking -v
```

Output:
```
tests/test_update_skill.py::test_confirm_returns_signoff_and_restart_flag PASSED [ 50%]
tests/test_pipeline.py::test_pipeline_invokes_restart_after_speaking PASSED [100%]

========================= 2 passed in 0.06s =========================
```

`test_pipeline_invokes_restart_after_speaking` asserts an ordered event log
`order == ["play", "play", "restart"]` — the confirmation prompt is played,
then the sign-off is played, and only then is the injected `restart_in_place`
callable invoked.

## AC-4

A negative, unrelated, or silent confirmation reply performs no restart and
returns the assistant to normal listening.

Command:
```
pytest tests/test_update_skill.py::test_decline_or_silence_cancels_no_restart tests/test_pipeline.py::test_decline_or_silence_cancels_no_restart -v
```

Output:
```
tests/test_update_skill.py::test_decline_or_silence_cancels_no_restart PASSED [ 50%]
tests/test_pipeline.py::test_decline_or_silence_cancels_no_restart PASSED [100%]

========================= 2 passed in 0.06s =========================
```

`test_update_skill.py::test_decline_or_silence_cancels_no_restart` checks
`UpdateSkill.handle_reply()` returns `restart=False` for "no", "not now", and
"" (silence). `test_pipeline.py::test_decline_or_silence_cancels_no_restart`
checks the pipeline never calls the injected restart callable when the reply
result carries `restart=False` (the default), and that the loop returns to
normal (no exception, no restart call).

## AC-5

`restart_in_place()` re-execs `[sys.executable, "-m", "assistant.app"]` and
makes no network/git/subprocess call.

Command:
```
pytest tests/test_selfupdate.py -v
```

Output:
```
tests/test_selfupdate.py::test_restart_in_place_reexecs_source_target PASSED [100%]

========================= 1 passed in 0.05s =========================
```

`assistant/core/selfupdate.py` imports only `logging`, `os`, `sys` from the
standard library — no `subprocess`, `git`, `httpx`, or network client is
imported or called, so FC-6 (no network call) holds by construction (absence
of such an import in the module the test exercises).

## AC-6

The restart mechanism is injected into `VoicePipeline` (not hard-wired), and
`os.execv` is never called during the test suite.

`VoicePipeline.__init__` takes `restart_in_place: Callable[[], None] | None`
(`assistant/core/pipeline.py`), defaulting to the real
`assistant.core.selfupdate.restart_in_place` only when the caller passes none
— every pipeline test in `tests/test_pipeline.py` either doesn't trigger a
restart or passes a fake `restart_in_place` recorder, so the real `os.execv`
is never reached. `tests/test_selfupdate.py` monkeypatches `os.execv` before
calling `restart_in_place()` directly.

Command (full suite, confirms no real `os.execv` invocation — a real call
would replace the pytest process and the run would never produce output):
```
pytest
```

Output: see AC-7 (same run — it completed and printed a summary, which alone
proves `os.execv` never fired for real during the suite).

## AC-7

`pytest` is green and `ruff check assistant tests` is clean.

Note: a fresh venv with only `pip install -e ".[dev]"` hit pre-existing
collection errors unrelated to this feature (`webrtcvad`, `textual`,
`piper-tts` imported unconditionally by modules the test files pull in). Per
the brooder's environment instructions this venv also installed
`vad,llm,nlu,scheduling,search,tts,tui,gcal,stt,wake` so the full suite could
run; this is an environment-setup matter, not a code change.

Command:
```
pytest
```

Output:
```
tests/eval/test_tool_eval.py s                                           [  0%]
tests/test_aec.py ........                                               [  1%]
tests/test_audio_processing.py .....                                     [  1%]
tests/test_calendar_blocklist.py ......                                  [  2%]
tests/test_calendar_extraction.py ....................                   [  5%]
tests/test_calendar_skill.py .......................................     [ 10%]
tests/test_calendar_state_store.py ........                              [ 11%]
tests/test_calendar_watcher.py .............                             [ 13%]
tests/test_clock_skill.py ...                                            [ 13%]
tests/test_config.py ................................                    [ 18%]
tests/test_configfile.py .                                               [ 18%]
tests/test_control.py ..............                                     [ 20%]
tests/test_conversation.py ...                                           [ 20%]
tests/test_ddgs_provider.py .....                                        [ 21%]
tests/test_devices.py ....                                               [ 21%]
tests/test_earcon.py ....                                                [ 22%]
tests/test_eval_extract.py ..                                            [ 22%]
tests/test_exa_provider.py .........                                     [ 23%]
tests/test_fallback_provider.py .........                                [ 24%]
tests/test_general_skill.py .......                                      [ 25%]
tests/test_google_calendar.py ...........                                [ 27%]
tests/test_livekit_detector.py ........                                  [ 28%]
tests/test_logging.py .........                                          [ 29%]
tests/test_manifest.py ..                                                [ 29%]
tests/test_mic_hub.py ......                                             [ 30%]
tests/test_multi_search.py ........                                      [ 31%]
tests/test_ollama_provider.py ..................                         [ 33%]
tests/test_open_meteo.py .......                                         [ 34%]
tests/test_orchestrator.py ..............                                [ 36%]
tests/test_orchestrator_verify.py ................                       [ 38%]
tests/test_persona.py .............                                      [ 40%]
tests/test_pipeline.py ................................................. [ 47%]
...................                                                      [ 49%]
tests/test_piper_tts.py ....                                             [ 50%]
tests/test_recorder.py ........                                          [ 51%]
tests/test_reminder_skill.py ......................                      [ 54%]
tests/test_reminder_store.py ............                                [ 55%]
tests/test_replay_provider.py .......                                    [ 56%]
tests/test_scheduler.py ...........                                      [ 58%]
tests/test_selfupdate.py .                                               [ 58%]
tests/test_stand_down_skill.py ....                                      [ 58%]
tests/test_standdown.py .....                                            [ 59%]
tests/test_state.py ....                                                 [ 59%]
tests/test_tavily_provider.py .........                                  [ 61%]
tests/test_timer_skill.py ............                                   [ 62%]
tests/test_timespec.py ..................                                [ 65%]
tests/test_train_batch.py .....                                          [ 65%]
tests/test_tui_app.py ..........                                         [ 67%]
tests/test_tui_collapse.py ..                                            [ 67%]
tests/test_tui_config_schema.py ........                                 [ 68%]
tests/test_tui_configfile.py ....                                        [ 68%]
tests/test_tui_control.py ...                                            [ 69%]
tests/test_tui_discovery.py ......................................       [ 74%]
tests/test_tui_envfile.py ...                                            [ 74%]
tests/test_tui_logcolor.py .........                                     [ 75%]
tests/test_tui_logparse.py ......                                        [ 76%]
tests/test_tui_ollama.py ........                                        [ 77%]
tests/test_tui_reflow.py ..                                              [ 78%]
tests/test_tui_runlog.py .....                                           [ 78%]
tests/test_tui_screens.py ...................................            [ 83%]
tests/test_tui_selection.py ...                                          [ 83%]
tests/test_tui_supervisor.py ......                                      [ 84%]
tests/test_tui_widgets.py ..........                                     [ 85%]
tests/test_update_skill.py ...                                           [ 86%]
tests/test_verify.py .......................                             [ 89%]
tests/test_voice_download.py ...                                         [ 89%]
tests/test_wake_registry.py ...                                          [ 90%]
tests/test_weather_skill.py ....                                         [ 90%]
tests/test_web_search_skill.py ..........................                [ 94%]
tests/test_wikipedia_provider.py .........                               [ 95%]
tests/test_zen_provider.py ..................                            [ 97%]
tests/test_zen_provider_guards.py .................                      [100%]

================== 752 passed, 2 skipped, 1 warning in 20.27s ==================
```

Command:
```
ruff check assistant tests
```

Output:
```
All checks passed!
```
