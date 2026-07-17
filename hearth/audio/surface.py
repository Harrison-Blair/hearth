"""The audio surface: continuous capture, stage orchestration, turn submission.

Runnable as the `hearth-audio` console script or `python -m hearth.audio.surface`.
Reaches the engine ONLY over the wire, through `hearth.veneers.base` (PLM-007's
client contract) -- same as `chat`, declaring its surface identity as `"audio"`.

**The crux is the capture loop (FC-15 duplex).** Capture is a single always-running
task that consumes frames and feeds wake detection *regardless of whether a turn is
outstanding with the engine*. When a wake fires and an utterance is captured and
transcribed, the transcript is handed to a **separate** submit concern via a queue;
the capture task never awaits the engine call, so frames keep arriving during a
turn. A design that awaited `submit` inside the capture path would stop listening
mid-turn -- the wrong shape, and PLM-009 (mic live while speaking) needs this.

Unlike `chat`, which fails fast at a terminal, this unattended surface **retries
with backoff** when the engine is unreachable (FC-10): a headless box must survive
the engine starting later.
"""
from __future__ import annotations

import asyncio
import contextlib
import sys
from contextlib import asynccontextmanager

from hearth.audio import voice as voice_check
from hearth.audio.config import AudioSettings
from hearth.audio.source import LiveAudioSource
from hearth.audio.stages import (
    FixedTranscriber,
    MarkerRenderer,
    RecordingPlayer,
    ScriptedEndpointer,
    ScriptedWakeDetector,
    resolve_output_device,
)
from hearth.veneers.base import EngineUnreachable, connect, send_turn

# This surface's self-declared identity, sent with every turn so the engine can
# attribute the logged turn to the audio surface (PLM-007 FTHR-025). Named once.
SURFACE = "audio"

# The two presentation tags (FC-9). `HEARD` is the listening side (transcript),
# `SPOKEN` the speaking side (the answer that was rendered to speech).
HEARD = "heard"
SPOKEN = "spoken"

# Default per-tag ANSI colours: heard vs spoken read distinctly (FC-9), in the
# surface family's `[<colour>tag<reset>]` style (cf. hearth-chat's answer line).
# Overridable via `PresentationConfig`; these are the shipped defaults.
DEFAULT_TAG_COLORS = {HEARD: "36", SPOKEN: "35"}  # cyan / magenta


def present_line(text: str, tag: str, colors: dict[str, str] = DEFAULT_TAG_COLORS) -> str:
    """Pure (text, tag) -> styled line, tag in {heard, spoken}. Each tag gets its
    own colour so heard and spoken text are visually distinct (FC-9). No device
    needed -- presentation is a pure function of its arguments."""
    color = colors[tag]
    return f"[\033[{color}m{tag}\033[0m] {text}"


def render(message: dict) -> str | None:
    """What is safe to present from an inbound wire message. Whitelist-only:
    reads only the already-curated fields the gateway lets cross the boundary
    (`text` / `label` / `message`) and never reaches for tool internals
    (`query`/`arguments`/`observation`/`result`), so no internal detail can be
    presented even if it were somehow on the dict. This is the surface end of
    PLM-007's shared safety policy (FC-8, FC-9)."""
    kind = message.get("type")
    if kind == "answer":
        return message.get("text", "")
    if kind == "tool_activity":
        return f"… {message.get('label', '')}"
    if kind == "error":
        return f"error: {message.get('message', '')}"
    # `done` and anything unknown produce no output.
    return None


@asynccontextmanager
async def open_with_retry(
    host: str,
    port: int,
    *,
    max_attempts: int,
    base_delay: float,
    connect_fn=connect,
    sleep=asyncio.sleep,
):
    """Enter the engine connection, retrying with exponential backoff while it is
    unreachable (FC-10). Wraps `hearth.veneers.base.connect` (the client
    contract's connect seam) rather than re-implementing it. After `max_attempts`
    the last `EngineUnreachable` propagates -- retry is bounded, not infinite."""
    delay = base_delay
    async with contextlib.AsyncExitStack() as stack:
        for attempt in range(1, max_attempts + 1):
            try:
                connection = await stack.enter_async_context(connect_fn(host, port))
            except EngineUnreachable:
                if attempt == max_attempts:
                    raise
                await sleep(delay)
                delay *= 2
                continue
            yield connection
            return


def make_submit(websocket):
    """The default turn-submission seam: send one turn over the wire declaring the
    `audio` surface, and return the inbound wire messages."""

    async def submit(transcript: str) -> list[dict]:
        return await send_turn(websocket, transcript, SURFACE)

    return submit


