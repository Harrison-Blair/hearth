from tui import configfile


def test_write_fields_into_null_section(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("llm:\nstt:\n  model: base\n")

    configfile.write_fields(str(path), {("llm", "model"): "qwen3"})

    data = configfile.read(str(path))
    assert data["llm"]["model"] == "qwen3"
    assert data["stt"]["model"] == "base"
