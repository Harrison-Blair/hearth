"""The `hearth-audio` veneer: the listening surface.

A separate process that captures audio continuously, runs it through injected
wake/endpoint/STT stages, submits the resulting transcript to the engine over
the wire (via `hearth.veneers.base`, the PLM-007 client contract), and presents
what it heard and what came back. This package ships the **spine** -- surface,
capture loop, stage seams, config -- exercised against stage doubles. The real
wake, endpointing, and transcription are FTHR-029/030/031, plugged into the
`stages` interfaces defined here.

Like every veneer, it reaches the engine ONLY over the wire: nothing here imports
engine internals (`hearth.brain`/`loop`/`memory`/`gateway`).
"""
