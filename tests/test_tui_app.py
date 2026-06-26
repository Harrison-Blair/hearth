from assistant.tui.app import _as_option


def test_as_option_normalizes_str_and_tuple():
    # Bare strings become (label, value) with both equal; tuples pass through.
    assert _as_option("llama3.2") == ("llama3.2", "llama3.2")
    assert _as_option(("qwen2.5  —  1.8 GB", "qwen2.5")) == ("qwen2.5  —  1.8 GB", "qwen2.5")
