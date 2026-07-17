"""Audio surface spine tests (FTHR-028).

Exercise the `hearth-audio` veneer's spine against **stage doubles** and the
supplied-frames source -- no real wake/STT, no hardware. These prove the spine
orchestrates a turn and is **duplex-shaped** (capture is continuous and
turn-independent); they do NOT prove any real wake/VAD/STT works (FTHR-029/030/
031) nor that a real mic captures while playing (FTHR-033 manual smoke).
"""
from __future__ import annotations

import ast
import asyncio
import pathlib

import pytest


# --- the tracer: supplied frames drive a full turn ---------------------------


async def test_supplied_audio_drives_a_turn_end_to_end():
    """A doubled wake trigger in the supplied frames produces a captured
    utterance, a doubled transcript, a turn submitted via the contract, and the
    answer presented. The spine's tracer proof."""
    from hearth.audio.source import SuppliedFramesSource
    from hearth.audio.stages import FixedTranscriber, ScriptedEndpointer, ScriptedWakeDetector
    from hearth.audio.surface import AudioSurface

    submitted: list[str] = []
    presented: list[str] = []

    async def submit(transcript: str) -> list[dict]:
        submitted.append(transcript)
        return [
            {"type": "answer", "turn_id": "t", "text": "hello there"},
            {"type": "done", "turn_id": "t"},
        ]

    surface = AudioSurface(
        source=SuppliedFramesSource(["wake", "endpoint"]),
        wake=ScriptedWakeDetector(trigger="wake"),
        endpointer=ScriptedEndpointer(sentinel="endpoint"),
        transcriber=FixedTranscriber("what time is it"),
        submit=submit,
        present=presented.append,
    )

    await asyncio.wait_for(surface.run(), timeout=2.0)

    assert submitted == ["what time is it"]
    # Heard transcript and engine answer both reach the surface.
    joined = "\n".join(presented)
    assert "what time is it" in joined
    assert "hello there" in joined


# --- the crux: duplex, deadlock-shaped ---------------------------------------


async def test_capture_continues_while_a_turn_is_in_flight():
    """AC-4's load-bearing duplex test. The submit seam **blocks** (never
    completes); more frames arrive while it is blocked. The capture loop must
    keep consuming them and detect a **second** wake.

    Shaped so a sequential implementation -- one that awaits the submit inside
    the capture path -- cannot pass: it stalls on the first (blocked) submit
    and never reaches the second wake, so the bounded `wait_for` **times out**
    rather than mis-asserting. A serial loop fails to make progress here; it
    does not fail an assertion.
    """
    from hearth.audio.source import SuppliedFramesSource
    from hearth.audio.stages import FixedTranscriber, ScriptedEndpointer
    from hearth.audio.surface import AudioSurface

    wake_count = 0
    second_wake = asyncio.Event()

    class CountingWake:
        def detect(self, frame) -> bool:
            nonlocal wake_count
            if frame == "wake":
                wake_count += 1
                if wake_count >= 2:
                    second_wake.set()
                return True
            return False

    async def blocking_submit(transcript: str) -> list[dict]:
        # Never returns: a turn is outstanding with the engine for the whole
        # remainder of the test.
        await asyncio.Event().wait()
        return []

    surface = AudioSurface(
        source=SuppliedFramesSource(["wake", "endpoint", "wake", "endpoint"], pace=True),
        wake=CountingWake(),
        endpointer=ScriptedEndpointer(sentinel="endpoint"),
        transcriber=FixedTranscriber("hi"),
        submit=blocking_submit,
        present=lambda _m: None,
    )

    run_task = asyncio.create_task(surface.run())
    try:
        # A sequential spine blocks on the first submit and never gets here;
        # this wait_for then times out and fails the test -- the PLM-007-F5 bar.
        await asyncio.wait_for(second_wake.wait(), timeout=1.5)
    finally:
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task

    assert wake_count >= 2


# --- retry with backoff (FC-10), unlike chat's fail-fast ---------------------


async def test_unreachable_engine_is_retried_with_backoff():
    """With the engine unreachable the surface retries (bounded, backing off)
    rather than exiting; once reachable, it proceeds. Contrast chat's
    fail-fast."""
    from hearth.audio.surface import open_with_retry
    from hearth.veneers.base import EngineUnreachable

    attempts = 0
    delays: list[float] = []

    def flaky_connect(host, port):
        # An async context manager whose __aenter__ fails until the 3rd try.
        class _CM:
            async def __aenter__(self):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise EngineUnreachable(host, port)
                return "connection"

            async def __aexit__(self, *exc):
                return False

        return _CM()

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async with open_with_retry(
        "127.0.0.1",
        8765,
        max_attempts=5,
        base_delay=0.5,
        connect_fn=flaky_connect,
        sleep=fake_sleep,
    ) as connection:
        assert connection == "connection"

    assert attempts == 3  # failed twice, succeeded on the third
    # Backoff grows between retries rather than hammering at a fixed interval.
    assert delays == [0.5, 1.0]


