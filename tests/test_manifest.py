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


def test_upsert_maps_livekit_eval_metrics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # A livekit <model>_eval.json: cmd_upsert records the *optimal* operating point.
    eval_json = tmp_path / "calcifer_smoke_eval.json"
    eval_json.write_text(json.dumps({
        "aut": 0.02, "fpph": 3.1, "recall": 0.99, "accuracy": 0.98, "threshold": 0.5,
        "optimal_threshold": 0.62, "optimal_recall": 0.93, "optimal_fpph": 0.05,
        "n_positive": 50, "n_negative": 400, "validation_hours": 0.22,
    }))
    mod = _load_manifest_module()
    mod.cmd_upsert(argparse.Namespace(
        slug="calcifer_smoke", phrase="Calcifer", eval=str(eval_json), target_fpph=0.1,
    ))

    entry = json.loads((tmp_path / "models" / "wake" / "models.json").read_text())["calcifer_smoke"]
    assert entry["phrase"] == "Calcifer"
    assert entry["model_path"] == "models/wake/calcifer_smoke.onnx"
    assert entry["threshold"] == 0.62  # optimal, not the fixed-0.5 threshold
    assert entry["recall"] == 0.93
    assert entry["fpph"] == 0.05
    assert entry["gate_passed"] is True  # optimal_fpph 0.05 <= target 0.1
    assert "trained_at" in entry
