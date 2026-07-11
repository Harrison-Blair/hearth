# FTHR-011 molt evidence — Logging infra plus dual-model logging and per-session transcript

## AC-1

Tests in `tests/test_logging.py` were written first and run against the unchanged
code (no `hearth/logging_setup.py`, no `hearth/transcript.py`, `Loop`/`BrainConsult`
without `transcript=` kwargs or a `logger` attribute). All 6 fail for the expected
reasons: `ModuleNotFoundError` on the not-yet-existing modules, and `TypeError`/
`AttributeError` on the not-yet-existing `transcript=` constructor kwargs and
`hearth.loop.logger`.

Command: `.venv/bin/python -m pytest tests/test_logging.py -v` (pre-implementation)

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/penguin/.claude/jobs/f05ea59d/tmp/burrows/FTHR-011
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 6 items

tests/test_logging.py::test_setup_logging_creates_rotating_handler FAILED [ 16%]
tests/test_logging.py::test_setup_logging_is_idempotent FAILED           [ 33%]
tests/test_logging.py::test_websockets_logger_routed_to_file FAILED      [ 50%]
tests/test_logging.py::test_consult_turn_logs_both_models FAILED         [ 66%]
tests/test_logging.py::test_transcript_contains_ordered_turn_lines FAILED [ 83%]
tests/test_logging.py::test_logging_failure_does_not_crash_turn FAILED   [100%]

=================================== FAILURES ===================================
_________________ test_setup_logging_creates_rotating_handler __________________

tmp_path = PosixPath('/tmp/pytest-of-penguin/pytest-118/test_setup_logging_creates_rot0')

    def test_setup_logging_creates_rotating_handler(tmp_path):
        from logging.handlers import RotatingFileHandler
    
>       from hearth.logging_setup import setup_logging
E       ModuleNotFoundError: No module named 'hearth.logging_setup'

tests/test_logging.py:52: ModuleNotFoundError
_______________________ test_setup_logging_is_idempotent _______________________

tmp_path = PosixPath('/tmp/pytest-of-penguin/pytest-118/test_setup_logging_is_idempote0')

    def test_setup_logging_is_idempotent(tmp_path):
        from logging.handlers import RotatingFileHandler
    
>       from hearth.logging_setup import setup_logging
E       ModuleNotFoundError: No module named 'hearth.logging_setup'

tests/test_logging.py:75: ModuleNotFoundError
____________________ test_websockets_logger_routed_to_file _____________________

tmp_path = PosixPath('/tmp/pytest-of-penguin/pytest-118/test_websockets_logger_routed_0')

    def test_websockets_logger_routed_to_file(tmp_path):
>       from hearth.logging_setup import setup_logging
E       ModuleNotFoundError: No module named 'hearth.logging_setup'

tests/test_logging.py:87: ModuleNotFoundError
______________________ test_consult_turn_logs_both_models ______________________

tmp_path = PosixPath('/tmp/pytest-of-penguin/pytest-118/test_consult_turn_logs_both_mo0')
two_tier_llm_config = LLMConfig(backends={'local': LLMBackend(base_url='http://local-llm.test/v1', model='qwen3:14b', api_key_env=None, supp...ow=8192, cost_tier='free', enabled=True)}, tiers=LLMTiers(default='local', tool='remote'), timeout=60.0, max_retries=2)
caplog = <_pytest.logging.LogCaptureFixture object at 0x7f5dff31fb60>

    async def test_consult_turn_logs_both_models(tmp_path, two_tier_llm_config, caplog):
        caplog.set_level(logging.INFO)
    
        make, clients = _drive_consult_turn(two_tier_llm_config)
        log = EventLog(str(tmp_path / "events.db"))
>       loop = make(log)
               ^^^^^^^^^

tests/test_logging.py:224: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

log = <hearth.memory.log.EventLog object at 0x7f5dff0b5160>, extra_kwargs = {}

    def make(log, extra_kwargs=None):
        extra_kwargs = extra_kwargs or {}
        registry = _FakeRegistry()
>       consult = BrainConsult(router, registry, log, config, transcript=transcript)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       TypeError: BrainConsult.__init__() got an unexpected keyword argument 'transcript'

tests/test_logging.py:212: TypeError
_________________ test_transcript_contains_ordered_turn_lines __________________

tmp_path = PosixPath('/tmp/pytest-of-penguin/pytest-118/test_transcript_contains_order0')
two_tier_llm_config = LLMConfig(backends={'local': LLMBackend(base_url='http://local-llm.test/v1', model='qwen3:14b', api_key_env=None, supp...ow=8192, cost_tier='free', enabled=True)}, tiers=LLMTiers(default='local', tool='remote'), timeout=60.0, max_retries=2)

    async def test_transcript_contains_ordered_turn_lines(tmp_path, two_tier_llm_config):
