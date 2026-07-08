## AC-1

Three tests added to `tests/test_tui_supervisor.py`, test-first, in the existing
real-subprocess style (`sys.executable -c <script>` children driven through the real
`DaemonSupervisor`, mirroring `LOOP_CHILD`/`ECHO_CHILD`):

- `test_supervisor_treats_reexec_as_running`
- `test_reexec_does_not_signal_stopped`
- `test_pdeathsig_survives_reexec`

This is a verification-and-harden feather (per spec): `os.execv` is inherently
transparent to `asyncio`'s subprocess machinery (same pid, no `SIGCHLD`, fds not
close-on-exec), so all three pass immediately against the **unchanged**
`tui/supervisor.py`/`tui/app.py` — there is no natural bug to reproduce. Per the
spec's AC-1 bar ("meaningfully exercising the re-exec path... document how it would
fail if the supervisor mishandled re-exec — e.g. temporarily simulate the
mishandling"), each test was paired with a throwaway `DaemonSupervisor` subclass that
injects one specific, plausible mishandling, and the *same assertions* were run
against that subclass to confirm the test actually discriminates. These subclasses
lived only in a scratch file (`tests/_demo_broken_reexec.py`), were never part of the
committed suite, and were deleted immediately after capturing this evidence — no
production code was touched to produce these failures.

Command (baseline, pre-implementation — the tests already pass because os.execv is
naturally transparent; there is nothing to implement):
```
source .venv/bin/activate
pytest tests/test_tui_supervisor.py -v
```
Output:
```
tests/test_tui_supervisor.py::test_start_streams_lines_and_merges_env PASSED [ 11%]
tests/test_tui_supervisor.py::test_stop_terminates_running_child PASSED  [ 22%]
tests/test_tui_supervisor.py::test_restart_relaunches_child PASSED       [ 33%]
tests/test_tui_supervisor.py::test_send_is_noop_when_not_running PASSED  [ 44%]
tests/test_tui_supervisor.py::test_env_file_merges_into_child PASSED     [ 55%]
tests/test_tui_supervisor.py::test_session_override_beats_env_file PASSED [ 66%]
tests/test_tui_supervisor.py::test_supervisor_treats_reexec_as_running PASSED [ 77%]
tests/test_tui_supervisor.py::test_reexec_does_not_signal_stopped PASSED [ 88%]
tests/test_tui_supervisor.py::test_pdeathsig_survives_reexec PASSED      [100%]

9 passed in 0.88s
```

**Mishandling demo 1** — `RunningFalseAfterExecSupervisor` overrides `running` to
always return `False` (simulating a supervisor that wrongly treats the re-exec'd pid
as dead):
```
pytest tests/_demo_broken_reexec.py -k running_flips -q
```
```
F
FAILED tests/_demo_broken_reexec.py::test_treats_reexec_as_running_FAILS_if_running_flips
E       assert False
E        +  where False = <...RunningFalseAfterExecSupervisor object>.running
1 failed, 2 deselected in 0.02s
```

**Mishandling demo 2** — `EOFsAtReexecSupervisor` overrides `lines()` to end right
after the first marker (simulating a supervisor whose stdout stream wrongly EOFs at
the re-exec boundary — exactly the case that would flip the real TUI pump to
`stopped`):
```
pytest tests/_demo_broken_reexec.py -k lines_ends -q
```
```
F
FAILED tests/_demo_broken_reexec.py::test_reexec_does_not_signal_stopped_FAILS_if_lines_ends
E   StopAsyncIteration
1 failed, 2 deselected in 0.02s
```

**Mishandling demo 3** — a "fake TUI" spawns the re-exec'ing grandchild *without*
`preexec_fn=_die_with_parent` (simulating pdeathsig never being armed), is then
SIGKILLed, and the grandchild is asserted reaped:
```
pytest tests/_demo_broken_reexec.py -k not_armed -q
```
```
F
FAILED tests/_demo_broken_reexec.py::test_pdeathsig_survives_reexec_FAILS_if_not_armed
E   AssertionError: re-exec'd daemon survived its TUI's death (pdeathsig lost)
5.37s
```

Command (post-implementation — no production change was needed; same command,
included for completeness):
```
pytest tests/test_tui_supervisor.py -v
```
Output: identical 9 passed shown above (unchanged, since no fix was required).

## AC-2

`test_supervisor_treats_reexec_as_running` drives a child that prints `MARKER_1`,
`os.execv`s in place into a second stage that prints `MARKER_2` and idles, all through
the real `DaemonSupervisor`. Asserts `sup.running is True` both immediately after
`MARKER_1` (pre-exec) and after `MARKER_2` (post-exec) — no `SIGCHLD` fires across an
in-place `execv` since the pid and open fds are unchanged, so `returncode` stays
`None`.

