"""Offline replay eval: re-run captured turns through the real orchestrator.

Loads the curated captures (``tests/eval/captures/*.jsonl``), builds the real
orchestrator with a :class:`ReplayProvider` in place of Ollama, and re-runs each
captured turn's routing decision (``Orchestrator._decide``, exactly like the live
eval). Scores against the captured baseline:

- ``tool`` turns: exact tool name + exact arguments;
- ``direct`` turns: normalized-exact reply match (a ``difflib`` similarity is
  printed on drift for diagnostics);
- a :class:`ReplayMiss` scores as a fail — the prompt/system/tool catalogue
  changed since capture, so the baseline must be re-recorded.

``fallback`` turns (LLM-down at capture time) record a degradation, not a
routing decision, and are skipped.

Run standalone:  ``python -m tests.eval.run_replay``
Or via pytest:   ``tests/eval/test_replay_eval.py`` (skips when no captures).
"""

from __future__ import annotations

import asyncio
import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from assistant.core.config import Config
from assistant.core.events import Turn
from assistant.core.orchestrator import Orchestrator

from tests.eval.replay import ReplayMiss, ReplayProvider
from tests.eval.run_eval import build_orchestrator

CAPTURES_DIR = Path(__file__).parent / "captures"


def load_captures(directory: Path = CAPTURES_DIR) -> list[dict]:
    records: list[dict] = []
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def scoreable_turns(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("kind") == "turn" and r.get("route") in ("tool", "direct")]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.casefold())).strip()


@dataclass
class TurnResult:
    text: str
    expected: str
    got: str
    passed: bool


async def replay_turn(orch: Orchestrator, turn: dict) -> TurnResult:
    history = [Turn(h["role"], h["content"]) for h in turn.get("history", [])]
    if turn["route"] == "tool":
        expected = f"tool {turn['tool']} args={turn['slots']}"
    else:
        expected = "direct answer"
    try:
        resp = await orch._decide(Orchestrator._messages(turn["text"], history))
    except ReplayMiss as miss:
        return TurnResult(
            turn["text"], expected,
            f"MISS ({miss}) — prompt changed since capture; re-record the baseline", False,
        )
    call = resp.tool_calls[0] if resp.tool_calls else None

    if turn["route"] == "tool":
        if call is None:
            return TurnResult(
                turn["text"], expected, "direct answer" if resp.content else "no decision", False
            )
        passed = call.name == turn["tool"] and call.arguments == turn["slots"]
        return TurnResult(turn["text"], expected, f"tool {call.name} args={call.arguments}", passed)

    if call is not None:
        return TurnResult(turn["text"], expected, f"tool {call.name}", False)
    if _normalize(resp.content) == _normalize(turn["speech"]):
        return TurnResult(turn["text"], expected, "direct answer", True)
    ratio = difflib.SequenceMatcher(None, resp.content, turn["speech"]).ratio()
    return TurnResult(
        turn["text"], expected, f"direct answer, content drifted (similarity {ratio:.2f})", False
    )


async def run_replay(records: list[dict]) -> tuple[float, list[TurnResult]]:
    turns = scoreable_turns(records)
    llm_records = [r for r in records if str(r.get("kind", "")).startswith("llm.")]
    replay = ReplayProvider(llm_records, on_miss="strict")
    orch = build_orchestrator(Config(), replay)
    results = [await replay_turn(orch, turn) for turn in turns]
    score = sum(r.passed for r in results) / len(results) if results else 1.0
    return score, results


def format_table(results: list[TurnResult], score: float) -> str:
    lines = [f"{'':4}{'utterance':<48}{'expected':<32}got"]
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        lines.append(f"{mark:<4}{r.text[:47]:<48}{r.expected[:31]:<32}{r.got}")
    passed = sum(r.passed for r in results)
    lines.append("")
    lines.append(f"score: {passed}/{len(results)} = {score:.0%} (gate 100%)")
    return "\n".join(lines)


def main() -> int:
    records = load_captures()
    if not scoreable_turns(records):
        print(f"no captured turns in {CAPTURES_DIR}; see tests/eval/README.md")
        return 1
    score, results = asyncio.run(run_replay(records))
    print(format_table(results, score))
    return 0 if score == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
