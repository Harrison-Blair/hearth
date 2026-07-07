"""General-knowledge fallback skill: answer anything via the LLM."""

from __future__ import annotations

import logging

from assistant.core.events import Command, Intent, SkillResult
from assistant.core.persona import canned, with_persona
from assistant.llm.base import LLMProvider
from assistant.skills.base import Skill

log = logging.getLogger(__name__)


class GeneralSkill(Skill):
    name = "general"
    intents = {"general"}

    def tools(self) -> list[dict]:
        # The general fallback is reached by the model answering directly (no tool
        # call), so it must not be offered as a callable tool.
        return []

    def __init__(
        self,
        llm: LLMProvider,
        system_prompt: str,
        persona_suffix: str = "",
        persona_enabled: bool = False,
    ) -> None:
        self._llm = llm
        self._system = with_persona(system_prompt, persona_suffix)
        self._persona_enabled = persona_enabled

    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        draft = intent.slots.get("draft")
        if draft:
            return await self._restyle(draft)
        messages = [{"role": t.role, "content": t.content} for t in cmd.history]
        messages.append({"role": "user", "content": cmd.text})
        try:
            answer = await self._llm.chat(messages, system=self._system, label="answer")
        except Exception as exc:  # noqa: BLE001 - never crash the loop on an LLM error
            log.error("LLM completion failed: %s", exc)
            return SkillResult(
                speech=canned("llm_offline", enabled=self._persona_enabled),
                success=False,
                voiced=True,
            )
        if not answer:
            return SkillResult(
                speech=canned("no_answer", enabled=self._persona_enabled),
                success=False,
                voiced=True,
            )
        return SkillResult(speech=answer, voiced=True)  # self._system already carries persona

    async def _restyle(self, draft: str) -> SkillResult:
        """Re-voice the model's own direct answer in persona without changing its
        meaning. The draft is ground truth: a refusal must stay a refusal, never be
        turned into a confirmation. On any LLM error, speak the draft verbatim rather
        than lose it."""
        prompt = (
            "Rephrase the following answer in your own voice. Keep every fact exactly "
            "as stated; do not add information, and never confirm or deny anything the "
            "answer does not. If it declines or says it cannot do something, your "
            f"rephrasing must decline too.\n\nAnswer: {draft}"
        )
        try:
            styled = await self._llm.complete(prompt, system=self._system, label="restyle")
        except Exception as exc:  # noqa: BLE001 - never crash the loop on an LLM error
            log.error("LLM restyle failed: %s", exc)
            return SkillResult(speech=draft)
        if styled and styled.strip():
            return SkillResult(speech=styled.strip(), voiced=True)  # persona system prompt used
        return SkillResult(speech=draft)
