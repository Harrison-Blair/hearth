"""Weather skill: fetch an Open-Meteo forecast and speak a short answer.

Routing is keyphrase-gated for the common "here" case; the LLM tool path fills a
`location` slot when the user names a place ("weather in Tokyo"), which the skill
resolves via geocoding. The provider returns current conditions plus a multi-day
daily table; one LLM call turns that data plus today's date into a one- or
two-sentence spoken answer to the user's specific question — "today", "tomorrow",
"this weekend", "will it rain Friday" all handled without in-skill date parsing.

Every step degrades gracefully — a lookup, geocoding, or LLM failure speaks an
apology instead of crashing the pipeline (offline-first).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from assistant.core.events import Command, Intent, SkillResult
from assistant.llm.base import LLMProvider
from assistant.skills.base import Skill
from assistant.weather.base import Forecast, WeatherProvider

log = logging.getLogger(__name__)


def _local_now() -> datetime:
    return datetime.now().astimezone()


_MAX_LOCATION_CHARS = 60  # a location is echoed into a geocoding query and speech: cap it

_WEATHER_SYSTEM = (
    "You are a voice assistant answering a weather question aloud. Use the forecast "
    "data provided to answer the user's specific question — the day or days they "
    "asked about. Reply in one or two short, plain spoken sentences, stating "
    "temperatures with their unit (e.g. '72 degrees'). No markdown, lists, or emoji."
)

_WEATHER_PROMPT = (
    "Today is {today}.\n"
    "Forecast for {location} (temperatures in {temp_unit}, wind in {wind_unit}, "
    "precipitation in {precip_unit}):\n"
    "{body}\n\n"
    'User question: "{question}"'
)


class WeatherSkill(Skill):
    name = "weather"
    intents = {"weather"}
    tool_specs = {
        "weather": {
            "description": (
                "Get the weather forecast — current conditions or any day up to 16 days "
                "ahead — for the user's home area or a named place. Use for questions "
                "about temperature, rain, snow, wind, or what to wear."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "city or place; omit for the user's home area",
                    }
                },
            },
        }
    }

    def __init__(
        self,
        weather: WeatherProvider,
        llm: LLMProvider,
        *,
        home_lat: float,
        home_lon: float,
        home_name: str,
        now: Callable[[], datetime] = _local_now,
    ) -> None:
        self._weather = weather
        self._llm = llm
        self._home_lat = home_lat
        self._home_lon = home_lon
        self._home_name = home_name
        self._now = now

    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        try:
            return await self._handle(cmd, intent)
        except Exception as exc:  # noqa: BLE001 - never crash the loop on a lookup/LLM error
            log.error("Weather lookup failed: %s", exc)
            return SkillResult("Sorry, I couldn't get the weather just now.", success=False)

    async def _handle(self, cmd: Command, intent: Intent) -> SkillResult:
        location = (intent.slots.get("location") or "").strip()[:_MAX_LOCATION_CHARS]
        if location:
            place = await self._weather.geocode(location)
            if place is None:
                return SkillResult(f"I couldn't find {location}.", success=False)
            lat, lon, name = place.latitude, place.longitude, place.name
        else:
            lat, lon, name = self._home_lat, self._home_lon, self._home_name

        forecast = await self._weather.forecast(lat, lon, name=name)
        prompt = _WEATHER_PROMPT.format(
            today=self._now().strftime("%A, %B %d, %Y"),
            location=forecast.location,
            temp_unit=forecast.units.get("temp", ""),
            wind_unit=forecast.units.get("wind", ""),
            precip_unit=forecast.units.get("precip", ""),
            body=self._format(forecast),
            question=cmd.text,
        )
        answer = await self._llm.complete(prompt, system=_WEATHER_SYSTEM, label="weather")
        if not answer:
            return SkillResult("I couldn't put the forecast into words.", success=False)
        return SkillResult(speech=answer, data={"location": forecast.location})

    @staticmethod
    def _format(forecast: Forecast) -> str:
        c = forecast.current
        lines = [
            f"Right now: {c['temp']} (feels like {c['apparent']}), {c['description']}, "
            f"wind {c['wind']}, humidity {c['humidity']}%."
        ]
        for row in forecast.daily:
            lines.append(
                f"{row['weekday']} {row['date']}: {row['description']}, "
                f"high {row['high']}, low {row['low']}, "
                f"{row['precip_prob']}% chance of precipitation ({row['precip']}), "
                f"wind up to {row['wind_max']}."
            )
        return "\n".join(lines)
