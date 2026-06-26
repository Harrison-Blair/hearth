import argparse
import importlib.util
import json
from pathlib import Path


def _load_manifest_module():
    path = Path(__file__).resolve().parent.parent / "training" / "manifest.py"
    spec = importlib.util.spec_from_file_location("training_manifest", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_regen_backfills_disk_models_and_preserves_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wake = tmp_path / "models" / "wake"
    wake.mkdir(parents=True)
    (wake / "hey_assistant.onnx").touch()
    (wake / "penguin.onnx").touch()
    # A curated entry with eval metrics must survive a regen untouched.
    existing = {
        "hey_assistant": {
            "phrase": "hey assistant",
            "model_path": "models/wake/hey_assistant.onnx",
            "tp_rate": 0.94,
        }
    }
    (wake / "models.json").write_text(json.dumps(existing))

    _load_manifest_module().cmd_regen(argparse.Namespace())

    data = json.loads((wake / "models.json").read_text())
    assert data["hey_assistant"] == existing["hey_assistant"]  # preserved, metrics intact
    assert data["penguin"] == {  # backfilled, phrase derived from the filename
        "phrase": "penguin",
        "model_path": "models/wake/penguin.onnx",
    }
