"""Config: FIELDS-driven editor built from touch widgets (steppers + pickers).

Each schema field renders as a label row plus a height-3 control: numbers get a
``Stepper``, selects get a full-width button that opens a ``PickerScreen``, and
the wake-model multiselect keeps its checkbox list. Save / Apply / Reset keep
the previous semantics (write config.yaml / env overrides + restart / re-seed
from default-config.yaml).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Label, SelectionList, Static
from textual.widgets.selection_list import Selection as SelectionOption

from assistant.wake import registry
from tui import discovery
from tui.config_schema import FIELDS, Field, coerce
from tui.screens.picker import PickerScreen
from tui.widgets import NavBar, Stepper

if TYPE_CHECKING:
    from assistant.core.config import Config


def field_id(field: Field) -> str:
    return "field-" + "_".join(field.key)


class ConfigScreen(Screen):
    DEFAULT_CSS = """
    ConfigScreen VerticalScroll { padding: 0 1; }
    ConfigScreen Label { height: 1; margin-top: 1; }
    ConfigScreen .select-field { width: 1fr; }
    ConfigScreen Horizontal { height: 3; }
    /* Expand to fit the options; cap and scroll the rest. */
    ConfigScreen #field-wake_model_paths { height: auto; max-height: 10; border: round $panel; }
    ConfigScreen #field-tts_ack_phrases { height: auto; max-height: 6; border: round $panel; }
    ConfigScreen #wake-phrases { height: auto; color: $text-muted; }
    ConfigScreen #wake-clean-smoke { width: 1fr; margin-top: 1; }
    ConfigScreen #voice-test, ConfigScreen #voice-get { width: 1fr; }
    ConfigScreen #model-detail { height: auto; color: $text-muted; margin-top: 1; }
    ConfigScreen #config-actions { dock: bottom; height: 3; }
    ConfigScreen #config-actions Button { width: 1fr; }
    """

    def __init__(self) -> None:
        super().__init__()
        # Chosen value per select field (button labels may carry extra meta).
        self._select_values: dict[tuple[str, ...], str] = {}

    def compose(self) -> ComposeResult:
        cfg = self.app._config
        yield NavBar("Config")
        with VerticalScroll():
            for field in FIELDS:
                yield Label(field.label)
                yield from self._field_widgets(field, cfg)
            yield Static(id="model-detail")
        with Horizontal(id="config-actions"):
            yield Button("Save", id="config-save", variant="primary")
            yield Button("Apply", id="config-apply")
            yield Button("Reset", id="config-reset", variant="warning")

    WAKE_KEY = ("wake", "model_paths")
    VOICE_KEY = ("tts", "model_path")

    def _field_widgets(self, field: Field, cfg: Config) -> ComposeResult:
        wid = field_id(field)
        if field.kind == "multiselect":
            if field.key == self.WAKE_KEY:
                # Wake models are discovered live: options/selection filled on resume.
                yield SelectionList(id=wid)
                yield Static(id="wake-phrases")
                yield Button("Clean smoke-test models", id="wake-clean-smoke", variant="warning")
            else:
                # Static-option multiselect (e.g. ack sounds): populate inline,
                # pre-checking whatever the effective config holds.
                checked = set(discovery.current_value_list(cfg, field.key))
                options = field.options() if field.options else []
                yield SelectionList(
                    *(SelectionOption(label, value, value in checked) for label, value in options),
                    id=wid,
                )
            return
        current = discovery.current_value(cfg, field.key)
        if field.kind == "number":
            yield Stepper(
                float(current or 0), lo=field.lo, hi=field.hi, step=field.step, id=wid
            )
            return
        self._select_values[field.key] = current
        with Horizontal():
            yield Button(current or "(pick…)", id=wid, classes="select-field")
        if field.key == self.VOICE_KEY:
            with Horizontal():
                yield Button("Test voice", id="voice-test", variant="primary")
                yield Button("Get more voices", id="voice-get")

    def _on_screen_resume(self, event: events.ScreenResume) -> None:
        self.app._refresh_status()  # freshly mounted NavBar dots need a first paint
        # Pick up wake models trained/cleaned since the last visit.
        self.app.run_worker(self.app._refresh_wake_options(), group="wake-options")

    # ---- values in/out --------------------------------------------------------

    def form_strings(self) -> dict[tuple[str, ...], str]:
        """Single-valued fields as strings (for env-override diffing)."""
        out: dict[tuple[str, ...], str] = {}
        for field in FIELDS:
            if field.kind == "multiselect":
                continue
            if field.kind == "number":
                out[field.key] = self.query_one(f"#{field_id(field)}", Stepper).value_str
            elif value := self._select_values.get(field.key, ""):
                out[field.key] = value
        return out

    def form_values(self) -> dict[tuple[str, ...], object]:
        """All fields coerced to the types config.yaml expects."""
        values: dict[tuple[str, ...], object] = {
            key: coerce(self._field_by_key(key), raw)
            for key, raw in self.form_strings().items()
        }
        for field in FIELDS:
            if field.kind == "multiselect":
                values[field.key] = self.selected_multiselect(field)
        return values

    def selected_multiselect(self, field: Field) -> list[str]:
        return list(self.query_one(f"#{field_id(field)}", SelectionList).selected)

    def selected_wake_models(self) -> list[str]:
        return list(self.query_one("#field-wake_model_paths", SelectionList).selected)

    @staticmethod
    def _field_by_key(key: tuple[str, ...]) -> Field:
        return next(f for f in FIELDS if f.key == key)

    def set_from_config(self, cfg: Config) -> None:
        """Re-seed every single-valued control (Reset button). The wake multiselect
        is repopulated separately (its options are discovered); static-option
        multiselects are re-checked here."""
        for field in FIELDS:
            if field.kind == "multiselect":
                if field.key != self.WAKE_KEY:
                    self._reseed_static_multiselect(field, cfg)
                continue
            current = discovery.current_value(cfg, field.key)
            if field.kind == "number":
                self.query_one(f"#{field_id(field)}", Stepper).value = float(current or 0)
            else:
                self._select_values[field.key] = current
                self.query_one(f"#{field_id(field)}", Button).label = current or "(pick…)"

    def _reseed_static_multiselect(self, field: Field, cfg: Config) -> None:
        sel = self.query_one(f"#{field_id(field)}", SelectionList)
        wanted = set(discovery.current_value_list(cfg, field.key))
        sel.deselect_all()
        for value in wanted:
            sel.select(value)

    def set_volume(self, value: float) -> None:
        """Keep the volume stepper in sync with the live volume controls on Home."""
        self.query_one("#field-audio_output_volume", Stepper).value = value

    # ---- wake models ----------------------------------------------------------

    def populate_wake_models(self, cfg: Config, options: list[tuple[str, str]]) -> None:
        sel = self.query_one("#field-wake_model_paths", SelectionList)
        # Keep the user's unsaved checks across refreshes; first fill pre-checks
        # whatever the effective config actually loads.
        current = set(sel.selected) if sel.option_count else set(cfg.wake.model_refs())
        sel.clear_options()
        sel.add_options(
            SelectionOption(label, value, value in current) for label, value in options
        )
        self.refresh_wake_phrases()

    def refresh_wake_phrases(self) -> None:
        phrases = registry.phrases_for(self.selected_wake_models())
        text = ", ".join(phrases) if phrases else "(no wake models selected)"
        self.query_one("#wake-phrases", Static).update(f"Wake phrases: {text}")

    @on(SelectionList.SelectedChanged, "#field-wake_model_paths")
    def _on_wake_models_changed(self) -> None:
        self.refresh_wake_phrases()

    @on(Button.Pressed, "#wake-clean-smoke")
    def _on_clean_smoke(self) -> None:
        self.app._clean_smoke_models()

    # ---- voice test / download ------------------------------------------------

    @on(Button.Pressed, "#voice-test")
    async def _on_voice_test(self) -> None:
        await self.app._on_test_voice()

    @on(Button.Pressed, "#voice-get")
    def _on_voice_get(self) -> None:
        self.app.push_screen("voices")

    # ---- select fields (picker) -----------------------------------------------

    @on(Button.Pressed, ".select-field")
    async def _open_picker(self, event: Button.Pressed) -> None:
        field = next(f for f in FIELDS if field_id(f) == event.button.id)
        options = await self.app._select_options(field)
        button = event.button

        def _picked(value: str | None) -> None:
            if value is None:
                return
            self._select_values[field.key] = value
            button.label = value
            if field.key == ("llm", "model"):
                self.query_one("#model-detail", Static).update(f"Loading details for {value}…")
                self.app.run_worker(
                    self.app._show_model_detail(value), group="model-detail", exclusive=True
                )
                self.app.run_worker(self.app._on_model_picked(value), group="model-default")
            elif field.key == self.VOICE_KEY:
                # Persist + restart so the daemon reloads at the new voice's sample
                # rate (a bare rate/ack tweak is live-testable, a model swap is not).
                self.app.run_worker(self.app._on_voice_picked(value), group="voice")

        self.app.push_screen(
            PickerScreen(field.label, options, self._select_values.get(field.key, "")),
            _picked,
        )

    # ---- actions ----------------------------------------------------------------

    @on(Button.Pressed, "#config-save")
    async def _on_save(self) -> None:
        await self.app._on_config_save(self.form_values())

    @on(Button.Pressed, "#config-apply")
    async def _on_apply(self) -> None:
        await self.app._on_config_apply(self.form_strings())

    @on(Button.Pressed, "#config-reset")
    async def _on_reset(self) -> None:
        await self.app._on_config_reset()
