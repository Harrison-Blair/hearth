import asyncio
import os
import signal
import sys

import pytest

from tui.supervisor import DaemonSupervisor

# A child that reports two env vars, then echoes one line from stdin, then exits.
ECHO_CHILD = (
    "import os,sys;"
    "print('OVERRIDE', os.environ.get('ASSISTANT_TEST', ''), flush=True);"
    "print('PASSTHROUGH', os.environ.get('PASSTHROUGH_VAR', ''), flush=True);"
    "line=sys.stdin.readline();"
    "print('GOT', line.strip(), flush=True)"
)

# A child that runs until terminated.
LOOP_CHILD = "import time\nwhile True: time.sleep(0.05)"


async def test_start_streams_lines_and_merges_env(monkeypatch):
    monkeypatch.setenv("PASSTHROUGH_VAR", "inherited")
    sup = DaemonSupervisor([sys.executable, "-c", ECHO_CHILD])
    await sup.start({"ASSISTANT_TEST": "override"})

    await sup.send("hello")  # reaches the child's stdin
    lines = [line async for line in sup.lines()]

    assert "OVERRIDE override" in lines  # override applied
    assert "PASSTHROUGH inherited" in lines  # os.environ inherited
    assert "GOT hello" in lines  # send() reached child stdin
    await sup.stop()


async def test_stop_terminates_running_child():
    sup = DaemonSupervisor([sys.executable, "-c", LOOP_CHILD])
    await sup.start()
    assert sup.running
    await sup.stop()
    assert not sup.running


async def test_restart_relaunches_child():
    sup = DaemonSupervisor([sys.executable, "-c", LOOP_CHILD])
    await sup.start()
    first = sup._proc.pid
    await sup.restart()
    assert sup.running
    assert sup._proc.pid != first
    await sup.stop()


async def test_send_is_noop_when_not_running():
    sup = DaemonSupervisor([sys.executable, "-c", LOOP_CHILD])
    await sup.send("ignored")  # must not raise


MODEL_CHILD = (
    "import os;print('MODEL', os.environ.get('ASSISTANT_LLM__MODEL', ''), flush=True)"
)


