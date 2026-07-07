# FTHR-007 molt evidence

Note on environment: this worktree's checkout predates a `.venv`. Per the
brooder's spawn instructions (a known pre-existing packaging gap — `pip
install -e ".[dev]"` alone is missing `webrtcvad`/`httpx` needed to import
`assistant.core.pipeline`/`assistant.weather`), a fresh venv was created here
and `pip install -e ".[dev,all,tui]"` was used instead. No test or app code
was changed to work around this; it is purely a local venv setup step.

## AC-1

The spec's Tests section names new/extended tests in `tests/test_pipeline.py`,
`tests/test_general_skill.py`, `tests/test_update_skill.py`, and (for
`skills/base.py`'s fallback) a new `tests/test_skill_base.py`. All were written
first and run against the unmodified code.

### Pre-implementation: FAILING for the expected reason

Command (targeted, all the new/extended tests for this feather):

```
source .venv/bin/activate && pytest -q \
  "tests/test_pipeline.py::test_skill_exception_persona_enabled_speaks_canned_variant_voiced" \
  "tests/test_pipeline.py::test_cant_help_persona_disabled_is_byte_identical" \
  "tests/test_pipeline.py::test_cant_help_persona_enabled_speaks_canned_variant_voiced" \
  "tests/test_pipeline.py::test_reply_error_generic_persona_disabled_is_byte_identical" \
  "tests/test_pipeline.py::test_reply_error_generic_persona_enabled_speaks_canned_variant_voiced" \
  "tests/test_general_skill.py::test_empty_answer_is_unsuccessful" \
  "tests/test_general_skill.py::test_llm_error_is_handled" \
  "tests/test_general_skill.py::test_llm_error_persona_enabled_carries_registry_variant" \
  "tests/test_general_skill.py::test_no_answer_persona_enabled_carries_registry_variant" \
  "tests/test_update_skill.py::test_confirm_persona_disabled_is_byte_identical_and_voiced" \
  "tests/test_update_skill.py::test_confirm_persona_enabled_uses_seeded_rng_for_a_deterministic_variant" \
  "tests/test_skill_base.py::test_unexpected_reply_fallback_is_byte_identical_when_persona_disabled" \
  "tests/test_skill_base.py::test_unexpected_reply_fallback_carries_registry_variant_when_persona_enabled"
```

Verbatim output (unmodified `assistant/`):

```
FAILED tests/test_pipeline.py::test_skill_exception_persona_enabled_speaks_canned_variant_voiced
FAILED tests/test_pipeline.py::test_cant_help_persona_disabled_is_byte_identical
FAILED tests/test_pipeline.py::test_cant_help_persona_enabled_speaks_canned_variant_voiced
FAILED tests/test_pipeline.py::test_reply_error_generic_persona_disabled_is_byte_identical
FAILED tests/test_pipeline.py::test_reply_error_generic_persona_enabled_speaks_canned_variant_voiced
FAILED tests/test_general_skill.py::test_empty_answer_is_unsuccessful - asser...
FAILED tests/test_general_skill.py::test_llm_error_is_handled - assert False
FAILED tests/test_general_skill.py::test_llm_error_persona_enabled_carries_registry_variant
FAILED tests/test_general_skill.py::test_no_answer_persona_enabled_carries_registry_variant
FAILED tests/test_update_skill.py::test_confirm_persona_disabled_is_byte_identical_and_voiced
FAILED tests/test_update_skill.py::test_confirm_persona_enabled_uses_seeded_rng_for_a_deterministic_variant
FAILED tests/test_skill_base.py::test_unexpected_reply_fallback_is_byte_identical_when_persona_disabled
FAILED tests/test_skill_base.py::test_unexpected_reply_fallback_carries_registry_variant_when_persona_enabled
13 failed, 1 warning in 0.22s
```

Representative failure reasons (verbatim tracebacks, one per new construct
touched — all failing on the missing plumbing this feather adds, never on a
setup/import error):

```
E       TypeError: VoicePipeline.__init__() got an unexpected keyword argument 'persona_enabled'. Did you mean 'decision_enabled'?
tests/test_pipeline.py:221: TypeError

    async def test_empty_answer_is_unsuccessful():
        result = await GeneralSkill(FakeLLM(""), "x").handle(Command("?"), Intent("general"))
        assert not result.success
        assert result.speech == "Sorry, I don't have an answer for that."
        # FTHR-007: canned() at the speak site marks it voiced -> the Revoicer
        # seam never tries to restyle a template.
