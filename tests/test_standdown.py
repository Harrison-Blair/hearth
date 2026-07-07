"""StandDown: engage/resume/deadline-expiry state, with an injected clock."""

from assistant.core.standdown import StandDown


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_inactive_by_default():
    sd = StandDown()
    assert not sd.active
    assert sd.remaining is None


def test_engage_with_duration_expires():
    clock = FakeClock()
    sd = StandDown(clock=clock)
    sd.engage(60)
    assert sd.active
    clock.now += 30
    assert sd.active
    assert sd.remaining == 30
    clock.now += 30
    assert not sd.active
    assert sd.remaining is None


def test_engage_indefinite_never_expires():
    clock = FakeClock()
    sd = StandDown(clock=clock)
    sd.engage(None)
    clock.now += 10_000_000
    assert sd.active
    assert sd.remaining is None


def test_resume_clears():
    sd = StandDown()
    sd.engage(None)
    sd.resume()
    assert not sd.active


def test_reengage_after_expiry():
    clock = FakeClock()
    sd = StandDown(clock=clock)
    sd.engage(10)
    clock.now += 20
    assert not sd.active
    sd.engage(10)
    assert sd.active
