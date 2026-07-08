"""GoogleCalendar provider over a mocked httpx transport — no network, no google-auth."""

import json
from datetime import datetime, timezone

import httpx
import pytest

from assistant.calendar.google_calendar import GoogleCalendar

CAL_ID = "cal@group.calendar.google.com"


class FakeTokens:
    def __init__(self):
        self.calls = 0

    async def token(self) -> str:
        self.calls += 1
        return "test-token"


def _provider(handler, **kwargs) -> GoogleCalendar:
    return GoogleCalendar(
        token_source=FakeTokens(), transport=httpx.MockTransport(handler), **kwargs
    )


def _events_response(*items):
    return httpx.Response(200, json={"items": list(items)})


TIMED_ITEM = {
    "id": "ev1",
    "summary": "Dentist",
    "start": {"dateTime": "2026-07-07T15:00:00-04:00"},
    "end": {"dateTime": "2026-07-07T16:00:00-04:00"},
}
ALL_DAY_ITEM = {
    "id": "ev2",
    "summary": "Conference",
    "start": {"date": "2026-07-08"},
    "end": {"date": "2026-07-09"},
}


async def test_list_events_parses_timed_and_all_day():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["params"] = dict(request.url.params)
        return _events_response(TIMED_ITEM, ALL_DAY_ITEM)

    provider = _provider(handler)
    events = await provider.list_events(
        CAL_ID,
        time_min=datetime(2026, 7, 7, tzinfo=timezone.utc),
        time_max=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )

    assert seen["params"]["singleEvents"] == "true"
    assert seen["params"]["orderBy"] == "startTime"
    assert seen["params"]["timeMin"] == "2026-07-07T00:00:00+00:00"
    assert seen["params"]["timeMax"] == "2026-07-14T00:00:00+00:00"
    assert "cal%40group.calendar.google.com/events" in seen["url"]

    timed, all_day = events
    assert timed.id == "ev1"
    assert timed.title == "Dentist"
    assert not timed.all_day
    assert timed.start == datetime.fromisoformat("2026-07-07T15:00:00-04:00")
    assert timed.end == datetime.fromisoformat("2026-07-07T16:00:00-04:00")
    assert timed.calendar_id == CAL_ID
    assert all_day.all_day
    assert all_day.start.tzinfo is not None
    assert (all_day.start.year, all_day.start.month, all_day.start.day) == (2026, 7, 8)


async def test_list_events_parses_description():
    tagged = dict(TIMED_ITEM, description="daily [hidden] routine")

    provider = _provider(lambda request: _events_response(tagged, ALL_DAY_ITEM))
    events = await provider.list_events(
        CAL_ID,
        time_min=datetime(2026, 7, 7, tzinfo=timezone.utc),
        time_max=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )

    assert events[0].description == "daily [hidden] routine"
    assert events[1].description == ""  # absent in the payload


async def test_list_events_sends_bearer_token():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer test-token"
        return _events_response()

    provider = _provider(handler)
    events = await provider.list_events(
        CAL_ID,
        time_min=datetime(2026, 7, 7, tzinfo=timezone.utc),
        time_max=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )
    assert events == []


async def test_create_event_posts_summary_and_times():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "new1",
                "summary": seen["body"]["summary"],
                "start": seen["body"]["start"],
                "end": seen["body"]["end"],
            },
        )

    provider = _provider(handler)
    start = datetime.fromisoformat("2026-07-07T15:00:00-04:00")
    end = datetime.fromisoformat("2026-07-07T16:00:00-04:00")
    event = await provider.create_event(CAL_ID, title="Dentist", start=start, end=end)

    assert seen["method"] == "POST"
    assert seen["body"] == {
        "summary": "Dentist",
        "start": {"dateTime": "2026-07-07T15:00:00-04:00"},
        "end": {"dateTime": "2026-07-07T16:00:00-04:00"},
    }
    assert event.id == "new1"
    assert event.start == start


async def test_update_event_patches_only_given_fields():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"id": "ev1", "summary": "Dentist", "start": {"dateTime": "2026-07-07T16:00:00-04:00"}},
        )

    provider = _provider(handler)
    new_start = datetime.fromisoformat("2026-07-07T16:00:00-04:00")
    event = await provider.update_event(CAL_ID, "ev1", start=new_start)

    assert seen["method"] == "PATCH"
    assert seen["url"].endswith("/events/ev1")
    assert seen["body"] == {"start": {"dateTime": "2026-07-07T16:00:00-04:00"}}
    assert event.start == new_start


async def test_delete_event_tolerates_already_gone():
    codes = iter([204, 404, 410])

    def handler(request):
        assert request.method == "DELETE"
        return httpx.Response(next(codes))

    provider = _provider(handler)
    await provider.delete_event(CAL_ID, "ev1")  # 204
    await provider.delete_event(CAL_ID, "ev1")  # 404 -> success
    await provider.delete_event(CAL_ID, "ev1")  # 410 -> success


async def test_delete_event_raises_on_other_errors():
    provider = _provider(lambda request: httpx.Response(403))
    with pytest.raises(httpx.HTTPStatusError):
        await provider.delete_event(CAL_ID, "ev1")


async def test_list_events_raises_on_http_error():
    provider = _provider(lambda request: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await provider.list_events(
            CAL_ID,
            time_min=datetime(2026, 7, 7, tzinfo=timezone.utc),
            time_max=datetime(2026, 7, 8, tzinfo=timezone.utc),
        )


async def test_health_checks_each_calendar():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"id": "x"})

    provider = _provider(handler, health_calendar_ids=["a@x.com", "b@x.com"])
    assert await provider.health() is True
    assert len(seen) == 2
    assert seen[0].endswith("/calendars/a%40x.com")


async def test_health_false_on_forbidden():
    provider = _provider(
        lambda request: httpx.Response(403), health_calendar_ids=["a@x.com"]
    )
    assert await provider.health() is False


async def test_health_false_on_network_error():
    def handler(request):
        raise httpx.ConnectError("no route")

    provider = _provider(handler, health_calendar_ids=["a@x.com"])
    assert await provider.health() is False
