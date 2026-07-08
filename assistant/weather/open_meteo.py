"""Weather via the Open-Meteo API.

Open-Meteo's forecast and geocoding APIs are free, keyless, and need no account —
the same offline-first-but-remote-accelerator shape as the web_search capability.
One call fetches current conditions plus a multi-day daily outlook; a second,
optional call resolves a spoken place name to coordinates.

Uses httpx (already a dependency) so no new packages are needed.
"""

from __future__ import annotations

import logging

import httpx

from assistant.weather.base import Forecast, Place, WeatherProvider

log = logging.getLogger(__name__)

# WMO weather interpretation codes -> short spoken phrases.
_WMO = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "heavy freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "heavy freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light rain showers",
    81: "rain showers",
    82: "violent rain showers",
    85: "light snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with heavy hail",
}

# The full days-of-week table so the LLM never has to derive a weekday itself.
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _describe(code) -> str:
    try:
        return _WMO.get(int(code), "unknown conditions")
    except (TypeError, ValueError):
        return "unknown conditions"


def _weekday(iso_date: str) -> str:
    """Weekday name for a 'YYYY-MM-DD' string, without importing datetime math
    for every row: Open-Meteo already returns ISO dates, so derive via ordinal."""
    try:
        from datetime import date

        y, m, d = (int(p) for p in iso_date.split("-"))
        return _WEEKDAYS[date(y, m, d).weekday()]
    except Exception:  # noqa: BLE001 - a malformed date just loses its weekday label
        return ""


class OpenMeteoWeather(WeatherProvider):
    def __init__(
        self,
        *,
        forecast_endpoint: str = "https://api.open-meteo.com/v1/forecast",
        geocoding_endpoint: str = "https://geocoding-api.open-meteo.com/v1/search",
        temperature_unit: str = "fahrenheit",
        wind_speed_unit: str = "mph",
        precipitation_unit: str = "inch",
        timezone: str = "auto",
        forecast_days: int = 16,
        timeout: float = 10.0,
    ) -> None:
        self._forecast_url = forecast_endpoint
        self._geocoding_url = geocoding_endpoint
        self._temperature_unit = temperature_unit
        self._wind_speed_unit = wind_speed_unit
        self._precipitation_unit = precipitation_unit
        self._timezone = timezone
        self._forecast_days = forecast_days
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def forecast(self, lat: float, lon: float, *, name: str) -> Forecast:
        params = {
            "latitude": lat,
            "longitude": lon,
            "timezone": self._timezone,
            "temperature_unit": self._temperature_unit,
            "wind_speed_unit": self._wind_speed_unit,
            "precipitation_unit": self._precipitation_unit,
            "forecast_days": self._forecast_days,
            "current": (
                "temperature_2m,apparent_temperature,weather_code,"
                "wind_speed_10m,relative_humidity_2m"
            ),
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,precipitation_sum,wind_speed_10m_max"
            ),
        }
        try:
            resp = await self._client.get(self._forecast_url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - re-raise; the skill degrades gracefully
            log.error("Open-Meteo forecast failed: %s", exc)
            raise

        cur = data.get("current") or {}
        cur_units = data.get("current_units") or {}
        daily_units = data.get("daily_units") or {}
        units = {
            "temp": cur_units.get("temperature_2m", "°"),
            "wind": cur_units.get("wind_speed_10m", ""),
            "precip": daily_units.get("precipitation_sum", ""),
        }
        current = {
            "temp": cur.get("temperature_2m"),
            "apparent": cur.get("apparent_temperature"),
            "description": _describe(cur.get("weather_code")),
            "wind": cur.get("wind_speed_10m"),
            "humidity": cur.get("relative_humidity_2m"),
        }

        daily = data.get("daily") or {}
        dates = daily.get("time") or []
        codes = daily.get("weather_code") or []
        highs = daily.get("temperature_2m_max") or []
        lows = daily.get("temperature_2m_min") or []
        precip_prob = daily.get("precipitation_probability_max") or []
        precip_sum = daily.get("precipitation_sum") or []
        wind_max = daily.get("wind_speed_10m_max") or []
        rows: list[dict] = []
        for i, iso in enumerate(dates):
            rows.append(
                {
                    "date": iso,
                    "weekday": _weekday(iso),
                    "description": _describe(codes[i] if i < len(codes) else None),
                    "high": highs[i] if i < len(highs) else None,
                    "low": lows[i] if i < len(lows) else None,
                    "precip_prob": precip_prob[i] if i < len(precip_prob) else None,
                    "precip": precip_sum[i] if i < len(precip_sum) else None,
                    "wind_max": wind_max[i] if i < len(wind_max) else None,
                }
            )

        return Forecast(location=name, current=current, daily=rows, units=units)

    async def geocode(self, place: str) -> Place | None:
        params = {"name": place, "count": 1, "language": "en", "format": "json"}
        try:
            resp = await self._client.get(self._geocoding_url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - re-raise; the skill degrades gracefully
            log.error("Open-Meteo geocoding failed: %s", exc)
            raise

        results = data.get("results") or []
        if not results:
            return None
        top = results[0]
        parts = [top.get("name"), top.get("admin1"), top.get("country")]
        label = ", ".join(p for p in parts if p)
        return Place(
            name=label or place,
            latitude=top["latitude"],
            longitude=top["longitude"],
        )

    async def health(self) -> bool:
        try:
            await self.forecast(0.0, 0.0, name="health")
        except Exception:  # noqa: BLE001 - health is a boolean probe
            return False
        return True
