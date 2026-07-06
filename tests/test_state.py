import io

from assistant.core.state import MARKER, NullStateEmitter, StateEmitter, parse


def test_emitter_writes_parseable_state_line():
    buf = io.StringIO()
    StateEmitter(buf).state("listening")
    out = buf.getvalue()
    assert out.startswith(MARKER)
    assert parse(out.strip()) == {"state": "listening"}


def test_state_carries_extra_fields():
    buf = io.StringIO()
    StateEmitter(buf).state("thinking", transcript="hello there")
    assert parse(buf.getvalue().strip()) == {"state": "thinking", "transcript": "hello there"}


def test_level_tick_tags_current_state():
    buf = io.StringIO()
    em = StateEmitter(buf)
    em.state("listening")
    em.level(1234.7)
    last = buf.getvalue().strip().splitlines()[-1]
    assert parse(last) == {"state": "listening", "level": 1235}  # rounded int


def test_parse_rejects_non_marker_and_bad_json():
    assert parse("2026-07-05 INFO assistant: hi") is None
    assert parse(MARKER + "not-json") is None
    assert parse(MARKER + "[1, 2, 3]") is None  # not a dict


def test_null_emitter_is_silent_and_safe():
    em = NullStateEmitter()
    em.state("listening", transcript="x")
    em.level(10.0)  # no output, no exception
