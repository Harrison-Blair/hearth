"""StandDownSkill: duration parsing -> engage, indefinite fallback, wording."""

from assistant.core.events import Command, Intent
from assistant.core.standdown import StandDown
from assistant.skills.stand_down import StandDownSkill


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _skill():
    standdown = StandDown(clock=FakeClock())
    return StandDownSkill(standdown), standdown


async def test_duration_engages_timed():
    skill, standdown = _skill()
    res = await skill.handle(
        Command("stand down for 30 minutes"), Intent(type="stand_down")
    )
    assert res.success
    assert "30 minutes" in res.speech
    assert standdown.active
    assert standdown.remaining == 30 * 60


async def test_no_duration_engages_indefinite():
    skill, standdown = _skill()
    res = await skill.handle(Command("stand down"), Intent(type="stand_down"))
    assert res.success
    assert "screen" in res.speech
    assert standdown.active
    assert standdown.remaining is None


async def test_duration_slot_preferred_over_text():
    skill, standdown = _skill()
    await skill.handle(
        Command("stand down for a bit"),
        Intent(type="stand_down", slots={"duration": "5 minutes"}),
    )
    assert standdown.remaining == 5 * 60


async def test_garbage_duration_is_indefinite():
    skill, standdown = _skill()
    res = await skill.handle(Command("stand down for a while"), Intent(type="stand_down"))
    assert standdown.active
    assert standdown.remaining is None
    assert "screen" in res.speech
