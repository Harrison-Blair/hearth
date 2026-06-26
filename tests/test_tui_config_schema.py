from tui.config_schema import (
    FIELDS,
    Field,
    changed_fields,
    env_name,
    overrides_for,
)


def test_env_name_builds_nested_assistant_var():
    assert env_name(("llm", "model")) == "ASSISTANT_LLM__MODEL"
    assert env_name(("wake", "model_paths")) == "ASSISTANT_WAKE__MODEL_PATHS"
    assert env_name(("logging", "level")) == "ASSISTANT_LOGGING__LEVEL"


def test_field_env_property_matches_helper():
    f = Field(("audio", "output_volume"), "Output volume", "number")
    assert f.env == "ASSISTANT_AUDIO__OUTPUT_VOLUME"


def test_overrides_for_maps_keys_to_env_vars():
    changes = {("llm", "model"): "llama3.2:3b", ("logging", "level"): "DEBUG"}
    assert overrides_for(changes) == {
        "ASSISTANT_LLM__MODEL": "llama3.2:3b",
        "ASSISTANT_LOGGING__LEVEL": "DEBUG",
    }


def test_changed_fields_keeps_only_differences():
    current = {("llm", "model"): "qwen2.5:3b-instruct", ("logging", "level"): "INFO"}
    form = {("llm", "model"): "llama3.2:3b", ("logging", "level"): "INFO"}
    assert changed_fields(form, current) == {("llm", "model"): "llama3.2:3b"}


def test_changed_fields_compares_as_strings():
    # Numbers seeded as strings shouldn't register as changed when equal.
    assert changed_fields({("wake", "threshold"): "0.6"}, {("wake", "threshold"): "0.6"}) == {}


def test_schema_ships_expected_fields():
    keys = {f.key for f in FIELDS}
    assert ("wake", "model_paths") in keys
    assert ("llm", "model") in keys
    assert ("audio", "output_volume") in keys
