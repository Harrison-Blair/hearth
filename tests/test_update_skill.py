"""UpdateSkill: confirm-then-act flow, canned in-character sign-off, no LLM call."""

import random

from assistant.core import persona
from assistant.core.events import Command, Intent
from assistant.skills.update import UpdateSkill


def _skill(persona_enabled=False, rng=None):
    return UpdateSkill(persona_enabled=persona_enabled, rng=rng)


async def test_update_command_prompts_confirmation():
    skill = _skill()
    # A few paraphrases of the same request; routing itself is the orchestrator's
    # job (covered in test_orchestrator.py) — here we just check handle()'s contract.
    for text in ("update yourself", "restart to load the latest code", "check for updates"):
        res = await skill.handle(Command(text), Intent(type="update_self"))
        assert res.expects_reply is True
        assert res.restart is False
        assert res.speech  # non-empty confirmation prompt


async def test_confirm_returns_signoff_and_restart_flag():
    skill = _skill()
    res = await skill.handle_reply(Command("yes"))
    assert res.restart is True
    assert res.speech  # non-empty in-character sign-off


async def test_decline_or_silence_cancels_no_restart():
    skill = _skill()
    for text in ("no", "not now", ""):
        res = await skill.handle_reply(Command(text))
        assert res.restart is False


async def test_confirm_persona_disabled_is_byte_identical_and_voiced():
    # FTHR-007: canned() replaces the local _SIGNOFFS/random.choice; disabled ->
    # the exact current literal, and it's voiced so the Revoicer seam never
    # touches it.
    skill = _skill()
    res = await skill.handle_reply(Command("yes"))
    assert res.speech == "Restarting now."
    assert res.voiced


async def test_confirm_persona_enabled_uses_seeded_rng_for_a_deterministic_variant():
    skill = _skill(persona_enabled=True, rng=random.Random(1))
    res = await skill.handle_reply(Command("yes"))
    assert res.restart is True
    assert res.voiced
    expected = persona.canned("update_signoff", enabled=True, rng=random.Random(1))
    assert res.speech == expected
    assert res.speech in persona._CANNED["update_signoff"][1]
