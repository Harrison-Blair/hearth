"""General-knowledge fallback skill: answer anything via the LLM."""

from __future__ import annotations

import logging

from assistant.core.events import Command, Intent, SkillResult
from assistant.llm.base import LLMProvider
from assistant.skills.base import Skill

log = logging.getLogger(__name__)


class GeneralSkill(Skill):
    name = "general"
    intents = {"general"}

    def __init__(self, llm: LLMProvider, system_prompt: str) -> None:
        self._llm = llm
        self._system = system_prompt

    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        try:
            answer = await self._llm.complete(cmd.text, system=self._system)
        except Exception as exc:  # noqa: BLE001 - never crash the loop on an LLM error
            log.error("LLM completion failed: %s", exc)
            return SkillResult(speech="Sorry, I couldn't reach my language model.", success=False)
        if not answer:
            return SkillResult(speech="Sorry, I don't have an answer for that.", success=False)
        return SkillResult(speech=answer)
