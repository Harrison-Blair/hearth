"""Plain data records passed along the voice pipeline.

Kept in core/ so interfaces in audio/stt/nlu/skills can share them without
importing each other (avoids circular dependencies).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WakeEvent:
    """A wake-word activation."""

    name: str
    score: float


@dataclass
class Turn:
    """One message in a conversation's history."""

    role: str  # "user" or "assistant"
    content: str


@dataclass
class Command:
    """A transcribed user utterance to be routed and handled."""

    text: str
    spoken: bool = True
    history: list[Turn] = field(default_factory=list)


@dataclass
class ToolCall:
    """A tool the model asked to run, with its parsed arguments."""

    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class Intent:
    """A routed intent with extracted slots."""

    type: str
    slots: dict = field(default_factory=dict)
    raw_text: str = ""


@dataclass
class SkillResult:
    """The outcome of a skill handling a command."""

    speech: str
    data: dict | None = None
    success: bool = True
    expects_reply: bool = False
    restart: bool = False
    # True when ``speech`` is already persona-flavored (e.g. an LLM call whose
    # system prompt carries the persona suffix) and must not be re-styled by the
    # pipeline's Revoicer seam. False (the default) means plain/deterministic
    # text that still needs revoicing when persona is on.
    voiced: bool = False
