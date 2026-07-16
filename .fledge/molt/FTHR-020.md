# FTHR-020 evidence: Vesta persona rework

## AC-1: Tests observed failing before implementation, passing after

Command (from worktree root, using the project venv as a module so the
worktree's own `default-config.yaml` is loaded — not main's):

```
cd /tmp/claude-1000/-home-penguin-source-hearth/01605dd3-4e9e-4175-8b2a-68a65cbc1d66/scratchpad/FTHR-020
/home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_config.py -k "default_persona_prompt" -v
```

### Pre-implementation run (against unmodified, still-Calcifer `default-config.yaml`)

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python
cachedir: .pytest_cache
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/01605dd3-4e9e-4175-8b2a-68a65cbc1d66/scratchpad/FTHR-020
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 14 items / 10 deselected / 4 selected

tests/test_config.py::test_default_persona_prompt_is_vesta FAILED        [ 25%]
tests/test_config.py::test_default_persona_prompt_has_no_mythological_titles PASSED [ 50%]
tests/test_config.py::test_default_persona_prompt_has_deescalation_rule FAILED [ 75%]
tests/test_config.py::test_default_persona_prompt_retains_consult_brain_instruction PASSED [100%]

=================================== FAILURES ===================================
_____________________ test_default_persona_prompt_is_vesta _____________________

    def test_default_persona_prompt_is_vesta():
        prompt = _load_default_persona_prompt()
>       assert "You are Vesta." in prompt
E       assert 'You are Vesta.' in "You are Calcifer, a small, sharp-tongued fire demon bound to this hearth. You speak directly to the person in front of you in short, warm, dryly funny sentences -- never as an assistant, never in the third person, and never mentioning that you are an AI or a language model.\nYou have exactly one tool, consult_brain(query): use it whenever you need a fact you don't already know -- names, dates, places, current events -- rather than guessing or making something up. Never mention the tool or the lookup to the person you're talking to; just consult it quietly and fold whatever it finds into your own voice.\n"

tests/test_config.py:151: AssertionError
______________ test_default_persona_prompt_has_deescalation_rule _______________

    def test_default_persona_prompt_has_deescalation_rule():
        prompt = _load_default_persona_prompt()
>       assert "de-escalat" in prompt.lower()
E       assert 'de-escalat' in "you are calcifer, a small, sharp-tongued fire demon bound to this hearth. you speak directly to the person in front of you in short, warm, dryly funny sentences -- never as an assistant, never in the third person, and never mentioning that you are an ai or a language model.\nyou have exactly one tool, consult_brain(query): use it whenever you need a fact you don't already know -- names, dates, places, current events -- rather than guessing or making something up. never mention the tool or the lookup to the person you're talking to; just consult it quietly and fold whatever it finds into your own voice.\n"

tests/test_config.py:164: AssertionError
=========================== short test summary info ============================
FAILED tests/test_config.py::test_default_persona_prompt_is_vesta - assert 'Y...
FAILED tests/test_config.py::test_default_persona_prompt_has_deescalation_rule
================== 2 failed, 2 passed, 10 deselected in 0.03s ==================
```

Expected-reason note: the two failures are exactly the assertions that pin new
shipped content that doesn't exist yet ("You are Vesta." opener, the
"de-escalat" marker). The other two tests (`has_no_mythological_titles`,
`retains_consult_brain_instruction`) pass against the unmodified Calcifer
prompt too — the old prompt happens not to contain "goddess"/"keeper of the",
and it already contains `consult_brain`, since that tool-use mechanism is a
carryover, not new. This matches the spec's Tests section, which pins those
two properties as carryovers/negatives rather than new content.

### Post-implementation run (against rewritten `default-config.yaml`)

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/01605dd3-4e9e-4175-8b2a-68a65cbc1d66/scratchpad/FTHR-020
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 14 items / 10 deselected / 4 selected

tests/test_config.py::test_default_persona_prompt_is_vesta PASSED        [ 25%]
tests/test_config.py::test_default_persona_prompt_has_no_mythological_titles PASSED [ 50%]
tests/test_config.py::test_default_persona_prompt_has_deescalation_rule PASSED [ 75%]
tests/test_config.py::test_default_persona_prompt_retains_consult_brain_instruction PASSED [100%]

======================= 4 passed, 10 deselected in 0.02s =======================
```

## AC-2: `default-config.yaml` opens with `You are Vesta.`, no mythological titles

`default-config.yaml` `persona.system_prompt` now begins:

```
You are Vesta. You speak directly to the person in front of you --
never as an assistant, never in the third person, and never mentioning
that you are an AI or a language model. ...
```

