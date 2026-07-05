from tui import envfile


def test_parse_ignores_comments_and_blanks():
    text = "# c\n\nASSISTANT_LLM__MODEL=llama3.2:3b\nbad line no equals\n"
    assert envfile.parse(text) == {"ASSISTANT_LLM__MODEL": "llama3.2:3b"}


def test_read_missing_file_returns_empty(tmp_path):
    assert envfile.read(str(tmp_path / "nope.env")) == ""


def test_read_returns_file_text(tmp_path):
    path = tmp_path / ".env"
    path.write_text("ASSISTANT_LOGGING__LEVEL=DEBUG\n")
    assert envfile.read(str(path)) == "ASSISTANT_LOGGING__LEVEL=DEBUG\n"
