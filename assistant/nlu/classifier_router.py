"""LLM-classifier intent router with an offline keyphrase fallback.

Tier two of the router: the local LLM classifies every utterance against the
known intents, which fixes the substring false-positives a pure keyphrase match
suffers ("what time should I leave" is not a clock query). When the LLM is
unreachable or returns something unusable, we degrade to the keyphrase tier so
routing still works fully offline.

Note: under this always-classify scheme a general question costs two sequential
LLM calls (classify here, then the GeneralSkill answers). That is inherent to the
design, not a bug; the classify prompt is kept tiny and json-only to limit it.
"""

from __future__ import annotations

import json
import logging

from assistant.core.events import Intent
from assistant.llm.base import LLMProvider
from assistant.nlu.router import IntentRouter

log = logging.getLogger(__name__)


class ClassifierRouter(IntentRouter):
    def __init__(
        self,
        llm: LLMProvider,
        fallback: IntentRouter,
        intents: dict[str, str],
    ) -> None:
        self._llm = llm
        self._fallback = fallback
        self._intents = intents  # ordered {label: description}; keys are the valid set

    async def route(self, text: str) -> Intent:
        try:
            data = json.loads(
                await self._llm.complete(self._prompt(text), json=True, label="classify")
            )
            label = data.get("intent")
            if isinstance(label, str):
                label = label.strip().lower()
                if label in self._intents:
                    return Intent(type=label, raw_text=text)
            log.warning("Classifier returned no usable intent (%r); falling back", label)
        except Exception as exc:  # noqa: BLE001 - any LLM/JSON failure -> keyphrase tier
            log.warning("Intent classification failed: %s; falling back", exc)
        return await self._fallback.route(text)

    def _prompt(self, text: str) -> str:
        catalogue = "\n".join(f"- {label}: {desc}" for label, desc in self._intents.items())
        return (
            "Classify the user's request into exactly one intent.\n"
            f"{catalogue}\n"
            'Reply with ONLY a JSON object: {"intent": "<one label from the list>"}.\n'
            "If unsure, choose general.\n"
            'Example: "what time is it" -> {"intent": "time"}\n'
            'Example: "what time should I leave for the airport" -> {"intent": "general"}\n'
            f'Request: "{text}"'
        )