async def test_env_file_merges_into_child(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nASSISTANT_LLM__MODEL=from-dotenv\n")
    sup = DaemonSupervisor([sys.executable, "-c", MODEL_CHILD], env_file=str(env))
    await sup.start()
    lines = [line async for line in sup.lines()]
    assert "MODEL from-dotenv" in lines
    await sup.stop()


async def test_session_override_beats_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ASSISTANT_LLM__MODEL=from-dotenv\n")
    sup = DaemonSupervisor([sys.executable, "-c", MODEL_CHILD], env_file=str(env))
    await sup.start({"ASSISTANT_LLM__MODEL": "from-override"})
    lines = [line async for line in sup.lines()]
    assert "MODEL from-override" in lines  # UI override wins over .env
    await sup.stop()


# ---- in-place re-exec (os.execv, same pid, inherited fds) -----------------------

# Stage 2: what the daemon looks like after re-exec'ing itself. Prints a marker
# distinct from stage 1's, then idles forever (until the test stops it).
REEXEC_STAGE2 = "import time\nprint('MARKER_2', flush=True)\nwhile True: time.sleep(0.05)"

# Stage 1: prints a marker, then re-execs in place (same pid, same stdio fds)
# into stage 2 — mirrors assistant/core/selfupdate.py:restart_in_place.
REEXEC_STAGE1 = (
    "import os, sys\n"
    "print('MARKER_1', flush=True)\n"
    f"os.execv(sys.executable, [sys.executable, '-c', {REEXEC_STAGE2!r}])\n"
)


async def test_supervisor_treats_reexec_as_running():
    sup = DaemonSupervisor([sys.executable, "-c", REEXEC_STAGE1])
    await sup.start()
    assert sup.running

    it = sup.lines().__aiter__()
    assert await asyncio.wait_for(it.__anext__(), 5) == "MARKER_1"
    # No SIGCHLD across an in-place execv: same pid, the process never exits,
    # so returncode stays None and running stays True.
    assert sup.running

    assert await asyncio.wait_for(it.__anext__(), 5) == "MARKER_2"
    assert sup.running

    await sup.stop()


async def test_reexec_does_not_signal_stopped():
    """Models tui/app.py:_pump (lines 239-252): the `async for line in
    self.supervisor.lines()` loop only falls through to `_set_state("stopped")`
    (line 252) once `lines()` ends (stdout EOF). If the re-exec kept the
    parent's read end of stdout open (same fd across execv), `lines()` must
    still be *blocked waiting*, not terminated, right after the post-re-exec
    marker — so the pump's stopped branch is never reached at the re-exec
    boundary.
    """
    sup = DaemonSupervisor([sys.executable, "-c", REEXEC_STAGE1])
    await sup.start()

    it = sup.lines().__aiter__()
    assert await asyncio.wait_for(it.__anext__(), 5) == "MARKER_1"
    assert await asyncio.wait_for(it.__anext__(), 5) == "MARKER_2"

    # If lines() had ended (EOF), __anext__() would raise StopAsyncIteration
    # immediately instead of timing out here.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(it.__anext__(), 0.3)

    await sup.stop()


# A "fake TUI": spawns a daemon-like child through the real DaemonSupervisor
# (so PR_SET_PDEATHSIG is armed exactly as in production), prints the child's
# pid, then sits idle until the test kills it.
_FAKE_TUI = """
import asyncio, sys
from tui.supervisor import DaemonSupervisor

async def main():
    sup = DaemonSupervisor([sys.executable, "-c", {grandchild!r}])
    await sup.start()
    print("CHILD_PID", sup._proc.pid, flush=True)
    await asyncio.sleep(60)

asyncio.run(main())
"""

# The "daemon": re-execs itself once (so pdeathsig must survive the execv),
# then idles forever.
_PDEATHSIG_GRANDCHILD = (
    "import os, sys\n"
    "os.execv(sys.executable, [sys.executable, '-c', "
    "'import time\\nwhile True: time.sleep(0.05)'])\n"
)


async def test_pdeathsig_survives_reexec():
    """`_die_with_parent` arms PR_SET_PDEATHSIG relative to the daemon's
    immediate parent (the TUI) before exec. A normal execve preserves this
    flag (it is cleared only for set-uid/set-gid binaries), so a daemon that
    re-execs itself should still be reaped if the TUI dies. Simulate a TUI
    crash (SIGKILL, no cleanup) via an intermediate process that spawns the
    daemon through the real DaemonSupervisor, and assert the re-exec'd
    grandchild is reaped rather than orphaned.
    """
    outer_script = _FAKE_TUI.format(grandchild=_PDEATHSIG_GRANDCHILD)
    outer = await asyncio.create_subprocess_exec(
        sys.executable, "-c", outer_script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    child_pid = None
    try:
        line = await asyncio.wait_for(outer.stdout.readline(), 5)
        child_pid = int(line.decode().split()[1])

        await asyncio.sleep(0.3)  # let the grandchild actually re-exec first

        outer.kill()  # SIGKILL: simulate an unclean TUI crash
        # Don't unconditionally await outer.wait(): if pdeathsig did NOT
        # survive, the re-exec'd grandchild inherits outer's stdout fd and
        # keeps it open indefinitely, which blocks asyncio's subprocess
        # transport teardown here forever. Bound it instead — the real
        # assertion below is the child-reaped poll, not this wait.
        try:
            await asyncio.wait_for(outer.wait(), 2)
        except asyncio.TimeoutError:
            pass

        deadline = asyncio.get_event_loop().time() + 5
        reaped = False
        while asyncio.get_event_loop().time() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                reaped = True
                break
            await asyncio.sleep(0.1)
        assert reaped, "re-exec'd daemon survived its TUI's death (pdeathsig lost)"
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
