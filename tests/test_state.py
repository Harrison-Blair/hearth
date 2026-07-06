import io
import json

from assistant.core.state import MARKER, NullStateEmitter, StateEmitter


def _payload(line: str) -> dict:
    assert line.startswith(MARKER)
    return json.loads(line[len(MARKER):])


def test_emitter_writes_parseable_state_line():
    buf = io.StringIO()
    StateEmitter(buf).state("listening")
    assert _payload(buf.getvalue().strip()) == {"state": "listening"}


def test_state_carries_extra_fields():
    buf = io.StringIO()
    StateEmitter(buf).state("thinking", transcript="hello there")
    assert _payload(buf.getvalue().strip()) == {"state": "thinking", "transcript": "hello there"}


def test_level_tick_tags_current_state():
    buf = io.StringIO()
    em = StateEmitter(buf)
    em.state("listening")
    em.level(1234.7)
    last = buf.getvalue().strip().splitlines()[-1]
    assert _payload(last) == {"state": "listening", "level": 1235}  # rounded int


def test_null_emitter_is_silent_and_safe():
    em = NullStateEmitter()
    em.state("listening", transcript="x")
    em.level(10.0)  # no output, no exception
