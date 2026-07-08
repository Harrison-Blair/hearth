from tui.logparse import dedup_key, parse


def test_parses_well_formed_line():
    line = "12:34:56 INFO    assistant.core.pipeline: Listening for wake word..."
    p = parse(line)
    assert p.timestamp == "12:34:56"
    assert p.level == "INFO"
    assert p.logger == "assistant.core.pipeline"
    assert p.message == "Listening for wake word..."
    assert p.raw == line


def test_llm_line_routes_to_llm_view():
    p = parse("12:00:00 INFO    assistant.llm.ollama_provider: LLM response: hi")
    assert p.is_llm is True
    assert p.message == "LLM response: hi"


def test_non_llm_line_is_app_only():
    p = parse("12:00:00 INFO    assistant.core.pipeline: Reply: 'it is noon'")
    assert p.is_llm is False


def test_non_matching_line_falls_back_gracefully():
    # A traceback / raw print: no fields, raw preserved, never routed to LLM.
    line = '  File "x.py", line 3, in <module>'
    p = parse(line)
    assert p.timestamp is None
    assert p.level is None
    assert p.logger is None
    assert p.message == line
    assert p.raw == line
    assert p.is_llm is False


def test_dedup_key_ignores_timestamp():
    # Same event a second apart collapses; differing message does not.
    a = parse("12:00:00 WARNING assistant.llm: reconnecting")
    b = parse("12:00:01 WARNING assistant.llm: reconnecting")
    c = parse("12:00:02 WARNING assistant.llm: gave up")
    assert dedup_key(a) == dedup_key(b)
    assert dedup_key(a) != dedup_key(c)


def test_dedup_key_falls_back_to_raw_for_unparsed_lines():
    line = '  File "x.py", line 3, in <module>'
    assert dedup_key(parse(line)) == line
