import json

from tests.eval.extract import extract


def _entry(ts, data=None, **fields):
    entry = {"ts": ts, "level": "INFO", "logger": "x", "message": "m", **fields}
    if data is not None:
        entry["data"] = data
    return json.dumps(entry)


def test_extract_keeps_turn_and_llm_records_only():
    lines = [
        _entry("t1", {"kind": "turn", "text": "hi", "route": "direct"}),
        _entry("t2", {"kind": "llm.chat_tools", "label": "agent"}),
        _entry("t3", {"kind": "llm.complete", "label": "agent"}),
        _entry("t4", {"kind": "route.tool", "tool": "echo"}),  # not a replay record
        _entry("t5", {"kind": "boot.config"}),
        _entry("t6"),  # plain log line, no data
        "not json at all",
        "",
    ]

    records = extract(lines)

    assert [r["kind"] for r in records] == ["turn", "llm.chat_tools", "llm.complete"]
    assert records[0] == {"ts": "t1", "kind": "turn", "text": "hi", "route": "direct"}


def test_extract_preserves_full_payload():
    data = {
        "kind": "llm.chat_tools",
        "label": "agent",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": ["echo"],
        "content": "",
        "tool_calls": [{"name": "echo", "arguments": {"text": "hi"}}],
        "latency_ms": 42,
    }

    records = extract([_entry("t1", data)])

    assert records == [{"ts": "t1", **data}]
