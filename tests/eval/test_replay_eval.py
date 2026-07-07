"""Offline replay gate: runs whenever curated captures exist, skips otherwise,
so a fresh checkout's ``pytest`` stays green before any baseline is recorded.
See tests/eval/README.md for the capture -> curate -> replay workflow."""

from __future__ import annotations

import pytest

from tests.eval.run_replay import format_table, load_captures, run_replay, scoreable_turns


async def test_replay_matches_baseline():
    records = load_captures()
    if not scoreable_turns(records):
        pytest.skip("no captured turns in tests/eval/captures/; see tests/eval/README.md")

    score, results = await run_replay(records)
    print("\n" + format_table(results, score))
    assert score == 1.0, (
        f"replay score {score:.0%}: orchestrator decisions drifted from the captured "
        "baseline (or the prompt changed — re-record with tests.eval.extract)"
    )
