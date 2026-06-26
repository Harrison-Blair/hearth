from tui import configfile
from tui.config_schema import FIELDS, coerce


def _field(key):
    return next(f for f in FIELDS if f.key == key)


def test_read_missing_file_returns_empty(tmp_path):
    assert configfile.read(str(tmp_path / "nope.yaml")) == {}


def test_write_fields_sets_nested_key_and_preserves_others(tmp_path):
    path = str(tmp_path / "config.yaml")
    configfile.write_fields(
        path,
        {("audio", "output_volume"): 0.5, ("llm", "model"): "qwen2.5:3b-instruct"},
    )
    # Overwrite one key; the other section/key must survive untouched.
    configfile.write_fields(path, {("audio", "output_volume"): 0.8})
    data = configfile.read(path)
    assert data["audio"]["output_volume"] == 0.8
    assert data["llm"]["model"] == "qwen2.5:3b-instruct"


def test_write_fields_creates_intermediate_maps(tmp_path):
    path = str(tmp_path / "config.yaml")
    configfile.write_fields(path, {("wake", "threshold"): 0.6})
    assert configfile.read(path) == {"wake": {"threshold": 0.6}}


def test_coerce_types():
    assert coerce(_field(("recorder", "silence_ms")), "800") == 800  # int
    assert coerce(_field(("wake", "threshold")), "0.6") == 0.6  # float
    assert coerce(_field(("audio", "output_volume")), "1.0") == 1.0  # float fallback
    assert coerce(_field(("stt", "model")), "base.en") == "base.en"  # str
