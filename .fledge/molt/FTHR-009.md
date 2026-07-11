# FTHR-009 molt evidence

Note on provenance: an earlier brooder session died mid-implementation on this
feather. This evidence file was lost with it. The implementation and test
files it left behind (uncommitted, in this worktree) were audited against the
spec, one factual test bug was found and fixed (see AC-1), and the
test-first failing capture below was genuinely re-derived by reverting the
implementation-side changes (keeping the test files) and re-running the full
suite against the unimplemented production code.

## AC-1: tests observed failing before implementation, passing after

**Re-derivation method.** The implementation files (`config.yaml`,
`default-config.yaml`, `hearth/app.py`, `hearth/brain/router.py`,
`hearth/config.py`, `hearth/loop.py`) were stashed back to their pre-feather
state (`git stash push -- <those files>`) and the new `hearth/tools/consult.py`
was moved out of the tree, while every test file (reworked and new) stayed in
place. The full suite was then run against that unimplemented tree.

Command: `.venv/bin/python -m pytest -q --continue-on-collection-errors`
(run from the worktree root, using the shared repo venv).

Verbatim output (pre-implementation, unimplemented production code):

```
==================================== ERRORS ====================================
_________________ ERROR collecting tests/test_consult_brain.py _________________
ImportError while importing test module '.../tests/test_consult_brain.py'.
tests/test_consult_brain.py:15: in <module>
    from hearth.tools.consult import BrainConsult
E   ModuleNotFoundError: No module named 'hearth.tools.consult'
__________________ ERROR collecting tests/test_e2e_veneer.py ___________________
tests/test_e2e_veneer.py:35: in <module>
    from hearth.tools.consult import BrainConsult
E   ModuleNotFoundError: No module named 'hearth.tools.consult'
__________________ ERROR collecting tests/test_loop_tools.py ___________________
tests/test_loop_tools.py:17: in <module>
    from hearth.tools.consult import BrainConsult
E   ModuleNotFoundError: No module named 'hearth.tools.consult'
_____________ ERROR collecting tests/test_orchestrator_persona.py ______________
tests/test_orchestrator_persona.py:15: in <module>
    from hearth.tools.consult import BrainConsult
E   ModuleNotFoundError: No module named 'hearth.tools.consult'
=================================== FAILURES ===================================
_______________ test_run_daemon_wires_wikipedia_tool_brain_side ________________
>       registry = captured["loop"]._consult._tool_registry
E       AttributeError: 'Loop' object has no attribute '_consult'
tests/test_app.py:34: AttributeError
__________________ test_loop_multi_turn_reconstructs_history ___________________
>       assert second_contents == [PERSONA_PROMPT, "first message", "answer 1", "second message"]
E       AssertionError: assert ['first messa...cond message'] == ['You are Cal...cond message']
E         At index 0 diff: 'first message' != 'You are Calcifer.'
E         Right contains one more item: 'second message'
tests/test_loop.py:89: AssertionError
________________ test_brain_available_true_when_remote_enabled _________________
>       assert router.brain_available() is True
E       AttributeError: 'Router' object has no attribute 'brain_available'
tests/test_router.py:79: AttributeError
_______________ test_brain_available_false_when_remote_disabled ________________
>       assert router.brain_available() is False
E       AttributeError: 'Router' object has no attribute 'brain_available'
tests/test_router.py:84: AttributeError
=========================== short test summary info ============================
FAILED tests/test_app.py::test_run_daemon_wires_wikipedia_tool_brain_side - AttributeError: 'Loop' object has no attribute '_consult'
FAILED tests/test_loop.py::test_loop_multi_turn_reconstructs_history - AssertionError: assert ['first messa...cond message'] == ['You are Cal...co...
FAILED tests/test_router.py::test_brain_available_true_when_remote_enabled - AttributeError: 'Router' object has no attribute 'brain_available'
FAILED tests/test_router.py::test_brain_available_false_when_remote_disabled - AttributeError: 'Router' object has no attribute 'brain_available'
ERROR tests/test_consult_brain.py
ERROR tests/test_e2e_veneer.py
ERROR tests/test_loop_tools.py
ERROR tests/test_orchestrator_persona.py
4 failed, 26 passed, 4 errors in 0.13s
```

