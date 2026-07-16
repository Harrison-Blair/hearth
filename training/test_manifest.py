"""Unit tests for manifest.py's `remove` subcommand (FTHR-021).

manifest.py is stdlib-only, so these run under the normal repo-root pytest
(no training/.venv-train needed). Isolated via a tmp_path-redirected MANIFEST
path, mirroring hearth's own tmp_path test-isolation convention.
"""

from __future__ import annotations

import argparse
import json

import manifest


def _write_manifest(path, data):
    path.write_text(json.dumps(data))


def test_remove_existing_slug_deletes_entry(tmp_path, monkeypatch):
    manifest_path = tmp_path / "models.json"
    other_entry = {
        "phrase": "Other",
        "model_path": "models/wake/other.onnx",
        "fpph": 0.05,
        "recall": 0.99,
        "threshold": 0.5,
        "gate_passed": True,
        "trained_at": "2026-01-01T00:00:00",
    }
    _write_manifest(
        manifest_path,
        {
            "legacy_phrase": {
                "phrase": "Legacy Phrase",
                "model_path": "models/wake/legacy_phrase.onnx",
                "fpph": 0.08,
                "recall": 0.95,
                "threshold": 0.6,
                "gate_passed": True,
                "trained_at": "2026-01-01T00:00:00",
            },
            "other": other_entry,
        },
    )
    monkeypatch.setattr(manifest, "MANIFEST", manifest_path)

    manifest.cmd_remove(argparse.Namespace(slug="legacy_phrase"))

    result = json.loads(manifest_path.read_text())
    assert "legacy_phrase" not in result
    assert result["other"] == other_entry


def test_remove_missing_slug_is_a_noop(tmp_path, monkeypatch):
    manifest_path = tmp_path / "models.json"
    data = {
        "other": {
            "phrase": "Other",
            "model_path": "models/wake/other.onnx",
        },
    }
    _write_manifest(manifest_path, data)
    monkeypatch.setattr(manifest, "MANIFEST", manifest_path)

    manifest.cmd_remove(argparse.Namespace(slug="not_there"))

    result = json.loads(manifest_path.read_text())
    assert result == data
