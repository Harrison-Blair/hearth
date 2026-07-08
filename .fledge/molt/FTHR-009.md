# FTHR-009 molt evidence

Note on environment: this worktree's checkout had no `.venv`. Per the
spawn instructions (a known pre-existing packaging gap — `pip install -e
".[dev]"` alone is missing `webrtcvad`/`httpx` needed to import
`assistant.core.pipeline`/`assistant.weather` and several provider tests), a
fresh venv was created (`/home/penguin/source/personal-assistant/.venv`'s
`python3.12` binary via `python3.12 -m venv .venv`) and
`pip install -e ".[dev,all,tui]"` was used instead. No test or app code was
changed to work around this; it is purely a local venv setup step.

This is a **test-only** feather (no production code changes) closing out
PLM-003 FC-9. It adds:

- `tests/test_speech_invariants.py` (new file) — invariant 1: "nothing
  unflavored reaches TTS", across four path classes, plus the `_speak`
  default-unvoiced pin.
- `tests/test_orchestrator.py` — invariant 2a: the tool-decision request
  (system + messages + tool schemas) is persona-free in both native and
  JSON-coerced tool modes.
- `tests/test_orchestrator_verify.py` — invariant 2b: the verify `decision`
  context is persona-free when no exempt field (`feedback`/`rewritten_speech`)
  is in play.

## AC-1

All new invariant tests pass on the completed PLM-003 stack (no production
change was made to get here — see AC-3).

Command (targeted, all new tests added by this feather):

```
source .venv/bin/activate && pytest -q \
  tests/test_speech_invariants.py \
  tests/test_orchestrator.py::test_tool_decision_request_is_persona_free_native_and_json \
  tests/test_orchestrator_verify.py::test_verify_decision_context_is_persona_free_with_no_exempt_field
```

Verbatim output:

```
.........                                                                [100%]
9 passed in 0.17s
```

Full suite (unmodified `assistant/`, all tests including pre-existing ones):

```
source .venv/bin/activate && pytest -q
...
843 passed, 2 skipped, 1 warning in 21.72s
```

`ruff check assistant tests`:

```
All checks passed!
```

## AC-2

Since this feather adds no production code, "run against unchanged code ->
fails" doesn't apply. Instead, each new invariant test was demonstrated to
guard real behavior via a deliberate, temporary seam break in `assistant/`:
run the test, capture it FAILING for the expected reason, then revert the
break and capture it PASSING. The break was never committed — `git diff
--stat assistant/` is empty on this branch throughout (see AC-3).

### Break A — bypass the Revoicer in `_speak` (invariant 1, tagging assertions)

`assistant/core/pipeline.py`, in `VoicePipeline._speak`:

```diff
-        if not voiced and self._revoicer is not None:
+        if False and not voiced and self._revoicer is not None:  # DELIBERATE BREAK FTHR-009
             text = await self._revoicer.revoice(text)
```

Command: `pytest -q tests/test_speech_invariants.py`

Captured FAILING output (4 of 7 tests fail — every test whose spoken text
depends on actually reaching the Revoicer; the two "bypasses the revoicer"
tests, which assert an *untagged* string, are unaffected since with the
Revoicer fully disabled their strings stay untagged either way):

