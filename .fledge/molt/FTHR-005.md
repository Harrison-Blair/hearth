# FTHR-005 — Tracer: Revoicer seam — voiced flag, pipeline choke point, config, wiring

## AC-1

Tests were written first (new `tests/test_revoice.py`; extended
`tests/test_pipeline.py`, `tests/test_general_skill.py`, `tests/test_weather_skill.py`,
`tests/test_web_search_skill.py`, `tests/test_orchestrator_verify.py`,
`tests/test_config.py`), then run against the unmodified code to confirm they fail
for the expected reason (missing `assistant.core.revoice` module, missing
`SkillResult.voiced`/`Revoicer` wiring, missing `PersonaConfig.revoice_enabled`/
`revoice_timeout_s`).

### Pre-implementation (FAILING) run

Command:
```
source .venv/bin/activate && pytest tests/test_revoice.py tests/test_pipeline.py \
  tests/test_general_skill.py tests/test_weather_skill.py tests/test_web_search_skill.py \
  tests/test_orchestrator_verify.py tests/test_config.py -q --continue-on-collection-errors --tb=line
```

Output (tail; full 90-failure list + the collection error for `test_revoice.py`):
```
E   assert [False] == [True]

      At index 0 diff: False != True
      Use -v to get more diff
tests/test_orchestrator_verify.py:293: assert [False] == [True]
E   AttributeError: 'PersonaConfig' object has no attribute 'revoice_enabled'
.venv/lib/python3.14/site-packages/pydantic/main.py:1042: AttributeError: 'PersonaConfig' object has no attribute 'revoice_enabled'
E   AttributeError: 'PersonaConfig' object has no attribute 'revoice_enabled'
.venv/lib/python3.14/site-packages/pydantic/main.py:1042: AttributeError: 'PersonaConfig' object has no attribute 'revoice_enabled'
E   AttributeError: 'PersonaConfig' object has no attribute 'revoice_enabled'
.venv/lib/python3.14/site-packages/pydantic/main.py:1042: AttributeError: 'PersonaConfig' object has no attribute 'revoice_enabled'
E   AttributeError: 'PersonaConfig' object has no attribute 'revoice_enabled'
.venv/lib/python3.14/site-packages/pydantic/main.py:1042: AttributeError: 'PersonaConfig' object has no attribute 'revoice_enabled'
=============================== warnings summary ===============================
.venv/lib/python3.14/site-packages/webrtcvad.py:1
  .../webrtcvad.py:1: UserWarning: pkg_resources is deprecated as an API. ...

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_pipeline.py::test_wake_routes_and_speaks_reply - TypeError:...
FAILED tests/test_pipeline.py::test_speak_chunks_multi_sentence_reply - TypeE...
FAILED tests/test_pipeline.py::test_speak_single_sentence_plays_once - TypeEr...
FAILED tests/test_pipeline.py::test_unvoiced_reply_is_revoiced_before_tts - T...
FAILED tests/test_pipeline.py::test_voiced_reply_bypasses_revoicer - TypeErro...
FAILED tests/test_pipeline.py::test_no_revoicer_is_byte_identical_regardless_of_voiced
... (all test_pipeline.py tests fail: TypeError: VoicePipeline.__init__() got an
    unexpected keyword argument 'revoicer', since the _pipeline() factory now
    always passes revoicer=... to the constructor)
FAILED tests/test_general_skill.py::test_returns_llm_answer - AttributeError:...
FAILED tests/test_general_skill.py::test_empty_answer_is_unsuccessful - Attri...
FAILED tests/test_general_skill.py::test_llm_error_is_handled - AttributeErro...
FAILED tests/test_general_skill.py::test_draft_is_restyled_not_reanswered - A...
FAILED tests/test_general_skill.py::test_restyle_falls_back_to_draft_on_error
FAILED tests/test_general_skill.py::test_restyle_empty_falls_back_to_draft - ...
  (AttributeError: 'SkillResult' object has no attribute 'voiced')
FAILED tests/test_weather_skill.py::test_home_path_uses_home_coords_no_geocode
FAILED tests/test_weather_skill.py::test_unknown_location_apologizes - Attrib...
FAILED tests/test_weather_skill.py::test_provider_error_degrades_gracefully
FAILED tests/test_web_search_skill.py::test_happy_path_answers_with_attribution_and_progress
FAILED tests/test_web_search_skill.py::test_assess_bad_json_falls_back_to_plain_summary
FAILED tests/test_orchestrator_verify.py::test_pre_reject_speaks_filler_and_redecides
FAILED tests/test_orchestrator_verify.py::test_post_reject_speaks_filler_and_redecides
FAILED tests/test_orchestrator_verify.py::test_filler_silent_on_approve_and_rewrite
FAILED tests/test_orchestrator_verify.py::test_post_rewrite_replaces_speech
FAILED tests/test_orchestrator_verify.py::test_pre_reject_barge_aborts_turn
  (rec.voiced == [True] assertion fails — SayRecorder.voiced list empty/False;
   result.voiced AttributeError)
FAILED tests/test_config.py::test_revoice_defaults - AttributeError: 'Persona...
FAILED tests/test_config.py::test_revoice_loads_from_yaml - AttributeError: '...
FAILED tests/test_config.py::test_revoice_env_override - AttributeError: 'Per...
ERROR tests/test_revoice.py
  (ModuleNotFoundError: No module named 'assistant.core.revoice')
90 failed, 75 passed, 1 warning, 1 error in 0.47s
```

