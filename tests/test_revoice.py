"""Revoicer: restyles a plain skill reply in persona via a live LLM call, with a
failure-cooldown circuit, a bounded timeout, and a digit-preservation guard.

Stub LLM only, no network (see CLAUDE.md test conventions).
"""

import asyncio
import time

from assistant.core.revoice import Revoicer


class StubLLM:
    """Scripted `complete()` reply, or an exception, or a hang. Records every
    call so tests can assert on prompt/system/label and count live calls."""

    def __init__(self, reply="", exc=None, hang=False):
        self.reply = reply
        self.exc = exc
        self.hang = hang
        self.calls = []

    async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
        self.calls.append((prompt, system, label))
        if self.hang:
            await asyncio.sleep(10)
        if self.exc:
            raise self.exc
        return self.reply

    async def chat(self, *a, **k):
        raise AssertionError("Revoicer must not call chat()")

    async def chat_tools(self, *a, **k):
        raise AssertionError("Revoicer must not call chat_tools()")

    async def health(self):
        return True


def _clock(start=0.0):
    """A manually-advanceable fake clock for deterministic circuit tests."""
    state = {"t": start}

    def now():
        return state["t"]

    def advance(dt):
        state["t"] += dt

    return now, advance


async def test_restyles_via_stub_and_preserves_digits():
    llm = StubLLM(reply="Ha! It's 3:15, obviously.")
    revoicer = Revoicer(llm, "persona-block", timeout_s=1.0)
    result = await revoicer.revoice("It's 3:15.")
    assert result == "Ha! It's 3:15, obviously."
    assert len(llm.calls) == 1


async def test_timeout_returns_plain_within_budget_and_warns(caplog):
    llm = StubLLM(hang=True)
    revoicer = Revoicer(llm, "persona-block", timeout_s=0.05)
    start = time.monotonic()
    with caplog.at_level("WARNING"):
        result = await revoicer.revoice("It's 3:15.")
    elapsed = time.monotonic() - start
    assert result == "It's 3:15."
    assert elapsed < 1.0  # bounded by timeout_s, not the 10s hang
    assert any("revoice" in r.message.lower() for r in caplog.records)


async def test_stub_error_returns_plain():
    llm = StubLLM(exc=RuntimeError("boom"))
    revoicer = Revoicer(llm, "persona-block", timeout_s=1.0)
    result = await revoicer.revoice("It's 3:15.")
    assert result == "It's 3:15."


async def test_empty_reply_returns_plain():
    llm = StubLLM(reply="   ")
    revoicer = Revoicer(llm, "persona-block", timeout_s=1.0)
    result = await revoicer.revoice("It's 3:15.")
    assert result == "It's 3:15."


async def test_digit_mutation_returns_plain():
    llm = StubLLM(reply="It's 4:15 now.")  # 3:15 mutated to 4:15
    revoicer = Revoicer(llm, "persona-block", timeout_s=1.0)
    result = await revoicer.revoice("It's 3:15.")
    assert result == "It's 3:15."


async def test_digit_drop_returns_plain():
    llm = StubLLM(reply="It's the time now.")  # digits dropped entirely
    revoicer = Revoicer(llm, "persona-block", timeout_s=1.0)
    result = await revoicer.revoice("It's 3:15.")
    assert result == "It's 3:15."


async def test_open_circuit_after_failure_is_immediate_zero_calls():
    now, _advance = _clock()
    llm = StubLLM(exc=RuntimeError("boom"))
    revoicer = Revoicer(llm, "persona-block", timeout_s=1.0, now=now)
    first = await revoicer.revoice("hello")
    assert first == "hello"
    assert len(llm.calls) == 1
    # Circuit now open: immediate passthrough, no further LLM call.
    second = await revoicer.revoice("hello again")
    assert second == "hello again"
    assert len(llm.calls) == 1


async def test_circuit_recloses_after_cooldown():
    now, advance = _clock()
    llm = StubLLM(exc=RuntimeError("boom"))
    revoicer = Revoicer(llm, "persona-block", timeout_s=1.0, cooldown_s=10.0, now=now)
    await revoicer.revoice("hello")
    assert len(llm.calls) == 1
    advance(10.1)
    llm.exc = None
    llm.reply = "Restyled hello"
    result = await revoicer.revoice("hello")
    assert len(llm.calls) == 2
    assert result == "Restyled hello"


async def test_seeded_unhealthy_is_immediate_passthrough_zero_calls():
    llm = StubLLM(reply="should not be used")
    revoicer = Revoicer(llm, "persona-block", timeout_s=1.0, healthy=False)
    result = await revoicer.revoice("hello")
    assert result == "hello"
    assert llm.calls == []


async def test_revoice_disabled_is_passthrough_zero_calls():
    llm = StubLLM(reply="styled")
    revoicer = Revoicer(llm, "persona-block", timeout_s=1.0, enabled=False)
    result = await revoicer.revoice("hello")
    assert result == "hello"
    assert llm.calls == []


async def test_prompt_carries_persona_and_plain_text_no_history():
    llm = StubLLM(reply="styled reply")
    revoicer = Revoicer(llm, "PERSONA-BLOCK", timeout_s=1.0)
    await revoicer.revoice("the plain reply")
    assert len(llm.calls) == 1
    prompt, system, label = llm.calls[0]
    assert prompt == "the plain reply"  # no history threaded in - single string prompt
    assert "PERSONA-BLOCK" in system
    assert label == "revoice"