>       assert result.voiced
E       assert False
E        +  where False = SkillResult(speech="Sorry, I don't have an answer for that.", data=None, success=False, expects_reply=False, restart=False, voiced=False).voiced

tests/test_general_skill.py:63: AssertionError

___________ test_llm_error_persona_enabled_carries_registry_variant ____________
    async def test_llm_error_persona_enabled_carries_registry_variant():
>       skill = GeneralSkill(FakeLLM(exc=RuntimeError("boom")), "x", persona_enabled=True)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       TypeError: GeneralSkill.__init__() got an unexpected keyword argument 'persona_enabled'

tests/test_general_skill.py:75: TypeError

__ test_confirm_persona_disabled_is_byte_identical_and_voiced __
    def _skill(persona_enabled=False, rng=None):
>       return UpdateSkill(persona_enabled=persona_enabled, rng=rng)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       TypeError: UpdateSkill() takes no arguments

tests/test_update_skill.py:11: TypeError

____ test_unexpected_reply_fallback_is_byte_identical_when_persona_disabled ____
    async def test_unexpected_reply_fallback_is_byte_identical_when_persona_disabled():
        result = await _StubSkill().handle_reply(Command("out of the blue"))
        assert not result.success
        assert result.speech == "Sorry, I wasn't expecting a reply."
>       assert result.voiced  # canned() at the return site -> Revoicer never touches it
        ^^^^^^^^^^^^^^^^^^^^
E       assert False
E        +  where False = SkillResult(speech="Sorry, I wasn't expecting a reply.", data=None, success=False, expects_reply=False, restart=False, voiced=False).voiced

tests/test_skill_base.py:28: AssertionError
```

Each failure is for the expected reason: the constructor/attribute the test
exercises doesn't exist yet (`persona_enabled` kwarg, `rng` kwarg) or the
current code doesn't yet mark the result `voiced=True` — never a setup/import
error or a wrong-test-name error.

### Post-implementation: PASSING

Same command, after implementing `pipeline.py`, `skills/general.py`,
`skills/base.py`, `skills/update.py`, `app.py`:

```
tests/test_pipeline.py .....                                             [ 38%]
tests/test_general_skill.py ....                                         [ 69%]
tests/test_update_skill.py ..                                            [ 84%]
tests/test_skill_base.py ..                                              [100%]
13 passed, 1 warning in 0.13s
```

## AC-2

All FC-7 call sites speak registry variants when persona is enabled and the
exact current literals when disabled:

- `pipeline.py` `_handle`'s orchestration-failure site and `_dispatch_reply`'s
  skill-crash site → `canned("error_generic", enabled=...)`.
- `pipeline.py` `_handle`'s `result is None` site → `canned("cant_help", enabled=...)`.
- `skills/general.py`'s LLM-exception site → `canned("llm_offline", enabled=...)`;
  empty-answer site → `canned("no_answer", enabled=...)`.
- `skills/update.py`'s `handle_reply` confirm branch → `canned("update_signoff", enabled=..., rng=...)`.
- `skills/base.py`'s default `handle_reply` fallback → `canned("unexpected_reply", enabled=self.persona_enabled)`.

Command:

```
source .venv/bin/activate && pytest -q tests/test_pipeline.py tests/test_general_skill.py tests/test_update_skill.py tests/test_skill_base.py
```

Output:

```
........................................................................ [ 78%]
....................                                                     [100%]
92 passed, 1 warning in 0.26s
```

Disabled-byte-identical is pinned by (all passing): `test_skill_exception_is_spoken_and_loop_survives`
(`tts.spoke == ["Sorry, something went wrong."]`), `test_cant_help_persona_disabled_is_byte_identical`
(`"Sorry, I can't help with that yet."`), `test_reply_error_generic_persona_disabled_is_byte_identical`
(`["confirm?", "Sorry, something went wrong."]`), `test_empty_answer_is_unsuccessful` /
`test_llm_error_is_handled` (exact current strings), `test_confirm_persona_disabled_is_byte_identical_and_voiced`
(`"Restarting now."`), `test_unexpected_reply_fallback_is_byte_identical_when_persona_disabled`
(`"Sorry, I wasn't expecting a reply."`).

Enabled-variant is pinned by: `test_skill_exception_persona_enabled_speaks_canned_variant_voiced`,
`test_cant_help_persona_enabled_speaks_canned_variant_voiced`,
`test_reply_error_generic_persona_enabled_speaks_canned_variant_voiced`,
`test_llm_error_persona_enabled_carries_registry_variant`,
`test_no_answer_persona_enabled_carries_registry_variant`,
`test_confirm_persona_enabled_uses_seeded_rng_for_a_deterministic_variant` (seeded rng ->
deterministic variant, matched against `persona.canned(..., rng=random.Random(1))` directly),
`test_unexpected_reply_fallback_carries_registry_variant_when_persona_enabled`.

## AC-3

Template lines are voiced at their source (`voiced=True` on every `SkillResult`
or `_speak(..., voiced=True)` call this feather touches), so the pipeline's
Revoicer seam (`_speak`: `if not voiced and self._revoicer is not None: ...`)
never restyles them. Each persona-enabled test above wires a spy `FakeRevoicer`
and asserts zero (or exactly the *other*, still-unvoiced text's) calls:

- `test_skill_exception_persona_enabled_speaks_canned_variant_voiced`:
  `revoicer.calls == []`.
- `test_cant_help_persona_enabled_speaks_canned_variant_voiced`:
  `revoicer.calls == []`.
- `test_reply_error_generic_persona_enabled_speaks_canned_variant_voiced`:
  `revoicer.calls == ["confirm?"]` — only the *unrelated*, still-unvoiced
  "confirm?" prompt (asked by `UpdateSkill`-style `expects_reply`, not part of
  this feather) reaches the revoicer; the canned error line never does.
- `test_llm_error_persona_enabled_carries_registry_variant` /
  `test_no_answer_persona_enabled_carries_registry_variant`: assert
  `result.voiced` directly on the `SkillResult` (no revoicer spy needed at the
  skill layer — `voiced=True` is the pipeline's own gate).
- `test_confirm_persona_enabled_uses_seeded_rng_for_a_deterministic_variant` /
  `test_unexpected_reply_fallback_carries_registry_variant_when_persona_enabled`:
  same, `result.voiced` asserted directly.

Command/output: see AC-1's post-implementation run above (all these tests are
in that run and pass).

## AC-4

Grep-clean: no literal spoken string for these five messages (plus the three
former `_SIGNOFFS` lines) remains anywhere in `assistant/` outside `persona.py`.

Commands + output:

```
$ grep -rn "Sorry, something went wrong\." assistant/
assistant/core/persona.py:64:        "Sorry, something went wrong.",