All failures are for the expected reason: the `Revoicer` seam, the `SkillResult.voiced`
field, and the `PersonaConfig.revoice_*` fields do not exist yet on unmodified code.

### Post-implementation (PASSING) run

Command:
```
source .venv/bin/activate && pytest tests/test_revoice.py tests/test_pipeline.py \
  tests/test_general_skill.py tests/test_weather_skill.py tests/test_web_search_skill.py \
  tests/test_orchestrator_verify.py tests/test_config.py -q
```

Output:
```
........................................................................ [ 40%]
........................................................................ [ 81%]
................................                                         [100%]
=============================== warnings summary ===============================
.venv/lib/python3.14/site-packages/webrtcvad.py:1
  .../webrtcvad.py:1: UserWarning: pkg_resources is deprecated as an API. ...

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
176 passed, 1 warning in 0.56s
```

## AC-2

End-to-end: with persona enabled (a `Revoicer` injected), an unvoiced `SkillResult`
is restyled before TTS with digits intact; a `voiced=True` result and a
persona-disabled run (`revoicer=None`) reach TTS byte-identical to the skill's own
speech.

Command:
```
pytest tests/test_pipeline.py -k "revoic" tests/test_revoice.py::test_restyles_via_stub_and_preserves_digits -v
```

Output:
```
tests/test_pipeline.py::test_unvoiced_reply_is_revoiced_before_tts PASSED [ 25%]
tests/test_pipeline.py::test_voiced_reply_bypasses_revoicer PASSED       [ 50%]
tests/test_pipeline.py::test_no_revoicer_is_byte_identical_regardless_of_voiced PASSED [ 75%]
tests/test_revoice.py::test_restyles_via_stub_and_preserves_digits PASSED [100%]

================= 4 passed, 68 deselected, 1 warning in 0.13s ==================
```

