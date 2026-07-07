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

### Post-implementation

(added below once implementation is complete)

<!-- AC-2..AC-5 sections appended below as each criterion is satisfied -->
