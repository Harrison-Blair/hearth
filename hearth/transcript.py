"""Per-session human-readable transcript.

Deliberately dumb: `append` writes one timestamped line to
`<transcript_dir>/<session_id>.txt`, creating the file (and directory) on
first write. Best-effort -- a write failure (disk full, permission error) is
caught and swallowed here, never raised into the caller's turn.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone


class Transcript:
    def __init__(self, transcript_dir: str) -> None:
        self._dir = transcript_dir

    def append(self, session_id: str, line: str) -> None:
        try:
            os.makedirs(self._dir, exist_ok=True)
            path = os.path.join(self._dir, f"{session_id}.txt")
            timestamp = datetime.now(timezone.utc).isoformat()
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} {line}\n")
        except OSError:
            pass
