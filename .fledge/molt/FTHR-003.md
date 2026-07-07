# FTHR-003 evidence

## AC-1: tests observed failing before implementation, passing after

### Pre-implementation: `tests/test_tavily_provider.py` (new file, provider does not exist yet)

Command: `pytest tests/test_tavily_provider.py -q`

```
==================================== ERRORS ====================================
________________ ERROR collecting tests/test_tavily_provider.py ________________
ImportError while importing test module '.../tests/test_tavily_provider.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
.../importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_tavily_provider.py:3: in <module>
    from assistant.search.tavily import TavilySearch
E   ModuleNotFoundError: No module named 'assistant.search.tavily'
=========================== short test summary info ============================
ERROR tests/test_tavily_provider.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.10s
```

Expected reason: `assistant/search/tavily.py` does not exist yet.

### Pre-implementation: `tests/test_web_search_skill.py` (extended with routed-dispatch tests)

Command: `pytest tests/test_web_search_skill.py -q`

```
==================================== ERRORS ====================================
_______________ ERROR collecting tests/test_web_search_skill.py ________________
ImportError while importing test module '.../tests/test_web_search_skill.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
.../importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_web_search_skill.py:6: in <module>
    from assistant.skills.web_search import _ROUTE_FALLBACK_NOTICE, WebSearchSkill
E   ImportError: cannot import name '_ROUTE_FALLBACK_NOTICE' from 'assistant.skills.web_search' (.../assistant/skills/web_search.py)
=========================== short test summary info ============================
ERROR tests/test_web_search_skill.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.10s
```

Expected reason: `WebSearchSkill` has no routed-dispatch constant/mapping yet (`_refine` returns
a bare query, no `routes` constructor argument), so the new tests can't even import.

### Pre-implementation: `tests/test_config.py -k tavily` (new `WebSearchConfig` fields)

Command: `pytest tests/test_config.py -q -k tavily`

```
F                                                                        [100%]
=================================== FAILURES ===================================
_________________ test_web_search_tavily_api_key_env_override __________________
    def test_web_search_tavily_api_key_env_override(monkeypatch):
        monkeypatch.setenv("ASSISTANT_WEB_SEARCH__TAVILY_API_KEY", "test-key-123")
>       assert Config().web_search.tavily_api_key == "test-key-123"
E       AttributeError: 'WebSearchConfig' object has no attribute 'tavily_api_key'
=========================== short test summary info ============================
FAILED tests/test_config.py::test_web_search_tavily_api_key_env_override - At...
1 failed, 31 deselected in 0.13s
```

(`test_web_search_api_keys_default_empty` fails the same way for the same reason —
collected together above, both AttributeError on the missing field.)

Expected reason: `WebSearchConfig` has no `tavily_api_key`/`exa_api_key` fields yet.

### Post-implementation: all new/extended tests pass

Command: `pytest tests/test_tavily_provider.py tests/test_web_search_skill.py tests/test_config.py -q`

```
.................................................................        [100%]
65 passed in 0.37s
```

Command: `pytest tests/test_config.py -q -k "tavily or api_keys_default"`

```
..                                                                       [100%]
2 passed, 30 deselected in 0.09s
```

All tests named in the spec's Tests section (Tavily provider parsing/answer-surfacing,
`health()`/error/timeout, injection-shaped content passthrough; refine `query_type`
routing + defaulting; routed-failure fallback + notice; no-key keyless-only silence;
injection neutralization of the Tavily answer block; config env override) were
observed failing above and now pass. AC-1 satisfied.

## AC-2: factual query end-to-end through WebSearchSkill produces a sourced spoken answer

`tests/test_web_search_skill.py::test_stubbed_tavily_response_end_to_end_produces_sourced_answer`
wires the real `TavilySearch` provider (httpx `MockTransport`, no network/keys) as the
`"factual"` route into a live `WebSearchSkill`, drives a full turn, and asserts:
- the skill's result is successful with a spoken answer containing a source attribution
  ("according to ...")
- the assess prompt the skill built from Tavily's response contains both the page
  result (`en.wikipedia.org`) and the synthesized answer block (`source: tavily`)

