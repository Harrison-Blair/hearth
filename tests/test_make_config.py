import sys
from pathlib import Path

import pytest

# make_config.py lives under training/ (its own venv), not the assistant package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))

import make_config  # noqa: E402


def base_cfg() -> dict:
    return {"n_samples": 20000, "target_false_positives_per_hour": 0.2, "custom_negative_phrases": []}


def test_single_word_phrase_is_auto_tuned():
    cfg = base_cfg()
    applied = make_config.apply_single_word_tuning(cfg, "penguin")
    assert applied
    assert cfg["n_samples"] >= 40000
    assert cfg["target_false_positives_per_hour"] <= 0.1
    # The plural is always added (cheap, dep-free) and the word itself never is.
    assert "penguins" in cfg["custom_negative_phrases"]
    assert "penguin" not in cfg["custom_negative_phrases"]


def test_multi_word_phrase_keeps_baseline():
    cfg = base_cfg()
    applied = make_config.apply_single_word_tuning(cfg, "hey assistant")
    assert not applied
    assert cfg["n_samples"] == 20000
    assert cfg["target_false_positives_per_hour"] == 0.2
    assert cfg["custom_negative_phrases"] == []


def test_unknown_word_falls_back_to_plural_only():
    # An invented word isn't in any pronunciation dictionary; tuning still applies
    # and never crashes — negatives degrade to just the plural.
    cfg = base_cfg()
    assert make_config.apply_single_word_tuning(cfg, "zorblax")
    assert cfg["custom_negative_phrases"] == ["zorblaxs"]


def test_soundalikes_returns_real_words():
    pytest.importorskip("pronouncing")
    words = make_config.soundalikes("penguin")
    assert words  # at least one similar-sounding real word
    assert "penguin" not in words and "penguins" not in words
