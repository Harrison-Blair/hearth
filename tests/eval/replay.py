"""Replay LLM provider: serves captured responses for the offline eval.

Keys are content hashes of ``(kind, label, payload)``, so a capture and a later
replay need no shared identifiers: when the orchestrator sends byte-identical
prompts and tool catalogues, the hash hits. A deliberate prompt/system/tool
change is therefore a *miss* — the forcing function to re-record the baseline.
"""

from __future__ import annotations

import hashlib
import json as _json
from collections import deque

from assistant.core.events import ToolCall
from assistant.llm.base import ChatResponse, LLMProvider


class ReplayMiss(Exception):
    """A live LLM call had no captured counterpart."""


def _clip(s: str, n: int = 160) -> str:
    return s if len(s) <= n else s[:n] + "…"


def replay_key(kind: str, label: str, payload: dict) -> str:
    blob = _json.dumps(
        {"kind": kind, "label": label, "payload": payload},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _key_of_record(record: dict) -> str | None:
    """Rebuild the replay key from a captured ``llm.*`` record (the shapes
    OllamaProvider logs). Non-LLM records return None."""
    kind = record.get("kind", "")
    label = record.get("label") or "llm"
    if kind == "llm.complete":
        payload = {
            "prompt": record.get("prompt"),
            "system": record.get("system"),
            "json": record.get("json", False),
        }
    elif kind == "llm.chat":
        payload = {"messages": record.get("messages")}
    elif kind == "llm.chat_tools":
        # Sorted names so the key survives registration-order changes; a changed
        # tool *set* still (correctly) misses.
        payload = {"messages": record.get("messages"), "tools": sorted(record.get("tools") or [])}
    else:
        return None
    return replay_key(kind, label, payload)


class ReplayProvider(LLMProvider):
    """LLMProvider that answers from captured records instead of a live model.

    ``on_miss="strict"`` (default) raises :class:`ReplayMiss` on an unseen call;
    ``on_miss="empty"`` returns an empty response, simulating an unreachable LLM
    for degradation tests.
    """

    def __init__(self, records: list[dict], *, on_miss: str = "strict") -> None:
        if on_miss not in ("strict", "empty"):
            raise ValueError(f"on_miss must be 'strict' or 'empty', got {on_miss!r}")
        self._on_miss = on_miss
        self._responses: dict[str, deque[dict]] = {}
        for record in records:
            key = _key_of_record(record)
            if key is not None:
                self._responses.setdefault(key, deque()).append(record)
        self.misses: list[str] = []

    def _lookup(self, kind: str, label: str, payload: dict, describe: str) -> dict | None:
        key = replay_key(kind, label or "llm", payload)
        queue = self._responses.get(key)
        if queue:
            # FIFO so repeated identical calls replay in captured order; the last
            # response stays in place for any further repeats.
            return queue.popleft() if len(queue) > 1 else queue[0]
        self.misses.append(describe)
        if self._on_miss == "strict":
            raise ReplayMiss(f"no captured {kind} [{label or 'llm'}] for: {describe}")
        return None

    async def complete(
        self, prompt: str, *, system: str | None = None, json: bool = False, label: str = ""
    ) -> str:
        record = self._lookup(
            "llm.complete", label,
            {"prompt": prompt, "system": system, "json": json},
            _clip(prompt),
        )
        return record["response"] if record else ""

    async def chat(
        self, messages: list[dict], *, system: str | None = None, label: str = ""
    ) -> str:
        # System-prepended to match the message list OllamaProvider logs.
        msgs = [{"role": "system", "content": system}, *messages] if system else messages
        record = self._lookup("llm.chat", label, {"messages": msgs}, _clip(str(msgs[-1])))
        return record["response"] if record else ""

    async def chat_tools(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        label: str = "",
    ) -> ChatResponse:
        msgs = [{"role": "system", "content": system}, *messages] if system else messages
        tool_names = sorted(t["function"]["name"] for t in tools or [])
        record = self._lookup(
            "llm.chat_tools", label, {"messages": msgs, "tools": tool_names}, _clip(str(msgs[-1]))
        )
        if record is None:
            return ChatResponse()
        calls = [
            ToolCall(name=c["name"], arguments=dict(c.get("arguments") or {}))
            for c in record.get("tool_calls") or []
        ]
        return ChatResponse(content=record.get("content") or "", tool_calls=calls)

    async def health(self) -> bool:
        return True