>       from hearth.transcript import Transcript
E       ModuleNotFoundError: No module named 'hearth.transcript'

tests/test_logging.py:239: ModuleNotFoundError
___________________ test_logging_failure_does_not_crash_turn ___________________

tmp_path = PosixPath('/tmp/pytest-of-penguin/pytest-118/test_logging_failure_does_not_0')
llm_config = LLMConfig(backends={'local': LLMBackend(base_url='http://localhost:11434/v1', model='qwen3:14b', api_key_env=None, sup...dow=8192, cost_tier='free', enabled=True)}, tiers=LLMTiers(default='local', tool='local'), timeout=60.0, max_retries=2)
canned_completion = <function canned_completion.<locals>._make at 0x7f5dff38fab0>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f5dff4e2b10>

    async def test_logging_failure_does_not_crash_turn(tmp_path, llm_config, canned_completion, monkeypatch):
        import hearth.loop as loop_module
        from hearth.loop import Loop
    
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=canned_completion(text="answer one"))
    
        backend_config = llm_config.backends["local"]
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=backend_config.base_url
        )
        router = Router(llm_config, clients={"local": client})
        log = EventLog(str(tmp_path / "events.db"))
        config = _Config(llm_config)
    
        class _RaisingTranscript:
            def append(self, session_id: str, line: str) -> None:
                raise RuntimeError("disk full")
    
        def _raise(*args, **kwargs):
            raise RuntimeError("logging broke")
    
>       monkeypatch.setattr(loop_module.logger, "info", _raise)
                            ^^^^^^^^^^^^^^^^^^
E       AttributeError: module 'hearth.loop' has no attribute 'logger'

tests/test_logging.py:284: AttributeError
=========================== short test summary info ============================
FAILED tests/test_logging.py::test_setup_logging_creates_rotating_handler - ModuleNotFoundError: No module named 'hearth.logging_setup'
FAILED tests/test_logging.py::test_setup_logging_is_idempotent - ModuleNotFoundError: No module named 'hearth.logging_setup'
FAILED tests/test_logging.py::test_websockets_logger_routed_to_file - ModuleNotFoundError: No module named 'hearth.logging_setup'
FAILED tests/test_logging.py::test_consult_turn_logs_both_models - TypeError: BrainConsult.__init__() got an unexpected keyword argument 'tran...
FAILED tests/test_logging.py::test_transcript_contains_ordered_turn_lines - ModuleNotFoundError: No module named 'hearth.transcript'
FAILED tests/test_logging.py::test_logging_failure_does_not_crash_turn - AttributeError: module 'hearth.loop' has no attribute 'logger'
============================== 6 failed in 0.06s ===============================
```

Post-implementation, the same 6 tests pass:

Command: `.venv/bin/python -m pytest tests/test_logging.py -v`

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/penguin/.claude/jobs/f05ea59d/tmp/burrows/FTHR-011
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 6 items

tests/test_logging.py::test_setup_logging_creates_rotating_handler PASSED [ 16%]
tests/test_logging.py::test_setup_logging_is_idempotent PASSED           [ 33%]
tests/test_logging.py::test_websockets_logger_routed_to_file PASSED      [ 50%]
tests/test_logging.py::test_consult_turn_logs_both_models PASSED         [ 66%]
tests/test_logging.py::test_transcript_contains_ordered_turn_lines PASSED [ 83%]
tests/test_logging.py::test_logging_failure_does_not_crash_turn PASSED   [100%]

============================== 6 passed in 0.02s ===============================
```

Full suite (44 baseline + 6 new) green, and `ruff check .` clean:

Command: `.venv/bin/python -m pytest -q`

```
..................................................                       [100%]
50 passed in 0.13s
```

Command: `.venv/bin/python -m ruff check .`

```
All checks passed!
```

Note: while implementing, `test_consult_turn_logs_both_models`/`test_websockets_logger_routed_to_file`
initially failed intermittently depending on run order, because `tests/test_app.py`'s
`test_run_daemon_wires_wikipedia_tool_brain_side` calls the real `_run_daemon` (which
now calls `setup_logging`), mutating the process-global root/`websockets` loggers for
the rest of the pytest session. Fixed by adding an autouse `_reset_logging_state`
fixture to `tests/conftest.py` that snapshots and restores root/`websockets` logger
handlers, level, and the idempotency marker around every test. Verified order-independence:
`pytest tests/test_logging.py tests/test_app.py -q` → `8 passed`.