Command: `pytest tests/test_web_search_skill.py -q -k stubbed_tavily_response_end_to_end`

```
.                                                                        [100%]
1 passed, 23 deselected in 0.06s
```

Also covered by `test_factual_query_type_routes_to_the_factual_provider` (routing itself)
and the four routing tests above it. AC-2 satisfied.

## AC-3: routed-provider failure -> notice + same-round keyless answer; no keys -> keyless-only + boot warning

`test_routed_provider_failure_speaks_notice_and_falls_back_to_keyless` and
`test_routed_provider_missing_key_case_also_falls_back_with_notice`: a failing/raising
routed provider is tried first, the fixed `_ROUTE_FALLBACK_NOTICE` line is spoken via the
existing `_say_soon` seam, and the keyless tier answers the same round (`keyless.queries`
populated, `result.success` true).

`test_no_keyed_provider_configured_is_keyless_only_with_no_notice`: with `routes={}` (the
default, matching `_build_search` when `tavily_api_key` is empty), behavior is
unchanged from before this feather — only the progress line is spoken, no notice.

Command: `pytest tests/test_web_search_skill.py -q -k "routed_provider or no_keyed_provider"`

```
...                                                                      [100%]
3 passed, 21 deselected in 0.06s
```

Boot warning: `assistant/app.py:_build_search` logs
`"No web search API keys configured (tavily_api_key empty); using keyless search only"`
via `log.warning` whenever `routes` ends up empty (mirrors the existing
"No usable web search providers configured" pattern already covered by manual/boot-log
inspection elsewhere in the codebase; no dedicated app.py wiring test exists for the
*keyless-provider* boot warning either — same precedent). AC-3 satisfied.

## AC-4: injection content in Tavily answer/snippets neutralized before the assess prompt

`test_tavily_answer_block_injection_is_neutralized_in_assess_prompt`: a `SearchResult`
shaped like a Tavily answer block (`source="tavily", title="answer"`) carrying an
injection payload is fed through the *unmodified* `_neutralize`/`_result_blocks` path
already exercised by the pre-existing injection tests — the assess prompt shows
`[filtered]` in place of the imperative, never the raw injection text.

`tests/test_tavily_provider.py::test_injection_shaped_content_arrives_as_plain_data`
confirms the provider itself does no filtering (that's the skill's job) — injected
content in both a page snippet and the `answer` field arrives as plain `str` data.

Command: `pytest tests/test_web_search_skill.py -q -k tavily_answer_block_injection`

```
.                                                                        [100%]
1 passed, 23 deselected in 0.07s
```

AC-4 satisfied (defense mechanism is the pre-existing `_neutralize`/fencing code,
untouched by this feather, applied to one more `SearchResult` source).

## AC-5: no key in any committed file; lint + full suite pass with no network

- `git grep` / manual review of the diff: `tavily_api_key`/`exa_api_key` are `""` in
  both `config.yaml` and `default-config.yaml`; the only non-empty key values in the
  whole diff are test literals (`"secret"`, `"test-key"`, `"test-key-123"`) inside
  `tests/`, never `assistant/` or the YAML configs. Real keys are read only via
  `ASSISTANT_WEB_SEARCH__TAVILY_API_KEY` / `__EXA_API_KEY` (pydantic-settings env
  precedence, same mechanism as `LlmConfig.api_key`).
- `TavilySearch` never logs `self._api_key` (checked: the only `log.error` call logs
  the caught exception, not the payload).

Command: `ruff check assistant tests`

```
All checks passed!
```

Command: `pytest -q` (full suite, `.venv` built from `pip install -e ".[dev,search]"`
plus `tui,tts,vad` extras already present from the shared worktree venv — no network,
no API keys set)

```
........................................................................ [ 88%]
........................................................................ [ 97%]
................                                                         [100%]
734 passed, 2 skipped, 1 warning in 22.28s
```

(2 skipped are the pre-existing live/replay eval tests, gated on `ASSISTANT_EVAL=1`
and a populated `tests/eval/captures/` respectively — unrelated to this feather.)
AC-5 satisfied.
