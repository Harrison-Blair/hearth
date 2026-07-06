"""Weather provider interface.

A capability behind an ABC, like search/ and llm/: the pipeline-facing skill
depends only on WeatherProvider, never a concrete backend, so a different weather
API could replace Open-Meteo with a one-line change in app.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Place:
    """A geocoded location. Flows only provider -> skill, so it lives here."""

    name: str  # spoken label, e.g. "Tokyo, Japan"
    latitude: float
    longitude: float


@dataclass
class Forecast:
    """A location's current conditions plus a per-day outlook. Flows only
    provider -> skill; the skill formats it for the LLM to speak."""

    location: str  # spoken label for the place
    current: dict  # {temp, apparent, description, wind, humidity}
    daily: list[dict] = field(default_factory=list)  # one row per day
    units: dict = field(default_factory=dict)  # {"temp": "°F", "wind": "mph", "precip": "in"}


class WeatherProvider(ABC):
    @abstractmethod
    async def geocode(self, place: str) -> Place | None:
        """Resolve a place name to coordinates; None if not found."""

    @abstractmethod
    async def forecast(self, lat: float, lon: float, *, name: str) -> Forecast:
        """Return current conditions and the daily outlook for a location."""

    @abstractmethod
    async def health(self) -> bool:
        """Return True if the backend is reachable."""

    async def aclose(self) -> None:
        """Release any held resources (e.g. an HTTP client). No-op by default."""
