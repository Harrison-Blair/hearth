import httpx
import pytest

from assistant.weather.open_meteo import OpenMeteoWeather


def _patch_transport(monkeypatch, handler):
    orig = httpx.AsyncClient

    def factory(**kwargs):
        return orig(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


_FORECAST_JSON = {
    "current_units": {"temperature_2m": "°F", "wind_speed_10m": "mp/h"},
    "daily_units": {"precipitation_sum": "inch"},
    "current": {
        "temperature_2m": 72.0,
        "apparent_temperature": 70.0,
        "weather_code": 3,
        "wind_speed_10m": 5.0,
        "relative_humidity_2m": 55,
    },
    "daily": {
        "time": ["2026-07-05", "2026-07-06"],
        "weather_code": [0, 61],
        "temperature_2m_max": [90.0, 85.0],
        "temperature_2m_min": [70.0, 68.0],
        "precipitation_probability_max": [5, 60],
        "precipitation_sum": [0.0, 0.3],
        "wind_speed_10m_max": [8.0, 12.0],
    },
}


async def test_forecast_maps_current_and_daily(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=_FORECAST_JSON)

    _patch_transport(monkeypatch, handler)
    fc = await OpenMeteoWeather().forecast(33.749, -84.388, name="Atlanta")

    assert fc.location == "Atlanta"
    assert fc.current["temp"] == 72.0
    assert fc.current["description"] == "overcast"  # WMO code 3
    assert fc.units == {"temp": "°F", "wind": "mp/h", "precip": "inch"}
    assert len(fc.daily) == 2
    assert fc.daily[0]["description"] == "clear sky"  # code 0
    assert fc.daily[1]["description"] == "light rain"  # code 61
    assert fc.daily[0]["weekday"] == "Sunday"  # 2026-07-05
    assert fc.daily[1]["high"] == 85.0
    assert fc.daily[1]["precip_prob"] == 60


async def test_forecast_sends_configured_params(monkeypatch):
    captured = {}

    def handler(request):
        captured.update(dict(request.url.params))
        return httpx.Response(200, json=_FORECAST_JSON)

    _patch_transport(monkeypatch, handler)
    await OpenMeteoWeather(
        temperature_unit="celsius", wind_speed_unit="kmh", forecast_days=7, timezone="America/New_York"
    ).forecast(1.5, 2.5, name="X")

    assert captured["latitude"] == "1.5"
    assert captured["longitude"] == "2.5"
    assert captured["temperature_unit"] == "celsius"
    assert captured["wind_speed_unit"] == "kmh"
    assert captured["forecast_days"] == "7"
    assert captured["timezone"] == "America/New_York"
    assert "temperature_2m_max" in captured["daily"]


async def test_forecast_reraises_on_http_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("dns failure")

    _patch_transport(monkeypatch, handler)
    with pytest.raises(httpx.ConnectError):
        await OpenMeteoWeather().forecast(0.0, 0.0, name="X")


async def test_geocode_maps_first_result(monkeypatch):
    def handler(request):
        assert "geocoding" in str(request.url)
        assert request.url.params.get("name") == "Tokyo"
        return httpx.Response(200, json={
            "results": [{
                "name": "Tokyo", "admin1": "Tokyo", "country": "Japan",
                "latitude": 35.68, "longitude": 139.69,
            }]
        })

    _patch_transport(monkeypatch, handler)
    place = await OpenMeteoWeather().geocode("Tokyo")
    assert place is not None
    assert place.name == "Tokyo, Tokyo, Japan"
    assert place.latitude == 35.68
    assert place.longitude == 139.69


async def test_geocode_returns_none_when_no_results(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={})

    _patch_transport(monkeypatch, handler)
    assert await OpenMeteoWeather().geocode("Nowheresville") is None


async def test_health_true_on_success(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=_FORECAST_JSON)

    _patch_transport(monkeypatch, handler)
    assert await OpenMeteoWeather().health() is True


async def test_health_false_when_api_raises(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("dns failure")

    _patch_transport(monkeypatch, handler)
    assert await OpenMeteoWeather().health() is False