async def test_unreachable_engine_gives_up_after_bounded_attempts():
    """Retry is bounded: after exhausting its attempts the surface surfaces
    `EngineUnreachable` rather than looping forever."""
    from hearth.audio.surface import open_with_retry
    from hearth.veneers.base import EngineUnreachable

    def always_refuses(host, port):
        class _CM:
            async def __aenter__(self):
                raise EngineUnreachable(host, port)

            async def __aexit__(self, *exc):
                return False

        return _CM()

    async def fake_sleep(delay: float) -> None:
        return None

    with pytest.raises(EngineUnreachable):
        async with open_with_retry(
            "127.0.0.1",
            8765,
            max_attempts=3,
            base_delay=0.1,
            connect_fn=always_refuses,
            sleep=fake_sleep,
        ):
            pass


# --- config loads independently and carries the hoisted wake schema ----------


def test_audio_config_loads_independently_and_carries_wake_schema(tmp_path, monkeypatch):
    """The surface loads `config/audio.yaml` via the shared facility with the
    engine's config absent, and the wake-model list parses as ordered
    `{path, threshold}` entries with per-model thresholds and no global
    threshold (FC-12 + the hoisted FC-3 schema)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    # Only audio.yaml exists -- no engine.yaml. Independent load.
    (config_dir / "audio.yaml").write_text(
        "engine:\n"
        "  host: 127.0.0.1\n"
        "  port: 8765\n"
        "wake_models:\n"
        "  - path: models/wake/vesta.onnx\n"
        "    threshold: 0.5\n"
        "  - path: models/wake/second.onnx\n"
        "    threshold: 0.72\n"
    )
    monkeypatch.setattr("hearth.config.CONFIG_DIR", config_dir)
    for key in list(__import__("os").environ):
        if key.startswith("HEARTH_"):
            monkeypatch.delenv(key, raising=False)

    from hearth.audio.config import AudioSettings

    settings = AudioSettings()
    assert not (config_dir / "engine.yaml").exists()
    assert [(m.path, m.threshold) for m in settings.wake_models] == [
        ("models/wake/vesta.onnx", 0.5),
        ("models/wake/second.onnx", 0.72),
    ]
    # No global threshold on the model: thresholds are strictly per-model (FC-3).
    assert not hasattr(settings, "threshold")


# --- presentation goes only through the shared safety policy -----------------


def test_surface_presents_via_safety_policy():
    """A tool-activity / error event reaches the surface output only through the
    whitelist: no query / arguments / observation / result / internal detail can
    leak, even when present on the message dict."""
    from hearth.audio.surface import render

    activity = render(
        {
            "type": "tool_activity",
            "turn_id": "t",
            "phase": "act",
            "label": "consulting the brain",
            "query": "SECRET_QUERY",
            "arguments": "SECRET_ARGS",
            "observation": "SECRET_OBS",
            "result": "SECRET_RESULT",
        }
    )
    assert activity is not None
    assert "consulting the brain" in activity
    for forbidden in ("SECRET_QUERY", "SECRET_ARGS", "SECRET_OBS", "SECRET_RESULT"):
        assert forbidden not in activity

    # Errors present only the already-curated client message.
    err = render({"type": "error", "turn_id": "t", "message": "the turn failed"})
    assert err is not None and "the turn failed" in err

    answer = render({"type": "answer", "turn_id": "t", "text": "it is noon"})
    assert answer is not None and "it is noon" in answer


# --- AC-2/AC-3: the surface reaches the engine only over the wire ------------


def test_audio_reaches_engine_only_over_the_wire():
    """Nothing under `hearth/audio/` may import engine internals: it talks to
    the engine only through the veneer client contract (`hearth.veneers.base`)
    and reads only the shared config facility (`hearth.config`)."""
    import hearth.audio

    forbidden = ("hearth.brain", "hearth.loop", "hearth.memory", "hearth.gateway")
    allowed_prefixes = ("hearth.audio", "hearth.veneers.base")

    root = pathlib.Path(hearth.audio.__file__).parent
    offenders: list[tuple[str, str]] = []
    disallowed: set[str] = set()
    for py in sorted(root.rglob("*.py")):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            for module in modules:
                if any(module == f or module.startswith(f + ".") for f in forbidden):
                    offenders.append((py.name, module))
                if module == "hearth" or module.startswith("hearth."):
                    if module != "hearth.config" and not any(
                        module == p or module.startswith(p) for p in allowed_prefixes
                    ):
                        disallowed.add(module)

    assert offenders == [], f"audio surface imports engine internals: {offenders}"
    assert disallowed == set(), f"unexpected hearth imports in audio surface: {disallowed}"
