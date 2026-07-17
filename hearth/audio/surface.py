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

from hearth.audio.config import AudioSettings
from hearth.audio.source import LiveAudioSource
from hearth.audio.stages import FixedTranscriber, ScriptedEndpointer, ScriptedWakeDetector
from hearth.veneers.base import EngineUnreachable, connect, send_turn

# This surface's self-declared identity, sent with every turn so the engine can
# attribute the logged turn to the audio surface (PLM-007 FTHR-025). Named once.
SURFACE = "audio"


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
    runs unchanged against either.
    """

    def __init__(self, *, source, wake, endpointer, transcriber, submit, present) -> None:
        self._source = source
        self._wake = wake
        self._endpointer = endpointer
        self._transcriber = transcriber
        self._submit = submit
        self._present = present
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
                self._present(f"heard: {transcript}")
                for message in await self._submit(transcript):
                    rendered = render(message)
                    if rendered is not None:
                        self._present(rendered)
            finally:
                self._utterances.task_done()


async def _run(settings: AudioSettings) -> None:
    async with open_with_retry(
        settings.engine.host,
        settings.engine.port,
        max_attempts=settings.retry.max_attempts,
        base_delay=settings.retry.base_delay_s,
    ) as websocket:
        # NOTE: this feather ships no real wake/VAD/STT (AC-10). The runnable
        # surface is wired with the trivial stage doubles as placeholders so the
        # spine is a working tracer; FTHR-029/030/031 replace these three seams
        # with real implementations through the same injection points.
        surface = AudioSurface(
            source=LiveAudioSource(device=settings.input_device),
            wake=ScriptedWakeDetector(),
            endpointer=ScriptedEndpointer(),
            transcriber=FixedTranscriber(""),
            submit=make_submit(websocket),
            present=print,
        )
        await surface.run()


def main() -> int:
    settings = AudioSettings()
    try:
        asyncio.run(_run(settings))
    except EngineUnreachable as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
