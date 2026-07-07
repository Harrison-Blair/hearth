"""Tool-call eval cases: realistic single-turn utterances + expected decision.

Each case pins the outcome the model should reach through the orchestrator's tool
decision — either a tool (a skill intent) with the key argument(s) that must be
present, or a direct answer (no tool) for general knowledge. Argument checks are
deliberately loose: we assert the important slot is present (and plausible where
robust, via ``arg_contains``), never exact string equality where the model has
latitude in how it phrases a query, duration, or reminder text.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    utterance: str
    tool: str | None  # a skill intent, or None to expect a direct answer
    required_args: tuple[str, ...] = ()  # arg keys that must be present + non-empty
    arg_contains: dict[str, str] = field(default_factory=dict)  # arg -> case-insensitive substring
    note: str = ""


CASES: list[Case] = [
    # clock: time / date (no arguments)
    Case("what time is it", "time"),
    Case("do you have the time", "time"),
    Case("what's today's date", "date"),
    Case("what day of the week is it", "date"),
    # timer: needs a duration; list/cancel take no required args
    Case("set a timer for 5 minutes", "timer", required_args=("duration",)),
    Case("start a 30 second timer", "timer", required_args=("duration",)),
    Case("how much time is left on my timer", "list_timers"),
    Case("cancel my pasta timer", "cancel_timer"),
    # reminder: create / list / manage
    Case("remind me to call mom at 6pm", "reminder", required_args=("text",)),
    Case("remind me to take out the trash tomorrow morning", "reminder", required_args=("text",)),
    Case("what reminders do I have", "list_reminders"),
    Case("read back my reminders", "list_reminders"),
    Case("cancel my reminder to call mom", "manage_reminders", required_args=("text",)),
    # weather: with and without a named place
    Case("what's the weather in Tokyo", "weather",
         required_args=("location",), arg_contains={"location": "tokyo"}),
    Case("what's the weather like today", "weather"),
    Case("will it rain tomorrow", "weather"),
    # web_search: live/current info
    Case("search the web for the latest news on the mars rover", "web_search",
         required_args=("query",)),
    Case("look up the current price of bitcoin", "web_search", required_args=("query",)),
    # direct answer: general knowledge, no tool
    Case("what's the capital of France", None),
    Case("who wrote Pride and Prejudice", None),
    Case("how many legs does a spider have", None),
]
