"""Tests for `training/manifest.py select` (FTHR-032).

`manifest.py` is a deliberately standalone stdlib-only script (it never imports
the hearth runtime), so these tests load it by path and drive its functions with
`CONFIG`/`MANIFEST` monkeypatched at tmp files, rather than importing a package.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

MANIFEST_PY = Path(__file__).resolve().parent.parent / "training" / "manifest.py"

# An audio-surface config (FTHR-028 shape): a top-level `wake_models` list of
# {path, threshold}, with sibling sections around it so block boundaries matter.
AUDIO_CONFIG = """\
engine:
  host: 127.0.0.1
  port: 8765

input_device: null

wake_models:
  - path: models/wake/vesta.onnx
    threshold: 0.5

endpoint:
  silence_ms: 800
  max_utterance_ms: 12000
"""

# Same surface config but with no wake_models section at all -- the case that
# raises the unhandled StopIteration on today's code.
AUDIO_CONFIG_NO_WAKE = """\
engine:
  host: 127.0.0.1
  port: 8765

input_device: null

endpoint:
  silence_ms: 800
"""

ENGINE_CONFIG = """\
llm:
  tiers:
    default: local
gateway:
  host: 127.0.0.1
"""


def load_manifest_module():
    """Load training/manifest.py by path as an isolated module."""
    spec = importlib.util.spec_from_file_location("manifest_under_test", MANIFEST_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def select_ns(*refs: str) -> argparse.Namespace:
    return argparse.Namespace(refs=list(refs))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A loaded manifest module with CONFIG -> tmp audio.yaml and MANIFEST -> tmp
    registry carrying vesta at its real 0.77 threshold plus a second model."""
    mod = load_manifest_module()
    audio = tmp_path / "audio.yaml"
    audio.write_text(AUDIO_CONFIG)
    registry = tmp_path / "models.json"
    registry.write_text(
        json.dumps(
            {
                "vesta": {
                    "phrase": "Vesta",
                    "model_path": "models/wake/vesta.onnx",
                    "threshold": 0.77,
                },
                "prometheus": {
                    "phrase": "Prometheus",
                    "model_path": "models/wake/prometheus.onnx",
                    "threshold": 0.61,
                },
            }
        )
    )
    monkeypatch.setattr(mod, "CONFIG", audio)
    monkeypatch.setattr(mod, "MANIFEST", registry)
    return mod, audio, registry


def test_select_on_config_without_wake_section_raises_today_then_errors_cleanly(
    tmp_path, monkeypatch
):
    """Against unchanged code the bare next() raises StopIteration; after the fix
    the same case exits with a clear error naming the section and file (AC-4)."""
    mod = load_manifest_module()
    audio = tmp_path / "audio.yaml"
    audio.write_text(AUDIO_CONFIG_NO_WAKE)
    registry = tmp_path / "models.json"
    registry.write_text(
        json.dumps(
            {"vesta": {"phrase": "Vesta", "model_path": "models/wake/vesta.onnx", "threshold": 0.77}}
        )
    )
    monkeypatch.setattr(mod, "CONFIG", audio)
    monkeypatch.setattr(mod, "MANIFEST", registry)

    with pytest.raises(SystemExit) as exc:
        mod.cmd_select(select_ns("vesta"))

    message = str(exc.value)
    assert "wake_models" in message
    assert "audio.yaml" in message


def test_select_writes_path_and_threshold_from_registry(env):
    """select writes {path, threshold} with the threshold sourced from the
    registry (vesta's real 0.77), and a round-trip read returns it (AC-2)."""
    mod, audio, _ = env
    mod.cmd_select(select_ns("vesta"))

    assert mod._read_wake_models() == [("models/wake/vesta.onnx", 0.77)]

    text = audio.read_text()
    assert "path: models/wake/vesta.onnx" in text
    assert "threshold: 0.77" in text
    # The stale default threshold must be gone, replaced by the registry value.
    assert "threshold: 0.5" not in text


def test_select_targets_audio_config_not_engine_config(env, tmp_path):
    """CONFIG points at config/audio.yaml, and select never writes the engine
    config (AC-3 / FC-13 repoint)."""
    fresh = load_manifest_module()
    assert fresh.CONFIG == Path("config/audio.yaml")
    assert "engine.yaml" not in str(fresh.CONFIG)

    mod, _, _ = env
    engine = tmp_path / "engine.yaml"
    engine.write_text(ENGINE_CONFIG)
    mod.cmd_select(select_ns("vesta"))
    assert engine.read_text() == ENGINE_CONFIG


def test_multiple_models_each_keep_their_own_threshold(env):
    """Two selected models each carry their own threshold -- no single shared
    threshold (AC-5 / FC-3 from the writer side)."""
    mod, _, _ = env
    mod.cmd_select(select_ns("vesta", "prometheus"))

    got = mod._read_wake_models()
    assert got == [
        ("models/wake/vesta.onnx", 0.77),
        ("models/wake/prometheus.onnx", 0.61),
    ]
    thresholds = [t for _, t in got]
    assert len(set(thresholds)) == 2  # distinct per-model, not one shared value


def test_manifest_stays_standalone():
    """Loading manifest.py imports no hearth.* runtime module (AC-6). Run in a
    clean subprocess because this test process already imports hearth via
    conftest."""
    script = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('m', r'{MANIFEST_PY}')\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "leaked = [n for n in sys.modules if n == 'hearth' or n.startswith('hearth.')]\n"
        "assert not leaked, leaked\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
