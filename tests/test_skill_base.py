"""Skill base class: the default handle_reply fallback for a stray reply that
no skill's expects_reply flow was actually waiting for (FTHR-007)."""

from assistant.core import persona
from assistant.core.events import Command, Intent, SkillResult
from assistant.skills.base import Skill


class _StubSkill(Skill):
    """Any registered skill that doesn't override handle_reply — the fallback
    is inherited from the base class unchanged."""

    name = "stub"
    intents = {"stub"}

    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        return SkillResult(speech="handled")


class _PersonaStubSkill(_StubSkill):
    persona_enabled = True


async def test_unexpected_reply_fallback_is_byte_identical_when_persona_disabled():
    result = await _StubSkill().handle_reply(Command("out of the blue"))
    assert not result.success
    assert result.speech == "Sorry, I wasn't expecting a reply."
    assert result.voiced  # canned() at the return site -> Revoicer never touches it


async def test_unexpected_reply_fallback_carries_registry_variant_when_persona_enabled():
    result = await _PersonaStubSkill().handle_reply(Command("out of the blue"))
    assert not result.success
    assert result.voiced
    assert result.speech in persona._CANNED["unexpected_reply"][1]
