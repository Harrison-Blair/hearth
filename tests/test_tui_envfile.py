from tui import envfile

EXAMPLE = """# example
ASSISTANT_LLM__MODEL=qwen2.5:3b-instruct
ASSISTANT_LOGGING__LEVEL=INFO
ASSISTANT_WEB_SEARCH__API_KEY=
"""


def test_parse_ignores_comments_and_blanks():
    text = "# c\n\nASSISTANT_LLM__MODEL=llama3.2:3b\nbad line no equals\n"
    assert envfile.parse(text) == {"ASSISTANT_LLM__MODEL": "llama3.2:3b"}


def test_read_missing_file_returns_empty(tmp_path):
    assert envfile.read(str(tmp_path / "nope.env")) == ""


def test_write_then_read_roundtrip(tmp_path):
    path = str(tmp_path / ".env")
    envfile.write(path, "ASSISTANT_LOGGING__LEVEL=DEBUG")  # no trailing newline
    assert envfile.read(path) == "ASSISTANT_LOGGING__LEVEL=DEBUG\n"


def test_add_missing_appends_absent_keys_with_example_values():
    current = "ASSISTANT_LLM__MODEL=llama3.2:3b\n"
    result = envfile.add_missing(current, EXAMPLE)
    parsed = envfile.parse(result)
    assert parsed["ASSISTANT_LLM__MODEL"] == "llama3.2:3b"  # existing value preserved
    assert parsed["ASSISTANT_LOGGING__LEVEL"] == "INFO"  # added from example
    assert "ASSISTANT_WEB_SEARCH__API_KEY" in parsed  # added (empty value)


def test_add_missing_noop_when_complete():
    current = (
        "ASSISTANT_LLM__MODEL=x\nASSISTANT_LOGGING__LEVEL=y\nASSISTANT_WEB_SEARCH__API_KEY=z\n"
    )
    assert envfile.add_missing(current, EXAMPLE) == current


def test_remove_extra_drops_keys_not_in_example_keeps_comments():
    current = "# keep me\nASSISTANT_LLM__MODEL=x\nASSISTANT_BOGUS__KEY=1\n"
    result = envfile.remove_extra(current, EXAMPLE)
    parsed = envfile.parse(result)
    assert "ASSISTANT_BOGUS__KEY" not in parsed
    assert parsed["ASSISTANT_LLM__MODEL"] == "x"
    assert "# keep me" in result  # comments survive


def test_remove_extra_all_gone_is_empty():
    assert envfile.remove_extra("ASSISTANT_BOGUS__KEY=1\n", EXAMPLE) == ""
