"""Stamp a training config for a given wake phrase from training/wakeword.yml.

Overrides the phrase-specific fields (target_phrase, model_name) so all shared
tuning stays in one place. A single-word phrase ("penguin") is automatically
optimized for detection accuracy — short triggers false-fire heavily, so we raise
n_samples (robustness), lower target_false_positives_per_hour (stricter accept
gate), and add the plural + similar-sounding real words as negatives. `--smoke`
shrinks the sample/step counts for a fast end-to-end validation run and suffixes
the model name so it can't clobber a full model. Prints the path of the written
config on stdout (for train.sh to consume); auto-tune notes go to stderr.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

import yaml

BASE = Path("training/wakeword.yml")


def slug(phrase: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", phrase.lower()).strip("_") or "wakeword"


def is_single_word(phrase: str) -> bool:
    return len(phrase.split()) == 1


def _strip_stress(phones: str) -> list[str]:
    """CMU phones like 'P EH1 NG' -> ['P', 'EH', 'NG'] (drop stress digits)."""
    return [re.sub(r"\d", "", p) for p in phones.split()]


def soundalikes(word: str, n: int = 6, threshold: float = 0.6) -> list[str]:
    """Real English words that sound similar to `word`, for use as negatives.

    Ranks the CMU pronouncing dictionary by phonetic similarity. Returns [] when
    the optional `pronouncing` dep is missing (plural-only fallback) or the word
    isn't in the dictionary (invented names)."""
    try:
        import pronouncing
    except ImportError:
        return []

    pron = pronouncing.phones_for_word(word.lower())
    if not pron:
        return []
    target = _strip_stress(pron[0])
    plural = f"{word.lower()}s"

    scored: dict[str, float] = {}
    for entry, phones in pronouncing.pronunciations:
        cand = entry.lower()
        if cand == word.lower() or cand == plural or not cand.isalpha():
            continue
        ratio = difflib.SequenceMatcher(None, target, _strip_stress(phones)).ratio()
        if ratio >= threshold and ratio > scored.get(cand, 0.0):
            scored[cand] = ratio
    return [w for w, _ in sorted(scored.items(), key=lambda kv: kv[1], reverse=True)[:n]]


def apply_single_word_tuning(cfg: dict, phrase: str) -> bool:
    """Optimize a one-word phrase for detection accuracy. Returns True if applied."""
    if not is_single_word(phrase):
        return False
    word = phrase.lower()
    cfg["n_samples"] = max(int(cfg.get("n_samples", 20000)), 40000)
    cfg["target_false_positives_per_hour"] = min(
        float(cfg.get("target_false_positives_per_hour", 0.2)), 0.1
    )
    negatives = set(cfg.get("custom_negative_phrases") or [])
    negatives.update({f"{word}s", *soundalikes(word)})
    negatives.discard(word)
    cfg["custom_negative_phrases"] = sorted(negatives)
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phrase", default=None, help="wake phrase (default: base config's)")
    ap.add_argument("--name", default=None, help="model name (default: slug of phrase)")
    ap.add_argument("--smoke", action="store_true", help="tiny fast validation run")
    ap.add_argument("--out", default=None, help="output path (default: training/work/<name>.yml)")
    a = ap.parse_args()

    cfg = yaml.safe_load(BASE.read_text())
    phrase = a.phrase or cfg["target_phrase"][0]
    name = a.name or slug(phrase)
    cfg["target_phrase"] = [phrase]
    if apply_single_word_tuning(cfg, phrase):
        print(
            f"==> Single-word phrase '{phrase}': auto-tuned for accuracy "
            f"(n_samples={cfg['n_samples']}, "
            f"target_false_positives_per_hour={cfg['target_false_positives_per_hour']}, "
            f"{len(cfg['custom_negative_phrases'])} negative phrases)",
            file=sys.stderr,
        )
    if a.smoke:
        name = f"{name}_smoke"
        cfg["n_samples"] = 2000
        cfg["n_samples_val"] = 500
        cfg["steps"] = 20000
    cfg["model_name"] = name

    out = Path(a.out or f"training/work/{name}.yml")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(cfg, sort_keys=False))
    print(out)
