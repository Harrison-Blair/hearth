from assistant.wake import registry


def test_prettify_underscores_and_version_suffix():
    assert registry.prettify("hey_assistant") == "hey assistant"
    assert registry.prettify("penguin") == "penguin"
    # Stock models carry a version suffix that shouldn't leak into the phrase.
    assert registry.prettify("hey_jarvis_v0.1") == "hey jarvis"


def test_phrase_for_uses_manifest_then_stem():
    manifest = {"foo": {"phrase": "okay foo", "model_path": "models/wake/foo.onnx"}}
    # Recorded model: matched by the manifest entry's model_path stem.
    assert registry.phrase_for("models/wake/foo.onnx", manifest) == "okay foo"
    # Unrecorded model: falls back to the prettified filename stem.
    assert registry.phrase_for("models/wake/hey_there.onnx", manifest) == "hey there"


def test_phrases_for_dedupes_preserving_order():
    manifest = {}
    # Same phrase reached two ways (path + bare stem) collapses to one entry.
    refs = ["models/wake/penguin.onnx", "models/wake/hey_there.onnx", "penguin"]
    assert [registry.phrase_for(r, manifest) for r in refs] == [
        "penguin",
        "hey there",
        "penguin",
    ]
    assert registry.phrases_for(refs) == ["penguin", "hey there"]