`test_unvoiced_reply_is_revoiced_before_tts`: a `FakeSkill(voiced=False)` reply is
sent through a `FakeRevoicer` before reaching `FakeTTS` (`revoicer.calls ==
["it is noon"]`, `tts.spoke == ["Ha, it is noon!"]`).
`test_voiced_reply_bypasses_revoicer`: a `FakeSkill(voiced=True)` reply never
touches the revoicer (`revoicer.calls == []`) and TTS sees the skill's speech
byte-identical.
`test_no_revoicer_is_byte_identical_regardless_of_voiced`: with `revoicer=None`
(persona disabled in `app.py`'s wiring), TTS is byte-identical to the skill's own
reply regardless of the `voiced` flag — this is PLM-003 AC-1's byte-identical
guarantee.
`test_restyles_via_stub_and_preserves_digits` (`Revoicer.revoice` directly): the
stub's styled reply keeps every digit sequence (`"3:15"`) verbatim.

## AC-3

Timeout, stub error, empty output, and both open-circuit cases (a live failure and
a seeded-unhealthy boot) all fall back to the plain string, bounded by
`revoice_timeout_s`, immediate when the circuit is already open, with a warning
logged, and the reply is never dropped.

Command:
```
pytest tests/test_revoice.py -k "timeout or error or empty or open_circuit or seeded_unhealthy or circuit_recloses" -v
```

Output:
```
tests/test_revoice.py::test_timeout_returns_plain_within_budget_and_warns PASSED [ 16%]
tests/test_revoice.py::test_stub_error_returns_plain PASSED              [ 33%]
tests/test_revoice.py::test_empty_reply_returns_plain PASSED             [ 50%]
tests/test_revoice.py::test_open_circuit_after_failure_is_immediate_zero_calls PASSED [ 66%]
tests/test_revoice.py::test_circuit_recloses_after_cooldown PASSED       [ 83%]
tests/test_revoice.py::test_seeded_unhealthy_is_immediate_passthrough_zero_calls PASSED [100%]

======================= 6 passed, 5 deselected in 0.07s ========================
```

`test_timeout_returns_plain_within_budget_and_warns`: a hanging stub (`asyncio.sleep(10)`)
with `timeout_s=0.05` returns the plain string in well under the 10s hang
(`elapsed < 1.0`) and logs a WARNING mentioning "revoice".
`test_stub_error_returns_plain` / `test_empty_reply_returns_plain`: an exception or
blank reply both fall back to the plain string.
`test_open_circuit_after_failure_is_immediate_zero_calls`: after one failure, a
second call is an immediate passthrough with **zero** further LLM calls
(`len(llm.calls) == 1` after both calls).
`test_seeded_unhealthy_is_immediate_passthrough_zero_calls`: constructing with
`healthy=False` (how `app.py` seeds the circuit from the boot LLM health check)
never calls the LLM at all (`llm.calls == []`).
`test_circuit_recloses_after_cooldown`: after `cooldown_s` elapses (fake clock),
the circuit allows a live call again.

## AC-4

A revoiced output that drops or mutates any digit sequence from the plain string
is discarded in favor of the plain string.

Command:
```
pytest tests/test_revoice.py -k digit -v
```

Output:
```
tests/test_revoice.py::test_restyles_via_stub_and_preserves_digits PASSED [ 33%]
tests/test_revoice.py::test_digit_mutation_returns_plain PASSED          [ 66%]
tests/test_revoice.py::test_digit_drop_returns_plain PASSED              [100%]

======================= 3 passed, 8 deselected in 0.01s ========================
```

`test_digit_mutation_returns_plain`: stub reply mutates "3:15" -> "4:15"; the guard
rejects it and the plain string is spoken.
`test_digit_drop_returns_plain`: stub reply drops the digits entirely; same result.

## AC-5

`revoice_enabled` and `revoice_timeout_s` are typed `PersonaConfig` fields
(`assistant/core/config.py`), mirrored in `config.yaml` and `default-config.yaml`.
`revoice_enabled=False` makes zero revoice LLM calls, while LLM-backed skill
replies (`GeneralSkill`, `WeatherSkill`, the `WebSearchSkill` plain-summary
fallback) stay flavored on their own via their persona-bearing system prompts
(marked `voiced=True`, independent of the Revoicer).

Command:
```
pytest tests/test_config.py::test_revoice_defaults tests/test_config.py::test_revoice_loads_from_yaml \
  tests/test_config.py::test_revoice_env_override tests/test_revoice.py::test_revoice_disabled_is_passthrough_zero_calls -v
```

Output:
```
tests/test_config.py::test_revoice_defaults PASSED                       [ 25%]
tests/test_config.py::test_revoice_loads_from_yaml PASSED                [ 50%]
tests/test_config.py::test_revoice_env_override PASSED                   [ 75%]
tests/test_revoice.py::test_revoice_disabled_is_passthrough_zero_calls PASSED [100%]

======================= 4 passed, 41 deselected in 0.14s =======================
```

LLM-skill replies stay flavored regardless of the Revoicer:
```
pytest tests/test_general_skill.py tests/test_weather_skill.py::test_home_path_uses_home_coords_no_geocode \
  tests/test_web_search_skill.py::test_assess_bad_json_falls_back_to_plain_summary \
  tests/test_web_search_skill.py::test_happy_path_answers_with_attribution_and_progress -v
```
```
tests/test_general_skill.py::test_returns_llm_answer PASSED              [ 10%]
tests/test_general_skill.py::test_history_precedes_current_text PASSED   [ 20%]
tests/test_general_skill.py::test_empty_answer_is_unsuccessful PASSED    [ 30%]
tests/test_general_skill.py::test_llm_error_is_handled PASSED            [ 40%]
tests/test_general_skill.py::test_draft_is_restyled_not_reanswered PASSED [ 50%]
tests/test_general_skill.py::test_restyle_falls_back_to_draft_on_error PASSED [ 60%]
tests/test_general_skill.py::test_restyle_empty_falls_back_to_draft PASSED [ 70%]
tests/test_weather_skill.py::test_home_path_uses_home_coords_no_geocode PASSED [ 80%]
tests/test_web_search_skill.py::test_assess_bad_json_falls_back_to_plain_summary PASSED [ 90%]
tests/test_web_search_skill.py::test_happy_path_answers_with_attribution_and_progress PASSED [100%]

============================== 10 passed in 0.06s ==============================
```
(`test_returns_llm_answer`/`test_draft_is_restyled_not_reanswered` assert
`result.voiced` True; the offline-failure paths assert `not result.voiced`, per
the spec's "LLM-offline failure strings stay unvoiced until FTHR-007's
templates".)

## AC-6

`ruff check assistant tests` and the full suite pass without native extras* or
network.

Commands:
```
source .venv/bin/activate && ruff check assistant tests
source .venv/bin/activate && pytest -q
```

Output:
```
All checks passed!
```
```
ss...................................................................... [  9%]
........................................................................ [ 18%]
........................................................................ [ 27%]
........................................................................ [ 36%]
........................................................................ [ 45%]
........................................................................ [ 54%]
........................................................................ [ 63%]
........................................................................ [ 72%]
........................................................................ [ 81%]
........................................................................ [ 90%]
........................................................................ [ 99%]
.                                                                        [100%]
791 passed, 2 skipped, 1 warning in 21.85s
```

\* No network was used (all LLM/HTTP calls are stubbed, per the existing test
conventions). One pre-existing, unrelated gap: `pip install -e ".[dev]"` alone is
not actually sufficient to import `assistant.core.pipeline` / `assistant.weather`
on a fresh checkout — `assistant/audio/recorder.py` imports `webrtcvad`
unconditionally and `assistant/weather/open_meteo.py` imports `httpx`
unconditionally, neither of which `[dev]` pulls in (confirmed reproducible on
unmodified `main` in a fresh venv, independent of this feather's changes). This
worktree's `.venv` was built with `pip install -e ".[dev,all,tui]"` to match what
the main repo's own `.venv` actually has installed, and no native/device/model
code path was exercised — everything above is stub-only.