All failures/errors are for the expected reasons named in the spec's
Implementation order note: the new modules fail on missing
`hearth.tools.consult`/`Router.brain_available`, and the reworked
`test_loop.py`/`test_app.py` assertions fail against the old (non-persona,
non-`_consult`) `Loop`. `test_select_default_ignores_tools_available` and
`test_select_tier_override_reaches_remote` pass unchanged because the old
`Router.select(tools_available=False, tier_override=...)` already behaves
identically for those two specific call shapes (no `tools_available=True`
call exists in the reworked suite) — the inversion these tests pin is that
`tools_available` no longer exists as a promotion path at all, which is
exercised by `test_orchestrator_first_request_offers_consult_brain_at_default_tier`
et al. once `Loop` stops passing it.

Implementation files were then restored (`git stash pop`, `consult.py` moved
back) and the same suite made to pass in full — see verbatim output below.

Command: `.venv/bin/python -m pytest -q` (post-implementation):

```
..........................................                             [100%]
42 passed in 0.13s
```

**One test-authorship bug found and fixed during the audit** (not part of
the AC-1 capture above, which pre-dates the fix): in
`tests/test_loop_tools.py::test_consult_dispatches_nested_wikipedia_search`,
the assertion for the `wikipedia_search` **observation** event
(`events[4].payload`) expected the remote brain's second-round chat text
("Findings: Ada Lovelace, mathematician.") instead of what
`_FakeRegistry.dispatch` actually returns (`"OBSERVATION_TEXT"`, its default).
The observation event is logged from `dispatch(...)`'s return value, not from
the LLM's next completion — that's `events[5]` (the `consult_brain`
observation, which correctly carries the nested completion's text). Verified
by running the test as originally written against the finished implementation:
it failed with `AssertionError: assert {'name': 'wik...RVATION_TEXT'} == {'name': 'wik...thematician.'}`,
confirming the bug was in the assertion, not the code. Fixed the expected
value to `{"name": "wikipedia_search", "result": "OBSERVATION_TEXT"}`; the
test still pins the full event shape/order and both observation payloads
independently, so it is not weakened.

Full test list (42, run individually — see below for AC-scoped subsets):
`.venv/bin/python -m pytest -v` — all `PASSED`, no `xfail`/`skip`.

## AC-2: top turn served local with persona prompt, offers only `consult_brain`, `routing_decision.tier == "default"`

Command:
```
.venv/bin/python -m pytest -v tests/test_router.py tests/test_orchestrator_persona.py \
  tests/test_e2e_veneer.py::test_e2e_multiturn_chat_and_consult \
  tests/test_loop_tools.py::test_orchestrator_first_request_offers_consult_brain_at_default_tier
```
Output:
```
tests/test_router.py::test_select_default_ignores_tools_available PASSED
tests/test_router.py::test_select_tier_override_reaches_remote PASSED
tests/test_router.py::test_brain_available_true_when_remote_enabled PASSED
tests/test_router.py::test_brain_available_false_when_remote_disabled PASSED
tests/test_orchestrator_persona.py::test_system_prompt_is_first_message PASSED
tests/test_orchestrator_persona.py::test_who_are_you_answers_local_only PASSED
tests/test_e2e_veneer.py::test_e2e_multiturn_chat_and_consult PASSED
tests/test_loop_tools.py::test_orchestrator_first_request_offers_consult_brain_at_default_tier PASSED
8 passed in 0.04s
```
`test_system_prompt_is_first_message` asserts `messages[0] == {"role": "system",
"content": PERSONA_PROMPT}`. `test_orchestrator_first_request_offers_consult_brain_at_default_tier`
asserts the first request's `tools` names are exactly `["consult_brain"]` and
`routing_decision.payload["tier"] == "default"`/`backend_name == "local"`.
`test_who_are_you_answers_local_only` asserts the remote host is never hit for
a chat-only turn (`AssertionError` raised inside the remote handler if it were).

## AC-3: `consult_brain` runs the remote brain over wikipedia; findings incorporated into the final answer

Command:
```
.venv/bin/python -m pytest -v tests/test_consult_brain.py \
  tests/test_loop_tools.py::test_consult_dispatches_nested_wikipedia_search \
  tests/test_e2e_veneer.py::test_e2e_remote_tier_consult_same_shape
```
Output:
```
tests/test_consult_brain.py::test_consult_runs_nested_react_over_wikipedia PASSED
tests/test_consult_brain.py::test_consult_brain_error_becomes_observation PASSED
tests/test_consult_brain.py::test_consult_timeout_becomes_observation PASSED
tests/test_loop_tools.py::test_consult_dispatches_nested_wikipedia_search PASSED
tests/test_e2e_veneer.py::test_e2e_remote_tier_consult_same_shape PASSED
5 passed in 0.04s
```
`test_consult_dispatches_nested_wikipedia_search` drives a full turn where the
local brain emits `consult_brain`, `BrainConsult` selects the remote tier
(`Router.select(tier_override="tool")`), the remote brain emits
`wikipedia_search`, and the orchestrator's final answer
(`"Ada Lovelace was a mathematician."`) is the remote brain's own follow-up
completion after seeing the wikipedia observation — i.e. genuinely
incorporated, not just echoed. `test_e2e_remote_tier_consult_same_shape`
proves the same over a real second httpx client/base_url (`openrouter.test`)
so the tier split is a real distinct backend, not same-backend reuse.

## AC-4: `wikipedia_search` reachable only from inside the nested consult

Command:
```
.venv/bin/python -m pytest -v tests/test_loop_tools.py::test_wikipedia_search_never_offered_at_top_level \
  tests/test_loop_tools.py::test_nested_tool_round_cap \
  tests/test_router.py::test_select_tier_override_reaches_remote
```
Output:
```
tests/test_loop_tools.py::test_wikipedia_search_never_offered_at_top_level PASSED
tests/test_loop_tools.py::test_nested_tool_round_cap PASSED
tests/test_router.py::test_select_tier_override_reaches_remote PASSED
3 passed in 0.01s
```
`test_wikipedia_search_never_offered_at_top_level` asserts the top-level
request's `tools` list never contains `wikipedia_search` (the orchestrator
registry only ever builds `consult.SPEC`). `test_nested_tool_round_cap`
confirms the round cap that bounds repeated `wikipedia_search` calls
(`agent.max_tool_rounds`, distinct from `agent.max_consult_rounds`) applies
inside the nested loop, not the top-level one.