`test_reexec_does_not_signal_stopped` models `tui/app.py:_pump`'s exact rule (the
`async for line in self.supervisor.lines()` loop at lines 239-252 only reaches
`_set_state("stopped")` once `lines()` ends/EOFs): after observing both markers, it
asserts the *next* `lines()` read times out (`asyncio.TimeoutError`) rather than
raising `StopAsyncIteration` — proving the stream is still open/blocked, not
terminated, at the re-exec boundary. Since the pump's `async for` never falls through
to its post-loop `stopped` branch until `lines()` actually ends, this shows the pump
cannot flip to `stopped` at a re-exec.

Command:
```
pytest tests/test_tui_supervisor.py::test_supervisor_treats_reexec_as_running tests/test_tui_supervisor.py::test_reexec_does_not_signal_stopped -v
```
Output:
```
tests/test_tui_supervisor.py::test_supervisor_treats_reexec_as_running PASSED [ 50%]
tests/test_tui_supervisor.py::test_reexec_does_not_signal_stopped PASSED [100%]

2 passed in 0.03s
```

No change to `tui/supervisor.py` or `tui/app.py` was needed — both assertions hold
against the unchanged code (see AC-1's mishandling demos for what would have failed).

## AC-3

`test_pdeathsig_survives_reexec` verifies the parent-death signal directly: an
intermediate "fake TUI" process spawns a daemon-like child through the real
`DaemonSupervisor` (so `PR_SET_PDEATHSIG` is armed exactly as in production via
`_die_with_parent`), the child immediately `os.execv`s itself once, then the fake TUI
is SIGKILLed (simulating an unclean crash — no `on_unmount`/cleanup). The test then
polls for the re-exec'd grandchild's pid to disappear, confirming the kernel reaped it
via the still-armed pdeathsig, surviving the `execv`.

Command:
```
pytest tests/test_tui_supervisor.py::test_pdeathsig_survives_reexec -v
```
Output:
```
tests/test_tui_supervisor.py::test_pdeathsig_survives_reexec PASSED [100%]

1 passed in 0.53s
```

This confirms subtlety (1) from the spec: a normal `execve` (no `preexec_fn`, no
set-uid/set-gid) preserves `PR_SET_PDEATHSIG`, so `assistant/core/selfupdate.py`'s
`restart_in_place()` needs no re-arm — the daemon's self re-exec inherits the flag
armed at its original spawn. No change to `assistant/core/selfupdate.py` was
required; per the protocol, the orchestrator would have been messaged before any
`assistant/**` edit had this test failed, but it did not.

One real-world subtlety surfaced while writing the test itself (not production code):
`asyncio`'s subprocess `Process.wait()` can block indefinitely on the *outer* ("fake
TUI") process if a surviving grandchild keeps the outer's inherited stdout pipe fd
open (verified with a minimal repro outside pytest). The test bounds that wait with
`asyncio.wait_for(outer.wait(), 2)` and swallows the timeout — the real assertion is
the separate `os.kill(child_pid, 0)` poll on the grandchild, not the outer's exit.
Without this bound, a genuine pdeathsig regression would make the test hang instead of
failing cleanly, which the mishandling demo above confirms still fails correctly with
the bound in place.

## AC-4

`git diff --stat` against `main`'s merge-base shows only the test file changed:
```
tests/test_tui_supervisor.py | 137 +++++++++++++++++++++++++++++++++++++++++++
1 file changed, 137 insertions(+)
```
No changes to `tui/supervisor.py` or `tui/app.py` — the spec's Approach anticipated
this as the ideal outcome ("execv is transparent and little or no production code
changes"), and both re-exec observables (AC-2) and the pdeathsig subtlety (AC-3)
verified true against the unmodified code, so no change was required to satisfy them.

## AC-5

Full suite (fresh venv: `pip install -e ".[dev,all,tui]"` — `all` pulls in every
per-capability extra `tests/test_recorder.py`/`test_piper_tts.py`/etc. need for
collection to succeed; `tui` is not included in `all` and must be named explicitly):
```
source .venv/bin/activate
pytest -q
```
Output:
```
755 passed, 2 skipped, 1 warning in 19.87s
```
(The 2 skips are the pre-existing live/replay eval gates — `ASSISTANT_EVAL` unset and
no captured replay baseline — unrelated to this feather.)

Lint:
```
ruff check assistant tests tui
```
Output:
```
All checks passed!
```