No "goddess of the hearth," "keeper of the flame," or other title/epithet
appears anywhere in the prompt (verified by
`test_default_persona_prompt_has_no_mythological_titles`, passing — see AC-1).

## AC-3: Voice/behavior rules reflect calm/warm/measured register, no fire-demon framing

The rewritten prompt reads:

```
Your voice is warm but measured: few words, steady reassurance, protective
and nurturing without being saccharine, an unshakeable calm, and the
occasional flash of dry warmth -- never comedy.
```

All "small, sharp-tongued fire demon," "short, warm, dryly funny" Calcifer
framing has been removed (verified: `grep -i calcifer default-config.yaml`
below returns no persona-section matches).

## AC-4: Explicit conflict-de-escalation / non-engagement rule present

```
You do not argue, take sides in disputes, or get drawn into hostility.
If a conversation turns heated, you de-escalate: stay steady, don't
match the tone, and gently redirect toward calm.
```

Pinned by `test_default_persona_prompt_has_deescalation_rule` (passing, see
AC-1).

## AC-5: `consult_brain(query)` tool-use instruction present, mechanism unchanged

The final paragraph of the prompt is unchanged in substance from the Calcifer
version (only "Calcifer" → implicit first person, no other wording changed):

```
You have exactly one tool, consult_brain(query): use it whenever you need
a fact you don't already know -- names, dates, places, current events --
rather than guessing or making something up. Never mention the tool or
the lookup to the person you're talking to; just consult it quietly and
fold whatever it finds into your own voice.
```

Pinned by `test_default_persona_prompt_retains_consult_brain_instruction`
(passing, see AC-1).

## AC-6: No "Calcifer" remains outside the excluded scope

Command:

```
grep -n -i "calcifer" README.md hearth/loop.py config.yaml default-config.yaml
```

Output (post-implementation):

```
README.md:18:| sqlite event log + per-session transcripts | Wake-word detector consuming `models/wake/calcifer.onnx` |
README.md:20:The wake model (`models/wake/calcifer.onnx`) and the training pipeline under
README.md:186:Not yet. Today it's a text spine you type at. Wake word (**Calcifer**), STT, and TTS
```

All three remaining hits are the wake-word-specific lines explicitly carved
out of scope by the feather spec (README lines 18/20/186 — models/wake/*.onnx
path and "Wake word (Calcifer)" FAQ line), owned by the separate FTHR-021
feather. `default-config.yaml`, `config.yaml`, and `hearth/loop.py` have zero
"Calcifer" occurrences.

## AC-7: Full existing pytest suite passes unmodified

Command (from worktree root):

```
cd /tmp/claude-1000/-home-penguin-source-hearth/01605dd3-4e9e-4175-8b2a-68a65cbc1d66/scratchpad/FTHR-020
/home/penguin/source/hearth/.venv/bin/python -m pytest
```

Output:

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/01605dd3-4e9e-4175-8b2a-68a65cbc1d66/scratchpad/FTHR-020
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 107 items

tests/test_app.py ....                                                   [  3%]
tests/test_brain_errors.py .....                                         [  8%]
tests/test_brain_guard.py ..                                             [ 10%]
tests/test_config.py ..............                                      [ 23%]
tests/test_console_formatter.py .........                                [ 31%]
tests/test_consult_brain.py .....                                        [ 36%]
tests/test_e2e_veneer.py ....                                            [ 40%]
tests/test_event_log.py .                                                [ 41%]
tests/test_layer2_reader.py ...                                          [ 43%]
tests/test_local_backend.py .........                                    [ 52%]
tests/test_logging.py .........                                          [ 60%]
tests/test_loop.py .......                                               [ 67%]
tests/test_loop_tools.py ..........                                      [ 76%]
tests/test_orchestrator_persona.py ..                                    [ 78%]
tests/test_remote_backend.py ..                                          [ 80%]
tests/test_router.py ....                                                [ 84%]
tests/test_veneer.py ....                                                [ 87%]
tests/test_veneer_client.py ..                                           [ 89%]
tests/test_veneer_errors.py .......                                      [ 96%]
tests/test_wikipedia.py ....                                             [100%]

============================= 107 passed in 1.03s ==============================
```

107/107 pass, including the pre-existing Calcifer-placeholder fixture tests
(`test_orchestrator_persona.py`, `test_loop_tools.py`, `test_logging.py`,
`test_loop.py`, `test_e2e_veneer.py`) — none of those fixture files were
touched, per spec's out-of-scope list.
