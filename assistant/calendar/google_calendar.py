"""Google Calendar via the Calendar v3 REST API.

google-auth is used only to mint/refresh the service-account access token (its
transport is sync, so refreshes run in a thread); every API call goes through
async httpx, matching the other remote providers. google-auth is imported
lazily inside ServiceAccountTokenSource so the test suite — which injects a
fake token source — never needs it installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from assistant.calendar.base import CalendarEvent, CalendarProvider

log = logging.getLogger(__name__)

_BASE = "https://www.googleapis.com/calendar/v3"
_SCOPE = "https://www.googleapis.com/auth/calendar"
# Refresh when the cached token has less than this long to live.
_REFRESH_MARGIN_S = 120.0


class ServiceAccountTokenSource:
    """Caches a service-account access token, refreshing it off-thread."""

    def __init__(self, credentials_path: str) -> None:
        self._path = os.path.expanduser(credentials_path)
        self._creds = None
        self._lock = asyncio.Lock()

    async def token(self) -> str:
        async with self._lock:
            if self._creds is None:
                from google.oauth2 import service_account

                self._creds = service_account.Credentials.from_service_account_file(
                    self._path, scopes=[_SCOPE]
                )
            if self._needs_refresh():
                from google.auth.transport.requests import Request

                await asyncio.to_thread(self._creds.refresh, Request())
            return self._creds.token

    def _needs_refresh(self) -> bool:
        if not self._creds.token or self._creds.expiry is None:
            return True
        # google-auth stores expiry as a naive UTC datetime.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return (self._creds.expiry - now).total_seconds() < _REFRESH_MARGIN_S


def _parse_when(field: dict) -> tuple[datetime | None, bool]:
    """Google's start/end object: {"dateTime": RFC3339} for timed events,
    {"date": "YYYY-MM-DD"} for all-day. All-day midnights get the local tz."""
    if "dateTime" in field:
        return datetime.fromisoformat(field["dateTime"]), False
    if "date" in field:
        return datetime.fromisoformat(field["date"]).astimezone(), True
    return None, False


def _parse_event(item: dict, calendar_id: str) -> CalendarEvent | None:
    start, all_day = _parse_when(item.get("start") or {})
    if start is None:
        return None
    end, _ = _parse_when(item.get("end") or {})
    return CalendarEvent(
        id=item.get("id", ""),
        calendar_id=calendar_id,
        title=item.get("summary") or "untitled event",
        start=start,
        end=end,
        all_day=all_day,
        description=item.get("description") or "",
    )


class GoogleCalendar(CalendarProvider):
    def __init__(
        self,
        credentials_path: str = "",
        *,
        timeout: float = 10.0,
        health_calendar_ids: list[str] | None = None,
        token_source=None,  # injectable for tests
        transport: httpx.AsyncBaseTransport | None = None,  # injectable for tests
    ) -> None:
        self._tokens = token_source or ServiceAccountTokenSource(credentials_path)
        self._health_ids = list(health_calendar_ids or [])
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {"Authorization": f"Bearer {await self._tokens.token()}"}
        try:
            resp = await self._client.request(method, url, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001 - re-raise; the skill degrades gracefully
            log.error("Google Calendar %s %s failed: %s", method, url, exc)
            raise

    @staticmethod
    def _events_url(calendar_id: str, event_id: str | None = None) -> str:
        url = f"{_BASE}/calendars/{quote(calendar_id, safe='')}/events"
        if event_id is not None:
            url += f"/{quote(event_id, safe='')}"
        return url

    async def list_events(
        self,
        calendar_id: str,
        *,
        time_min: datetime,
        time_max: datetime,
        max_results: int = 50,
    ) -> list[CalendarEvent]:
        params = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": "true",  # expand recurring events into instances
            "orderBy": "startTime",
            "maxResults": max_results,
        }
        resp = await self._request("GET", self._events_url(calendar_id), params=params)
        items = resp.json().get("items") or []
        events = (_parse_event(item, calendar_id) for item in items)
        return [e for e in events if e is not None]

    async def create_event(
        self, calendar_id: str, *, title: str, start: datetime, end: datetime
    ) -> CalendarEvent:
        body = {
            "summary": title,
            # tz-aware isoformat carries the UTC offset; no timeZone field needed.
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        resp = await self._request("POST", self._events_url(calendar_id), json=body)
        event = _parse_event(resp.json(), calendar_id)
        if event is None:  # a created event always has a start
            raise ValueError("Google Calendar returned an event without a start")
        return event

    async def update_event(
        self,
        calendar_id: str,
        event_id: str,
        *,
        title: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> CalendarEvent:
        body: dict = {}
        if title is not None:
            body["summary"] = title
        if start is not None:
            body["start"] = {"dateTime": start.isoformat()}
        if end is not None:
            body["end"] = {"dateTime": end.isoformat()}
        resp = await self._request("PATCH", self._events_url(calendar_id, event_id), json=body)
        event = _parse_event(resp.json(), calendar_id)
        if event is None:
            raise ValueError("Google Calendar returned an event without a start")
        return event

    async def delete_event(self, calendar_id: str, event_id: str) -> None:
        try:
            await self._request("DELETE", self._events_url(calendar_id, event_id))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (404, 410):  # already gone = success
                return
            raise

    async def health(self) -> bool:
        try:
            for calendar_id in self._health_ids:
                await self._request(
                    "GET", f"{_BASE}/calendars/{quote(calendar_id, safe='')}"
                )
            if not self._health_ids:
                await self._tokens.token()
        except Exception:  # noqa: BLE001 - health is a boolean probe
            return False
        return True
