# FTHR-007 molt evidence

## AC-1: tests observed failing before implementation, pass after

This feather is purely additive (`tests/test_e2e_veneer.py`, `MANUAL_SMOKE.md`)
— every real component it drives (`Veneer`, `Loop`, `Router`, `ToolRegistry`,
`EventLog`) already exists and is already unit-tested (FTHR-001..006). There
was no non-test code to change, so the "fails before / passes after"
demonstration takes the form the spec anticipated: writing the assembled test
first, confirming it genuinely exercises the real assembled system (rather
than passing vacuously) by temporarily breaking that assembly and observing
the test fail for the expected reason, then restoring and confirming green.

### Step 1 — initial run against the unchanged repo (`git status` clean, no
implementation edits made)

```
$ .venv/bin/pytest -q tests/test_e2e_veneer.py -v
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/penguin/source/hearth/.fledge/burrows/FTHR-007
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 3 items

tests/test_e2e_veneer.py ...                                             [100%]

============================== 3 passed in 0.03s ===============================
```

All 3 tests passed immediately — expected, since FTHR-001..006 already merged
the real components this test assembles. Per the spec's guidance for this
case ("if so, make sure your test's assertions are meaningful enough that
they'd genuinely fail if the assembly were broken — check by temporarily
breaking something"), the mutation check below is the required verification
evidence for these tests.

(Note: during test authoring, before I discovered the correct `httpx.AsyncClient`
wiring — matching `hearth/app.py`'s pattern of binding the shared LLM client to
the default tier's `base_url` — the tests failed with `ValueError: unknown url
type: '/chat/completions'`. That was a bug in the test's own client
construction, not evidence about the production assembly, so it isn't offered
as the AC-1 proof; the mutation test below is.)

### Step 2 — mutation: temporarily break the real `ToolRegistry`/tool-routing
wiring inside `Loop.run_turn`

`hearth/loop.py`, temporarily changed:

```python
tools_available = bool(tool_specs) and self._config.agent.tool_mode != "off"
```
to
```python
tools_available = False  # TEMP BREAK for test verification
```

```
$ .venv/bin/pytest -q tests/test_e2e_veneer.py -v
============================= test session starts ==============================
...
collected 3 items

tests/test_e2e_veneer.py FFF                                             [100%]

=================================== FAILURES ===================================
_____________________ test_e2e_multiturn_chat_and_tool_use _____________________
...
>       assert [m["type"] for m in turn2_messages] == [
            "tool_activity",
            "tool_activity",
            "answer",
            "done",
        ]
E       AssertionError: assert ['answer', 'done'] == ['tool_activi...swer', 'done']
E         At index 0 diff: 'answer' != 'tool_activity'
E         Right contains 2 more items, first extra item: 'answer'
tests/test_e2e_veneer.py:222: AssertionError
__________________ test_e2e_remote_tier_tool_turn_same_shape ___________________
...
>       assert [m["type"] for m in messages] == ["tool_activity", "tool_activity", "answer", "done"]
E       AssertionError: assert ['answer', 'done'] == ['tool_activi...swer', 'done']
tests/test_e2e_veneer.py:308: AssertionError
_____________________ test_e2e_remote_disabled_stays_local _____________________
...
>       assert [m["type"] for m in messages] == ["tool_activity", "tool_activity", "answer", "done"]
E       AssertionError: assert ['answer', 'done'] == ['tool_activi...swer', 'done']
tests/test_e2e_veneer.py:356: AssertionError
=========================== short test summary info ============================
FAILED tests/test_e2e_veneer.py::test_e2e_multiturn_chat_and_tool_use - Asser...
FAILED tests/test_e2e_veneer.py::test_e2e_remote_tier_tool_turn_same_shape - ...
FAILED tests/test_e2e_veneer.py::test_e2e_remote_disabled_stays_local - Asser...
============================== 3 failed in 0.05s ===============================
```

All 3 tests failed for the expected reason: with tool routing disabled, the
LLM never sees the tool spec, so it never emits a tool call and the wire never
sees `tool_activity` — exactly the assertion each test is designed to catch.
This confirms the tests exercise the real assembled tool-routing path rather
than passing vacuously.

### Step 3 — restore `hearth/loop.py` (verified byte-identical to
pre-mutation via `diff`), rerun

```
$ diff hearth/loop.py /tmp/loop.py.bak && echo "restored: identical to pre-mutation"
restored: identical to pre-mutation

$ .venv/bin/pytest -q tests/test_e2e_veneer.py -v
============================= test session starts ==============================
...
collected 3 items

tests/test_e2e_veneer.py ...                                             [100%]

============================== 3 passed in 0.02s ===============================
```

### Step 4 — full repo suite, green

```
$ .venv/bin/pytest -q
.................................                                        [100%]
33 passed in 0.09s

$ .venv/bin/ruff check tests/test_e2e_veneer.py
All checks passed!
```

## AC-2: assembled integration test, real Veneer over a real WebSocket,
multi-turn chat + tool-use turn, full event set + wire contract, history
reconstructed across turns

Covered by `test_e2e_multiturn_chat_and_tool_use` in
`tests/test_e2e_veneer.py`. Real components instantiated directly (no fakes):
`EventLog` (real sqlite at a `tmp_path`), `Router` (real, backed by
`httpx.MockTransport` at the LLM boundary only), `ToolRegistry` (real, backed
by `httpx.MockTransport` at the Wikipedia REST boundary only), `Loop` (real),
`Veneer` (real) — started via `websockets.serve(veneer._handle_connection,
"127.0.0.1", 0)` (ephemeral port) inside the test, driven by a real
`websockets.connect` client using the real `hearth.veneer.client.send_turn`
helper.

The test asserts:
- turn 1 (plain chat): wire messages are exactly `["answer", "done"]`.
- turn 2 (tool-use, same connection/session): wire messages are exactly
  `["tool_activity", "tool_activity", "answer", "done"]` with
  `phase`/`label` = `start`/`search` then `end`/`search`, and every message's
  keys are within the AC-6 wire whitelist (`type`/`turn_id`/`phase`/`label`/
  `text`) with none of the forbidden content keys (`query`, `arguments`,
  `observation`, `result`) present.
- the event log (queried directly off the real sqlite connection) contains,
  in order, for one session:
  `user_input, routing_decision, final_answer, user_input, routing_decision,
  tool_call, observation, final_answer` — i.e. both turns landed under one
  session, with `tool_call`/`observation` rows present for the tool turn.
- history continuity (FC-14): turn 2's first LLM request payload carries
  `[{"role": "user", "content": "hello there"}, {"role": "assistant",
  "content": "hi there"}, ...]` as its leading messages — turn 1's exchange,
  reconstructed by `Loop.run_turn` from the event log itself.

See AC-1 above for the passing run and the mutation-test proof that these
assertions are load-bearing.

## AC-3: same assembled scenario, remote tier, same event-sequence shape

Covered by `test_e2e_remote_tier_tool_turn_same_shape`. Same real-component
assembly as AC-2, but `LLMConfig` carries both a `local` and a `remote`
(OpenRouter-shaped: `api_key_env="HEARTH_LLM__OPENROUTER_API_KEY"`,
`model="openrouter/free"`) backend with `tiers.tool="remote"` and
`remote.enabled=True`. Asserts:
- the same wire shape: `["tool_activity", "tool_activity", "answer", "done"]`.
- the same event-sequence shape:
  `user_input, routing_decision, tool_call, observation, final_answer`.
- `routing_decision.payload == {"tier": "tool", "backend_name": "remote", ...}`.
- the actual LLM request body's `"model"` field is `"openrouter/free"` — proof
  the turn was actually driven through the remote-shaped backend, not just
  that the routing-decision label said so.

Passing run captured in the Step 3 log above (`3 passed`).

## AC-4: remote tier disabled by config, tool-use turn resolves to local
end-to-end

Covered by `test_e2e_remote_disabled_stays_local`. Same assembly as AC-3 but
`remote.enabled=False`. Asserts the wire shape is still
`["tool_activity", "tool_activity", "answer", "done"]`,
`routing_decision.payload["backend_name"] == "local"`, and the actual LLM
request body's `"model"` field is `"qwen3:14b"` (the local backend's model) —
proof the fallback actually happened at the HTTP-request level, not just in
the routing label.

Passing run captured in the Step 3 log above (`3 passed`).

## AC-5: `MANUAL_SMOKE.md`

Added at the repo root. Numbered sections: (1) local-only smoke test against
a real Ollama (start Ollama, force `llm.tiers.tool: local` or
`remote.enabled: false`, run `hearth run` + `python -m hearth.veneer.client`,
drive a plain question and a Wikipedia-triggering question, expected
behavior). (2) remote-tier smoke test against real OpenRouter (set
`HEARTH_LLM__OPENROUTER_API_KEY` in `.env`, confirm via `sqlite3 hearth.db`
that `routing_decision` shows `tier: tool, backend_name: remote`). (3) how to
tell environment issues (no Ollama running, no/invalid API key, no Wikipedia
network access) apart from real spine bugs (crash, timeout past
`turn_timeout_s`, wrong wire shape, missing event-log rows). Documentation
only — no runtime code touched; not a gating automated check.
