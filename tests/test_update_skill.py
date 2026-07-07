"""UpdateSkill: confirm-then-act flow, canned in-character sign-off, no LLM call."""

from assistant.core.events import Command, Intent
from assistant.skills.update import UpdateSkill


def _skill():
    return UpdateSkill()


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
