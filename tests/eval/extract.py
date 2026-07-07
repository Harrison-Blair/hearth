"""Extract replay-eval records from a per-run JSONL log.

The daemon's JSONL log (``logs/assistant-<stamp>/assistant.jsonl``) carries every
structured record; the replay eval needs only the ``turn`` records (one per
orchestrator turn) and the ``llm.*`` records (the model I/O that produced them).
This tool copies those into a capture file under ``tests/eval/captures/``.

Usage::

    python -m tests.eval.extract logs/assistant-<stamp>/assistant.jsonl \
        -o tests/eval/captures/session1.jsonl

Curation = open the output and delete unwanted ``turn`` lines; leftover ``llm.*``
lines are harmless (they are just unused cache entries).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path


def extract(lines: Iterable[str]) -> list[dict]:
    """Keep the ``data`` payload (plus timestamp) of every ``turn`` / ``llm.*``
    JSONL entry; skip everything else, including unparseable lines."""
    records: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        data = entry.get("data")
        if not isinstance(data, dict):
            continue
        kind = str(data.get("kind", ""))
        if kind == "turn" or kind.startswith("llm."):
            records.append({"ts": entry.get("ts"), **data})
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log", help="per-run JSONL log (logs/assistant-<stamp>/assistant.jsonl)")
    parser.add_argument(
        "-o", "--output", required=True,
        help="capture file to write (tests/eval/captures/<name>.jsonl)",
    )
    args = parser.parse_args(argv)

    records = extract(Path(args.log).read_text(encoding="utf-8").splitlines())
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    turns = sum(r["kind"] == "turn" for r in records)
    print(f"wrote {len(records)} records ({turns} turns) to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