## AC-5: a `BrainError`/timeout inside a consult degrades to an observation, not a crash

Command:
```
.venv/bin/python -m pytest -v tests/test_consult_brain.py::test_consult_brain_error_becomes_observation \
  tests/test_consult_brain.py::test_consult_timeout_becomes_observation
```
Output:
```
tests/test_consult_brain.py::test_consult_brain_error_becomes_observation PASSED
tests/test_consult_brain.py::test_consult_timeout_becomes_observation PASSED
2 passed in 0.02s
```
`test_consult_brain_error_becomes_observation` sends the remote backend a
malformed body (`{"choices": []}`, which `_OpenAICompatBackend` turns into a
`BrainError` per FTHR-008) and asserts `BrainConsult.__call__` returns a
non-empty string instead of raising. `test_consult_timeout_becomes_observation`
sets `consult_timeout_s=0.01` against a handler that sleeps 1s and asserts the
same graceful-string behavior — both are caught inside `BrainConsult.__call__`
(`except BrainError` / `except asyncio.TimeoutError`), so the outer
`Loop.run_turn` never even sees an exception from a consult.

## AC-6: remote/brain disabled → `consult_brain` not offered, every turn local-only

Command:
```
.venv/bin/python -m pytest -v tests/test_router.py::test_brain_available_false_when_remote_disabled \
  tests/test_e2e_veneer.py::test_e2e_remote_disabled_stays_local_chat_only
```
Output:
```
tests/test_router.py::test_brain_available_false_when_remote_disabled PASSED
tests/test_e2e_veneer.py::test_e2e_remote_disabled_stays_local_chat_only PASSED
2 passed in 0.02s
```
`test_e2e_remote_disabled_stays_local_chat_only` builds the real
Veneer/Loop/Router/BrainConsult stack with the remote backend `enabled=False`,
asserts the local request's `tools` list is empty (`consult_offered` is False
because `router.brain_available()` is False), and asserts the wire sequence is
plain `["answer", "done"]` — no `tool_activity` frames, no crash.

## Full suite / lint

```
$ .venv/bin/python -m pytest -q
..........................................                             [100%]
42 passed in 0.13s

$ ruff check .
All checks passed!
```

Baseline before this feather was 37 tests green (per spec dispatch); this
feather adds 5 net tests (42 total): 3 new in `test_consult_brain.py`, 2 new
in `test_orchestrator_persona.py`, plus `test_router.py`
(4 tests, was ~3) and `test_loop_tools.py` (4 tests) reworked in place,
`test_e2e_veneer.py` reworked to 3 tests, `test_app.py`/`test_loop.py`
existing tests updated for the new call shapes, no count change there.
