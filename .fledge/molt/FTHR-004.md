# FTHR-004 evidence

## AC-1

### Pre-implementation: `tests/test_exa_provider.py` (new file, provider does not exist yet)

Command: `pytest tests/test_exa_provider.py tests/test_web_search_skill.py -q`

```
==================================== ERRORS ====================================
_________________ ERROR collecting tests/test_exa_provider.py __________________
ImportError while importing test module '.../tests/test_exa_provider.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
.../importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_exa_provider.py:3: in <module>
    from assistant.search.exa import ExaSearch
E   ModuleNotFoundError: No module named 'assistant.search.exa'
_______________ ERROR collecting tests/test_web_search_skill.py ________________
ImportError while importing test module '.../tests/test_web_search_skill.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
.../importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_web_search_skill.py:8: in <module>
    from assistant.search.exa import ExaSearch
E   ModuleNotFoundError: No module named 'assistant.search.exa'
=========================== short test summary info ============================
ERROR tests/test_exa_provider.py
ERROR tests/test_web_search_skill.py
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
2 errors in 0.09s
```

Expected reason: `assistant/search/exa.py` does not exist yet, so both the new
`tests/test_exa_provider.py` and the semantic-route additions to
`tests/test_web_search_skill.py` (which import `ExaSearch` for the stubbed
end-to-end test) fail to even collect.

### Post-implementation: all new/extended tests pass

Command: `pytest tests/test_exa_provider.py tests/test_web_search_skill.py -q`

```
...................................                                      [100%]
35 passed in 0.08s
```

All tests named in the spec's Tests section (Exa provider highlights-mapping,
domain attribution, text/summary fallback when highlights absent, snippet
truncation for both paths, api-key header + `numResults`/`contents.highlights`
payload shape, `health()`/HTTP-error, injection-shaped content passthrough;
semantic `query_type` routing to a registered semantic provider) were observed
failing above (module didn't exist) and now pass. AC-1 satisfied.

## AC-2

`tests/test_web_search_skill.py::test_stubbed_exa_response_end_to_end_produces_sourced_answer`
wires the real `ExaSearch` provider (httpx `MockTransport`, no network/keys) as
the `"semantic"` route into a live `WebSearchSkill`, drives a full turn with a
`query_type: semantic` refine response, and asserts:
- the skill's result is successful with a spoken answer containing a source
  attribution ("according to ...")
- the assess prompt the skill built from Exa's highlights contains the result's
  domain (`en.wikipedia.org`)

Also covered by `test_semantic_query_type_routes_to_the_semantic_provider_when_registered`
(routing itself: a `semantic`-classified query reaches the registered semantic
provider, not the keyless tier).

Command: `pytest tests/test_web_search_skill.py -q -k "stubbed_exa_response_end_to_end or semantic_query_type_routes_to_the_semantic"`

```
..                                                                       [100%]
2 passed, 24 deselected in 0.04s
```

AC-2 satisfied.

## AC-3

`test_semantic_query_type_falls_back_to_factual_route_when_unregistered` (kept
from FTHR-003, still passing unmodified): a `semantic`-classified query with no
`"semantic"` route registered still falls to the `"factual"` route exactly as
before this feather — the fallback machinery FTHR-003 built is route-agnostic
and needed no changes.

`test_routed_provider_failure_speaks_notice_and_falls_back_to_keyless` and
`test_routed_provider_missing_key_case_also_falls_back_with_notice` (unmodified,
route-agnostic): a failing/raising routed provider (Tavily in these tests, same
code path Exa would hit) speaks `_ROUTE_FALLBACK_NOTICE` and falls back to the
keyless tier within the round.

`test_no_keyed_provider_configured_is_keyless_only_with_no_notice`: with
`routes={}` — the state of `_build_search` when both `tavily_api_key` and
`exa_api_key` are empty — behavior is unchanged, only the progress line is
spoken, no notice.

Command: `pytest tests/test_web_search_skill.py -q -k "routed_provider or no_keyed_provider or semantic_query_type_falls_back"`

```
....                                                                     [100%]
4 passed, 22 deselected in 0.04s
```

No code changes were made to `assistant/skills/web_search.py` for this feather —
only `assistant/app.py:_build_search` gained one new `if cfg.exa_api_key: routes["semantic"] = ExaSearch(...)`
branch, mirroring the existing `tavily_api_key` branch. AC-3 satisfied.

## AC-4

- `git diff` review: `exa_api_key` is `""` in both `config.yaml` and
  `default-config.yaml`; the only non-empty key values anywhere in the diff are
  test literals (`"secret"`, `"secret-key"`, `"bad"`, `"test-key"`) inside
  `tests/`, never `assistant/` or the YAML configs. Real keys are read only via
  `ASSISTANT_WEB_SEARCH__EXA_API_KEY` (pydantic-settings env precedence, the
  same mechanism as `tavily_api_key`).
- `ExaSearch` never logs `self._api_key`: the only `log.error` call logs the
  caught exception, not the payload or headers; the key is sent solely as the
  `x-api-key` request header.

Command: `ruff check assistant tests`

```
All checks passed!
```

Command: `pytest -q` (full suite, `.venv` built from
`pip install -e ".[dev,search,tui,tts,vad]"` — no network, no API keys set)

```
ss...................................................................... [  9%]
........................................................................ [ 19%]
........................................................................ [ 28%]
........................................................................ [ 38%]
........................................................................ [ 48%]
........................................................................ [ 57%]
........................................................................ [ 67%]
........................................................................ [ 77%]
........................................................................ [ 86%]
........................................................................ [ 96%]
...........................                                              [100%]
745 passed, 2 skipped, 1 warning in 19.64s
```

(2 skipped are the pre-existing live/replay eval tests, gated on
`ASSISTANT_EVAL=1` and a populated `tests/eval/captures/` respectively —
unrelated to this feather. The 1 warning is a pre-existing `webrtcvad` /
`pkg_resources` deprecation notice, unrelated to this feather.)
AC-4 satisfied.