$ grep -rn "Sorry, I can't help with that yet\." assistant/
assistant/core/persona.py:72:        "Sorry, I can't help with that yet.",
assistant/core/persona.py:74:            "That's not a trick I know. Sorry, I can't help with that yet.",

$ grep -rn "Sorry, I couldn't reach my language model\." assistant/
assistant/core/persona.py:80:        "Sorry, I couldn't reach my language model.",

$ grep -rn "Sorry, I don't have an answer for that\." assistant/
assistant/core/persona.py:88:        "Sorry, I don't have an answer for that.",

$ grep -rn "Sorry, I wasn't expecting a reply\." assistant/
assistant/core/persona.py:96:        "Sorry, I wasn't expecting a reply.",

$ grep -rn "_SIGNOFFS\|Ugh, fine — dousing myself\|Right, going dark for a second\|Fine, fine — reloading" assistant/
assistant/core/persona.py:106:            "Ugh, fine — dousing myself. Don't let the logs go cold.",
assistant/core/persona.py:107:            "Right, going dark for a second. Try not to miss me.",
assistant/core/persona.py:108:            "Fine, fine — reloading. Don't touch my wood while I'm gone.",
```

Every match is inside `assistant/core/persona.py`'s `_CANNED` registry — none
remain at any of the swapped call sites. (`_SIGNOFFS` itself no longer exists
in `assistant/skills/update.py`; the old tuple and the `random.choice` call on
it were removed.)

`ruff check` and the full suite:

```
$ ruff check assistant tests
All checks passed!

$ pytest -q
828 passed, 2 skipped, 1 warning in 20.93s
```

(The 2 skips are pre-existing offline eval-harness gates — `ASSISTANT_EVAL`/no
Ollama and an empty `tests/eval/captures/` baseline — unrelated to this
feather.)