## AC-2

`hearth/logging_setup.py::setup_logging(config: LoggingConfig)` builds a
`logging.handlers.RotatingFileHandler` from `config.dir`/`config.file_name`/
`config.max_bytes`/`config.backup_count`, attaches it to the root logger, sets
the root (and `websockets`) logger level from `config.level`, and guards against
duplicate handlers with a marker attribute (`_hearth_logging_configured`) on the
root logger — a second call is a no-op. `app.py`'s `_run_daemon` calls it exactly
once, early, before constructing the router/loop/veneer. No `logging.basicConfig`
or import-time side effect anywhere in `hearth/logging_setup.py` (defining the
function has no effect until called — proven by every other test file in the
suite importing `hearth.*` without ever seeing a handler attached unless a test
calls `setup_logging` or `_run_daemon` itself).

Verified by:
- `test_setup_logging_creates_rotating_handler` — asserts exactly one
  `RotatingFileHandler` on the root logger with the configured `maxBytes`/
  `backupCount`, and that a logged message lands in the file.
- `test_setup_logging_is_idempotent` — two `setup_logging` calls leave exactly
  one `RotatingFileHandler` attached.
- `test_websockets_logger_routed_to_file` — a message logged via
  `logging.getLogger("websockets")` lands in the same file.

All three pass — see the AC-1 post-implementation run above.

## AC-3

`Loop.run_turn` (`hearth/loop.py`) logs the orchestrator's local model/backend
right after `self._router.select()`, via `self._log_model("orchestrator", selection)`,
which reads the model name from `self._config.llm.backends[selection.backend_name].model`
and emits `logger.info("%s turn model backend=%s tier=%s model=%s", ...)`.
`BrainConsult.__call__` (`hearth/tools/consult.py`) does the same for the
consult's remote selection via `self._log_model(selection)` right after
`self._router.select(tier_override="tool")`.

Verified by `test_consult_turn_logs_both_models`: drives a full orchestrator
turn over `two_tier_llm_config` that triggers one `consult_brain` call, and
via `caplog` (level INFO) asserts a record mentions both `backend_name="local"`
+ `model="qwen3:14b"` and a separate record mentions `backend_name="remote"` +
`model="openrouter/free"`. Passes — see the AC-1 post-implementation run above.

## AC-4

`hearth/transcript.py::Transcript.append(session_id, line)` appends a
timestamped line to `<transcript_dir>/<session_id>.txt` (dir + file
created on first write). `Loop.run_turn` writes `"user: <text>"` immediately
after logging the user_input event, then (after the turn completes)
`"answer: <answer>"`. `BrainConsult.__call__` writes `"consult query: <query>"`
right after selecting the remote tier, and `"consult findings: <findings>"`
right before returning — both between the surrounding turn's user/answer
transcript lines, since the consult's dispatch is awaited synchronously inside
`Loop.run_turn`'s `run_react_rounds` call before the final answer is computed.
`app.py` constructs a `Transcript` from `settings.logging.transcript_dir` when
`settings.logging.transcript_enabled`, and passes it into both `BrainConsult`
and `Loop`.

Verified by `test_transcript_contains_ordered_turn_lines`: drives the same
consult-triggering turn with `transcript_enabled` wired in, reads
`<transcript_dir>/s1.txt`, and asserts the user text, the consult query, the
consult findings, and the final answer appear in that order. Passes — see the
AC-1 post-implementation run above.

## AC-5

Every logging/transcript call site added by this feather is wrapped in its
own `try/except Exception: pass` — `Loop._log_model`/`Loop._append_transcript`
in `hearth/loop.py`, `BrainConsult._log_model`/`BrainConsult._append_transcript`
in `hearth/tools/consult.py` — so a raising logger or a raising injected
`Transcript` never propagates out of `run_turn`. (`hearth/transcript.py`'s own
`Transcript.append` additionally swallows `OSError` internally for the real
disk-backed case; the test below bypasses that by injecting a fake object
whose `.append` always raises, to prove the *call site* wrapping, not just the
real class's internal one.)

Verified by `test_logging_failure_does_not_crash_turn`: monkeypatches
`hearth.loop.logger.info` to raise, and injects a `_RaisingTranscript` whose
`append` raises `RuntimeError`, into a `Loop` driving a normal (non-consult)
turn; asserts `run_turn` still returns the normal answer text unchanged.
Passes — see the AC-1 post-implementation run above.
