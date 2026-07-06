"""New-UI tests at the deployment size: 320x480 portrait ≈ 40x30 cells."""

import json

from textual.containers import ScrollableContainer
from textual.widgets import Button, OptionList, SelectionList, Static

from tui import configfile, discovery
from tui.app import AssistantTUI
from tui.screens.config import ConfigScreen
from tui.screens.home import HomeScreen
from tui.screens.logs import ChatModal, LogsScreen
from tui.screens.models import InstalledScreen, ModelDetailScreen, ModelsScreen
from tui.screens.now import NowScreen
from tui.screens.voices import VoicesScreen
from tui.supervisor import DaemonSupervisor
from tui.widgets import Stepper

SIZE = (40, 30)


class FakeSupervisor(DaemonSupervisor):
    def __init__(self, lines=()):
        super().__init__()
        self.sent = []
        self.restarts = 0
        self._lines = list(lines)
        self._running = False

    @property
    def running(self):
        return self._running

    async def start(self, overrides=None):
        self._running = True

    async def stop(self, timeout=5.0):
        self._running = False

    async def restart(self, overrides=None):
        self.restarts += 1
        self._running = True

    async def send(self, line):
        self.sent.append(line)

    async def lines(self):
        for line in self._lines:
            yield line


async def _fake_health(host=discovery.DEFAULT_HOST, **_):
    return True


async def _no_free(host, timeout=5.0):
    return None


def _make_app(monkeypatch, daemon_lines=()):
    monkeypatch.setattr(discovery, "ollama_health", _fake_health)
    monkeypatch.setattr("tui.app.free_ollama_port", _no_free)

    async def _no_results(query, refresh=False):
        return []

    monkeypatch.setattr(discovery, "search_registry", _no_results)

    async def _no_voices():
        return []

    monkeypatch.setattr(discovery, "piper_voice_catalog", _no_voices)
    return AssistantTUI(supervisor=FakeSupervisor(daemon_lines), ollama=FakeSupervisor())


def _assert_fits_40_cols(screen, name):
    for widget in screen.walk_children():
        if not widget.display:
            continue  # hidden log channels reflow when shown
        assert widget.region.right <= 40, f"{name}: {widget!r} overflows"
        if isinstance(widget, ScrollableContainer):
            assert widget.max_scroll_x == 0, f"{name}: {widget!r} scrolls horizontally"


