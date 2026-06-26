import sys

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
