import pytest

from tests.eval.replay import ReplayMiss, ReplayProvider, replay_key


def _complete_record(prompt="p", system="s", response="r", label="agent", json_mode=False):
    return {
        "kind": "llm.complete", "label": label, "model": "m", "prompt": prompt,
        "system": system, "response": response, "json": json_mode, "latency_ms": 1,
    }


def test_replay_key_stable_across_dict_ordering():
    assert replay_key("k", "l", {"x": 1, "y": 2}) == replay_key("k", "l", {"y": 2, "x": 1})
    assert replay_key("k", "l", {"x": 1}) != replay_key("k", "l", {"x": 2})


async def test_complete_replays_captured_response():
    provider = ReplayProvider([_complete_record(response="captured")])

    assert await provider.complete("p", system="s", label="agent") == "captured"


async def test_chat_key_includes_prepended_system():
    # OllamaProvider logs the system-prepended message list; the provider must
    # rebuild the same shape from a (messages, system=...) call to hit the key.
    record = {
        "kind": "llm.chat", "label": "answer", "model": "m",
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        "response": "hello", "latency_ms": 1,
    }
    provider = ReplayProvider([record])

    assert await provider.chat([{"role": "user", "content": "hi"}], system="sys",
                               label="answer") == "hello"


async def test_chat_tools_rebuilds_tool_calls():
    record = {
        "kind": "llm.chat_tools", "label": "agent", "model": "m",
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        "tools": ["b_tool", "a_tool"],  # captured in registration order
        "content": "",
        "tool_calls": [{"name": "a_tool", "arguments": {"x": "1"}}],
        "latency_ms": 1,
    }
    provider = ReplayProvider([record])

    resp = await provider.chat_tools(
        [{"role": "user", "content": "hi"}], system="sys",
        tools=[{"function": {"name": "a_tool"}}, {"function": {"name": "b_tool"}}],
        label="agent",
    )

    assert resp.content == ""
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "a_tool"
    assert resp.tool_calls[0].arguments == {"x": "1"}


async def test_strict_miss_raises_with_label():
    provider = ReplayProvider([])

    with pytest.raises(ReplayMiss) as exc:
        await provider.complete("unseen prompt", label="agent")

    assert "agent" in str(exc.value)
    assert "unseen prompt" in str(exc.value)


async def test_empty_mode_simulates_llm_down():
    provider = ReplayProvider([], on_miss="empty")

    assert await provider.complete("x") == ""
    resp = await provider.chat_tools([{"role": "user", "content": "x"}])
    assert resp.content == "" and resp.tool_calls == []
    assert provider.misses  # still recorded for diagnostics


async def test_duplicate_keys_replay_in_captured_order_then_stick():
    provider = ReplayProvider([
        _complete_record(response="first"),
        _complete_record(response="second"),
    ])

    assert await provider.complete("p", system="s", label="agent") == "first"
    assert await provider.complete("p", system="s", label="agent") == "second"
    assert await provider.complete("p", system="s", label="agent") == "second"