async def test_no_screen_overflows_40_columns(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        _assert_fits_40_cols(app.screen, "now")  # the launch face
        app.pop_screen()  # -> home (sits under Now)
        await pilot.pause()
        _assert_fits_40_cols(app.screen, "home")
        for name in ("logs", "config", "models", "installed", "voices"):
            app.push_screen(name)
            await pilot.pause()
            _assert_fits_40_cols(app.screen, name)
            app.pop_screen()
            await pilot.pause()


async def test_home_nav_roundtrips(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.pop_screen()  # launch shows Now; Home is the ◀ destination under it
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        for button, screen_type in (
            ("#nav-logs", LogsScreen),
            ("#nav-config", ConfigScreen),
            ("#nav-models", ModelsScreen),
        ):
            await pilot.click(button)
            await pilot.pause()
            assert isinstance(app.screen, screen_type)
            app.pop_screen()
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)


async def test_volume_buttons_send_control_commands(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.pop_screen()  # Now -> Home (the volume controls live on Home)
        await pilot.pause()
        start = app._volume
        app.supervisor.sent.clear()
        await pilot.click("#vol-up")
        await pilot.pause()
        assert app._volume == round(start + 0.05, 2)
        assert app.supervisor.sent == [f"SET audio.output_volume {app._volume}"]
        value_text = str(app._home.query_one("#vol-value", Static).render())
        assert value_text == f"{int(round(app._volume * 100))}%"


async def test_mute_toggles_and_restores(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.pop_screen()  # Now -> Home (the mute control lives on Home)
        await pilot.pause()
        before = app._volume
        await pilot.click("#vol-mute")
        await pilot.pause()
        assert app._muted and app._volume == 0.0
        assert str(app._home.query_one("#vol-mute", Button).label) == "Unmute"
        await pilot.pause(0.4)  # leave the button's active-effect window
        await pilot.click("#vol-mute")
        await pilot.pause()
        assert not app._muted and app._volume == before


async def test_chat_modal_sends_text_command(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("logs")
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, ChatModal)
        await pilot.press(*"hello there")
        await pilot.press("enter")
        await pilot.pause()
        assert "TEXT hello there" in app.supervisor.sent
        assert isinstance(app.screen, LogsScreen)


async def test_hidden_channel_line_reflows_on_switch(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("logs")
        await pilot.pause()
        # Write a long line into the hidden LLM channel; it wraps at a fallback
        # width because the widget has no size yet.
        long_line = "word " * 14
        app._log("llm", long_line)
        await pilot.pause()
        app._logs_screen.show_channel("llm")
        await pilot.pause()
        llm = app._logs_screen.log_widget("llm")
        assert llm.lines, "line must render once the channel is shown"
        assert all(strip.cell_length <= llm.scrollable_content_region.width for strip in llm.lines)


async def test_stepper_change_flows_into_apply_overrides(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("config")
        await pilot.pause()
        stepper = app._config_screen.query_one("#field-wake_threshold", Stepper)
        stepper.value = 0.9
        await app._on_config_apply(app._config_screen.form_strings())
        assert app._overrides["ASSISTANT_WAKE__THRESHOLD"] == "0.9"
        assert app.supervisor.restarts == 1


async def test_save_writes_coerced_values(monkeypatch, tmp_path):
    app = _make_app(monkeypatch)
    written = {}

    def _fake_write(path, values):
        written.update(values)

    monkeypatch.setattr(configfile, "write_fields", _fake_write)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("config")
        await pilot.pause()
        app._config_screen.query_one("#field-recorder_silence_ms", Stepper).value = 800
        await pilot.click("#config-save")
        await pilot.pause()
        assert written[("recorder", "silence_ms")] == 800  # int, not "800"
        assert isinstance(written[("wake", "model_paths")], list)


async def test_picker_updates_select_field(monkeypatch):
    app = _make_app(monkeypatch)

    # Keep the wake multiselect empty so real on-disk models can't push the
    # log-level button below the 40x30 viewport and out of click range.
    def _no_wake(root=discovery.WAKE_MODEL_DIR, **_):
        return []

    monkeypatch.setattr(discovery, "wake_models", _no_wake)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("config")
        await pilot.pause()
        await pilot.click("#field-logging_level")
        await pilot.pause()
        picker = app.screen
        opts = picker.query_one("#picker-options", OptionList)
        opts.highlighted = 0
        await pilot.press("enter")
        await pilot.pause()
        assert app._config_screen._select_values[("logging", "level")] == "DEBUG"
        label = str(app._config_screen.query_one("#field-logging_level", Button).label)
        assert label == "DEBUG"


async def test_picking_llm_model_persists_as_default(monkeypatch):
    app = _make_app(monkeypatch)

    def _no_wake(root=discovery.WAKE_MODEL_DIR, **_):
        return []

    monkeypatch.setattr(discovery, "wake_models", _no_wake)

    async def _models_info(host=discovery.DEFAULT_HOST, **_):
        return [
            discovery.OllamaModel(
                name="other:3b", size=0, parameter_size="", quantization="",
                family="", modified_at="",
            )
        ]

    monkeypatch.setattr(discovery, "ollama_models_info", _models_info)

    async def _no_detail(host, name):
        return None

    monkeypatch.setattr(discovery, "ollama_model_detail", _no_detail)
    written = {}
    monkeypatch.setattr(configfile, "write_fields", lambda path, values: written.update(values))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("config")
        await pilot.pause()
        app._overrides["ASSISTANT_LLM__MODEL"] = "stale:1b"
        await pilot.click("#field-llm_model")
        await pilot.pause()
        opts = app.screen.query_one("#picker-options", OptionList)
        opts.highlighted = 0  # "other:3b"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert written == {("llm", "model"): "other:3b"}
        assert "ASSISTANT_LLM__MODEL" not in app._overrides
        assert app.supervisor.restarts == 1


async def test_wake_multiselect_flows_into_apply_as_json(monkeypatch):
    app = _make_app(monkeypatch)

    # The Field stores the provider function object, so patch what it calls at
    # runtime (the glob), not the discovery attribute.
    def _paths(root=discovery.WAKE_MODEL_DIR, **_):
        return ["models/wake/test.onnx", "models/wake/calcifer.onnx"]

    monkeypatch.setattr(discovery, "wake_models", _paths)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("config")
        await pilot.pause()
        sel = app._config_screen.query_one("#field-wake_model_paths", SelectionList)
        sel.deselect_all()
        sel.select(sel.get_option_at_index(0))
        await pilot.pause()
        await app._on_config_apply(app._config_screen.form_strings())
        assert json.loads(app._overrides["ASSISTANT_WAKE__MODEL_PATHS"]) == [
            "models/wake/test.onnx"
        ]


async def test_test_voice_button_sends_say(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("config")
        await pilot.pause()
        app._config_screen.query_one("#field-tts_length_scale", Stepper).value = 1.2
        app.supervisor.sent.clear()
        await app._on_test_voice()
        assert app.supervisor.sent == [
            "SAY 1.2|hmm? Testing the voice. The weather today is sunny and mild."
        ]


async def test_picking_voice_persists_and_restarts(monkeypatch):
    app = _make_app(monkeypatch)
    written = {}
    monkeypatch.setattr(configfile, "write_fields", lambda path, values: written.update(values))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        # A different voice than the configured one persists + restarts.
        await app._on_voice_picked("models/piper/en_US-amy-low.onnx")
        assert written == {("tts", "model_path"): "models/piper/en_US-amy-low.onnx"}
        assert app.supervisor.restarts == 1


async def test_picking_same_voice_is_a_noop(monkeypatch):
    app = _make_app(monkeypatch)
    written = {}
    monkeypatch.setattr(configfile, "write_fields", lambda path, values: written.update(values))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await app._on_voice_picked(app._config.tts.model_path)  # unchanged
        assert written == {} and app.supervisor.restarts == 0


async def test_ack_multiselect_flows_into_apply_as_json(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("config")
        await pilot.pause()
        sel = app._config_screen.query_one("#field-tts_ack_phrases", SelectionList)
        sel.deselect_all()
        sel.select(sel.get_option_at_index(1))  # "uh huh?"
        await pilot.pause()
        await app._on_config_apply(app._config_screen.form_strings())
        assert json.loads(app._overrides["ASSISTANT_TTS__ACK_PHRASES"]) == ["uh huh?"]


async def test_voices_screen_lists_catalog_and_enables_download(monkeypatch):
    app = _make_app(monkeypatch)
    voices = [
        discovery.RegistryVoice(
            key="en_US-amy-low", quality="low", num_speakers=1, size_bytes=63_000_000,
            onnx_path="en/en_US/amy/low/en_US-amy-low.onnx",
            config_path="en/en_US/amy/low/en_US-amy-low.onnx.json",
        )
    ]

    async def _catalog():
        return voices

    monkeypatch.setattr(discovery, "piper_voice_catalog", _catalog)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("voices")
        await pilot.pause()
        opts = app._voices_screen.query_one("#voice-list", OptionList)
        assert opts.option_count == 1
        button = app._voices_screen.query_one("#voice-download", Button)
        assert button.disabled  # nothing picked yet
        opts.focus()
        opts.highlighted = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert not button.disabled
        assert app._voices_screen._selected.key == "en_US-amy-low"
        assert "en_US-amy-low" in str(button.label)


async def test_get_more_voices_button_opens_voices_screen(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("config")
        await pilot.pause()
        app._config_screen.query_one("#voice-get", Button)  # exists on the config screen
        app.push_screen("voices")  # the button's action
        await pilot.pause()
        assert isinstance(app.screen, VoicesScreen)


async def test_model_detail_install_enqueues_pull(monkeypatch):
    app = _make_app(monkeypatch)
    model = discovery.RegistryModel(name="qwen2.5", description="desc")
    tags = [discovery.RegistryTag(ref="qwen2.5:3b", size="1.9GB")]

    async def _tags(name, refresh=False):
        return tags

    pulled = []

    async def _pull(host, ref):
        pulled.append(ref)
        yield discovery.PullProgress(status="success", completed=1, total=1)

    monkeypatch.setattr(discovery, "registry_tags", _tags)
    monkeypatch.setattr(discovery, "pull_model", _pull)

    async def _no_models(host=discovery.DEFAULT_HOST, **_):
        return []

    monkeypatch.setattr(discovery, "ollama_models_info", _no_models)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("models")
        await pilot.pause()
        app._open_model_detail(model)
        await pilot.pause()
        assert isinstance(app.screen, ModelDetailScreen)
        tags_list = app.screen.query_one("#model-tags", OptionList)
        tags_list.focus()
        tags_list.highlighted = 0
        await pilot.press("enter")
        await pilot.pause()
        await pilot.click("#model-install")
        await pilot.pause()
        assert isinstance(app.screen, ModelsScreen)  # popped back to watch progress
        assert pulled == ["qwen2.5:3b"]


async def test_now_is_launch_face(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, NowScreen)


async def test_state_line_updates_now_screen(monkeypatch):
    app = _make_app(monkeypatch, daemon_lines=['@@STATE {"state": "listening"}'])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        indicator = app._now.query_one("#now-indicator", Static)
        assert str(indicator.render()) == "Listening…"
        assert indicator.has_class("state-listening")


async def test_state_lines_not_written_to_log(monkeypatch):
    app = _make_app(monkeypatch, daemon_lines=['@@STATE {"state": "thinking"}'])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert app._now._state == "thinking"
        assert all("@@STATE" not in text.plain for text, _ in app._pending["app"])


async def test_transcript_and_reply_render(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app._on_state({"state": "thinking", "transcript": "what time is it"})
        app._on_state({"state": "speaking", "text": "it is noon"})
        await pilot.pause()
        rendered = str(app._now.query_one("#now-transcript", Static).render())
        assert "you said: what time is it" in rendered
        assert "it is noon" in rendered


async def test_no_speech_and_error_show_banner(monkeypatch):
    app = _make_app(monkeypatch)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        banner = app._now.query_one("#now-banner", Static)
        app._on_state({"state": "no_speech"})
        await pilot.pause()
        assert "Didn't catch that" in str(banner.render())
        app._on_state({"state": "error", "message": "My brain's offline"})
        await pilot.pause()
        assert "My brain's offline" in str(banner.render())
        # A normal turn clears the banner again.
        app._on_state({"state": "listening"})
        await pilot.pause()
        assert str(banner.render()).strip() == ""


async def test_context_button_sends_verb_per_state(monkeypatch):
    for state, verb in (
        ("idle", "LISTEN"),
        ("listening", "CANCEL"),
        ("thinking", "CANCEL"),
        ("speaking", "STOP"),
    ):
        app = _make_app(monkeypatch)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app._on_state({"state": state})
            await pilot.pause()
            app.supervisor.sent.clear()
            await pilot.click("#now-context")
            await pilot.pause()
            assert verb in app.supervisor.sent, f"{state} should send {verb}"


async def test_installed_delete_calls_discovery(monkeypatch):
    app = _make_app(monkeypatch)
    models = [
        discovery.OllamaModel(
            name="qwen2.5:3b", size=1, parameter_size="3B", quantization="", family="",
            modified_at="",
        )
    ]

    async def _models(host=discovery.DEFAULT_HOST, **_):
        return models

    deleted = []

    async def _delete(host, name):
        deleted.append(name)
        models.clear()
        return True

    monkeypatch.setattr(discovery, "ollama_models_info", _models)
    monkeypatch.setattr(discovery, "delete_model", _delete)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.push_screen("installed")
        await pilot.pause()
        assert isinstance(app.screen, InstalledScreen)
        opts = app.screen.query_one("#installed-list", OptionList)
        opts.highlighted = 0
        await pilot.click("#model-delete")
        await pilot.pause()
        assert deleted == ["qwen2.5:3b"]