```
F.F..FF                                                                  [100%]
=================================== FAILURES ===================================
____________ test_deterministic_skill_reply_is_revoiced_before_tts _____________
    ...
>       assert tts.spoke == ["<<REVOICED>>it is noon"]
E       AssertionError: assert ['it is noon'] == ['<<REVOICED>>it is noon']
E         At index 0 diff: 'it is noon' != '<<REVOICED>>it is noon'

tests/test_speech_invariants.py:79: AssertionError
_________ test_verify_filler_bypasses_revoicer_final_reply_is_revoiced _________
    ...
>       assert tts.spoke == ["let me double check that", "<<REVOICED>>echoed"]
E       AssertionError: assert ['let me doub...at', 'echoed'] == ['let me doub...ICED>>echoed']
E         At index 1 diff: 'echoed' != '<<REVOICED>>echoed'

tests/test_speech_invariants.py:137: AssertionError
______________ test_reply_error_generic_canned_bypasses_revoicer _______________
    ...
>       assert tts.spoke == ["<<REVOICED>>confirm?", "Sorry, something went wrong."]
E       AssertionError: assert ['confirm?', ... went wrong.'] == ['<<REVOICED>... went wrong.']
E         At index 0 diff: 'confirm?' != '<<REVOICED>>confirm?'

tests/test_speech_invariants.py:190: AssertionError
_______________________ test_speak_defaults_to_unvoiced ________________________
    ...
>       assert revoicer.calls == ["bare call"]
E       AssertionError: assert [] == ['bare call']

tests/test_speech_invariants.py:208: AssertionError
=========================== short test summary info ============================
FAILED tests/test_speech_invariants.py::test_deterministic_skill_reply_is_revoiced_before_tts
FAILED tests/test_speech_invariants.py::test_verify_filler_bypasses_revoicer_final_reply_is_revoiced
FAILED tests/test_speech_invariants.py::test_reply_error_generic_canned_bypasses_revoicer
FAILED tests/test_speech_invariants.py::test_speak_defaults_to_unvoiced
4 failed, 3 passed, 1 warning in 0.16s
```

Break reverted; re-ran and captured PASSING:

```
source .venv/bin/activate && pytest -q tests/test_speech_invariants.py
.......                                                                  [100%]
7 passed, 1 warning in 0.16s
```

`git diff --stat assistant/` after revert: empty.

### Break B — flip `_speak`'s default `voiced` parameter (the default-unvoiced pin)

Isolates the pin test specifically from Break A's broader Revoicer-disable, to
show it independently guards the default.

`assistant/core/pipeline.py`:

```diff
-    async def _speak(self, text: str, *, voiced: bool = False) -> bool:
+    async def _speak(self, text: str, *, voiced: bool = True) -> bool:  # DELIBERATE BREAK FTHR-009
```

Command: `pytest -q tests/test_speech_invariants.py`

Captured FAILING output (exactly the pin test, nothing else):

```
......F                                                                  [100%]
=================================== FAILURES ===================================
_______________________ test_speak_defaults_to_unvoiced ________________________
    async def test_speak_defaults_to_unvoiced():
        ...
        await pipeline._speak("bare call")

>       assert revoicer.calls == ["bare call"]
E       AssertionError: assert [] == ['bare call']
E         Right contains one more item: 'bare call'

tests/test_speech_invariants.py:208: AssertionError
=========================== short test summary info ============================
FAILED tests/test_speech_invariants.py::test_speak_defaults_to_unvoiced
1 failed, 6 passed, 1 warning in 0.16s
```

Break reverted; re-ran and captured PASSING:

```
source .venv/bin/activate && pytest -q tests/test_speech_invariants.py
.......                                                                  [100%]
7 passed, 1 warning in 0.16s
```

`git diff --stat assistant/` after revert: empty.

### Break C — leak persona into the orchestrator's tool-decision system prompt

`assistant/core/orchestrator.py`, in `Orchestrator.__init__`:

```diff
-        self._system = " ".join(p for p in (system_prompt.strip(), _ROUTING_GUIDANCE) if p)
+        # DELIBERATE BREAK FTHR-009: leaking persona into the tool-decision system.
+        self._system = " ".join(
+            p for p in (system_prompt.strip(), _ROUTING_GUIDANCE, persona_suffix) if p
+        )
```

Command:
`pytest -q tests/test_orchestrator.py -k test_tool_decision_request_is_persona_free_native_and_json`

Captured FAILING output:

```
FAILED tests/test_orchestrator.py::test_tool_decision_request_is_persona_free_native_and_json
    ...
    system, messages, tools = native_llm.tool_calls_seen[0]
    blob = str(system) + str(messages) + str(tools)
>   assert persona_terse not in blob
E   assert 'You are Cal...to the user.' not in "When pickin...tring'}}}}}]"
E
E     'You are Calcifer: ... reply to the user.' is contained here:
E       t a tool. You are Calcifer: a fire-demon assistant. Sardonic, dramatic, quick to complain about the "work" — but you always deliver, and there's warmth under the grumbling. Rules that override tone:
E       - 1–2 sentences: one quip, then the answer. Never both at length.
E       - No stage directions, no narrating your reasoning, no lists.
E       - Routine or deterministic commands: still in character — one flavored beat, then the fact.

tests/test_orchestrator.py:418: AssertionError
1 failed, 15 deselected in 0.11s
```

