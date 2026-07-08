"""Unit tests for train_batch.py pure logic — no native deps (no livekit/torch)."""

import importlib.util
import sys
from pathlib import Path

TRAINING = Path(__file__).resolve().parent.parent / "training"


def _load(name):
    sys.path.insert(0, str(TRAINING))
    spec = importlib.util.spec_from_file_location(name, TRAINING / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tb = _load("train_batch")
tr = _load("train")


def test_parse_phrases_ignores_blanks_and_comments():
    text = "\n".join([
        "# a comment",
        "hey calcifer",
        "",
        "   ",
        "athena  # trailing comment",
        "# full line",
        "hey penguin",
    ])
    assert tb.parse_phrases(text) == ["hey calcifer", "athena", "hey penguin"]


def test_derive_config_sets_phrase_and_drops_calcifer_specific():
    base = {
        "model_name": "calcifer",
        "target_phrases": ["calcifer"],
        "custom_negative_phrases": ["calcify", "lucifer"],
        "n_samples": 25000,
        "steps": 100000,
        "model": {"model_type": "conv_attention", "model_size": "medium"},
    }
    cfg = tb.derive_config(base, "hey penguin")
    assert cfg["model_name"] == "hey_penguin"           # slugified
    assert cfg["target_phrases"] == ["hey penguin"]
    assert "custom_negative_phrases" not in cfg          # dropped, not inherited
    assert cfg["n_samples"] == 25000                     # shared fields preserved
    assert cfg["steps"] == 100000
    assert cfg["model"] == {"model_type": "conv_attention", "model_size": "medium"}
    # base template is untouched (deepcopy)
    assert base["model_name"] == "calcifer"
    assert base["custom_negative_phrases"] == ["calcify", "lucifer"]


def test_smoke_then_overrides_ordering_on_derived_config():
    base = {"model_name": "calcifer", "target_phrases": ["calcifer"],
            "custom_negative_phrases": ["x"], "n_samples": 25000, "n_samples_val": 5000,
            "steps": 100000, "tts_batch_size": 100}
    cfg = tb.derive_config(base, "athena")
    tr.apply_smoke_overrides(cfg)
    tr.apply_overrides(cfg, n_samples=1000, steps=None)
    assert cfg["model_name"] == "athena_smoke"   # slug + load-bearing _smoke suffix
    assert cfg["n_samples"] == 1000              # explicit override wins over smoke's 200
    assert cfg["n_samples_val"] == 200           # scaled 1000 // 5
    assert cfg["steps"] == 500                   # smoke steps kept (no explicit override)


def test_clear_run_keeps_clips_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "REPO", tmp_path)
    out = tmp_path / "training" / "output" / "calcifer"
    clips = out / "positive_train"
    clips.mkdir(parents=True)
    (clips / "clip_000000.wav").write_bytes(b"x")
    (out / "features_train.npy").write_bytes(b"x")
    (out / "checkpoints").mkdir()
    (out / "checkpoints" / "model.pt").write_bytes(b"x")

    tr.clear_run({"output_dir": "training/output", "model_name": "calcifer"})

    assert (clips / "clip_000000.wav").exists()          # clips survive
    assert not (out / "features_train.npy").exists()     # derived artifacts gone
    assert not (out / "checkpoints").exists()


def test_clear_run_clips_wipes_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "REPO", tmp_path)
    out = tmp_path / "training" / "output" / "calcifer"
    clips = out / "positive_train"
    clips.mkdir(parents=True)
    (clips / "clip_000000.wav").write_bytes(b"x")

    tr.clear_run({"output_dir": "training/output", "model_name": "calcifer"}, clips=True)

    assert not out.exists()

    # missing dir is a no-op, not an error
    tr.clear_run({"output_dir": "training/output", "model_name": "calcifer"}, clips=True)