class AudioSurface:
    """Orchestrates the listening spine over injected seams.

    All stages, the source, the submit seam, and the presenter are injected so
    FTHR-029/030/031 supply real stages and tests supply doubles -- the spine
    runs unchanged against either. The output seams (`renderer`/`player`) are
    injected the same way: FTHR-036/038 supply real ones, tests supply doubles;
    they default to the shipped doubles so the surface is a working tracer.
    """

    def __init__(
        self,
        *,
        source,
        wake,
        endpointer,
        transcriber,
        submit,
        present,
        renderer=None,
        player=None,
        colors=None,
    ) -> None:
        self._source = source
        self._wake = wake
        self._endpointer = endpointer
        self._transcriber = transcriber
        self._submit = submit
        self._present = present
        self._renderer = renderer if renderer is not None else MarkerRenderer()
        self._player = player if player is not None else RecordingPlayer()
        self._colors = colors if colors is not None else DEFAULT_TAG_COLORS
        self._utterances: asyncio.Queue[str] = asyncio.Queue()

    async def run(self) -> None:
        """Run the continuous capture loop and a concurrent submit loop until the
        source is exhausted and every captured utterance has been submitted."""
        submit_task = asyncio.create_task(self._submit_loop())
        try:
            await self._capture_loop()
            # Drain the utterances captured so far; submit runs concurrently, so
            # capture never waited on the engine.
            await self._utterances.join()
        finally:
            submit_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await submit_task

    async def _capture_loop(self) -> None:
        """The always-running capture task: consume every frame, feed wake
        detection, and on a wake collect the utterance and enqueue its transcript.
        Enqueuing does NOT block on the engine -- that is the submit loop's job --
        so frames keep being consumed while a turn is outstanding (FC-15)."""
        collecting = False
        utterance: list = []
        async for frame in self._source.frames():
            if not collecting:
                if self._wake.detect(frame):
                    collecting = True
                    utterance = []
                    self._endpointer.reset()
                continue
            utterance.append(frame)
            if self._endpointer.accept(frame):
                transcript = self._transcriber.transcribe(utterance)
                await self._utterances.put(transcript)
                collecting = False

    async def _submit_loop(self) -> None:
        """The separate submit concern: pull captured transcripts and submit each
        to the engine, presenting the heard transcript and the answer. Blocking
        here (a slow engine) never stalls capture."""
        while True:
            transcript = await self._utterances.get()
            try:
                self._present(present_line(transcript, HEARD, self._colors))
                for message in await self._submit(transcript):
                    if message.get("type") == "answer":
                        # Only the engine's final answer is spoken (FC-8); tool
                        # activity and errors are presented but never rendered.
                        self._speak(message.get("text", ""))
                    else:
                        shown = render(message)
                        if shown is not None:
                            self._present(shown)
            finally:
                self._utterances.task_done()

    def _speak(self, text: str) -> None:
        """The speak call site: render the final answer to audio frames and play
        them, then present it tagged `[spoken]`. This is the ONLY path to the
        renderer -- tool activity never reaches here (FC-8), the same discipline
        the gateway's whitelist enforces on the wire."""
        frames = self._renderer.render(text)
        self._player.play(frames)
        self._present(present_line(text, SPOKEN, self._colors))


async def _run(settings: AudioSettings) -> None:
    async with open_with_retry(
        settings.engine.host,
        settings.engine.port,
        max_attempts=settings.retry.max_attempts,
        base_delay=settings.retry.base_delay_s,
    ) as websocket:
        # NOTE: this feather ships no real wake/VAD/STT or TTS/playback. The
        # runnable surface is wired with the trivial doubles as placeholders so
        # the spine is a working tracer; FTHR-029/030/031 replace the input seams
        # and FTHR-036/038 the output seams (renderer/player) through the same
        # injection points. The output device resolves to the system default
        # when unset (FC-5); the absent-voice first-run error is FTHR-037.
        surface = AudioSurface(
            source=LiveAudioSource(device=settings.input_device),
            wake=ScriptedWakeDetector(),
            endpointer=ScriptedEndpointer(),
            transcriber=FixedTranscriber(""),
            renderer=MarkerRenderer(),
            player=RecordingPlayer(device=resolve_output_device(settings.output_device)),
            submit=make_submit(websocket),
            present=print,
            colors=settings.presentation.colors(),
        )
        await surface.run()


def main(*, fetch=voice_check.download_voice, voices_dir=voice_check.VOICES_DIR, serve=None) -> int:
    settings = AudioSettings()
    # First-run voice check, BEFORE serving (FTHR-037): resolve the configured
    # voice, fetch it if absent, or emit the absent-voice error and exit as a
    # configuration problem. An unset voice raises SystemExit here -- non-zero, no
    # traceback -- so serving is never reached. The seams are injected so tests
    # (and CI) drive this offline; production wires the real defaults.
    voice_check.ensure_voice(settings.voice, voices_dir=voices_dir, fetch=fetch)
    if serve is None:
        serve = lambda: asyncio.run(_run(settings))  # noqa: E731
    try:
        serve()
    except EngineUnreachable as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