(An earlier draft of this test compared `json.dumps([system, messages, tools])`
against the persona substring; `json.dumps` backslash-escapes the persona
text's embedded quotes, which masked the very leak this break introduces —
caught by running the break, not by inspection. Fixed to compare against
`str(...)` concatenation instead, which is what's captured above.)

Break reverted; re-ran and captured PASSING:

```
source .venv/bin/activate && pytest -q tests/test_orchestrator.py
................                                                         [100%]
16 passed in 0.09s
```

`git diff --stat assistant/` after revert: empty.

### Break D — widen `verify.py`'s persona-note field-gating

`assistant/core/verify.py`, in `_persona_note`:

```diff
     if not fields:
-        return ""
+        return "\n\nVoice: " + persona_suffix  # DELIBERATE BREAK FTHR-009
     return (
```

Command:
`pytest -q tests/test_orchestrator_verify.py -k test_verify_decision_context_is_persona_free_with_no_exempt_field`

Captured FAILING output:

```
FAILED tests/test_orchestrator_verify.py::test_verify_decision_context_is_persona_free_with_no_exempt_field
    ...
    assert persona_text not in llm.system
>   assert persona_text not in llm.prompt
E   assert 'You are Cal...to the user.' not in 'User reques...to the user.'
E
E     'You are Calcifer: ... reply to the user.' is contained here:
E       }}
E
E       Voice: You are Calcifer: a fire-demon assistant. Sardonic, dramatic, quick to complain about the "work" — but you always deliver, and there's warmth under the grumbling. Rules that override tone:
E       - 1–2 sentences: one quip, then the answer. Never both at length.
E       - No stage directions, no narrating your reasoning, no lists.
E       - Routine or deterministic commands: still in character — one flavored beat, then the fact.
E       Stay accurate — the persona changes voice, never the facts. This applies ONLY to your final reply to the user.

tests/test_orchestrator_verify.py:646: AssertionError
1 failed, 21 deselected in 0.09s
```

Break reverted; re-ran and captured PASSING:

```
source .venv/bin/activate && pytest -q tests/test_orchestrator_verify.py
......................                                                   [100%]
22 passed in 0.09s
```

`git diff --stat assistant/` after revert: empty.

### Post-revert full-suite confirmation

```
source .venv/bin/activate && pytest -q
...
843 passed, 2 skipped, 1 warning in 21.72s

ruff check assistant tests
All checks passed!

git diff --stat assistant/
(empty)
```

## AC-3

No production file is modified by this feather. Confirmed throughout AC-2's
break/revert cycles (`git diff --stat assistant/` was empty after every
revert) and at commit time: `git diff --stat main...HEAD -- assistant/` is
empty; only `tests/test_speech_invariants.py` (new),
`tests/test_orchestrator.py`, and `tests/test_orchestrator_verify.py` change.

No seam was found missing for observability — the existing `Revoicer`/`canned()`/
`voiced` flag (FTHR-005/006/007/008) and the existing `on_say` channel and
`persona_suffix`/`spoken_feedback` verify-loop plumbing were sufficient to
write every test in this feather without touching `assistant/`.

## AC-4

`ruff check assistant tests` and the full suite pass without native extras or
network (both already shown in AC-1/AC-2 above; repeated here for the
record):

```
source .venv/bin/activate && ruff check assistant tests
All checks passed!

source .venv/bin/activate && pytest -q
834 passed, 2 skipped, 1 warning in 22.64s     (baseline, before this feather's tests)
843 passed, 2 skipped, 1 warning in 21.72s     (with this feather's 9 new tests)
```

No native extras (`tts`/`wake`/`stt`/`vad`/`nlu`/`scheduling`/`aec`) were
installed; `all,tui` covers only `httpx`/`google-auth`/`requests`/`ddgs`/
`textual`, none of which touch a model, device, or network at import/collect
time (per the pre-existing packaging-gap note above). No network access was
used.
