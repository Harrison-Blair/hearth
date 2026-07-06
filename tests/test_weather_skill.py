from datetime import datetime

from assistant.core.events import Command, Intent
from assistant.skills.weather import WeatherSkill
from assistant.weather.base import Forecast, Place


class FakeWeather:
    def __init__(self, forecast=None, place=None, forecast_exc=None):
        self._forecast = forecast or _forecast()
        self._place = place
        self._forecast_exc = forecast_exc
        self.geocoded = []
        self.forecasts = []

    async def geocode(self, place):
        self.geocoded.append(place)
        return self._place

    async def forecast(self, lat, lon, *, name):
        self.forecasts.append((lat, lon, name))
        if self._forecast_exc:
            raise self._forecast_exc
        return Forecast(location=name, current=self._forecast.current,
                        daily=self._forecast.daily, units=self._forecast.units)

    async def health(self):
        return True


class FakeLLM:
    def __init__(self, answer="It'll hit 90 degrees and stay clear today."):
        self.answer = answer
        self.prompts = []

    async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
        self.prompts.append((prompt, system))
        return self.answer

    async def health(self):
        return True


def _forecast():
    return Forecast(
        location="Atlanta",
        current={"temp": 72, "apparent": 70, "description": "overcast", "wind": 5, "humidity": 55},
        daily=[{"date": "2026-07-05", "weekday": "Sunday", "description": "clear sky",
                "high": 90, "low": 70, "precip_prob": 5, "precip": 0.0, "wind_max": 8}],
        units={"temp": "°F", "wind": "mph", "precip": "inch"},
    )


def _skill(weather, llm, **kwargs):
    kwargs.setdefault("home_lat", 33.749)
    kwargs.setdefault("home_lon", -84.388)
    kwargs.setdefault("home_name", "Atlanta")
    kwargs.setdefault("now", lambda: datetime(2026, 7, 5, 9, 0))
    return WeatherSkill(weather, llm, **kwargs)


async def test_home_path_uses_home_coords_no_geocode():
    weather = FakeWeather()
    llm = FakeLLM()
    result = await _skill(weather, llm).handle(
        Command("what's the weather today"), Intent("weather")
    )
    assert result.success
    assert result.speech == llm.answer
    assert weather.geocoded == []  # no location slot -> home, no geocoding
    assert weather.forecasts == [(33.749, -84.388, "Atlanta")]
    # The LLM prompt carries today's date and the daily table.
    prompt, system = llm.prompts[0]
    assert "July 05, 2026" in prompt
    assert '"what\'s the weather today"' in prompt
    assert "high 90" in prompt


async def test_named_location_is_geocoded():
    weather = FakeWeather(place=Place(name="Tokyo, Japan", latitude=35.68, longitude=139.69))
    result = await _skill(weather, FakeLLM()).handle(
        Command("weather in Tokyo tomorrow"), Intent("weather", slots={"location": "Tokyo"})
    )
    assert result.success
    assert weather.geocoded == ["Tokyo"]
    assert weather.forecasts == [(35.68, 139.69, "Tokyo, Japan")]


async def test_unknown_location_apologizes():
    weather = FakeWeather(place=None)  # geocode returns nothing
    result = await _skill(weather, FakeLLM()).handle(
        Command("weather in Nowheresville"),
        Intent("weather", slots={"location": "Nowheresville"}),
    )
    assert not result.success
    assert "couldn't find nowheresville" in result.speech.lower()
    assert weather.forecasts == []  # never fetched a forecast


async def test_provider_error_degrades_gracefully():
    weather = FakeWeather(forecast_exc=RuntimeError("network down"))
    result = await _skill(weather, FakeLLM()).handle(
        Command("what's the weather"), Intent("weather")
    )
    assert not result.success
    assert "couldn't get the weather" in result.speech.lower()
