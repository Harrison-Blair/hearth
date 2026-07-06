"""Opt-in regression test for live tool-call formatting (Stage-1 gate).

Skips unless ``ASSISTANT_EVAL=1`` and a reachable Ollama with the configured model,
so the default offline ``pytest`` run stays green. See tests/eval/README.md.
"""

from __future__ import annotations

import os

import pytest

from assistant.core.config import Config
from tests.eval.run_eval import PASS_THRESHOLD, check_reachable, format_table, run_eval


async def test_tool_call_formatting():
    if os.environ.get("ASSISTANT_EVAL") != "1":
        pytest.skip("tool-call eval is opt-in; set ASSISTANT_EVAL=1 to run it")

    config = Config()
    if not await check_reachable(config):
        pytest.skip(
            f"Ollama not reachable at {config.llm.host} or model "
            f"{config.llm.model!r} not pulled"
        )

    score, results = await run_eval(config)
    print("\n" + format_table(results, score))
    assert score >= PASS_THRESHOLD, (
        f"tool-call accuracy {score:.0%} below gate {PASS_THRESHOLD:.0%}"
    )
