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

(recorded below once `assistant/search/exa.py` exists and the `app.py` semantic
route is wired)
