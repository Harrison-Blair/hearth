from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from tui.widgets import NavBar, Stepper


class _StepperApp(App):
    def __init__(self, **kwargs):
        super().__init__()
        self._kwargs = kwargs
        self.changes: list[float] = []

    def compose(self) -> ComposeResult:
        yield Stepper(id="s", **self._kwargs)

    def on_stepper_changed(self, event: Stepper.Changed) -> None:
        self.changes.append(event.value)


async def test_stepper_steps_and_posts_changed():
    app = _StepperApp(value=0.5, lo=0.0, hi=1.0, step=0.05)
    async with app.run_test(size=(40, 30)) as pilot:
        # Pause between clicks: a Button ignores presses inside its active-effect
        # window, so back-to-back clicks would swallow the second press.
        for selector in ("#s .stepper-inc", "#s .stepper-inc", "#s .stepper-dec"):
            await pilot.click(selector)
            await pilot.pause(0.5)
        assert app.changes == [0.55, 0.6, 0.55]
        assert app.query_one("#s", Stepper).value == 0.55


async def test_stepper_clamps_at_bounds_without_message():
    app = _StepperApp(value=3, lo=0, hi=3, step=1)
    async with app.run_test(size=(40, 30)) as pilot:
        await pilot.click("#s .stepper-inc")  # already at hi: no change, no message
        await pilot.pause()
        assert app.changes == []
        assert app.query_one("#s", Stepper).value == 3


def test_stepper_value_str_keeps_ints_int():
    s = Stepper(value=2, lo=0, hi=3, step=1)
    assert s.value_str == "2"
    s = Stepper(value=0.55, lo=0, hi=1, step=0.05)
    assert s.value_str == "0.55"


async def test_stepper_setter_updates_display_silently():
    app = _StepperApp(value=0.2, lo=0.0, hi=1.0, step=0.1)
    async with app.run_test(size=(40, 30)) as pilot:
        stepper = app.query_one("#s", Stepper)
        stepper.value = 0.7
        await pilot.pause()
        assert app.changes == []
        assert app.query_one("#s .stepper-value", Input).value == "0.7"


async def test_stepper_accepts_typed_value_on_enter():
    app = _StepperApp(value=0.66, lo=0.0, hi=1.0, step=0.05)
    async with app.run_test(size=(40, 30)) as pilot:
        box = app.query_one("#s .stepper-value", Input)
        box.focus()
        box.value = "0.5"
        await pilot.press("enter")
        assert app.changes == [0.5]
        assert app.query_one("#s", Stepper).value == 0.5


async def test_stepper_typed_value_is_clamped_and_normalized():
    app = _StepperApp(value=0.5, lo=0.0, hi=1.0, step=0.05)
    async with app.run_test(size=(40, 30)) as pilot:
        box = app.query_one("#s .stepper-value", Input)
        box.focus()
        box.value = "7"  # above hi: clamps to 1, display normalized
        await pilot.press("enter")
        assert app.changes == [1.0]
        assert box.value == "1"


async def test_stepper_unparseable_typed_value_reverts():
    app = _StepperApp(value=0.5, lo=0.0, hi=1.0, step=0.05)
    async with app.run_test(size=(40, 30)) as pilot:
        box = app.query_one("#s .stepper-value", Input)
        box.focus()
        box.value = ""  # cleared, then abandoned
        await pilot.press("enter")
        assert app.changes == []
        assert box.value == "0.5"


async def test_stepper_typed_value_commits_on_blur():
    app = _StepperApp(value=0.5, lo=0.0, hi=1.0, step=0.05)
    async with app.run_test(size=(40, 30)) as pilot:
        box = app.query_one("#s .stepper-value", Input)
        box.focus()
        await pilot.pause()  # focus must land before blurring can fire
        box.value = "0.8"
        app.set_focus(None)  # leave the field without pressing enter
        await pilot.pause()
        assert app.changes == [0.8]
        assert app.query_one("#s", Stepper).value == 0.8


async def test_stepper_buttons_still_step_after_typing():
    app = _StepperApp(value=0.5, lo=0.0, hi=1.0, step=0.05)
    async with app.run_test(size=(40, 30)) as pilot:
        box = app.query_one("#s .stepper-value", Input)
        box.focus()
        box.value = "0.7"
        await pilot.click("#s .stepper-inc")  # blur commits 0.7, then the press steps
        await pilot.pause(0.5)
        assert app.query_one("#s", Stepper).value == 0.75
        assert app.changes == [0.7, 0.75]


class _NavApp(App):
    def compose(self) -> ComposeResult:
        yield NavBar("Config")


async def test_navbar_dots_reflect_state():
    app = _NavApp()
    async with app.run_test(size=(40, 30)) as pilot:
        bar = app.query_one(NavBar)
        bar.set_dots(True, False)
        await pilot.pause()
        dots = app.query_one(".nav-dots", Static).render()
        # First dot (daemon) green, second (ollama) red.
        styles = [str(s.style) for s in getattr(dots, "spans", [])]
        assert any("green" in s for s in styles) and any("red" in s for s in styles)
